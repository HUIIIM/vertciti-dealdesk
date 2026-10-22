"""路由依赖：权限检查（不引入请求参数，OpenAPI 干净）。"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends

from app.core import security
from app.core.context import Actor


def perm(action: str) -> Callable[[], Actor]:
    def _dep() -> Actor:
        return security.require(action)
    _dep.__name__ = f"perm_{action.replace('.', '_')}"
    return _dep


def need(action: str):  # noqa: ANN201 — FastAPI Depends 对象
    return Depends(perm(action))
