"""兼容别名：intake 路由已迁至 app.api.intake（v2 分层）。"""
import sys

from app.api import intake as _impl

sys.modules[__name__] = _impl
