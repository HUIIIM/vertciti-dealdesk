"""共享 capped HTTP helper.

背景：第 17/18/22 项已给 GET 型抓取（fetch_page / robots.txt /
ddg_search）以及研究管线加了流式大小上限，但 POST 型 JSON 调用仍用
httpx.post + resp.json() 整页读入——TopHap MCP 的 JSON-RPC 调用
（app/services/tophap.py 的 _rpc 重试/多样式链每试一次读一整页）与
token 刷新端点响应（app/services/token_watch.py）。TopHap 是地址
pipeline 主源、响应含整套物业档案字段，异常端点/中间人返回超大
响应时无 Content-Length 预检、无流式停手。

GET 型 JSON API 同类缺口曾在 v1 线以第 23 项修复（get_json_capped），
但 v2 分层迁移未把 GET 变体带进本模块，四端点回归为整页读——
sell_readiness 的 Socrata DOB/ECB、ownership 的 NY DOS、providers 的
RentCast、geocode 的 Census。
Socrata 的 $limit 与 RentCast 的 limit=1 约束的是行数不是字节数，
异常/恶意端点返回超大响应时仍无上限。

本模块无 app 内依赖（只依赖 httpx），避免循环 import：tophap、
token_watch 与四家 GET 端点都可顶层 import（research_pipeline 顶层
import providers，providers 不能反向顶层 import research_pipeline，
故 helper 独立成模块）。

口径：MAX_POST_BYTES / MAX_JSON_BYTES 均与
research_pipeline.MAX_PAGE_BYTES 同值（2,000,000）；Content-Length
预检不读 body、流式累计超限停手。POST 超限抛 ResponseTooLarge；
GET 超限在返回 dict 里标 too_large；调用方均按各自既有诚实降级
口径处理（TopHap 记 MCPError 中文诊断、token_watch 按刷新失败
处理、四端点 ok=False + 中文 note / geocode 返回 None），
绝不截断残页凑解析。
"""

from __future__ import annotations

import json
import logging

import httpx

logger = logging.getLogger(__name__)

# POST 型 JSON 响应大小上限：与页面抓取上限同值。
# MCP 物业档案/CMA 正常响应通常几 KB 到几百 KB，2MB 留足余量。
MAX_POST_BYTES = 2_000_000

# GET 型 JSON API 响应大小上限：
# 与页面抓取上限同值。官方 JSON API 正常响应通常只有几 KB 到
# 几百 KB，2MB 留足余量。
MAX_JSON_BYTES = 2_000_000


class ResponseTooLarge(Exception):
    """响应体超过字节上限（已流式停手，未读整页、未用残页）。"""

    def __init__(self, limit: int, url: str = ""):
        super().__init__(f"响应过大（超过 {limit} 字节上限）")
        self.limit = limit
        self.url = url


def collect_capped(resp, limit: int) -> tuple[bytes | None, bool]:
    """流式读取响应体并执行字节上限（与 research_pipeline._collect_capped 同逻辑）。

    返回 (body, too_large)：Content-Length 超限在读 body 前停手；
    无预告长度时流式累计、超限中途停手。too_large=True 时 body=None。
    """
    clen = resp.headers.get("content-length")
    try:
        clen_val = int(clen) if clen is not None else None
    except (TypeError, ValueError):
        clen_val = None
    if clen_val is not None and clen_val > limit:
        return None, True
    chunks: list[bytes] = []
    total = 0
    for chunk in resp.iter_bytes(chunk_size=65536):
        total += len(chunk)
        if total > limit:
            return None, True
        chunks.append(chunk)
    return b"".join(chunks), False


class CappedResponse:
    """post_capped 返回的轻量响应对象：接口对齐 httpx.Response 的常用面。

    只保留调用方实际用到的 status_code / headers / text / json()，
    body 已在上限内完整读入内存（流式阶段已执行上限）。
    """

    def __init__(self, status_code: int, headers, content: bytes,
                 encoding: str | None = None):
        self.status_code = status_code
        self.headers = headers
        self.content = content
        self.encoding = encoding or "utf-8"

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding, errors="replace")

    def json(self):
        return json.loads(self.text)


def post_capped(url: str, *, limit: int | None = None, **kwargs) -> CappedResponse:
    """流式 POST 并执行字节上限，返回 CappedResponse。

    kwargs 透传 httpx.stream（json= / data= / headers= / timeout= 等）。
    超限抛 ResponseTooLarge 并留 warning log；网络异常/超时原样抛给
    调用方（各端点既有异常降级口径不变）。
    limit=None 时调用时读模块常量 MAX_POST_BYTES（便于测试调小上限）。
    """
    if limit is None:
        limit = MAX_POST_BYTES
    with httpx.stream("POST", url, **kwargs) as r:
        status = r.status_code
        headers = r.headers
        encoding = r.encoding
        body, too_large = collect_capped(r, limit)
        if too_large:
            logger.warning(
                "POST 响应过大（超过 %s 字节上限），已停止读取：url=%s",
                limit, url)
            raise ResponseTooLarge(limit, url)
        return CappedResponse(status, headers, body or b"", encoding)


def get_json_capped(url: str, *, params=None, headers=None,
                    timeout: float = 15, limit: int | None = None) -> dict:
    """流式 GET 一个 JSON 端点并执行字节上限。

    返回 {"status_code": int, "data": 解析结果或 None,
          "too_large": bool, "json_error": bool}：
    - 非 200：只回 status_code，不读 body（调用方按状态码降级）；
    - 200 且超限：too_large=True、data=None，并留 warning log；
    - 200 且非 JSON：json_error=True、data=None；
    - 网络异常/超时：原样抛给调用方（各端点既有异常降级口径不变）。
    limit=None 时调用时读模块常量 MAX_JSON_BYTES（便于测试调小上限）。
    """
    if limit is None:
        limit = MAX_JSON_BYTES
    with httpx.stream("GET", url, params=params, headers=headers,
                      timeout=timeout) as r:
        status = r.status_code
        if status != 200:
            return {"status_code": status, "data": None,
                    "too_large": False, "json_error": False}
        encoding = r.encoding or "utf-8"
        body, too_large = collect_capped(r, limit)
        if too_large:
            logger.warning(
                "JSON API 响应过大（超过 %s 字节上限），已停止读取：url=%s",
                limit, url)
            return {"status_code": status, "data": None,
                    "too_large": True, "json_error": False}
        try:
            data = json.loads((body or b"").decode(encoding,
                                                   errors="replace"))
        except Exception:  # noqa: BLE001
            return {"status_code": status, "data": None,
                    "too_large": False, "json_error": True}
        return {"status_code": status, "data": data,
                "too_large": False, "json_error": False}
