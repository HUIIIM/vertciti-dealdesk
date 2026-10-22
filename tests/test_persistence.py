"""持久化层（v2 蓝图 §7 数据）：Alembic 迁移、收编 v1 旧库、审计字段、Postgres 兼容。"""

from __future__ import annotations

import os
import sqlite3

import pytest
from sqlalchemy import inspect

from app.services import db
from app.services.persistence.engine import database_url, ensure_migrated, get_engine

V1_SCHEMA = """
CREATE TABLE projects (id INTEGER PRIMARY KEY AUTOINCREMENT, track TEXT NOT NULL,
  name TEXT NOT NULL DEFAULT '', address TEXT NOT NULL DEFAULT '', input_json TEXT NOT NULL DEFAULT '{}',
  score_json TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE uw_projects (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL DEFAULT '',
  input_json TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL, updated_at REAL NOT NULL);
INSERT INTO projects (track, name, address, input_json, score_json, created_at, updated_at)
  VALUES ('residential', '老项目', '1 Old St', '{"price": 1}', '{"total": 50}', 1.0, 2.0);
INSERT INTO uw_projects (name, input_json, created_at, updated_at) VALUES ('老核保', '{}', 1.0, 2.0);
"""


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    path = tmp_path / "p.db"
    monkeypatch.setenv("DEALDESK_DB", str(path))
    return path


def test_adopts_existing_v1_database_without_data_loss(fresh_db):
    with sqlite3.connect(fresh_db) as c:
        c.executescript(V1_SCHEMA)
    db.init_db()
    p = db.get_project(1)
    assert p["name"] == "老项目" and p["input"] == {"price": 1} and p["score"] == {"total": 50}
    assert db.get_uw_project(1)["name"] == "老核保"
    cols = {c["name"] for c in inspect(get_engine()).get_columns("projects")}
    assert "created_by" in cols
    assert "created_by" not in p  # v1 响应结构不变（金标准锁定）
    with sqlite3.connect(fresh_db) as c:
        assert c.execute("select version_num from alembic_version").fetchone()[0] == "0002"  # head


def test_fresh_database_gets_all_v2_tables(fresh_db):
    ensure_migrated()
    tables = set(inspect(get_engine()).get_table_names())
    for t in ("deals", "deal_versions", "runs", "field_provenance", "tasks", "approvals", "documents",
              "committee_votes", "decisions", "holding_actuals", "deal_events", "templates", "saved_views",
              "users", "audit_log", "projects", "uw_projects", "address_cache"):
        assert t in tables, t


def test_v2_tables_carry_audit_columns(fresh_db):
    ensure_migrated()
    insp = inspect(get_engine())
    for t in ("deals", "deal_versions", "runs", "tasks", "approvals", "documents", "committee_votes",
              "decisions", "holding_actuals", "templates", "saved_views", "users"):
        cols = {c["name"] for c in insp.get_columns(t)}
        assert {"created_at", "updated_at", "created_by"} <= cols, t


def test_db_file_deleted_and_recreated_is_remigrated(fresh_db):
    db.create_project("residential", "a", "b", {}, {})
    os.remove(fresh_db)
    db.init_db()
    assert db.list_projects() == []


def test_created_by_records_current_actor(fresh_db):
    from app.core.context import Actor, reset_actor, set_actor
    tok = set_actor(Actor("miao", "chairman"))
    try:
        db.create_project("residential", "x", "y", {}, {})
    finally:
        reset_actor(tok)
    with sqlite3.connect(fresh_db) as c:
        assert c.execute("select created_by from projects").fetchone()[0] == "miao"


def test_database_url_rewrites_heroku_style(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h/db")
    assert database_url() == "postgresql+psycopg://u:p@h/db"
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    assert database_url() == "postgresql+psycopg://u:p@h/db"


@pytest.mark.skipif(not os.environ.get("DEALDESK_TEST_PG_URL"), reason="未提供 DEALDESK_TEST_PG_URL")
def test_postgres_roundtrip(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["DEALDESK_TEST_PG_URL"])
    db.init_db()
    p = db.create_project("commercial", "PG 项目", "1 PG St", {"price": 2}, {"total": 70})
    assert db.get_project(p["id"])["input"] == {"price": 2}
    assert db.delete_project(p["id"]) is True
