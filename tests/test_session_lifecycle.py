"""账户生命周期事件吊销已签发会话（#72 / 审查 #52）。

签发会话 → 停用 / 改角色 / 改用户名 → 旧会话失效；即使随后恢复原值，旧会话也不复活。
无关字段（显示名）变更不吊销；他人会话不受影响；变更回滚则吊销一并回滚；改自己的角色只吊销旧会话、不锁账户。
"""
from __future__ import annotations

import secrets

import pytest
from sqlalchemy import select

from app.core import security, sessions
from app.services.persistence.engine import session_scope
from app.services.persistence.schema import User, WebSession


def _user(role: str = "analyst") -> int:
    name = f"lifecycle-{secrets.token_hex(4)}@example.com"
    with session_scope() as s:
        u = User(username=name, role=role, display_name="L", active=True,
                 token_sha256=security.token_hash("dd_seed_" + name), created_by="test")
        s.add(u)
        s.flush()
        return u.id


def _set(user_id: int, **values: object) -> None:
    with session_scope() as s:
        u = s.get(User, user_id)
        assert u is not None
        for k, v in values.items():
            setattr(u, k, v)


@pytest.mark.parametrize(("change", "restore"), [
    ({"active": False}, {"active": True}),
    ({"role": "viewer"}, {"role": "analyst"}),
    ({"username": "renamed-" + secrets.token_hex(4) + "@example.com"}, None),
])
def test_account_change_revokes_issued_sessions(change: dict[str, object], restore: dict[str, object] | None) -> None:
    uid = _user()
    raw = sessions.create_session(uid, created_by="test")
    assert sessions.resolve_session(raw) is not None
    _set(uid, **change)
    assert sessions.resolve_session(raw) is None
    if restore:
        _set(uid, **restore)
        assert sessions.resolve_session(raw) is None  # 恢复原值也不复活旧会话


def test_unrelated_change_keeps_session_and_other_users_untouched() -> None:
    uid, other = _user(), _user()
    raw, other_raw = (sessions.create_session(uid, created_by="test"),
                      sessions.create_session(other, created_by="test"))
    _set(uid, display_name="Renamed display only")
    assert sessions.resolve_session(raw) is not None
    _set(uid, active=False)
    assert sessions.resolve_session(other_raw) is not None
    with session_scope() as s:
        revoked = s.scalars(select(WebSession.revoked_at).where(WebSession.user_id == uid)).all()
    assert revoked and all(r is not None for r in revoked)


def test_rolled_back_change_keeps_sessions() -> None:
    """吊销与账户变更同一事务：变更回滚，吊销也回滚，会话仍有效（不出现"账户未变、会话已死"）。"""
    uid = _user()
    raw = sessions.create_session(uid, created_by="test")
    with pytest.raises(RuntimeError), session_scope() as s:
        u = s.get(User, uid)
        assert u is not None
        u.active = False
        s.flush()  # 钩子已在本事务内执行 UPDATE web_sessions
        raise RuntimeError("abort")
    with session_scope() as s:
        u = s.get(User, uid)
        assert u is not None and u.active is True
    assert sessions.resolve_session(raw) is not None


def test_self_change_revokes_own_sessions_but_keeps_account() -> None:
    """改自己的 role：自己的旧会话也吊销（须重新登录拿新角色），账户本身不被停用，可再次签发会话。"""
    uid = _user(role="chairman")
    raw = sessions.create_session(uid, created_by="test")
    _set(uid, role="analyst")
    assert sessions.resolve_session(raw) is None
    fresh = sessions.create_session(uid, created_by="test")
    resolved = sessions.resolve_session(fresh)
    assert resolved is not None and resolved.actor.role == "analyst"
