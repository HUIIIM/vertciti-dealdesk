"""本地项目库：SQLite（标准库 sqlite3，零依赖）."""

from __future__ import annotations

import json
import os
import sqlite3
import time

DB_PATH = os.environ.get("DEALDESK_DB", os.path.join(os.path.dirname(__file__), "..", "dealdesk.db"))
DB_PATH = os.path.abspath(DB_PATH)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
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
