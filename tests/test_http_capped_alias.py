"""app.http_capped 别名与 app.services.http_capped 同对象。

feat 线第 24 项曾建 app/http_capped.py 别名（与 geocode/providers 等
app 层别名同式），对平 main 树缺此别名，跨线移植的专属测试
`from app import http_capped` 直接 ImportError。本用例守住别名层：
两条导入路径必须是同一模块对象（sys.modules 同对象式），且别名面
暴露的 capped helper 与常量与实现面逐一相同对象。
"""

import importlib

import app.http_capped as alias
from app.services import http_capped as impl


def test_http_capped_alias_is_same_module_object():
    assert alias is impl
    assert importlib.import_module("app.http_capped") is impl


def test_http_capped_alias_exposes_same_helpers():
    for name in (
        "get_json_capped",
        "post_capped",
        "collect_capped",
        "MAX_JSON_BYTES",
        "MAX_POST_BYTES",
    ):
        assert getattr(alias, name) is getattr(impl, name)
