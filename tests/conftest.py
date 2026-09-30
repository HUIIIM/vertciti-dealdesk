"""pytest 会话级 DB 隔离。

pytest 在 collection 之前先加载 conftest.py，因此这里设置的 DEALDESK_DB
对所有测试模块生效（含 collection 阶段就 import app.main 的模块）。
配合 app/db.py 的连接时懒读（_db_path），测试数据永远写不到仓库根的
开发库 dealdesk.db —— 不再需要"跑前手动 rm -f dealdesk.db"。
"""
import atexit
import os
import tempfile

import pytest

_TMPDIR = tempfile.mkdtemp(prefix="dealdesk-test-")
_SESSION_DB = os.path.join(_TMPDIR, "dealdesk-test.db")
os.environ["DEALDESK_DB"] = _SESSION_DB


def _cleanup() -> None:
    try:
        if os.path.exists(_SESSION_DB):
            os.remove(_SESSION_DB)
        os.rmdir(_TMPDIR)
    except OSError:
        pass


atexit.register(_cleanup)


@pytest.fixture(autouse=True)
def _restore_session_db():
    # 记住测试开始前的 DEALDESK_DB（通常是会话级 tmp 库；test_v11 等
    # 在 setUpClass 里覆盖成自己的临时库），结束后原样恢复。
    # 注意：不能无脑重置回会话库——那样会破坏 setUpClass 的类级覆盖。
    if "DEALDESK_DB" not in os.environ:
        os.environ["DEALDESK_DB"] = _SESSION_DB
    before = os.environ["DEALDESK_DB"]
    yield
    os.environ["DEALDESK_DB"] = before
