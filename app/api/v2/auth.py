"""登录：Google（邀请制）与退出。浏览器整页跳转，不走 fetch；结果通过 `/app/#auth=…` 交还前端。"""
from __future__ import annotations

import hmac
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from app.api.v2.deps import LocalizedRoute
from app.services.v2 import google_auth

router = APIRouter(prefix="/api/v2", tags=["v2 · auth"], route_class=LocalizedRoute)
log = logging.getLogger("dealdesk.auth")
COOKIE = "dd_oauth"
COOKIE_PATH = "/api/v2/auth"


def _base(request: Request) -> str:
    """按请求推断对外地址：代理后取 X-Forwarded-Proto / Host（Vercel 会带上）。"""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


def _back(fragment: str) -> RedirectResponse:
    r = RedirectResponse(f"/app/#{fragment}", status_code=302)
    r.delete_cookie(COOKIE, path=COOKIE_PATH)
    return r


@router.get("/auth/providers")
def providers() -> dict[str, Any]:
    """登录页用：哪些登录方式可用（不需登录）。"""
    return {"google": google_auth.configured()}


@router.get("/auth/google/start", response_class=RedirectResponse, status_code=302)
def google_start(request: Request) -> Response:
    if not google_auth.configured():
        return _back("auth_error=not_configured")
    state, nonce = google_auth.new_state()
    r = RedirectResponse(google_auth.authorize_url(google_auth.redirect_uri(_base(request)), state, nonce),
                         status_code=302)
    secure = _base(request).startswith("https://")
    r.set_cookie(COOKIE, f"{state}.{nonce}", max_age=600, path=COOKIE_PATH, httponly=True, secure=secure,
                 samesite="lax")
    return r


@router.get("/auth/google/callback", response_class=RedirectResponse, status_code=302)
def google_callback(request: Request, code: str = "", state: str = "", error: str = "") -> Response:
    saved_state, _, nonce = (request.cookies.get(COOKIE) or "").partition(".")
    if error or not code or not saved_state or not hmac.compare_digest(saved_state, state):
        return _back("auth_error=failed")
    try:
        claims = google_auth.verify_id_token(
            google_auth.exchange_code(code, google_auth.redirect_uri(_base(request))), nonce)
        token, username = google_auth.sign_in(claims["email"], str(claims.get("name") or ""))
    except google_auth.GoogleAuthError as e:
        log.warning("google sign-in refused", extra={"extra_fields": {"reason": e.code}})
        return _back(f"auth_error={e.code}")
    log.info("google sign-in", extra={"extra_fields": {"username": username}})
    return _back(f"auth={token}")


@router.post("/auth/logout")
def logout(request: Request) -> dict[str, bool]:
    """退出：作废当前会话令牌（Google 登录换来的那种；长期访问令牌不受影响）。"""
    auth = request.headers.get("authorization", "")
    google_auth.sign_out(auth[7:].strip() if auth.lower().startswith("bearer ") else None)
    return {"ok": True}
