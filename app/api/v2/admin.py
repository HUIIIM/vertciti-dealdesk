"""管理：健康检查、就绪探针、最近错误、用户、审计查询、设置模板、保存的视图、数据源状态。"""
from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import text

from app.api.v2.deps import LocalizedRoute, need
from app.api.v2.schemas import (
    AuditOut,
    DataSourceOut,
    Generic,
    HealthOut,
    MeOut,
    TemplateIn,
    TemplateOut,
    UserCreatedOut,
    UserIn,
    UserOut,
    UserPatch,
    ViewIn,
    ViewOut,
)
from app.core import security
from app.core.context import current_actor
from app.core.i18n import label
from app.core.observability import RECENT_ERRORS
from app.domain.v2 import reproducible
from app.services.persistence.engine import database_url, ensure_migrated
from app.services.v2 import settings

router = APIRouter(prefix="/api/v2", tags=["v2 · admin"], route_class=LocalizedRoute)
_STARTED = time.time()
logger = logging.getLogger(__name__)


@router.get("/health", response_model=HealthOut)
def health() -> dict[str, Any]:
    """存活 + 数据库连通 + 迁移版本 + 引擎版本（部署后第一动作）。"""
    db_ok, rev, err = True, None, ""
    try:
        eng = ensure_migrated()
        with eng.connect() as c:
            rev = c.execute(text("select version_num from alembic_version")).scalar()
    except Exception as e:  # 健康检查要报告而不是抛（已记日志）
        # 对外只给异常类型：原文可能带数据库主机 / 用户名（health 不需要登录）；详情进服务端日志
        logger.exception("health: 数据库不可用")
        db_ok, err = False, type(e).__name__
    url = database_url()
    return {"ok": db_ok, "service": "dealdesk", "version": reproducible.APP_VERSION,
            "engine_version": reproducible.engine_version(), "db": {"ok": db_ok, "revision": rev,
            "kind": "postgres" if url.startswith("postgresql") else "sqlite", "error": err},
            "auth": "on" if security.auth_enabled() else "off", "uptime_s": round(time.time() - _STARTED, 1)}


@router.get("/me", response_model=MeOut)
def me() -> dict[str, Any]:
    a = current_actor()
    return {"username": a.username, "role": a.role, "role_label": security.ROLE_LABEL.get(a.role, a.role),
            # 内置身份（本机用户 / 匿名）的显示名按语言输出；真实用户的显示名是用户数据，原样返回
            "display_name": label(a.display_name) if a.username in ("local", "anonymous") else a.display_name,
            "auth": security.auth_enabled(),
            "permissions": sorted(k for k in security.PERMISSIONS if security.can(a, k))}


@router.get("/admin/errors", response_model=list[Generic], dependencies=[need("audit.read")])
def errors(limit: int = Query(50, ge=1, le=100)) -> list[dict[str, Any]]:
    return list(RECENT_ERRORS)[:limit]


@router.get("/admin/users", response_model=list[UserOut], dependencies=[need("users.manage")])
def users() -> list[dict[str, Any]]:
    return settings.list_users()


@router.post("/admin/users", response_model=UserCreatedOut, status_code=201, dependencies=[need("users.manage")])
def create_user(body: UserIn) -> dict[str, Any]:
    """创建用户并返回一次性访问令牌（只显示这一次）。"""
    return settings.create_user(body.username, body.role, body.display_name, body.email)


@router.patch("/admin/users/{username}", response_model=UserOut, dependencies=[need("users.manage")])
def update_user(username: str, body: UserPatch) -> dict[str, Any]:
    """邀请（填 Google 邮箱）/ 撤销（邮箱填空）、改角色、停用。"""
    return settings.update_user(username, body.model_dump(exclude_unset=True))


@router.get("/admin/audit", response_model=list[AuditOut], dependencies=[need("audit.read")])
def audit(
    entity: str | None = None, entity_id: str | None = None, limit: int = Query(200, ge=1, le=1000),
) -> list[dict[str, Any]]:
    return settings.audit_log(entity, entity_id, limit)


@router.get("/settings/templates", response_model=list[TemplateOut], dependencies=[need("deal.read")])
def templates(kind: str | None = None) -> list[dict[str, Any]]:
    return settings.list_templates(kind)


@router.put("/settings/templates", response_model=TemplateOut, dependencies=[need("settings.write")])
def save_template(body: TemplateIn) -> dict[str, Any]:
    return settings.save_template(body.kind, body.name, body.payload)


@router.get("/settings/views", response_model=list[ViewOut], dependencies=[need("deal.read")])
def views() -> list[dict[str, Any]]:
    return settings.list_views()


@router.put("/settings/views", response_model=ViewOut, dependencies=[need("deal.write")])
def save_view(body: ViewIn) -> dict[str, Any]:
    return settings.save_view(body.name, body.config)


@router.delete("/settings/views/{view_id}", status_code=204, dependencies=[need("deal.write")])
def delete_view(view_id: int) -> None:
    settings.delete_view(view_id)


@router.get("/settings/data-sources", response_model=list[DataSourceOut], dependencies=[need("deal.read")])
def data_sources() -> list[dict[str, Any]]:
    return settings.data_sources()
