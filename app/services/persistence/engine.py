"""数据库引擎与会话。

URL 解析（连接时懒读，测试可随时切换库）：
1. DATABASE_URL（生产 Postgres，如 postgresql+psycopg://user:pass@host/db；postgres:// 前缀自动改写）
2. 否则 SQLite：DEALDESK_DB 路径，缺省为仓库根 dealdesk.db（与 v1 同一个库文件）
"""
from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.paths import REPO_ROOT
from app.services.persistence.migrate import upgrade_head

_LOCK = threading.Lock()
_ENGINES: dict[str, Engine] = {}
_MIGRATED: dict[str, object] = {}  # url -> 库身份（SQLite 为文件 inode；被删重建即失效）


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return url
    path = Path(os.environ.get("DEALDESK_DB", str(REPO_ROOT / "dealdesk.db"))).resolve()
    return f"sqlite:///{path}"


def _sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:  # DBAPI 连接无公共类型
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def get_engine(url: str | None = None) -> Engine:
    url = url or database_url()
    with _LOCK:
        eng = _ENGINES.get(url)
        if eng is None:
            if url.startswith("sqlite"):
                # NullPool：每次会话新开连接——库文件被删重建（测试 / 运维）后不会拿到失效句柄
                eng = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30},
                                    poolclass=NullPool)
                event.listen(eng, "connect", _sqlite_pragmas)
            else:
                eng = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
            _ENGINES[url] = eng
    return eng


def _identity(url: str) -> object:
    if url.startswith("sqlite:///"):
        path = url[len("sqlite:///"):]
        try:
            st = Path(path).stat()
        except FileNotFoundError:
            return None
        return (st.st_dev, st.st_ino)
    return "server"


def ensure_migrated(url: str | None = None) -> Engine:
    """首次使用某个库时跑 Alembic 升级到 head（同进程同一库文件只跑一次）。"""
    url = url or database_url()
    eng = get_engine(url)
    ident = _identity(url)
    if ident is None or _MIGRATED.get(url) != ident:
        with _LOCK:
            ident = _identity(url)
            if ident is None or _MIGRATED.get(url) != ident:
                upgrade_head(eng)
                _MIGRATED[url] = _identity(url)
    return eng


@contextmanager
def session_scope() -> Iterator[Session]:
    """事务会话：正常退出提交、异常回滚。"""
    eng = ensure_migrated()
    maker = sessionmaker(bind=eng, expire_on_commit=False)
    s = maker()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
