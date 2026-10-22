"""ORM → dict（API 输出）。时间统一 ISO 8601 UTC。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import inspect as sa_inspect

from app.services.persistence.schema import Base


def iso(v: datetime | None) -> str | None:
    return None if v is None else v.isoformat()


def row(obj: Base, exclude: tuple[str, ...] = ()) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col in sa_inspect(obj).mapper.column_attrs:
        k = col.key
        if k in exclude:
            continue
        v = getattr(obj, k)
        out[k] = iso(v) if isinstance(v, datetime) else v
    return out
