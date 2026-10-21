"""兼容别名：实现已迁至 app.domain.report_narrative（v2 分层）。旧导入路径与 monkeypatch 指向同一模块对象。"""
import sys

from app.domain import report_narrative as _impl

sys.modules[__name__] = _impl
