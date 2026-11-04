"""JWKS 拉取响应大小上限测试（台账第 34 项）。

查实结论：PyJWT 2.15.1 的 PyJWKClient.fetch_data 用 urllib + json.load(response)
整页读入，无字节上限（只有 timeout 与缓存 lifespan）。google_auth 改用
_CappedPyJWKClient：fetch_data 改走共享 helper
app/services/http_capped.get_json_capped（流式 + MAX_JSON_BYTES 上限）：
超限/非 200/拉取失败一律按 PyJWKClient 既有异常契约收敛，
verify_id_token 侧仍收敛为 GoogleAuthError("verify_failed")，口径不变。
全部用替身，不碰公网、不读真实凭证。
"""

from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError

from app.core import google_auth
from app.services import http_capped
from app.services import research_pipeline as rp

_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
KID = "test-kid-1"


def _jwks_body() -> bytes:
    jwk = RSAAlgorithm.to_jwk(_key.public_key(), as_dict=True)
    jwk.update({"kid": KID, "use": "sig", "alg": "RS256"})
    return json.dumps({"keys": [jwk]}).encode()


def _id_token() -> str:
    now = int(time.time())
    return jwt.encode(
        {"iss": "https://accounts.google.com", "aud": "test-client-id",
         "iat": now, "exp": now + 3600, "email": "boss@example.com",
         "email_verified": True, "name": "Boss"},
        _key, algorithm="RS256", headers={"kid": KID})


class _Resp:
    """httpx.stream 替身的流式响应（与 test_google_token_size_cap 同式）。"""

    def __init__(self, body=b"", headers=None, status_code=200,
                 ctype="application/json"):
        self.status_code = status_code
        self._body = body if isinstance(body, bytes) else body.encode()
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


def _client() -> google_auth._CappedPyJWKClient:
    return google_auth._CappedPyJWKClient(
        google_auth.JWKS_URL, cache_keys=True, lifespan=3600)


def test_constant_matches_json_and_page_cap():
    assert google_auth.MAX_JWKS_BYTES == http_capped.MAX_JSON_BYTES
    assert http_capped.MAX_JSON_BYTES == rp.MAX_PAGE_BYTES == 2_000_000


def test_jwks_under_cap_ok_and_signing_key_usable(monkeypatch):
    _patch_stream(monkeypatch, _Resp(body=_jwks_body()))
    client = _client()
    data = client.fetch_data()
    assert data["keys"][0]["kid"] == KID
    # 经 PyJWKClient 既有 kid 匹配链能取到可验签的 key（缓存命中、不再出网）
    signing = client.get_signing_key_from_jwt(_id_token())
    assert signing.key == _key.public_key()


def test_jwks_exactly_at_cap_ok(monkeypatch):
    body = _jwks_body()
    monkeypatch.setattr(google_auth, "MAX_JWKS_BYTES", len(body))
    _patch_stream(monkeypatch, _Resp(body=body))
    data = _client().fetch_data()
    assert data["keys"][0]["kid"] == KID


def test_jwks_streamed_over_cap_rejected(monkeypatch):
    monkeypatch.setattr(google_auth, "MAX_JWKS_BYTES", 100)
    _patch_stream(monkeypatch, _Resp(body=_jwks_body()))
    with pytest.raises(PyJWKClientConnectionError):
        _client().fetch_data()


def test_jwks_content_length_precheck_skips_body(monkeypatch):
    monkeypatch.setattr(google_auth, "MAX_JWKS_BYTES", 100)
    body = _jwks_body()
    resp = _Resp(body=body, headers={"content-length": str(len(body))})
    _patch_stream(monkeypatch, resp)
    with pytest.raises(PyJWKClientConnectionError):
        _client().fetch_data()
    assert resp.iter_called is False  # 预检命中直接停手，不读 body


def test_jwks_non_200_rejected(monkeypatch):
    _patch_stream(monkeypatch, _Resp(body=b"oops", status_code=500))
    with pytest.raises(PyJWKClientConnectionError):
        _client().fetch_data()


def test_jwks_non_json_rejected(monkeypatch):
    _patch_stream(monkeypatch, _Resp(body=b"not-json{", ctype="text/plain"))
    with pytest.raises(PyJWKClientError):
        _client().fetch_data()


def test_jwks_fetch_failure_rejected(monkeypatch):
    def _boom(*a, **k):
        raise httpx.ConnectError("boom", request=httpx.Request("GET", google_auth.JWKS_URL))
    _patch_stream(monkeypatch, _boom)
    with pytest.raises(PyJWKClientConnectionError):
        _client().fetch_data()


def test_verify_id_token_over_cap_converges_verify_failed(env, monkeypatch):
    monkeypatch.setattr(google_auth, "MAX_JWKS_BYTES", 100)
    _patch_stream(monkeypatch, _Resp(body=_jwks_body()))
    monkeypatch.setattr(google_auth, "_jwks", _client)
    with pytest.raises(google_auth.GoogleAuthError) as ei:
        google_auth.verify_id_token(_id_token())
    assert ei.value.code == "verify_failed"


def test_verify_id_token_capped_jwks_happy_path(env, monkeypatch):
    _patch_stream(monkeypatch, _Resp(body=_jwks_body()))
    monkeypatch.setattr(google_auth, "_jwks", _client)
    ident = google_auth.verify_id_token(_id_token())
    assert ident.email == "boss@example.com" and ident.name == "Boss"
