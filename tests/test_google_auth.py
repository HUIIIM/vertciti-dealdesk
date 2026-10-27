"""Google 登录（OAuth + PKCE + 会话 cookie）：假 JWKS / 假 token 端点全流程，不出网。

覆盖：放行与 cookie 属性、验签失败拒、email_verified=false 拒、未建档拒、停用拒、
state 不符拒、无事务拒、PKCE 缺失拒、登出吊销、跨源写请求 403、滑动续期。
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core import google_auth, security
from app.main import app
from app.services.persistence.engine import session_scope
from app.services.persistence.schema import User, WebSession

CID = "test-client-id"
BOSS = "boss@example.com"

_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_bad_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _FakeJWKClient:
    def get_signing_key_from_jwt(self, token: str) -> SimpleNamespace:
        return SimpleNamespace(key=_key.public_key())


def _id_token(email: str = BOSS, *, verified: bool = True, aud: str = CID,
              iss: str = "https://accounts.google.com", key: rsa.RSAPrivateKey = _key,
              exp_delta: int = 3600) -> str:
    now = int(time.time())
    return jwt.encode({"iss": iss, "aud": aud, "iat": now, "exp": now + exp_delta,
                       "email": email, "email_verified": verified, "name": "Boss"},
                      key, algorithm="RS256", headers={"kid": "test-kid"})


@pytest.fixture()
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEALDESK_AUTH", "on")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://dealdesk.vercel.app/auth/google/callback")
    monkeypatch.setenv("DEALDESK_SESSION_COOKIE_SECURE", "0")
    monkeypatch.setattr(google_auth, "_jwks", lambda: _FakeJWKClient())


def _fake_token_endpoint(token: str) -> object:
    def _post(url: str, data: dict, timeout: float = 0) -> httpx.Response:
        req = httpx.Request("POST", url)
        if not data.get("code_verifier"):
            return httpx.Response(400, json={"error": "invalid_grant"}, request=req)
        return httpx.Response(200, json={"id_token": token}, request=req)
    return _post


class _StreamResp:
    """把 httpx.Response 包成 httpx.stream 的流式替身。"""

    def __init__(self, resp: httpx.Response) -> None:
        self._resp = resp
        self.status_code = resp.status_code
        self.headers = resp.headers
        self.encoding = "utf-8"

    def __enter__(self) -> _StreamResp:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def iter_bytes(self, chunk_size: int = 65536):  # type: ignore[no-untyped-def]
        body = self._resp.content
        for i in range(0, len(body), chunk_size):
            yield body[i:i + chunk_size]


def _patch_token_endpoint(monkeypatch: pytest.MonkeyPatch, token: str) -> None:
    """生产 exchange_code 已改 http_capped.post_capped（httpx.stream）：把
    fake_post 适配成 stream 替身，fake 本体逻辑（PKCE 校验）不变。"""
    fake_post = _fake_token_endpoint(token)

    def fake_stream(method: str, url: str, **kwargs: object) -> _StreamResp:
        return _StreamResp(fake_post(url, **kwargs))  # type: ignore[arg-type]

    # http_capped 是 google_auth 实际调用的模块，其 httpx 与 google_auth.httpx 同一对象
    monkeypatch.setattr(google_auth.http_capped.httpx, "stream", fake_stream)


def _ensure_user(username: str, role: str, display: str, active: bool = True) -> None:
    with session_scope() as s:
        u = s.scalar(select(User).where(User.username == username))
        if u is None:
            s.add(User(username=username, role=role, display_name=display, active=active,
                       token_sha256=security.token_hash("dd_seed_" + username), created_by="test"))
        else:
            u.active = active


@pytest.fixture()
def client(env: None) -> TestClient:
    _ensure_user(BOSS, "chairman", "老板")
    _ensure_user("off@example.com", "analyst", "停用号", active=False)
    return TestClient(app, follow_redirects=False)


def _begin(c: TestClient) -> tuple[str, dict[str, str]]:
    r = c.get("/auth/google/login")
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "code_challenge_method=S256" in loc and "code_challenge=" in loc
    from urllib.parse import parse_qs, urlparse
    state = parse_qs(urlparse(loc).query)["state"][0]
    return state, {"dd_oauth_tx": r.cookies.get("dd_oauth_tx", "")}


def _callback(c: TestClient, monkeypatch: pytest.MonkeyPatch, id_token: str,
              cookies: dict[str, str], state: str) -> httpx.Response:
    _patch_token_endpoint(monkeypatch, id_token)
    return c.get("/auth/google/callback", params={"code": "fake-code", "state": state}, cookies=cookies)


def test_happy_path_and_cookie_attrs(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    state, cookies = _begin(client)
    r = _callback(client, monkeypatch, _id_token("Boss@Example.com"), cookies, state)  # 邮箱大小写不敏感
    assert r.status_code == 302 and r.headers["location"] == "/app/"
    sc = r.headers["set-cookie"]
    assert "dd_session=" in sc and "HttpOnly" in sc and "SameSite=lax" in sc and "Max-Age=2592000" in sc
    raw = r.cookies.get("dd_session", "")
    assert raw.startswith("dd_sess_")
    me = client.get("/api/v2/me", cookies={"dd_session": raw})
    assert me.status_code == 200
    body = me.json()
    assert body["username"] == BOSS and body["role"] == "chairman"
    assert body["google_login"] is True and body["token_login"] is False


def test_bad_signature_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    state, cookies = _begin(client)
    r = _callback(client, monkeypatch, _id_token(key=_bad_key), cookies, state)
    assert "login_error=verify_failed" in r.headers["location"]


def test_email_unverified_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    state, cookies = _begin(client)
    r = _callback(client, monkeypatch, _id_token(verified=False), cookies, state)
    assert "login_error=email_unverified" in r.headers["location"]


def test_not_provisioned_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    state, cookies = _begin(client)
    r = _callback(client, monkeypatch, _id_token("stranger@example.com"), cookies, state)
    assert "login_error=not_provisioned" in r.headers["location"]


def test_disabled_user_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    state, cookies = _begin(client)
    r = _callback(client, monkeypatch, _id_token("off@example.com"), cookies, state)
    assert "login_error=disabled" in r.headers["location"]


def test_state_mismatch_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _state, cookies = _begin(client)
    r = _callback(client, monkeypatch, _id_token(), cookies, "wrong-state")
    assert "login_error=state_mismatch" in r.headers["location"]


def test_missing_tx_cookie_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    r = _callback(client, monkeypatch, _id_token(), {}, "any-state")
    assert "login_error=state_mismatch" in r.headers["location"]


def test_missing_pkce_verifier_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.google_auth import _sign_tx
    cookies = {"dd_oauth_tx": _sign_tx("st", "")}  # 事务里 verifier 为空：token 端点按 PKCE 校验拒
    r = _callback(client, monkeypatch, _id_token(), cookies, "st")
    assert "login_error=verify_failed" in r.headers["location"]


def test_logout_revokes_and_csrf_origin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    state, cookies = _begin(client)
    r = _callback(client, monkeypatch, _id_token(), cookies, state)
    raw = r.cookies.get("dd_session", "")
    # 跨源 Origin 的 cookie 写请求：/api 面被中间件 403、登出端点自身亦校验 403
    api_evil = client.put("/api/v2/settings/views", json={"name": "x", "config": {}},
                          cookies={"dd_session": raw}, headers={"Origin": "https://evil.example"})
    assert api_evil.status_code == 403
    evil = client.post("/auth/logout", cookies={"dd_session": raw},
                       headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403
    out = client.post("/auth/logout", cookies={"dd_session": raw},
                      headers={"Origin": "http://testserver"})
    assert out.status_code == 200
    me = client.get("/api/v2/me", cookies={"dd_session": raw})
    assert me.json()["username"] == "anonymous"


def test_sliding_renewal(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    state, cookies = _begin(client)
    r = _callback(client, monkeypatch, _id_token(), cookies, state)
    raw = r.cookies.get("dd_session", "")
    th = security.token_hash(raw)
    with session_scope() as s:  # 把过期时间压到剩 10 天（< 半程 15 天）应触发续期
        row = s.scalar(select(WebSession).where(WebSession.token_sha256 == th))
        assert row is not None
        row.expires_at = datetime.now(timezone.utc) + timedelta(days=10)
    me = client.get("/api/v2/me", cookies={"dd_session": raw})
    assert me.status_code == 200
    assert "dd_session=" in me.headers.get("set-cookie", "")
    with session_scope() as s:
        row = s.scalar(select(WebSession).where(WebSession.token_sha256 == th))
        assert row is not None
        exp = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
        assert exp > datetime.now(timezone.utc) + timedelta(days=25)
