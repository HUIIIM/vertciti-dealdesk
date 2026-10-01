"""本地项目库：SQLite（标准库 sqlite3，零依赖）."""

from __future__ import annotations

import json
import os
import sqlite3
import time

def _db_path() -> str:
    """连接时懒读环境变量。

    不在 import 时求值：pytest collection 阶段各测试模块 import 顺序不定，
    任何时刻覆盖 DEALDESK_DB（conftest / setUpClass / monkeypatch）都能生效，
    测试数据永远写不到开发库 dealdesk.db。
    """
    return os.path.abspath(
        os.environ.get("DEALDESK_DB", os.path.join(os.path.dirname(__file__), "..", "dealdesk.db"))
    )


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                track TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                address TEXT NOT NULL DEFAULT '',
                input_json TEXT NOT NULL DEFAULT '{}',
                score_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS uw_projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL DEFAULT '',
                input_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )


def _uw_row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["input"] = json.loads(d.pop("input_json"))
    return d


def list_uw_projects() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, name, input_json, created_at, updated_at"
            " FROM uw_projects ORDER BY updated_at DESC"
        ).fetchall()
    return [_uw_row_to_dict(r) for r in rows]


def get_uw_project(pid: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT id, name, input_json, created_at, updated_at"
            " FROM uw_projects WHERE id = ?",
            (pid,),
        ).fetchone()
    return _uw_row_to_dict(row) if row else None


def create_uw_project(name: str, input_data: dict) -> dict:
    now = time.time()
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO uw_projects (name, input_json, created_at, updated_at)"
            " VALUES (?, ?, ?, ?)",
            (name, json.dumps(input_data or {}), now, now),
        )
        pid = cur.lastrowid
    return get_uw_project(pid)


def update_uw_project(pid: int, name: str, input_data: dict) -> dict | None:
    now = time.time()
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE uw_projects SET name = ?, input_json = ?, updated_at = ?"
            " WHERE id = ?",
            (name, json.dumps(input_data or {}), now, pid),
        )
        if cur.rowcount == 0:
            return None
    return get_uw_project(pid)


def delete_uw_project(pid: int) -> bool:
    with _conn() as conn:
        cur = conn.execute("DELETE FROM uw_projects WHERE id = ?", (pid,))
        return cur.rowcount > 0


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["input"] = json.loads(d.pop("input_json"))
    d["score"] = json.loads(d.pop("score_json"))
    return d


def list_projects(track: str | None = None) -> list[dict]:
    with _conn() as conn:
        if track:
            rows = conn.execute(
                "SELECT * FROM projects WHERE track=? ORDER BY updated_at DESC", (track,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_project(pid: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    return _row_to_dict(row) if row else None


def create_project(track: str, name: str, address: str, input_data: dict, score: dict) -> dict:
    now = time.time()
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO projects (track, name, address, input_json, score_json, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (track, name, address, json.dumps(input_data, ensure_ascii=False),
             json.dumps(score, ensure_ascii=False), now, now),
        )
        pid = cur.lastrowid
    return get_project(pid)


def update_project(pid: int, name: str, address: str, input_data: dict, score: dict) -> dict | None:
    now = time.time()
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE projects SET name=?, address=?, input_json=?, score_json=?, updated_at=?"
            " WHERE id=?",
            (name, address, json.dumps(input_data, ensure_ascii=False),
             json.dumps(score, ensure_ascii=False), now, pid),
        )
        if cur.rowcount == 0:
            return None
    return get_project(pid)


def delete_project(pid: int) -> bool:
    with _conn() as conn:
        cur = conn.execute("DELETE FROM projects WHERE id=?", (pid,))
        return cur.rowcount > 0
