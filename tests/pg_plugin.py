"""pytest 插件：让整套测试跑在 Postgres 上（生产库形态），每个测试一个全新的库。

用法（CI 的 postgres job）：
    PG_ADMIN_URL=postgresql://dd:dd@localhost:5432/postgres \\
    pytest -p tests.pg_plugin tests/

测试里凡是 monkeypatch.setenv("DEALDESK_DB", 临时 SQLite 路径) 的地方，都被映射成
DATABASE_URL=该测试独享的 Postgres 库；不带该插件时一切照旧走 SQLite。
"""
from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

ADMIN_URL = os.environ.get("PG_ADMIN_URL", "postgresql://dd:dd@localhost:5432/postgres")


def _db_url(name: str) -> str:
    """把管理库 URL 的库名换成 name（保留 ?host= 等查询参数），并指定 psycopg3 驱动。"""
    u = urlsplit(ADMIN_URL)
    return urlunsplit(u._replace(scheme="postgresql+psycopg", path=f"/{name}"))


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """直接读 SQLite 文件 / 断言 SQLite URL 的测试在 Postgres 下没有意义：跳过并写明原因。"""
    skip = pytest.mark.skip(reason="sqlite_only：直接检查 SQLite 库文件")
    for item in items:
        if item.get_closest_marker("sqlite_only"):
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _pg_per_test(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    name = "t_" + uuid.uuid4().hex[:12]
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    url = _db_url(name)
    orig_setenv, orig_delenv = monkeypatch.setenv, monkeypatch.delenv

    def setenv(k: str, v: str, prepend: str | None = None) -> None:
        if k == "DEALDESK_DB":
            orig_setenv("DATABASE_URL", url)
        elif k != "DATABASE_URL":
            orig_setenv(k, v, prepend)

    def delenv(k: str, raising: bool = True) -> None:  # noqa: FBT001, FBT002 — 与 MonkeyPatch.delenv 签名一致
        if k != "DATABASE_URL":
            orig_delenv(k, raising=raising)

    monkeypatch.setenv = setenv  # type: ignore[method-assign]
    monkeypatch.delenv = delenv  # type: ignore[method-assign]
    orig_setenv("DATABASE_URL", url)
    yield
    from app.services.persistence import engine  # noqa: PLC0415 — 测试结束才需要，释放连接后再删库

    eng = engine._ENGINES.pop(url, None)  # noqa: SLF001
    if eng is not None:
        eng.dispose()
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
