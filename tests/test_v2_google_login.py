"""Google 登录（邀请制）：只有登记过邮箱的人能进；所有者第一次登录自动建董事长；state / nonce / aud 任一不对都拒绝；
会话令牌能用、能退出、过期作废、停用用户立即失效；邮箱在设置里邀请与撤销。"""
from __future__ import annotations

from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.core import security
from app.main import app
from app.services.persistence.engine import session_scope
from app.services.persistence.schema import UserSession, utcnow
from app.services.v2 import google_auth

CID = "cid.apps.googleusercontent.com"


class _Resp:
    def __init__(self, status: int, body: dict) -> None:
        self.status_code, self._body = status, body

    def json(self) -> dict:
        return self._body


@pytest.fixture
def g(tmp_path, monkeypatch):
    """开认证 + 配好 Google；Google 的两个端点换成假的：claims 里放什么，tokeninfo 就回什么。"""
    monkeypatch.setenv("DEALDESK_DB", str(tmp_path / "g.db"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DEALDESK_AUTH", "on")
    monkeypatch.setenv("DEALDESK_GOOGLE_CLIENT_ID", CID)
    monkeypatch.setenv("DEALDESK_GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("DEALDESK_PUBLIC_URL", "https://dd.example")
    monkeypatch.setenv("DEALDESK_OWNER_EMAIL", "Owner@Example.com")
    box: dict = {"claims": {}, "posted": {}}

    def post(url, data=None, timeout=None):
        assert url == google_auth.TOKEN_URL
        box["posted"] = data
        return _Resp(200, {"id_token": "idt"}) if data["code"] == "good" else _Resp(400, {"error": "invalid_grant"})

    def get(url, params=None, timeout=None):
        assert url == google_auth.TOKENINFO_URL and params == {"id_token": "idt"}
        return _Resp(200, box["claims"])

    monkeypatch.setattr(google_auth.httpx, "post", post)
    monkeypatch.setattr(google_auth.httpx, "get", get)
    chair = security.add_user("chair", "chairman")
    return TestClient(app, follow_redirects=False), box, chair


def _login(c: TestClient, box: dict, email: str, **over) -> str:
    """走一遍：start → 取 state / nonce → callback。返回跳回前端的片段（auth=… 或 auth_error=…）。"""
    r = c.get("/api/v2/auth/google/start")
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["client_id"] == [CID] and q["redirect_uri"] == ["https://dd.example/api/v2/auth/google/callback"]
    assert q["scope"] == ["openid email profile"]
    box["claims"] = {"aud": CID, "iss": "https://accounts.google.com", "nonce": q["nonce"][0], "email": email,
                     "email_verified": "true", "name": "Pat", **over.pop("claims", {})}
    state = over.pop("state", q["state"][0])
    cb = c.get("/api/v2/auth/google/callback", params={"code": over.pop("code", "good"), "state": state})
    assert cb.status_code == 302 and cb.headers["location"].startswith("/app/#")
    return cb.headers["location"].split("#", 1)[1]


def H(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def test_providers_and_not_configured(g, monkeypatch):
    c, _, _ = g
    assert c.get("/api/v2/auth/providers").json() == {"google": True}
    monkeypatch.delenv("DEALDESK_GOOGLE_CLIENT_SECRET")
    assert c.get("/api/v2/auth/providers").json() == {"google": False}
    assert c.get("/api/v2/auth/google/start").headers["location"] == "/app/#auth_error=not_configured"


def test_invited_email_signs_in_and_uninvited_is_refused(g):
    c, box, chair = g
    assert _login(c, box, "stranger@gmail.com") == "auth_error=not_invited"
    inv = c.post("/api/v2/admin/users", headers=H(chair),
                 json={"username": "pat", "role": "analyst", "email": " Pat@Gmail.com "})
    assert inv.status_code == 201 and inv.json()["email"] == "pat@gmail.com"
    frag = _login(c, box, "PAT@gmail.com")
    assert frag.startswith("auth=dds_")
    me = c.get("/api/v2/me", headers=H(frag[5:])).json()
    assert me["username"] == "pat" and me["role"] == "analyst"
    assert box["posted"]["client_secret"] == "secret" and box["posted"]["grant_type"] == "authorization_code"
    with session_scope() as s:  # 只存哈希
        assert s.scalar(select(UserSession.token_sha256)) == security.token_hash(frag[5:])


def test_owner_bootstraps_as_chairman_once(g):
    c, box, _ = g
    frag = _login(c, box, "owner@example.com")
    me = c.get("/api/v2/me", headers=H(frag[5:])).json()
    assert me["username"] == "owner" and me["role"] == "chairman" and me["display_name"] == "Pat"
    again = _login(c, box, "owner@example.com")
    assert c.get("/api/v2/me", headers=H(again[5:])).json()["username"] == "owner"  # 不重复建号
    users = c.get("/api/v2/admin/users", headers=H(again[5:])).json()
    assert [u["username"] for u in users].count("owner") == 1


@pytest.mark.parametrize("over", [
    {"state": "forged"},                                   # CSRF：state 对不上
    {"code": "bad"},                                       # 授权码换不到 id_token
    {"claims": {"aud": "someone-else"}},                   # 发给别的应用的 id_token
    {"claims": {"iss": "https://evil.example"}},
    {"claims": {"nonce": "replayed"}},                     # 重放
    {"claims": {"email_verified": "false"}},
])
def test_bad_callbacks_are_refused(g, over):
    c, box, chair = g
    c.post("/api/v2/admin/users", headers=H(chair), json={"username": "pat", "role": "viewer", "email": "p@g.com"})
    assert _login(c, box, "p@g.com", **over) == "auth_error=failed"


def test_callback_without_cookie_or_with_google_error(g):
    c, _, _ = g
    assert c.get("/api/v2/auth/google/callback", params={"code": "good", "state": "x"}).headers["location"] \
        == "/app/#auth_error=failed"
    assert c.get("/api/v2/auth/google/callback", params={"error": "access_denied"}).headers["location"] \
        == "/app/#auth_error=failed"


def test_session_expiry_logout_and_deactivation(g):
    c, box, chair = g
    c.post("/api/v2/admin/users", headers=H(chair), json={"username": "pat", "role": "analyst", "email": "p@g.com"})
    tok = _login(c, box, "p@g.com")[5:]
    assert c.get("/api/v2/deals", headers=H(tok)).status_code == 200
    assert c.post("/api/v2/auth/logout", headers=H(tok)).json() == {"ok": True}
    assert c.get("/api/v2/deals", headers=H(tok)).status_code == 401
    tok = _login(c, box, "p@g.com")[5:]
    with session_scope() as s:
        s.execute(update(UserSession).values(expires_at=utcnow() - timedelta(minutes=1)))
    assert c.get("/api/v2/deals", headers=H(tok)).status_code == 401
    tok = _login(c, box, "p@g.com")[5:]
    assert c.patch("/api/v2/admin/users/pat", headers=H(chair), json={"active": False}).json()["active"] is False
    assert c.get("/api/v2/deals", headers=H(tok)).status_code == 401
    assert _login(c, box, "p@g.com") == "auth_error=not_invited"


def test_invite_revoke_and_guards(g):
    c, box, chair = g
    c.post("/api/v2/admin/users", headers=H(chair), json={"username": "pat", "role": "viewer"})
    r = c.patch("/api/v2/admin/users/pat", headers=H(chair), json={"email": "Pat@G.com", "role": "analyst"})
    assert r.status_code == 200 and r.json()["email"] == "pat@g.com" and r.json()["role"] == "analyst"
    assert _login(c, box, "pat@g.com").startswith("auth=")
    dup = c.post("/api/v2/admin/users", headers=H(chair), json={"username": "pat2", "role": "viewer", "email": "pat@g.com"})
    assert dup.status_code == 409
    assert c.patch("/api/v2/admin/users/pat", headers=H(chair), json={"email": ""}).json()["email"] is None
    assert _login(c, box, "pat@g.com") == "auth_error=not_invited"
    assert c.patch("/api/v2/admin/users/chair", headers=H(chair), json={"active": False}).status_code == 422
    assert c.patch("/api/v2/admin/users/chair", headers=H(chair), json={"role": "viewer"}).status_code == 422
    assert c.patch("/api/v2/admin/users/nobody", headers=H(chair), json={"role": "viewer"}).status_code == 404
    assert c.patch("/api/v2/admin/users/pat", headers=H(chair), json={"email": "not-an-email"}).status_code == 422
    assert c.patch("/api/v2/admin/users/pat", json={"role": "viewer"}).status_code == 401
