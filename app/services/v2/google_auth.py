"""Google 登录（OpenID Connect 授权码流程），邀请制：只有董事长登记过邮箱的人能进，没有公开注册。

流程：
1. `/api/v2/auth/google/start`：生成随机 state 与 nonce，写进只给 `/api/v2/auth` 用的 HttpOnly cookie，跳转 Google。
2. Google 回到 `/api/v2/auth/google/callback?code&state`：比对 state；用授权码向 Google 换 id_token；
   交给 Google 的 tokeninfo 端点校验签名与有效期，再核对 aud（本应用）、iss、nonce、邮箱已验证。
3. 按邮箱找已启用的用户 → 签发会话令牌（只存 sha256，默认 12 小时）→ 跳回 `/app/#auth=<令牌>`。
   令牌放在 URL 片段里：片段不会发给任何服务器、不进访问日志；前端读出后立刻从地址栏抹掉。

配置（环境变量）：
- DEALDESK_GOOGLE_CLIENT_ID / DEALDESK_GOOGLE_CLIENT_SECRET：Google Cloud 控制台的 OAuth 客户端（Web 应用）。
- DEALDESK_PUBLIC_URL：对外地址（如 https://vertciti-dealdesk.vercel.app），用来拼回调地址；不设时按请求推断。
- DEALDESK_OWNER_EMAIL：所有者邮箱。此人第一次用 Google 登录且还没有账号时，自动建为董事长（解决“第一个人谁来邀请”）。
- DEALDESK_SESSION_HOURS：会话时长，默认 12。
"""
from __future__ import annotations

import os
import secrets
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select

from app.core import security
from app.services.persistence.engine import session_scope
from app.services.persistence.schema import User, UserSession, utcnow

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 — 公开端点地址，不是密钥
TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
ISSUERS = ("accounts.google.com", "https://accounts.google.com")
CALLBACK_PATH = "/api/v2/auth/google/callback"
OWNER_USERNAME = "owner"


class GoogleAuthError(Exception):
    """登录失败；code 给前端选提示语（not_invited / failed / not_configured）。"""

    def __init__(self, code: str, why: str = "") -> None:
        super().__init__(why or code)
        self.code = code


def client_id() -> str:
    return os.environ.get("DEALDESK_GOOGLE_CLIENT_ID", "").strip()


def configured() -> bool:
    return bool(client_id() and os.environ.get("DEALDESK_GOOGLE_CLIENT_SECRET", "").strip())


def redirect_uri(request_base: str) -> str:
    base = os.environ.get("DEALDESK_PUBLIC_URL", "").strip() or request_base
    return base.rstrip("/") + CALLBACK_PATH


def new_state() -> tuple[str, str]:
    return secrets.token_urlsafe(24), secrets.token_urlsafe(24)


def authorize_url(redirect: str, state: str, nonce: str) -> str:
    q = {"client_id": client_id(), "redirect_uri": redirect, "response_type": "code", "scope": "openid email profile",
         "state": state, "nonce": nonce, "prompt": "select_account"}
    return f"{AUTH_URL}?{urlencode(q)}"


def exchange_code(code: str, redirect: str) -> str:
    """授权码 → id_token（服务器到 Google，带 client secret）。"""
    r = httpx.post(TOKEN_URL, data={"code": code, "client_id": client_id(), "redirect_uri": redirect,
                                    "client_secret": os.environ.get("DEALDESK_GOOGLE_CLIENT_SECRET", ""),
                                    "grant_type": "authorization_code"}, timeout=10)
    if r.status_code != 200 or "id_token" not in r.json():
        raise GoogleAuthError("failed", f"token exchange {r.status_code}")
    return str(r.json()["id_token"])


def verify_id_token(id_token: str, nonce: str) -> dict[str, Any]:
    """由 Google tokeninfo 校验签名与有效期，再逐项核对声明。返回声明（含小写 email）。"""
    r = httpx.get(TOKENINFO_URL, params={"id_token": id_token}, timeout=10)
    if r.status_code != 200:
        raise GoogleAuthError("failed", f"tokeninfo {r.status_code}")
    c: dict[str, Any] = r.json()
    checks = (c.get("aud") == client_id(), c.get("iss") in ISSUERS, c.get("nonce") == nonce,
              str(c.get("email_verified")).lower() == "true", bool(c.get("email")))
    if not all(checks):
        raise GoogleAuthError("failed", "claims")
    c["email"] = str(c["email"]).strip().lower()
    return c


def _owner_email() -> str | None:
    return security.normalize_email(os.environ.get("DEALDESK_OWNER_EMAIL"))


def sign_in(email: str, name: str = "") -> tuple[str, str]:
    """邮箱 → (会话令牌明文, 用户名)。没被邀请 → not_invited；所有者第一次登录自动建董事长账号。"""
    email = security.normalize_email(email) or ""
    with session_scope() as s:
        u = s.scalar(select(User).where(User.email == email))
        if u is None and email and email == _owner_email():
            username = OWNER_USERNAME
            if s.scalar(select(User.id).where(User.username == username)) is not None:
                username = f"{OWNER_USERNAME}-{secrets.token_hex(3)}"
            u = User(username=username, role=security.Role.CHAIRMAN.value, display_name=name or username,
                     token_sha256=security.token_hash("dd_" + secrets.token_urlsafe(32)), email=email, active=True,
                     created_by="google-login")
            s.add(u)
        if u is None or not u.active:
            raise GoogleAuthError("not_invited", email)
        token = "dds_" + secrets.token_urlsafe(32)
        hours = float(os.environ.get("DEALDESK_SESSION_HOURS", "12") or 12)
        s.add(UserSession(token_sha256=security.token_hash(token), username=u.username,
                          expires_at=utcnow() + timedelta(hours=hours), created_by="google-login"))
        return token, u.username


def sign_out(token: str | None) -> None:
    """删掉这条会话令牌（长期访问令牌不受影响）。"""
    if not token:
        return
    with session_scope() as s:
        for row in s.scalars(select(UserSession).where(UserSession.token_sha256 == security.token_hash(token))):
            s.delete(row)
