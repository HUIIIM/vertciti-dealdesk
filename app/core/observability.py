"""可观测（v2 蓝图 §7）：请求编号、结构化日志、错误上报、身份注入中间件。

- 每个请求带 X-Request-ID（沿用入站值或新生成），回写到响应头，并注入日志与审计记录。
- 日志为单行 JSON（ts / level / logger / msg / request_id / actor + 额外字段），便于 Vercel / 日志平台检索。
- 未捕获异常：记录完整堆栈、写入内存环形缓冲（/api/v2/admin/errors 可查最近 100 条），
  设了 DEALDESK_ERROR_WEBHOOK 时异步 POST 一份摘要（不含请求体，避免泄露交易数据）；
  响应 500 JSON，带 request_id 便于对账。
- webhook 响应大小上限：上报改走 http_capped.post_capped 流式读取，
  响应体只确认送达、不解析；超限即停手并按上报失败处理（见 MAX_WEBHOOK_BYTES）。
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import traceback
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core import security, sessions
from app.core.context import current_actor, current_request_id, reset_actor, set_actor, set_request_id
from app.core.hardening import AUTH_THROTTLE, client_ip, headers_for
from app.core.i18n import T, lang_from_header, reset_lang, set_lang
from app.services import http_capped

log = logging.getLogger("dealdesk")
access_log = logging.getLogger("dealdesk.access")
# 错误上报 webhook 响应大小上限：与 POST 型 JSON 上限同值。
# webhook 端点为环境配置的外部 HTTP 地址，响应体本就被丢弃不用；
# 此前 httpx.post 非流式调用仍会把响应体整页读入内存，异常/被劫持的
# 端点返回超大或无界响应时可白吃内存、长挂上报线程。改走流式上限后
# 超限即停手，按上报失败处理（只记 warning，不影响主流程）。
MAX_WEBHOOK_BYTES = http_capped.MAX_POST_BYTES
RECENT_ERRORS: deque[dict[str, Any]] = deque(maxlen=100)
_RID_OK = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
# SEC-A1（2026-10-26）：DEALDESK_AUTH_PROTECT_V1 门控的 v1 持久化面——读/写项目库、
# 对比、研究证据与摄入待处理队列的路径。无状态计算面（/api/score 等）不在此列、保持公开
# （口径由 tests/test_v2_security.py::test_v1_protection_is_opt_in 钉住）。
# IVV-37（2026-10-27）：同一枚举门扩入 TopHap 配额面——后端会真调用 TopHap（付费
# 数据源）的匿名可达路由：comps 拉取、产权穿透（TopHap 解析持有人）、卖方动机分
# （TopHap 信号）、地址/链接搜集链（providers 链首源即 TopHap）。纯公开数据源面
# （Socrata/Census/DDG/EchoWatch）与状态面（/api/tophap/status 发现握手）不在此列。
_V1_PROTECTED = re.compile(
    r"^/api/(projects|uw/projects|compare|wb/research|wb/intake/pending|wb/intake/extracted"
    r"|wb/comps/pull|wb/ownership/tree|wb/sell-readiness/score|wb/intake/run)(/|$)")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        d = {"ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
             "level": record.levelname, "logger": record.name, "msg": record.getMessage(),
             "request_id": current_request_id() or None, "actor": current_actor().username}
        d.update(getattr(record, "extra_fields", {}))
        if record.exc_info:
            d["exc"] = "".join(traceback.format_exception(*record.exc_info))[-4000:]
        return json.dumps(d, ensure_ascii=False, default=str)


def configure_logging() -> None:
    root = logging.getLogger("dealdesk")
    if any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        return
    h = logging.StreamHandler()
    h.setFormatter(JsonFormatter())
    root.addHandler(h)
    root.setLevel(os.environ.get("DEALDESK_LOG_LEVEL", "INFO").upper())
    root.propagate = False


def _report(err: dict[str, Any]) -> None:
    RECENT_ERRORS.appendleft(err)
    url = os.environ.get("DEALDESK_ERROR_WEBHOOK", "").strip()
    if not url:
        return

    def _send() -> None:
        try:
            # 流式 POST＋上限：响应体只确认送达、不解析；超限抛
            # ResponseTooLarge，与网络异常一并收敛为上报失败。
            http_capped.post_capped(
                url, json={k: err[k] for k in ("at", "request_id", "path", "method", "error")},
                timeout=5, limit=MAX_WEBHOOK_BYTES)
        except Exception:  # noqa: BLE001 — 上报失败不影响主流程
            log.warning("error webhook 上报失败")
    threading.Thread(target=_send, daemon=True).start()


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = request.headers.get("x-request-id", "")
        rid = rid if _RID_OK.match(rid) else uuid.uuid4().hex
        rid_tok = set_request_id(rid)
        # 凭证两路：Authorization Bearer（API/应急令牌，浏览器不自动携带）优先；
        # 其次浏览器会话 cookie（Google 登录签发，服务端可吊销）——cookie 会被浏览器自动携带，
        # 故 cookie 身份的写请求另做 Origin 同源校验（与 SameSite=Lax 双保险，见下方 csrf_blocked）。
        auth = request.headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else None
        client = client_ip(request.client.host if request.client else None, request.headers.get("x-forwarded-for"))
        wait = AUTH_THROTTLE.blocked(client) if token and security.auth_enabled() else 0.0
        session_raw = request.cookies.get(sessions.COOKIE_NAME) if security.auth_enabled() else None
        resolved = None if token or wait else sessions.resolve_session(session_raw)
        actor = security.ANONYMOUS if wait else (resolved.actor if resolved else security.resolve_token(token))
        if token and not wait and actor is security.ANONYMOUS:
            AUTH_THROTTLE.fail(client)
            log.warning("invalid token", extra={"extra_fields": {"client": client}})
        origin = request.headers.get("origin", "")
        csrf_blocked = bool(
            resolved and request.method not in ("GET", "HEAD", "OPTIONS")
            and request.url.path.startswith("/api/")
            and origin and urlparse(origin).netloc != request.headers.get("host", ""))
        act_tok = set_actor(actor)
        lang_tok = set_lang(lang_from_header(request.headers.get("x-dd-lang")))
        t0 = time.perf_counter()
        path, method = request.url.path, request.method
        try:
            if wait:
                resp: Response = JSONResponse({"detail": T("令牌错误次数过多，请稍后再试"), "request_id": rid},
                                              status_code=429, headers={"Retry-After": str(int(wait) + 1)})
            elif csrf_blocked:
                resp = JSONResponse({"detail": T("请求来源异常，已拒绝"), "request_id": rid}, status_code=403)
            elif (security.protect_v1() and _V1_PROTECTED.match(path) and (
                    # IVV-37（2026-10-27）：写方法集补 PATCH（此前缺失；v1 暂无 PATCH
                    # 路由属潜伏缺口，先补齐免得日后新增 PATCH 面裸奔）。
                    (method in ("POST", "PUT", "PATCH", "DELETE") and not security.can(actor, "deal.write"))
                    or (method == "GET" and (actor is security.ANONYMOUS or not security.can(actor, "deal.read"))))):
                resp = JSONResponse(
                    {"detail": T("需要“分析”及以上角色") if method != "GET" else T("需要登录：请提供有效的访问令牌"),
                     "request_id": rid},
                    status_code=401 if actor is security.ANONYMOUS else 403)
            else:
                resp = await call_next(request)
        except Exception as e:
            err = {"at": datetime.now(timezone.utc).isoformat(), "request_id": rid, "path": path,
                   "method": method, "actor": actor.username, "error": f"{type(e).__name__}: {str(e)[:300]}",
                   "trace": traceback.format_exc()[-4000:]}
            log.exception("unhandled exception",
                          extra={"extra_fields": {"path": path, "method": method}})
            _report(err)
            resp = JSONResponse({"detail": T("服务器内部错误"), "request_id": rid}, status_code=500)
        resp.headers["X-Request-ID"] = rid
        for k, v in headers_for(path).items():
            resp.headers.setdefault(k, v)
        if resolved and resolved.renew and session_raw:  # 会话滑动续期：剩余不足半程时重发 30 天 cookie
            resp.set_cookie(sessions.COOKIE_NAME, session_raw, max_age=sessions.SESSION_DAYS * 86400,
                            path="/", httponly=True, secure=sessions.cookie_secure(), samesite="lax")
        if path.startswith("/api/"):  # 在重置身份之前写，日志里的 actor 才是本次请求的操作人
            access_log.info("request", extra={"extra_fields": {
                "method": method, "path": path, "status": resp.status_code,
                "ms": round((time.perf_counter() - t0) * 1000, 1)}})
        reset_lang(lang_tok)
        reset_actor(act_tok)
        set_request_id("")  # 不跨请求泄漏
        del rid_tok
        return resp
