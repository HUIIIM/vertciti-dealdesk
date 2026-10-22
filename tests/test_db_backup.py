"""备份 / 恢复工具：在线快照一致、恢复前另存原库、坏文件拒绝恢复。"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import db_backup  # noqa: E402

from app.services import db  # noqa: E402


@pytest.mark.sqlite_only
def test_backup_verify_restore_roundtrip(tmp_path, monkeypatch):
    live = tmp_path / "live.db"
    monkeypatch.setenv("DEALDESK_DB", str(live))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.init_db()
    db.create_project("residential", "备份前", "1 St", {}, {})
    snap = db_backup.backup(tmp_path / "bk")
    assert snap.stat().st_mode & 0o777 == 0o600  # 备份含业务数据：仅属主可读
    info = db_backup.verify(snap)
    assert info["ok"] and info["alembic"] and info["tables"]["projects"] == 1

    db.create_project("residential", "备份后", "2 St", {}, {})
    keep = db_backup.restore(snap)
    with sqlite3.connect(live) as c:
        assert [r[0] for r in c.execute("select name from projects")] == ["备份前"]
    with sqlite3.connect(keep) as c:  # 恢复前的库原样留着，可回退
        assert c.execute("select count(*) from projects").fetchone()[0] == 2


@pytest.mark.sqlite_only
def test_restore_refuses_corrupt_file_and_requires_yes(tmp_path, monkeypatch):
    monkeypatch.setenv("DEALDESK_DB", str(tmp_path / "live.db"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    bad = tmp_path / "bad.sqlite3"
    bad.write_bytes(b"SQLite format 3\x00" + b"\x00" * 200)
    with pytest.raises((SystemExit, sqlite3.DatabaseError)):
        db_backup.restore(bad)
    with pytest.raises(SystemExit, match="--yes"):
        db_backup.main(["restore", str(bad)])
