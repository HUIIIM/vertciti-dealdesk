"""浏览器会话（Google 登录后）：服务端记录 + 不透明 cookie，可吊销、30 天滑动续期。

- cookie 名 dd_session，只存随机明文（dd_sess_…），库里只存 sha256（同令牌口径）。
- 滑动续期：剩余有效期不足一半（15 天）时，resolve 顺延 expires_at 并标记需重发 cookie（中间件执行）。
- 吊销：登出吊销当前条；改密/停用等场景可按用户全吊销（revoke_all_for_user 预留给管理面）。
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.context import Actor
from app.core.security import token_hash
from app.services.persistence.engine import session_scope
from app.services.persistence.schema import User, WebSession

COOKIE_NAME = "dd_session"
SESSION_DAYS = 30
_RENEW_BELOW = timedelta(days=SESSION_DAYS // 2)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    """SQLite 读回的 DateTime 可能丢 tzinfo：按 UTC 归一，避免 aware/naive 比较报错。"""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def cookie_secure() -> bool:
    """生产（HTTPS）恒开；本机 HTTP 冒烟可经 DEALDESK_SESSION_COOKIE_SECURE=0 关闭。"""
    return os.environ.get("DEALDESK_SESSION_COOKIE_SECURE", "1").strip().lower() not in ("0", "false", "off")


def create_session(user_id: int, created_by: str) -> str:
    raw = "dd_sess_" + secrets.token_urlsafe(32)
    now = _now()
    with session_scope() as s:
        s.add(WebSession(token_sha256=token_hash(raw), user_id=user_id,
                         expires_at=now + timedelta(days=SESSION_DAYS), last_seen_at=now,
                         created_by=created_by))
    return raw


@dataclass(frozen=True)
class ResolvedSession:
    actor: Actor
    renew: bool  # True 时中间件需按 SESSION_DAYS 重发 cookie（滑动续期）


def resolve_session(raw: str | None) -> ResolvedSession | None:
    if not raw:
        return None
    now = _now()
    with session_scope() as s:
        row = s.scalar(select(WebSession).where(WebSession.token_sha256 == token_hash(raw)))
        if row is None or row.revoked_at is not None or _aware(row.expires_at) <= now:
            return None
        u = s.get(User, row.user_id)
        if u is None or not u.active:
            return None
        renew = _aware(row.expires_at) - now < _RENEW_BELOW
        row.last_seen_at = now
        if renew:
            row.expires_at = now + timedelta(days=SESSION_DAYS)
        return ResolvedSession(Actor(u.username, u.role, u.display_name), renew)


def revoke_session(raw: str | None) -> None:
    if not raw:
        return
    with session_scope() as s:
        row = s.scalar(select(WebSession).where(WebSession.token_sha256 == token_hash(raw)))
        if row is not None and row.revoked_at is None:
            row.revoked_at = _now()


def revoke_all_for_user(user_id: int) -> int:
    with session_scope() as s:
        rows = s.scalars(select(WebSession).where(
            WebSession.user_id == user_id, WebSession.revoked_at.is_(None))).all()
        for r in rows:
            r.revoked_at = _now()
        return len(rows)
