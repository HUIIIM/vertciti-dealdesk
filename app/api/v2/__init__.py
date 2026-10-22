"""v2 API（/api/v2）：交易生命周期。服务层异常统一映射为 404 / 409 / 422。"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.context import current_request_id
from app.services.v2.errors import ConflictError, InvalidInputError, NotFoundError


def install_error_handlers(app: FastAPI) -> None:
    def _h(status: int) -> Callable[[Request, Exception], Any]:
        async def handler(_req: Request, exc: Exception) -> JSONResponse:
            body: dict[str, Any] = {"detail": str(exc), "request_id": current_request_id()}
            extra = getattr(exc, "detail", None)
            if extra is not None and not isinstance(extra, str):
                body["gate"] = extra
            return JSONResponse(body, status_code=status)
        return handler
    app.add_exception_handler(NotFoundError, _h(404))
    app.add_exception_handler(ConflictError, _h(409))
    app.add_exception_handler(InvalidInputError, _h(422))


def routers() -> list[APIRouter]:
    # 延迟导入：子路由模块会反向导入本包（deps / schemas），放顶层会形成循环
    from app.api.v2 import admin, committee, deals, documents, portfolio, underwriting  # noqa: PLC0415
    return [deals.router, underwriting.router, documents.router, committee.router, portfolio.router, admin.router]
