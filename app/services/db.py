"""v1 项目库（住宅/商业项目、商业核保项目）——v2 起经 SQLAlchemy 访问，SQLite / Postgres 通用。

函数签名与返回结构与 v1 完全一致（金标准锁定）；新增的 created_by 列只写不出（不进 v1 响应）。
"""

from __future__ import annotations

import json
import os
import sqlite3
import time

from sqlalchemy import delete, select, update

from app.core.context import current_actor
from app.paths import REPO_ROOT
from app.services.persistence.engine import ensure_migrated, session_scope
from app.services.persistence.schema import LegacyProject, LegacyUwProject


def _db_path() -> str:
    """SQLite 路径（连接时懒读环境变量；见 persistence.engine.database_url）。"""
    return os.path.abspath(os.environ.get("DEALDESK_DB", str(REPO_ROOT / "dealdesk.db")))


def _conn() -> sqlite3.Connection:
    """v1 兼容：直接拿 SQLite 连接（仅测试/运维脚本用；业务代码走 session_scope）。"""
    ensure_migrated()
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """建表 / 升级到最新 schema（Alembic）。"""
    ensure_migrated()


def _uw_dict(r: LegacyUwProject) -> dict:
    return {"id": r.id, "name": r.name, "created_at": r.created_at, "updated_at": r.updated_at,
            "input": json.loads(r.input_json)}


def _proj_dict(r: LegacyProject) -> dict:
    return {"id": r.id, "track": r.track, "name": r.name, "address": r.address,
            "created_at": r.created_at, "updated_at": r.updated_at,
            "input": json.loads(r.input_json), "score": json.loads(r.score_json)}


def list_uw_projects() -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(select(LegacyUwProject).order_by(LegacyUwProject.updated_at.desc())).all()
        return [_uw_dict(r) for r in rows]


def get_uw_project(pid: int) -> dict | None:
    with session_scope() as s:
        r = s.get(LegacyUwProject, pid)
        return _uw_dict(r) if r else None


def create_uw_project(name: str, input_data: dict) -> dict:
    now = time.time()
    with session_scope() as s:
        r = LegacyUwProject(name=name, input_json=json.dumps(input_data or {}), created_at=now, updated_at=now,
                            created_by=current_actor().username)
        s.add(r)
        s.flush()
        pid = r.id
    return get_uw_project(pid)  # type: ignore[return-value]


def update_uw_project(pid: int, name: str, input_data: dict) -> dict | None:
    now = time.time()
    with session_scope() as s:
        res = s.execute(update(LegacyUwProject).where(LegacyUwProject.id == pid)
                        .values(name=name, input_json=json.dumps(input_data or {}), updated_at=now))
        if res.rowcount == 0:  # type: ignore[attr-defined]
            return None
    return get_uw_project(pid)


def delete_uw_project(pid: int) -> bool:
    with session_scope() as s:
        res = s.execute(delete(LegacyUwProject).where(LegacyUwProject.id == pid))
        return res.rowcount > 0  # type: ignore[attr-defined]


def list_projects(track: str | None = None) -> list[dict]:
    with session_scope() as s:
        q = select(LegacyProject).order_by(LegacyProject.updated_at.desc())
        if track:
            q = q.where(LegacyProject.track == track)
        return [_proj_dict(r) for r in s.scalars(q).all()]


def get_project(pid: int) -> dict | None:
    with session_scope() as s:
        r = s.get(LegacyProject, pid)
        return _proj_dict(r) if r else None


def create_project(track: str, name: str, address: str, input_data: dict, score: dict) -> dict:
    now = time.time()
    with session_scope() as s:
        r = LegacyProject(track=track, name=name, address=address,
                          input_json=json.dumps(input_data, ensure_ascii=False),
                          score_json=json.dumps(score, ensure_ascii=False), created_at=now, updated_at=now,
                          created_by=current_actor().username)
        s.add(r)
        s.flush()
        pid = r.id
    return get_project(pid)  # type: ignore[return-value]


def update_project(pid: int, name: str, address: str, input_data: dict, score: dict) -> dict | None:
    now = time.time()
    with session_scope() as s:
        res = s.execute(update(LegacyProject).where(LegacyProject.id == pid).values(
            name=name, address=address, input_json=json.dumps(input_data, ensure_ascii=False),
            score_json=json.dumps(score, ensure_ascii=False), updated_at=now))
        if res.rowcount == 0:  # type: ignore[attr-defined]
            return None
    return get_project(pid)


def delete_project(pid: int) -> bool:
    with session_scope() as s:
        res = s.execute(delete(LegacyProject).where(LegacyProject.id == pid))
        return res.rowcount > 0  # type: ignore[attr-defined]
