"""运维：健康检查、数据源状态；旧版页面地址跳转到 v2 工作台。"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

router = APIRouter(tags=["admin"])


@router.get("/api/health")
def health():
    return {"ok": True, "service": "dealdesk"}


@router.get("/api/tophap/status")
def tophap_status():
    """TopHap 数据源状态：开关 / 授权 / 连通性 / tool 面（OAuth 授权后的校验入口）。"""
    from app.services import tophap  # 懒导入：未启用时不增加启动依赖
    return tophap.status()


# ---------------- 旧版页面 → v2 工作台 ----------------
# v1 单页界面已下线：旧书签、旧外链统一 307 到 /app/（接口 /api/... 仍保留，v2 的市场 / 研究等功能在用）
LEGACY_PAGES = ("/", "/index.html", "/d", "/d.html", "/workbench.html", "/uw-commercial.html", "/res-legacy.html")


def _to_app() -> RedirectResponse:
    return RedirectResponse("/app/", status_code=307)


for _p in LEGACY_PAGES:
    router.add_api_route(_p, _to_app, methods=["GET"], include_in_schema=False)
