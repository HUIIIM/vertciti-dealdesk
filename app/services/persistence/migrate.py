"""以代码方式运行 Alembic（无需 alembic.ini；部署与测试同一路径）。

命令行：python -m app.services.persistence.migrate [upgrade|current|revision -m "msg"]
"""
from __future__ import annotations

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def alembic_config(engine: Engine | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    if engine is not None:
        cfg.set_main_option("sqlalchemy.url", engine.url.render_as_string(hide_password=False).replace("%", "%%"))
    return cfg


def upgrade_head(engine: Engine) -> None:
    cfg = alembic_config(engine)
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")


def main(argv: list[str]) -> None:
    # 延迟导入：engine 在顶层导入本模块（ensure_migrated → upgrade_head），反向放顶层会循环
    from app.services.persistence.engine import get_engine  # noqa: PLC0415
    eng = get_engine()
    cfg = alembic_config(eng)
    cmd = argv[0] if argv else "upgrade"
    if cmd == "upgrade":
        upgrade_head(eng)
        print("upgraded to head:", eng.url.render_as_string(hide_password=True))
    elif cmd == "current":
        command.current(cfg, verbose=True)
    elif cmd == "revision":
        msg = argv[argv.index("-m") + 1] if "-m" in argv else "change"
        command.revision(cfg, message=msg, autogenerate=True)
    else:
        raise SystemExit(f"unknown command: {cmd}")


if __name__ == "__main__":
    main(sys.argv[1:])
