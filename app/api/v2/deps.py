"""路由依赖：权限检查（不引入请求参数，OpenAPI 干净）；v2 路由类（英文请求时翻译固定标签）。"""
from __future__ import annotations

import json
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.core import i18n, security
from app.core.context import Actor
from app.core.i18n import current_lang


def perm(action: str) -> Callable[[], Actor]:
    def _dep() -> Actor:
        return security.require(action)
    _dep.__name__ = f"perm_{action.replace('.', '_')}"
    return _dep


def need(action: str) -> Any:  # FastAPI 的 Depends(...) 返回值没有公开类型
    return Depends(perm(action))


class LocalizedRoute(APIRoute):
    """英文请求时，把 JSON 响应里系统生成的固定标签（阶段名、假设名…）按精确匹配翻译；中文请求原样放行。

    动态句子已在生成处用 T() 按语言输出；这里只补模块级常量（导入时就定死、无法按请求切换的那部分）。
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def localized(request: Request) -> Response:
            resp = await handler(request)
            if current_lang() != "en" or resp.media_type != "application/json" or not resp.body:
                return resp
            body = i18n.localize(json.loads(bytes(resp.body)))
            headers = {k: v for k, v in resp.headers.items() if k.lower() not in ("content-length", "content-type")}
            return JSONResponse(body, status_code=resp.status_code, headers=headers, background=resp.background)

        return localized
