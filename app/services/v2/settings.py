"""设置与运维：假设模板 / 市场默认值 / 淘汰条件模板、保存的视图、用户、审计查询、数据源状态。"""
from __future__ import annotations

import os
from typing import Any

from sqlalchemy import select

from app.core import google_auth, security
from app.core.context import current_actor
from app.core.i18n import T, label
from app.domain.v2 import kill_criteria
from app.services.persistence import audit
from app.services.persistence.engine import session_scope
from app.services.persistence.schema import AuditLog, SavedView, Template, User
from app.services.v2.errors import ConflictError, InvalidInputError, NotFoundError
from app.services.v2.serialize import row

JSON = dict[str, Any]
KINDS = ("assumptions", "market", "kill_criteria")
BUILTIN = {
    ("kill_criteria", "商业默认"): {"track": "commercial", "criteria": kill_criteria.DEFAULT_COMMERCIAL},
    ("kill_criteria", "住宅默认"): {"track": "residential", "criteria": kill_criteria.DEFAULT_RESIDENTIAL},
    ("kill_criteria", "机构默认"): {"track": "institutional", "criteria": kill_criteria.DEFAULT_INSTITUTIONAL},
}


def list_templates(kind: str | None = None) -> list[JSON]:
    with session_scope() as s:
        q = select(Template)
        if kind:
            q = q.where(Template.kind == kind)
        saved = [row(t) for t in s.scalars(q.order_by(Template.kind, Template.name)).all()]
    names = {(t["kind"], t["name"]) for t in saved}
    builtin = [{"id": None, "kind": k, "name": n, "label": label(n), "payload": p, "builtin": True}
               for (k, n), p in BUILTIN.items() if (not kind or k == kind) and (k, n) not in names]
    return builtin + [{**t, "label": t["name"]} for t in saved]


def save_template(kind: str, name: str, payload: JSON) -> JSON:
    security.require("settings.write")
    if kind not in KINDS:
        raise InvalidInputError(T("模板类型只能是：{0}", ", ".join(KINDS)))
    if kind == "kill_criteria":
        try:
            payload = {**payload, "criteria": kill_criteria.validate(payload.get("criteria", []))}
        except ValueError as e:
            raise InvalidInputError(str(e)) from e
    with session_scope() as s:
        t = s.scalar(select(Template).where(Template.kind == kind, Template.name == name))
        before = row(t) if t else None
        if t is None:
            t = Template(kind=kind, name=name, payload=payload, created_by=current_actor().username)
            s.add(t)
        else:
            t.payload = payload
        s.flush()
        audit.record(s, "template", t.id, "update" if before else "create", before, row(t))
        return row(t)


def list_views() -> list[JSON]:
    with session_scope() as s:
        return [row(v) for v in s.scalars(select(SavedView).order_by(SavedView.name)).all()]


def save_view(name: str, config: JSON) -> JSON:
    security.require("deal.write")
    if not name.strip():
        raise InvalidInputError(T("视图名称不能为空"))
    with session_scope() as s:
        v = s.scalar(select(SavedView).where(SavedView.name == name.strip()))
        if v is None:
            before = None
            v = SavedView(name=name.strip(), config=config, created_by=current_actor().username)
            s.add(v)
        else:
            before = row(v)
            v.config = config
        s.flush()
        audit.record(s, "saved_view", v.id, "update" if before else "create", before, row(v))
        return row(v)


def delete_view(view_id: int) -> None:
    security.require("deal.write")
    with session_scope() as s:
        v = s.get(SavedView, view_id)
        if v is None:
            raise NotFoundError(T("视图不存在"))
        audit.record(s, "saved_view", v.id, "delete", row(v), None)
        s.delete(v)


def list_users() -> list[JSON]:
    security.require("users.manage")
    with session_scope() as s:
        return [row(u, exclude=("token_sha256",)) for u in s.scalars(select(User).order_by(User.username)).all()]


def create_user(username: str, role: str, display_name: str = "") -> JSON:
    security.require("users.manage")
    try:
        security.Role(role)
    except ValueError as e:
        raise InvalidInputError(T("角色只能是 chairman / analyst / viewer")) from e
    with session_scope() as s:
        if s.scalar(select(User.id).where(User.username == username)) is not None:
            raise ConflictError(T("用户名 {0} 已存在", username))
    try:
        token = security.add_user(username, role, display_name)
    except ValueError as e:  # 保留名
        raise InvalidInputError(str(e)) from e
    with session_scope() as s:
        u = s.scalar(select(User).where(User.username == username))
        if u is None:  # add_user 刚写入；读不到说明库状态异常
            raise NotFoundError(T("用户 {0} 创建后读取失败", username))
        audit.record(s, "user", u.id, "create", None, {"username": username, "role": role})
        return {**row(u, exclude=("token_sha256",)), "token": token,
                "note": T("访问令牌只显示这一次，请立即妥善保存")}


def audit_log(entity: str | None = None, entity_id: str | None = None, limit: int = 200) -> list[JSON]:
    security.require("audit.read")
    with session_scope() as s:
        q = select(AuditLog)
        if entity:
            q = q.where(AuditLog.entity == entity)
        if entity_id:
            q = q.where(AuditLog.entity_id == entity_id)
        return [row(a) for a in s.scalars(q.order_by(AuditLog.id.desc()).limit(min(limit, 1000))).all()]


def data_sources() -> list[JSON]:
    """数据源状态（只读、不发网络请求；TopHap 连通性看 /api/tophap/status）。"""
    return [
        {"key": "tophap", "label": T("TopHap 公共记录（MCP）"), "configured": os.environ.get("TOPHAP_ENABLED") == "1",
         "detail": T("OAuth token 1 小时有效；状态与重授权见 /api/tophap/status")},
        {"key": "rentcast", "label": T("RentCast 租金"), "configured": bool(os.environ.get("RENTCAST_API_KEY")),
         "detail": T("未设 RENTCAST_API_KEY 时跳过")},
        {"key": "census", "label": T("Census 人口与就业"), "configured": True, "detail": T("公开接口，免 key")},
        {"key": "web", "label": T("公开网页（遵守 robots.txt）"), "configured": True, "detail": T(
            "失败诚实降级为手动录入")},
        {"key": "google_login", "label": T("Google 登录"), "configured": google_auth.configured(),
         "detail": T("既有用户（用户名即邮箱）可用 Google 账号登录；未配置时登录页回退令牌登录")},
        {"key": "database", "label": T("数据库"), "configured": True,
         "detail": T("Postgres（DATABASE_URL）") if os.environ.get("DATABASE_URL") else T("SQLite（本机开发）")},
    ]


