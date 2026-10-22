"""Alembic 环境：复用调用方传入的连接（cfg.attributes['connection']），否则按 URL 建引擎。"""
from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine

from app.services.persistence.schema import Base

config = context.config
target_metadata = Base.metadata


def _run(connection) -> None:  # noqa: ANN001
    context.configure(connection=connection, target_metadata=target_metadata,
                      render_as_batch=connection.dialect.name == "sqlite", compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


conn = config.attributes.get("connection")
if conn is not None:
    _run(conn)
else:
    eng = create_engine(config.get_main_option("sqlalchemy.url"))
    with eng.begin() as c:
        _run(c)
