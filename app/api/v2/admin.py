"""管理：健康检查、就绪探针、最近错误、用户、审计查询、设置模板、保存的视图、数据源状态。"""
from __future__ import annotations

import time

from fastapi import APIRouter, Query
from sqlalchemy import text

from app.api.v2.deps import need
from app.api.v2.schemas import Generic, TemplateIn, UserIn, ViewIn
from app.core import security
from app.core.context import current_actor
from app.core.observability import RECENT_ERRORS
from app.domain.v2 import reproducible
from app.services.persistence.engine import database_url, ensure_migrated
from app.services.v2 import settings

router = APIRouter(prefix="/api/v2", tags=["v2 · admin"])
_STARTED = time.time()


@router.get("/health", response_model=Generic)
def health():
    """存活 + 数据库连通 + 迁移版本 + 引擎版本（部署后第一动作）。"""
    db_ok, rev, err = True, None, ""
    try:
        eng = ensure_migrated()
        with eng.connect() as c:
            rev = c.execute(text("select version_num from alembic_version")).scalar()
    except Exception as e:  # noqa: BLE001 — 健康检查要报告而不是抛
        db_ok, err = False, f"{type(e).__name__}: {str(e)[:200]}"
    url = database_url()
    return {"ok": db_ok, "service": "dealdesk", "version": reproducible.APP_VERSION,
            "engine_version": reproducible.engine_version(), "db": {"ok": db_ok, "revision": rev,
            "kind": "postgres" if url.startswith("postgresql") else "sqlite", "error": err},
            "auth": "on" if security.auth_enabled() else "off", "uptime_s": round(time.time() - _STARTED, 1)}


@router.get("/me", response_model=Generic)
def me():
    a = current_actor()
    return {"username": a.username, "role": a.role, "role_label": security.ROLE_LABEL.get(a.role, a.role),
            "display_name": a.display_name, "auth": security.auth_enabled(),
            "permissions": sorted(k for k in security.PERMISSIONS if security.can(a, k))}


@router.get("/admin/errors", response_model=list[Generic], dependencies=[need("audit.read")])
def errors(limit: int = Query(50, ge=1, le=100)):
    return list(RECENT_ERRORS)[:limit]


@router.get("/admin/users", response_model=list[Generic], dependencies=[need("users.manage")])
def users():
    return settings.list_users()


@router.post("/admin/users", response_model=Generic, status_code=201, dependencies=[need("users.manage")])
def create_user(body: UserIn):
    """创建用户并返回一次性访问令牌（只显示这一次）。"""
    return settings.create_user(body.username, body.role, body.display_name)


@router.get("/admin/audit", response_model=list[Generic], dependencies=[need("audit.read")])
def audit(entity: str | None = None, entity_id: str | None = None, limit: int = Query(200, ge=1, le=1000)):
    return settings.audit_log(entity, entity_id, limit)


@router.get("/settings/templates", response_model=list[Generic], dependencies=[need("deal.read")])
def templates(kind: str | None = None):
    return settings.list_templates(kind)


@router.put("/settings/templates", response_model=Generic, dependencies=[need("settings.write")])
def save_template(body: TemplateIn):
    return settings.save_template(body.kind, body.name, body.payload)


@router.get("/settings/views", response_model=list[Generic], dependencies=[need("deal.read")])
def views():
    return settings.list_views()


@router.put("/settings/views", response_model=Generic, dependencies=[need("deal.write")])
def save_view(body: ViewIn):
    return settings.save_view(body.name, body.config)


@router.delete("/settings/views/{view_id}", status_code=204, dependencies=[need("deal.write")])
def delete_view(view_id: int):
    settings.delete_view(view_id)


@router.get("/settings/data-sources", response_model=list[Generic], dependencies=[need("deal.read")])
def data_sources():
    return settings.data_sources()
