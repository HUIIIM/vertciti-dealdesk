"""HTTP 加固：安全响应头、令牌暴力尝试限流、请求体硬上限。

- 安全头对所有响应生效；v2 前端（/app/）额外下发严格 CSP（构建产物无内联脚本，script-src 只允许同源）。
  v1 静态页带内联脚本，其 CSP 由 vercel.json 里的 hash 管（见 AGENTS.md），这里不覆盖。
- 限流：同一来源 IP 在窗口期内带错令牌达到上限即 429，直到窗口滑过；只在认证开启时有意义。
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from app.core.i18n import T, lang_from_header, reset_lang, set_lang

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
}

APP_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


def headers_for(path: str) -> dict[str, str]:
    """某个路径应附加的安全头。"""
    if path == "/app" or path.startswith("/app/"):
        return {**SECURITY_HEADERS, "Content-Security-Policy": APP_CSP}
    return SECURITY_HEADERS


class AuthThrottle:
    """滑动窗口计数：key（来源 IP）在 window 秒内失败 limit 次即封，直到最早一次失败滑出窗口。"""

    def __init__(self, limit: int = 20, window: float = 300.0) -> None:
        self.limit, self.window = limit, window
        self._fails: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _trim(self, q: deque[float], now: float) -> None:
        while q and now - q[0] > self.window:
            q.popleft()

    def blocked(self, key: str, now: float | None = None) -> float:
        """被封则返回还需等待的秒数，否则 0。"""
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._fails.get(key)
            if not q:
                return 0.0
            self._trim(q, now)
            if len(q) < self.limit:
                return 0.0
            return max(0.0, self.window - (now - q[0]))

    def fail(self, key: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._fails[key]
            self._trim(q, now)
            q.append(now)

    def reset(self) -> None:
        with self._lock:
            self._fails.clear()


def client_ip(scope_client: str | None, forwarded_for: str | None) -> str:
    """限流用的来源 IP。

    部署在可信反向代理后（Vercel 等）时设 DEALDESK_TRUST_PROXY=1，取 X-Forwarded-For 第一跳；
    否则所有用户都显示为代理的 IP，一个人输错令牌就会把所有人一起锁住。缺省不信任该头（可被伪造）。
    """
    if os.environ.get("DEALDESK_TRUST_PROXY") == "1" and forwarded_for:
        first = forwarded_for.split(",")[0].strip()
        if first:
            return first
    return scope_client or "-"


AUTH_THROTTLE = AuthThrottle(
    limit=int(os.environ.get("DEALDESK_AUTH_FAIL_LIMIT", "20")),
    window=float(os.environ.get("DEALDESK_AUTH_FAIL_WINDOW", "300")),
)


MAX_BODY_BYTES = int(float(os.environ.get("DEALDESK_MAX_BODY_MB", "32")) * 1024 * 1024)


class _TooLargeError(Exception):
    pass


class BodySizeLimit:
    """请求体硬上限（纯 ASGI）。

    Content-Length 超限直接 413；没有 Content-Length 的分块上传边收边计数、超限立即中断——
    不让框架先把整个上传落到 /tmp（本机 /tmp 只有 512M）或读进内存。
    """

    def __init__(self, app: ASGIApp, limit: int = MAX_BODY_BYTES) -> None:
        self.app, self.limit = app, limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        cl = dict(scope.get("headers") or []).get(b"content-length")
        lang = lang_from_header(dict(scope.get("headers") or []).get(b"x-dd-lang", b"").decode("latin-1"))
        if cl is not None and cl.isdigit() and int(cl) > self.limit:
            await self._reject(send, lang)
            return
        seen = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > self.limit:
                    raise _TooLargeError
            return msg

        async def tracking_send(msg: Message) -> None:
            nonlocal started
            if msg["type"] == "http.response.start":
                started = True
            await send(msg)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _TooLargeError:
            if not started:
                await self._reject(send, lang)

    async def _reject(self, send: Send, lang: str) -> None:
        tok = set_lang(lang)  # 本中间件在语言上下文之外：按请求头自己定语言
        try:
            detail = T("请求太大：超过 {0} MB 上限", self.limit // 1024 // 1024)
        finally:
            reset_lang(tok)
        body = json.dumps({"detail": detail}, ensure_ascii=False).encode("utf-8")
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json; charset=utf-8"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
