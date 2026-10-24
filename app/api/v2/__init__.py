"""v2 API（/api/v2）：交易生命周期。服务层异常统一映射为 404 / 409 / 422。"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.core.context import current_request_id
from app.core.i18n import T
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

    async def integrity(_req: Request, _exc: Exception) -> JSONResponse:
        # 唯一约束冲突（并发保存同一版本号、重名等）：不是服务器故障，是“刚被别人改过”，可重试
        return JSONResponse({"detail": T("数据冲突：这条记录刚被别人改过或已存在，请刷新后重试"),
                             "request_id": current_request_id()}, status_code=409)
    app.add_exception_handler(IntegrityError, integrity)


def routers() -> list[APIRouter]:
    # 延迟导入：子路由模块会反向导入本包（deps / schemas），放顶层会形成循环
    from app.api.v2 import (  # noqa: PLC0415
        admin,
        auth,
        committee,
        deals,
        documents,
        intake,
        portfolio,
        underwriting,
    )
    return [deals.router, underwriting.router, documents.router, intake.router, committee.router, portfolio.router,
            admin.router, auth.router]
