"""服务层异常 → API 层映射为 HTTP 状态码（404 / 409 / 422）。"""
from __future__ import annotations


class NotFoundError(LookupError):
    pass


class ConflictError(RuntimeError):
    """状态冲突（关卡未过、重复投票等）→ 409。"""

    def __init__(self, message: str, detail: object | None = None) -> None:
        super().__init__(message)
        self.detail = detail


class InvalidInputError(ValueError):
    """输入不合法 → 422。"""
