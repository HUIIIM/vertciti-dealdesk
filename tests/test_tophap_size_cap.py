"""TopHap MCP / token 端点响应大小上限测试.

POST 型 JSON 调用改走共享 helper app/services/http_capped.post_capped
（流式 + MAX_POST_BYTES 上限，与 MAX_PAGE_BYTES 同值）：
- tophap._rpc：超限抛 MCPError（中文「响应过大」），enrich 诚实降级
  ok=False，不整页读入内存、不截断残页凑解析；
- token_watch 刷新：超限按刷新失败处理（refreshed=False + 中文原因，
  旧 token 与 .env 不动）。
全部用替身，不碰公网、不读真实 token。
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app import token_watch, tophap
from app.services import http_capped
from app.services import research_pipeline as rp


class _Resp:
    """httpx.stream 替身的流式响应。"""

    def __init__(self, body=b"", headers=None, status_code=200,
                 ctype="application/json"):
        self.status_code = status_code
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.headers = {"content-type": ctype, **(headers or {})}
        self.encoding = "utf-8"
        self.iter_called = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_bytes(self, chunk_size=65536):
        self.iter_called = True
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]


def _patch_stream(monkeypatch, resp_or_fn):
    fn = resp_or_fn if callable(resp_or_fn) and not isinstance(resp_or_fn, _Resp) \
        else (lambda *a, **k: resp_or_fn)
    monkeypatch.setattr(http_capped.httpx, "stream", fn)


def _rpc_ok_body(text="{}"):
    return {"jsonrpc": "2.0", "id": 1,
            "result": {"content": [{"type": "text", "text": text}]}}


# ---------- helper 本体 ----------

def test_post_cap_constant_matches_page_cap():
    assert http_capped.MAX_POST_BYTES == rp.MAX_PAGE_BYTES == 2_000_000
    assert tophap.MAX_RPC_BYTES == http_capped.MAX_POST_BYTES
    assert token_watch.MAX_TOKEN_BYTES == http_capped.MAX_POST_BYTES


def test_helper_under_cap_parses_json(monkeypatch):
    _patch_stream(monkeypatch, _Resp(body={"a": 1}))
    r = http_capped.post_capped("https://example.test/x", json={})
    assert r.status_code == 200
    assert r.json() == {"a": 1}
    assert r.text == '{"a": 1}'


def test_helper_exactly_at_cap_ok(monkeypatch):
    body = json.dumps({"a": 1}).encode()
    _patch_stream(monkeypatch, _Resp(body=body))
    r = http_capped.post_capped("https://example.test/x", limit=len(body))
    assert r.json() == {"a": 1}


def test_helper_content_length_precheck_skips_body(monkeypatch):
    body = json.dumps({"a": 1}).encode() + b"x" * 500
    resp = _Resp(body=body, headers={"content-length": str(len(body))})
    _patch_stream(monkeypatch, resp)
    with pytest.raises(http_capped.ResponseTooLarge):
        http_capped.post_capped("https://example.test/x", limit=100)
    assert resp.iter_called is False  # 预检命中直接停手，不读 body


def test_helper_streamed_over_cap_stops(monkeypatch, caplog):
    body = json.dumps({"a": "x" * 500}).encode()
    _patch_stream(monkeypatch, _Resp(body=body))
    with caplog.at_level(logging.WARNING, logger=http_capped.logger.name):
        with pytest.raises(http_capped.ResponseTooLarge):
            http_capped.post_capped("https://example.test/x", limit=100)
    assert any("响应过大" in rec.message for rec in caplog.records)


# ---------- TopHap MCP 路 ----------

def test_tophap_rpc_over_cap_mcp_error(monkeypatch):
    monkeypatch.setattr(tophap, "MAX_RPC_BYTES", 100)
    body = json.dumps(_rpc_ok_body('{"k": "' + "x" * 500 + '"}')).encode()
    _patch_stream(monkeypatch, _Resp(body=body))
    with pytest.raises(tophap.MCPError) as ei:
        tophap._rpc("tools/call", {"name": "x", "arguments": {}})
    assert "响应过大" in str(ei.value)
    assert "2000000" not in str(ei.value)  # 用的是调小后的上限，不是写死常量


def test_tophap_enrich_over_cap_honest_degrade(monkeypatch):
    monkeypatch.setenv("TOPHAP_ENABLED", "1")
    monkeypatch.setenv("TOPHAP_ACCESS_TOKEN", "fake-at")
    monkeypatch.setattr(tophap, "MAX_RPC_BYTES", 100)
    body = json.dumps(_rpc_ok_body()).encode() + b" " * 500
    _patch_stream(monkeypatch, _Resp(body=body))
    out = tophap.enrich_address("123 Main St, Tampa, FL 33602")
    assert out["ok"] is False
    assert out["fields"] == []
    assert "响应过大" in out["note"]


def test_tophap_rpc_under_cap_ok(monkeypatch):
    _patch_stream(monkeypatch, _Resp(body=_rpc_ok_body('{"attomId": 1}')))
    out = tophap._rpc("tools/call", {"name": "x", "arguments": {}})
    assert out == {"content": [{"type": "text", "text": '{"attomId": 1}'}]}


def test_tophap_rpc_sse_over_cap_stops(monkeypatch):
    monkeypatch.setattr(tophap, "MAX_RPC_BYTES", 100)
    sse = "data: " + json.dumps(_rpc_ok_body()) + "\n" + "data: " + "x" * 500
    _patch_stream(monkeypatch, _Resp(body=sse.encode(),
                                     ctype="text/event-stream"))
    with pytest.raises(tophap.MCPError) as ei:
        tophap._rpc("tools/call", {"name": "x", "arguments": {}})
    assert "响应过大" in str(ei.value)


# ---------- token 刷新路 ----------

def _setup_refresh_env(tmp_path, monkeypatch):
    now = int(time.time())
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TOPHAP_ACCESS_TOKEN=tok-old\n"
        "TOPHAP_REFRESH_TOKEN=ref-old\n"
        "TOPHAP_TOKEN_ENDPOINT=https://auth.example/token\n"
        "TOPHAP_CLIENT_ID=cid-123\n"
        f"TOPHAP_TOKEN_EXPIRES_AT={now - 100}\n")
    monkeypatch.setattr(tophap, "dotenv_path", lambda: env_file)
    return env_file


def test_token_refresh_over_cap_keeps_old_token(tmp_path, monkeypatch):
    env_file = _setup_refresh_env(tmp_path, monkeypatch)
    before = env_file.read_text()
    monkeypatch.setattr(token_watch, "MAX_TOKEN_BYTES", 100)
    body = json.dumps({"access_token": "tok-new",
                       "pad": "x" * 500}).encode()
    _patch_stream(monkeypatch, _Resp(body=body))
    r = token_watch.ensure_fresh_token()
    assert r["refreshed"] is False
    assert "响应过大" in r["reason"]
    assert env_file.read_text() == before  # 超限不写 .env，旧 token 保留


def test_token_refresh_under_cap_ok(tmp_path, monkeypatch):
    env_file = _setup_refresh_env(tmp_path, monkeypatch)
    _patch_stream(monkeypatch, _Resp(body={"access_token": "tok-new",
                                           "expires_in": 3600}))
    r = token_watch.ensure_fresh_token()
    assert r["refreshed"] is True
    assert "TOPHAP_ACCESS_TOKEN=tok-new" in env_file.read_text()
