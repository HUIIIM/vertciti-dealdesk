"""API 层：按领域拆分的路由（v2 蓝图 §7）。新端点进对应领域模块，main.py 只做装配。"""
from __future__ import annotations

from fastapi import APIRouter

from app.api import admin, deals, documents, exports, google_auth, intake, market, underwriting

# 装配顺序 = v1 main.py 中的注册顺序（intake 最先），保证路径匹配优先级不变
ROUTERS: list[APIRouter] = [
    intake.router,
    admin.router,
    deals.router,
    underwriting.router,
    market.router,
    documents.router,
    exports.router,
    google_auth.router,
]
