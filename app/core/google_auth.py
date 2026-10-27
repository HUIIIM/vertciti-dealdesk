"""Google 登录（OAuth 2.0 授权码流 + PKCE + id_token 验签）。

口径（董事长令 2026-10-22）：邮箱必须命中既有用户表（username 即邮箱、大小写不敏感）且 active 才放行；
不开放注册、不自动建号。id_token 校验全套：JWKS RS256 验签、iss、aud=GOOGLE_CLIENT_ID、exp、email_verified=true，
任一不过即拒。凭证只从环境变量读（GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REDIRECT_URI），不落代码不落日志。
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import urlencode

import httpx  # noqa: F401  （测试替身的历史 patch 点；token 换码已改走 http_capped 流式上限）
import jwt
from jwt import PyJWKClient

from app.services import http_capped

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 — 这是 Google 的 token 端点 URL，非密码
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")

# Google token 端点响应大小上限：与页面/POST 上限同值；
# 换码改走 http_capped.post_capped 流式停手，超限收敛为 verify_failed（旧口径不变）。
MAX_TOKEN_BYTES = http_capped.MAX_POST_BYTES


class GoogleAuthError(Exception):
    """校验失败（code 为机器可读原因，供登录页映射文案）。"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class GoogleIdentity:
    email: str
    name: str


def client_id() -> str:
    return os.environ.get("GOOGLE_CLIENT_ID", "").strip()


def client_secret() -> str:
    return os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()


def redirect_uri() -> str:
    return os.environ.get("GOOGLE_REDIRECT_URI", "").strip()


def configured() -> bool:
    return bool(client_id() and client_secret() and redirect_uri())


def new_state() -> str:
    return secrets.token_urlsafe(32)


def new_verifier() -> str:
    return secrets.token_urlsafe(64)


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorization_url(state: str, verifier: str) -> str:
    q = urlencode({
        "client_id": client_id(),
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "code_challenge": pkce_challenge(verifier),
        "code_challenge_method": "S256",
        "prompt": "select_account",
    })
    return f"{AUTH_URL}?{q}"


def exchange_code(code: str, verifier: str) -> dict[str, Any]:
    """授权码换 token。网络/协议错误一律收敛为 verify_failed，不外泄上游细节。

    token 端点响应改走 http_capped.post_capped 流式＋上限
    （Content-Length 预检＋流式停手，不整页读入）；超限/非 200/非 JSON
    与既有网络错误同路收敛为 verify_failed，用户可见文案不变。
    """
    try:
        r = http_capped.post_capped(TOKEN_URL, data={
            "code": code,
            "client_id": client_id(),
            "client_secret": client_secret(),
            "redirect_uri": redirect_uri(),
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        }, timeout=10, limit=MAX_TOKEN_BYTES)
        if r.status_code != 200:
            raise GoogleAuthError("verify_failed")
        data: dict[str, Any] = r.json()
    except GoogleAuthError:
        raise
    except Exception as e:  # 上游错误细节（含超限）只收敛为一类，不进用户可见文案
        raise GoogleAuthError("verify_failed") from e
    if not isinstance(data, dict) or not data.get("id_token"):
        raise GoogleAuthError("verify_failed")
    return data


@lru_cache(maxsize=1)
def _jwks() -> PyJWKClient:
    return PyJWKClient(JWKS_URL, cache_keys=True, lifespan=3600)


def verify_id_token(id_token: str) -> GoogleIdentity:
    """验签 + 声明校验。失败抛 GoogleAuthError（verify_failed / email_unverified）。"""
    try:
        key = _jwks().get_signing_key_from_jwt(id_token).key
        claims = jwt.decode(id_token, key, algorithms=["RS256"], audience=client_id(),
                            options={"require": ["exp", "iat", "iss", "aud", "email"]})
    except Exception as e:  # 验签/过期/受众不符同归一类
        raise GoogleAuthError("verify_failed") from e
    if claims.get("iss") not in ISSUERS:
        raise GoogleAuthError("verify_failed")
    if int(claims.get("exp", 0)) <= int(time.time()):
        raise GoogleAuthError("verify_failed")
    if claims.get("email_verified") is not True:
        raise GoogleAuthError("email_unverified")
    email = str(claims.get("email", "")).strip().lower()
    if not email:
        raise GoogleAuthError("verify_failed")
    return GoogleIdentity(email=email, name=str(claims.get("name", "")))
