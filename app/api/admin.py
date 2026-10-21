"""运维：健康检查、数据源状态、统一 dashboard 页面。"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from app.api.common import STATIC_DIR

router = APIRouter(tags=["admin"])


@router.get("/api/health")
def health():
    return {"ok": True, "service": "dealdesk"}


@router.get("/api/tophap/status")
def tophap_status():
    """TopHap 数据源状态：开关 / 授权 / 连通性 / tool 面（OAuth 授权后的校验入口）。"""
    from app.services import tophap  # 懒导入：未启用时不增加启动依赖
    return tophap.status()


# ---------------- 统一 dashboard 路由 ----------------
@router.get("/d", response_class=HTMLResponse)
def dashboard_page():
    """统一 dashboard（spec §2）：/d?addr=…&type=res|com."""
    path = os.path.join(STATIC_DIR, "d.html")
    if not os.path.exists(path):
        raise HTTPException(404, "dashboard 未构建")
    return HTMLResponse(open(path, encoding="utf-8").read())
