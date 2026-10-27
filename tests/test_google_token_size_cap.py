"""Google OAuth token 响应大小上限测试.

exchange_code 改走共享 helper app/services/http_capped.post_capped
（流式 + MAX_POST_BYTES 上限，与 MAX_PAGE_BYTES 同值）：
超限/非 200/非 JSON 一律收敛为既有 GoogleAuthError("verify_failed")，
不外泄上游细节、不改变用户可见文案；正常响应口径不变。
JWKS 走 PyJWKClient 自带缓存/上限，不在本项范围。
全部用替身，不碰公网、不读真实凭证。
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.core import google_auth
from app.services import http_capped
from app.services import research_pipeline as rp


class _Resp:
    """httpx.stream 替身的流式响应。"""

    def __init__(self, body=b"", headers=None, status_code=200,
                 ctype="application/json"):
        self.status_code = status_code
        if isinstance(body, bytes):
            self._body = body
        elif isinstance(body, str):
            self._body = body.encode()
        else:
            self._body = json.dumps(body).encode()
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


@pytest.fixture()
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI",
                       "https://dealdesk.vercel.app/auth/google/callback")


def test_constant_matches_post_and_page_cap():
    assert google_auth.MAX_TOKEN_BYTES == http_capped.MAX_POST_BYTES
    assert http_capped.MAX_POST_BYTES == rp.MAX_PAGE_BYTES == 2_000_000


def test_exchange_under_cap_ok(env, monkeypatch):
    _patch_stream(monkeypatch, _Resp(body={"id_token": "tok-123",
                                           "access_token": "at"}))
    out = google_auth.exchange_code("code-1", "verifier-1")
    assert out["id_token"] == "tok-123"


def test_exchange_exactly_at_cap_ok(env, monkeypatch):
    body = json.dumps({"id_token": "tok-123"}).encode()
    monkeypatch.setattr(google_auth, "MAX_TOKEN_BYTES", len(body))
    _patch_stream(monkeypatch, _Resp(body=body))
    out = google_auth.exchange_code("code-1", "verifier-1")
    assert out["id_token"] == "tok-123"


def test_exchange_streamed_over_cap_verify_failed(env, monkeypatch):
    monkeypatch.setattr(google_auth, "MAX_TOKEN_BYTES", 100)
    body = json.dumps({"id_token": "x" * 500}).encode()
    _patch_stream(monkeypatch, _Resp(body=body))
    with pytest.raises(google_auth.GoogleAuthError) as ei:
        google_auth.exchange_code("code-1", "verifier-1")
    assert ei.value.code == "verify_failed"


def test_exchange_content_length_precheck_skips_body(env, monkeypatch):
    monkeypatch.setattr(google_auth, "MAX_TOKEN_BYTES", 100)
    body = json.dumps({"id_token": "tok"}).encode() + b"x" * 500
    resp = _Resp(body=body, headers={"content-length": str(len(body))})
    _patch_stream(monkeypatch, resp)
    with pytest.raises(google_auth.GoogleAuthError) as ei:
        google_auth.exchange_code("code-1", "verifier-1")
    assert ei.value.code == "verify_failed"
    assert resp.iter_called is False  # 预检命中直接停手，不读 body


def test_exchange_non_200_verify_failed(env, monkeypatch):
    _patch_stream(monkeypatch,
                  _Resp(body={"error": "invalid_grant"}, status_code=400))
    with pytest.raises(google_auth.GoogleAuthError) as ei:
        google_auth.exchange_code("bad-code", "verifier-1")
    assert ei.value.code == "verify_failed"


def test_exchange_non_json_verify_failed(env, monkeypatch):
    _patch_stream(monkeypatch, _Resp(body=b"not-json{",
                                     ctype="text/plain"))
    with pytest.raises(google_auth.GoogleAuthError) as ei:
        google_auth.exchange_code("code-1", "verifier-1")
    assert ei.value.code == "verify_failed"


def test_exchange_missing_id_token_verify_failed(env, monkeypatch):
    _patch_stream(monkeypatch, _Resp(body={"access_token": "at-only"}))
    with pytest.raises(google_auth.GoogleAuthError) as ei:
        google_auth.exchange_code("code-1", "verifier-1")
    assert ei.value.code == "verify_failed"
