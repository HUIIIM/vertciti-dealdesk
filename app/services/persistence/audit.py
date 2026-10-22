"""审计日志：关键表每次写入记一条（谁、何时、改前改后、请求编号）。与业务写入同一事务提交。"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.context import current_actor, current_request_id
from app.services.persistence.schema import AuditLog


def record(s: Session, entity: str, entity_id: object, action: str,
           before: Any = None, after: Any = None) -> None:
    s.add(AuditLog(entity=entity, entity_id=str(entity_id), action=action, actor=current_actor().username,
                   before=before, after=after, request_id=current_request_id()))
