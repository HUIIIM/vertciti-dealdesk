"""站点根认证路由：Google 登录发起 / 回调 / 登出（路径不在 /api 下，与 OAuth 回调注册逐字一致）。

流程：/auth/google/login 302 到 Google（state + PKCE，事务数据进 10 分钟 HMAC 签名 cookie，一次性）→
回调验 state → 换 token → 验 id_token → 邮箱查既有用户（启用才放行）→ 建服务端会话、发 cookie → 302 /app/。
失败一律 302 /app/?login_error=<code>，由登录页映射中英文案（不向浏览器回显上游细节）。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from app.core import google_auth, security, sessions

log = logging.getLogger("dealdesk")
router = APIRouter(tags=["auth"])
_TX_COOKIE = "dd_oauth_tx"
_TX_TTL = 600


def _tx_secret() -> bytes:
    raw = os.environ.get("DEALDESK_SESSION_SECRET", "").strip() or google_auth.client_secret()
    return hashlib.sha256(("dealdesk-oauth-tx:" + raw).encode()).digest()


def _sign_tx(state: str, verifier: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(
        {"s": state, "v": verifier, "exp": int(time.time()) + _TX_TTL}).encode()).rstrip(b"=").decode()
    sig = hmac.new(_tx_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def _read_tx(raw: str | None) -> tuple[str, str] | None:
    if not raw or "." not in raw:
        return None
    payload, sig = raw.rsplit(".", 1)
    expect = hmac.new(_tx_secret(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expect):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except Exception:  # noqa: BLE001 — 事务 cookie 损坏即视为无事务
        return None
    if int(data.get("exp", 0)) <= int(time.time()):
        return None
    return str(data["s"]), str(data["v"])


def _fail(code: str) -> RedirectResponse:
    return RedirectResponse(f"/app/?login_error={code}", status_code=302)


def _set_tx(resp: Response, value: str, *, clear: bool = False) -> None:
    resp.set_cookie(_TX_COOKIE, value, max_age=0 if clear else _TX_TTL, path="/auth",
                    httponly=True, secure=sessions.cookie_secure(), samesite="lax")


def _set_session(resp: Response, raw: str) -> None:
    resp.set_cookie(sessions.COOKIE_NAME, raw, max_age=sessions.SESSION_DAYS * 86400, path="/",
                    httponly=True, secure=sessions.cookie_secure(), samesite="lax")


@router.get("/auth/google/login")
def google_login() -> Response:
    if not google_auth.configured():
        return _fail("not_configured")
    state, verifier = google_auth.new_state(), google_auth.new_verifier()
    resp = RedirectResponse(google_auth.authorization_url(state, verifier), status_code=302)
    _set_tx(resp, _sign_tx(state, verifier))
    return resp


@router.get("/auth/google/callback")
def google_callback(request: Request) -> Response:
    tx = _read_tx(request.cookies.get(_TX_COOKIE))
    if tx is None:
        return _fail("state_mismatch")
    state, verifier = tx
    q = request.query_params
    if q.get("error") or not q.get("code"):
        resp = _fail("verify_failed")
        _set_tx(resp, "", clear=True)
        return resp
    if not hmac.compare_digest(q.get("state", ""), state):
        resp = _fail("state_mismatch")
        _set_tx(resp, "", clear=True)
        return resp
    try:
        tokens = google_auth.exchange_code(q["code"], verifier)
        ident = google_auth.verify_id_token(str(tokens["id_token"]))
    except google_auth.GoogleAuthError as e:
        resp = _fail(e.code)
        _set_tx(resp, "", clear=True)
        return resp
    user = security.find_user_by_email(ident.email)
    if user is None:
        log.warning("google login rejected: email not provisioned", extra={"extra_fields": {"email": ident.email}})
        resp = _fail("not_provisioned")
        _set_tx(resp, "", clear=True)
        return resp
    if not user.active:
        resp = _fail("disabled")
        _set_tx(resp, "", clear=True)
        return resp
    raw = sessions.create_session(user.id, created_by="google-login")
    resp = RedirectResponse("/app/", status_code=302)
    _set_tx(resp, "", clear=True)
    _set_session(resp, raw)
    return resp


@router.post("/auth/logout")
def logout(request: Request) -> Response:
    # cookie 认证的写操作：有 Origin 时必须同源（与 SameSite=Lax 双保险）
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != request.headers.get("host", ""):
        return JSONResponse({"detail": "origin mismatch"}, status_code=403)
    sessions.revoke_session(request.cookies.get(sessions.COOKIE_NAME))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(sessions.COOKIE_NAME, path="/")
    return resp
