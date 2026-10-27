"""身份与权限（v2 蓝图 §7 权限）：角色 = 董事长 / 分析 / 只读；投委会投票与付款类操作分权。

运行模式：
- DEALDESK_AUTH 未设或为 off（缺省，与 v1 单用户本机工具一致）：所有请求视为本机用户 local（董事长）。
- DEALDESK_AUTH=on：v2 接口认两种凭证——`Authorization: Bearer <token>`（API/应急令牌，浏览器不自动携带），
  或浏览器会话 cookie（Google 登录签发，见 app/core/sessions.py；服务端记录、可吊销、SameSite=Lax，
  cookie 认证的写请求另校验 Origin 同源）。无有效凭证的请求身份为匿名只读（GET 可读公开端点，写操作 401）。
  另设 DEALDESK_AUTH_PROTECT_V1=1 时，v1 持久化面（项目/对比/研究证据/摄入待处理队列，见
  observability._V1_PROTECTED）的读要求登录（只读及以上）、增删改要求“分析”及以上。
- Google 登录：邮箱命中既有用户（username 即邮箱）且 active 才放行，不开放注册（app/core/google_auth.py）。
  令牌粘贴入口由 DEALDESK_TOKEN_LOGIN_ENABLED 控制（缺省关；Google 未配置时前端自动回退显示，防锁死）。
token 只存 sha256（users.token_sha256），明文只在创建时显示一次。
同一来源 IP 带错令牌过多会被限流 429（见 app/core/hardening.py）。
命令行：python -m app.core.security add-user <username> <chairman|analyst|viewer> [显示名]
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sys
from enum import Enum

from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.context import Actor, current_actor
from app.core.i18n import T
from app.services.persistence.engine import session_scope
from app.services.persistence.schema import User


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
# 内置身份的用户名保留：不能被真实用户占用，否则会继承内置身份的特权（计票按董事长、免分权检查）
RESERVED_USERNAMES = frozenset({"local", "anonymous", "system"})
ANONYMOUS = Actor("anonymous", "viewer", "匿名")


def auth_enabled() -> bool:
    return os.environ.get("DEALDESK_AUTH", "off").strip().lower() in ("on", "1", "true", "yes")


def token_login_enabled() -> bool:
    """令牌粘贴入口开关（过渡保留）：缺省关，开时登录页同时给令牌表单。"""
    return os.environ.get("DEALDESK_TOKEN_LOGIN_ENABLED", "").strip().lower() in ("on", "1", "true", "yes")


def find_user_by_email(email: str) -> User | None:
    """Google 登录的账号映射：邮箱 == username（大小写不敏感）。含未启用行，由调用方判 active。"""
    with session_scope() as s:
        u = s.scalar(select(User).where(func.lower(User.username) == email.strip().lower()))
        if u is not None:
            s.expunge(u)
        return u


def builtin_roles() -> dict[str, str]:
    """计票用的内置身份：只有认证关闭（单机模式）时本机用户才存在并视为董事长。"""
    return {} if auth_enabled() else {LOCAL.username: LOCAL.role}


def is_builtin_local(actor: Actor) -> bool:
    """单机模式下的唯一使用者（本机用户，或脚本 / 后台任务的内部身份 system），分权检查不适用。

    认证开启时永远为假：多人环境里任何名字都不享有这项豁免（保留名也不能被真实用户注册）。
    """
    return not auth_enabled() and actor.username in (LOCAL.username, "system")


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
        raise HTTPException(401, T("需要登录：请提供有效的访问令牌"))
    if not can(a, action):
        raise HTTPException(403, T("权限不足：{0} 需要{1}及以上角色（当前：{2}）",
                                   action, ROLE_LABEL[PERMISSIONS[action]], ROLE_LABEL.get(a.role, a.role)))
    return a


def resolve_token(token: str | None) -> Actor:
    """Token → 操作人；认证关闭时恒为本机董事长。"""
    if not auth_enabled():
        return LOCAL
    if not token:
        return ANONYMOUS
    with session_scope() as s:
        u = s.scalar(select(User).where(User.token_sha256 == token_hash(token), User.active.is_(True)))
        if u is None:
            return ANONYMOUS
        return Actor(u.username, u.role, u.display_name)


def add_user(username: str, role: str, display_name: str = "") -> str:
    """创建用户并返回一次性明文 token。"""
    Role(role)  # 校验
    if username.strip().lower() in RESERVED_USERNAMES:
        raise ValueError(T("用户名 {0} 是系统保留名，请换一个", username))
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
