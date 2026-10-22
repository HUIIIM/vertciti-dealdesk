"""HTTP 加固：安全响应头 + 令牌暴力尝试限流。

- 安全头对所有响应生效；v2 前端（/app/）额外下发严格 CSP（构建产物无内联脚本，script-src 只允许同源）。
  v1 静态页带内联脚本，其 CSP 由 vercel.json 里的 hash 管（见 AGENTS.md），这里不覆盖。
- 限流：同一来源 IP 在窗口期内带错令牌达到上限即 429，直到窗口滑过；只在认证开启时有意义。
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque

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


AUTH_THROTTLE = AuthThrottle(
    limit=int(os.environ.get("DEALDESK_AUTH_FAIL_LIMIT", "20")),
    window=float(os.environ.get("DEALDESK_AUTH_FAIL_WINDOW", "300")),
)
