#!/usr/bin/env python3
"""数据库备份 / 恢复 / 校验（运维手册 docs/RUNBOOK.md §备份）。

    python3 tools/db_backup.py backup  [目录]        # 缺省 ./backups；文件名带 UTC 时间戳
    python3 tools/db_backup.py verify  <备份文件>    # 完整性检查 + 迁移版本 + 各表行数
    python3 tools/db_backup.py restore <备份文件> --yes

- SQLite（缺省，DEALDESK_DB）：用 SQLite 在线备份 API，服务运行中也能拿到一致快照；
  恢复前先把现库另存为 *.pre-restore-<时间>，可回退。
- Postgres（设了 DATABASE_URL）：调用 pg_dump -Fc / pg_restore --clean，需本机装有客户端。
备份文件含业务数据：放 home 分区（/tmp 是 512M tmpfs），勿提交进仓库。
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.persistence.engine import database_url  # noqa: E402


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sqlite_path(url: str) -> Path | None:
    return Path(url[len("sqlite:///"):]) if url.startswith("sqlite:///") else None


def _pg_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def backup(out_dir: Path) -> Path:
    url = database_url()
    out_dir.mkdir(parents=True, exist_ok=True)
    src = _sqlite_path(url)
    if src is not None:
        if not src.exists():
            raise SystemExit(f"库文件不存在：{src}")
        dst = out_dir / f"dealdesk-{_stamp()}.sqlite3"
        with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
            s.backup(d)
    else:
        dst = out_dir / f"dealdesk-{_stamp()}.pgdump"
        subprocess.run(["pg_dump", "-Fc", "-f", str(dst), _pg_url(url)], check=True)
    dst.chmod(0o600)
    return dst


def verify(path: Path) -> dict[str, object]:
    if path.suffix != ".sqlite3":
        out = subprocess.run(["pg_restore", "--list", str(path)], check=True, capture_output=True, text=True)
        return {"ok": True, "entries": sum(1 for line in out.stdout.splitlines() if line and line[0] != ";")}
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as c:
        ok = c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        counts = {t: c.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}  # noqa: S608 — 表名来自 sqlite_master
        rev = None
        if "alembic_version" in tables:
            rev = c.execute("SELECT version_num FROM alembic_version").fetchone()
    return {"ok": ok, "alembic": rev[0] if rev else None, "tables": counts}


def restore(path: Path) -> Path | None:
    url = database_url()
    dst = _sqlite_path(url)
    if dst is None:
        subprocess.run(["pg_restore", "--clean", "--if-exists", "--no-owner", "-d", _pg_url(url), str(path)],
                       check=True)
        return None
    if not verify(path)["ok"]:
        raise SystemExit("备份文件完整性检查未通过，拒绝恢复")
    keep = None
    if dst.exists():
        keep = dst.with_name(f"{dst.name}.pre-restore-{_stamp()}")
        shutil.copy2(dst, keep)
    with sqlite3.connect(path) as s, sqlite3.connect(dst) as d:
        s.backup(d)
    return keep


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backup")
    b.add_argument("dir", nargs="?", default=str(ROOT / "backups"))
    v = sub.add_parser("verify")
    v.add_argument("file")
    r = sub.add_parser("restore")
    r.add_argument("file")
    r.add_argument("--yes", action="store_true", help="确认覆盖当前库")
    a = ap.parse_args(argv)
    if a.cmd == "backup":
        print(backup(Path(a.dir)))
    elif a.cmd == "verify":
        res = verify(Path(a.file))
        print(res)
        if not res["ok"]:
            raise SystemExit(1)
    else:
        if not a.yes:
            raise SystemExit("恢复会覆盖当前库：确认请加 --yes")
        keep = restore(Path(a.file))
        print(f"已恢复；原库另存为 {keep}" if keep else "已恢复")


if __name__ == "__main__":
    main()
