"""身份与权限（v2 蓝图 §7 权限）：角色 = 董事长 / 分析 / 只读；投委会投票与付款类操作分权。

运行模式：
- DEALDESK_AUTH 未设或为 off（缺省，与 v1 单用户本机工具一致）：所有请求视为本机用户 local（董事长）。
- DEALDESK_AUTH=on：v2 接口需 `Authorization: Bearer <token>`（或 cookie dd_token）；无有效 token 的请求
  身份为匿名只读（GET 可读公开端点，写操作 401）。另设 DEALDESK_AUTH_PROTECT_V1=1 时，v1 的项目
  增删改端点同样要求“分析”及以上。
token 只存 sha256（users.token_sha256），明文只在创建时显示一次。
命令行：python -m app.core.security add-user <username> <chairman|analyst|viewer> [显示名]
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sys
from enum import Enum

from fastapi import HTTPException

from app.core.context import Actor, current_actor


class Role(str, Enum):
    CHAIRMAN = "chairman"
    ANALYST = "analyst"
    VIEWER = "viewer"


ROLE_LABEL = {"chairman": "董事长", "analyst": "分析", "viewer": "只读"}
_RANK = {"viewer": 0, "analyst": 1, "chairman": 2}

# 权限矩阵：动作 → 最低角色。付款与审批决定只能董事长；投票须分析及以上（只读不能投）。
PERMISSIONS: dict[str, str] = {
    "deal.read": "viewer",
    "deal.write": "analyst",
    "deal.advance": "analyst",
    "deal.archive": "chairman",
    "document.write": "analyst",
    "task.write": "analyst",
    "decision.write": "analyst",
    "committee.vote": "analyst",
    "committee.package": "analyst",
    "approval.request": "analyst",
    "approval.decide": "chairman",
    "payment.approve": "chairman",
    "holding.write": "analyst",
    "settings.write": "chairman",
    "users.manage": "chairman",
    "audit.read": "chairman",
}

LOCAL = Actor("local", "chairman", "本机用户")
ANONYMOUS = Actor("anonymous", "viewer", "匿名")


def auth_enabled() -> bool:
    return os.environ.get("DEALDESK_AUTH", "off").strip().lower() in ("on", "1", "true", "yes")


def protect_v1() -> bool:
    return auth_enabled() and os.environ.get("DEALDESK_AUTH_PROTECT_V1", "") in ("1", "on", "true")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def can(actor: Actor, action: str) -> bool:
    need = PERMISSIONS[action]
    return _RANK.get(actor.role, -1) >= _RANK[need]


def require(action: str) -> Actor:
    """在路由内调用：无权限 → 401（未登录）/ 403（角色不够）。返回当前操作人。"""
    a = current_actor()
    if a.username == ANONYMOUS.username and auth_enabled():
        raise HTTPException(401, "需要登录：请提供有效的访问令牌")
    if not can(a, action):
        raise HTTPException(403, f"权限不足：{action} 需要{ROLE_LABEL[PERMISSIONS[action]]}及以上角色"
                                 f"（当前：{ROLE_LABEL.get(a.role, a.role)}）")
    return a


def resolve_token(token: str | None) -> Actor:
    """token → 操作人；认证关闭时恒为本机董事长。"""
    if not auth_enabled():
        return LOCAL
    if not token:
        return ANONYMOUS
    from sqlalchemy import select

    from app.services.persistence.engine import session_scope
    from app.services.persistence.schema import User
    with session_scope() as s:
        u = s.scalar(select(User).where(User.token_sha256 == token_hash(token), User.active.is_(True)))
        if u is None:
            return ANONYMOUS
        return Actor(u.username, u.role, u.display_name)


def add_user(username: str, role: str, display_name: str = "") -> str:
    """创建用户并返回一次性明文 token。"""
    Role(role)  # 校验
    from app.services.persistence.engine import session_scope
    from app.services.persistence.schema import User
    token = "dd_" + secrets.token_urlsafe(32)
    with session_scope() as s:
        s.add(User(username=username, role=role, display_name=display_name or username,
                   token_sha256=token_hash(token), created_by=current_actor().username))
    return token


if __name__ == "__main__":  # pragma: no cover — 运维命令行
    if len(sys.argv) >= 4 and sys.argv[1] == "add-user":
        tok = add_user(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "")
        print(f"用户 {sys.argv[2]}（{ROLE_LABEL[sys.argv[3]]}）已创建。访问令牌（只显示这一次）：\n{tok}")
    else:
        print(__doc__)
