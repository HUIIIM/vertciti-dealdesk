"""兼容别名：实现已迁至 app.services.render.pdf_uw（v2 分层）。旧导入路径与 monkeypatch 指向同一模块对象。"""
import sys

from app.services.render import pdf_uw as _impl

sys.modules[__name__] = _impl
