"""可观测（v2 蓝图 §7）：请求编号、结构化日志、错误上报、身份注入中间件。

- 每个请求带 X-Request-ID（沿用入站值或新生成），回写到响应头，并注入日志与审计记录。
- 日志为单行 JSON（ts / level / logger / msg / request_id / actor + 额外字段），便于 Vercel / 日志平台检索。
- 未捕获异常：记录完整堆栈、写入内存环形缓冲（/api/v2/admin/errors 可查最近 100 条），
  设了 DEALDESK_ERROR_WEBHOOK 时异步 POST 一份摘要（不含请求体，避免泄露交易数据）；
  响应 500 JSON，带 request_id 便于对账。
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import traceback
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

import httpx
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core import security
from app.core.context import current_actor, current_request_id, reset_actor, set_actor, set_request_id
from app.core.hardening import AUTH_THROTTLE, headers_for

log = logging.getLogger("dealdesk")
access_log = logging.getLogger("dealdesk.access")
RECENT_ERRORS: deque[dict[str, Any]] = deque(maxlen=100)
_RID_OK = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_V1_PROTECTED = re.compile(r"^/api/(projects|uw/projects)(/|$)")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        d = {"ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
             "level": record.levelname, "logger": record.name, "msg": record.getMessage(),
             "request_id": current_request_id() or None, "actor": current_actor().username}
        d.update(getattr(record, "extra_fields", {}))
        if record.exc_info:
            d["exc"] = "".join(traceback.format_exception(*record.exc_info))[-4000:]
        return json.dumps(d, ensure_ascii=False, default=str)


def configure_logging() -> None:
    root = logging.getLogger("dealdesk")
    if any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        return
    h = logging.StreamHandler()
    h.setFormatter(JsonFormatter())
    root.addHandler(h)
    root.setLevel(os.environ.get("DEALDESK_LOG_LEVEL", "INFO").upper())
    root.propagate = False


def _report(err: dict[str, Any]) -> None:
    RECENT_ERRORS.appendleft(err)
    url = os.environ.get("DEALDESK_ERROR_WEBHOOK", "").strip()
    if not url:
        return

    def _send() -> None:
        try:
            httpx.post(url, json={k: err[k] for k in ("at", "request_id", "path", "method", "error")}, timeout=5)
        except Exception:  # noqa: BLE001 — 上报失败不影响主流程
            log.warning("error webhook 上报失败")
    threading.Thread(target=_send, daemon=True).start()


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = request.headers.get("x-request-id", "")
        rid = rid if _RID_OK.match(rid) else uuid.uuid4().hex
        rid_tok = set_request_id(rid)
        # 只认 Authorization 头（不读 cookie）：浏览器不会自动携带，天然免疫 CSRF
        auth = request.headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else None
        client = request.client.host if request.client else "-"
        wait = AUTH_THROTTLE.blocked(client) if token and security.auth_enabled() else 0.0
        actor = security.ANONYMOUS if wait else security.resolve_token(token)
        if token and not wait and actor is security.ANONYMOUS:
            AUTH_THROTTLE.fail(client)
            log.warning("invalid token", extra={"extra_fields": {"client": client}})
        act_tok = set_actor(actor)
        t0 = time.perf_counter()
        path, method = request.url.path, request.method
        try:
            if wait:
                resp: Response = JSONResponse({"detail": "令牌错误次数过多，请稍后再试", "request_id": rid},
                                              status_code=429, headers={"Retry-After": str(int(wait) + 1)})
            elif (security.protect_v1() and method in ("POST", "PUT", "DELETE") and _V1_PROTECTED.match(path)
                    and not security.can(actor, "deal.write")):
                resp = JSONResponse({"detail": "需要“分析”及以上角色", "request_id": rid},
                                    status_code=401 if actor is security.ANONYMOUS else 403)
            else:
                resp = await call_next(request)
        except Exception as e:
            err = {"at": datetime.now(timezone.utc).isoformat(), "request_id": rid, "path": path,
                   "method": method, "actor": actor.username, "error": f"{type(e).__name__}: {str(e)[:300]}",
                   "trace": traceback.format_exc()[-4000:]}
            log.exception("unhandled exception",
                          extra={"extra_fields": {"path": path, "method": method}})
            _report(err)
            resp = JSONResponse({"detail": "服务器内部错误", "request_id": rid}, status_code=500)
        resp.headers["X-Request-ID"] = rid
        for k, v in headers_for(path).items():
            resp.headers.setdefault(k, v)
        if path.startswith("/api/"):  # 在重置身份之前写，日志里的 actor 才是本次请求的操作人
            access_log.info("request", extra={"extra_fields": {
                "method": method, "path": path, "status": resp.status_code,
                "ms": round((time.perf_counter() - t0) * 1000, 1)}})
        reset_actor(act_tok)
        set_request_id("")  # 不跨请求泄漏
        del rid_tok
        return resp
