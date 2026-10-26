"""routers 拆分冒烟测试。

守三件事：
1. 样板域（intake）的端点经 APIRouter 装配后行为与在 main.py 时一致
   （路由在位、校验口径不变、真实合并跑通）；
2. 路由只注册一次（迁移不许留双份）；
3. 冻结线：迁走的 handler 不许再出现在 app/main.py 里，新端点进 routers。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from app.main import app
from app.routers import intake as intake_router_mod

client = TestClient(app)

PAGE1 = ("1500 Atlantic Ave, Brooklyn, NY 11213\n"
         "Offering Price: $4,350,000\n"
         "Mixed-use retail building, 12,500 SF total rentable area")
PAGE2_OCR = ("In-Place NOI: $285,000\nCap Rate 6.55%\n"
             "Suite 1A  Laundromat  3,200 SF  $8,500")


def test_router_endpoints_registered_once():
    """以 OpenAPI 为注册真相：两端点各注册一次、仅 POST。"""
    paths = app.openapi()["paths"]
    for url in ("/api/wb/intake/pdf-ocr-pages",
                "/api/uw-commercial/intake/pdf-ocr-pages"):
        assert url in paths, url
        assert set(paths[url].keys()) == {"post"}, (url, paths[url].keys())


def test_router_module_standalone_routes():
    """router 模块自带两条路由（不靠 main.py 的 @app 装饰器）。"""
    rpaths = [r.path for r in intake_router_mod.router.routes]
    assert "/api/wb/intake/pdf-ocr-pages" in rpaths
    assert "/api/uw-commercial/intake/pdf-ocr-pages" in rpaths


def test_moved_endpoint_validation_unchanged():
    """空入参仍是 400 业务校验（而不是 404——证明路由确实经 router 在位）。"""
    for url in ("/api/wb/intake/pdf-ocr-pages",
                "/api/uw-commercial/intake/pdf-ocr-pages"):
        r = client.post(url, json={})
        assert r.status_code == 400, (url, r.status_code)


def test_moved_endpoint_still_merges():
    r = client.post("/api/uw-commercial/intake/pdf-ocr-pages", json={
        "page_texts": [PAGE1, ""], "ocr_pages": {"2": PAGE2_OCR},
        "filename": "smoke.pdf"})
    assert r.status_code == 200, r.text[:300]
    d = r.json()
    flat = {f["key"]: f for f in d["fields"]}
    assert flat["analysis.purchase_price"]["value"] == 4350000
    assert flat["analysis.underwritten_noi"]["value"] == 285000


def test_freeze_line_handlers_not_in_main():
    """冻结线守卫（v2 分层后加严）：main.py 只做装配——零路由定义、≤100 行；
    intake 域经 app.api.ROUTERS 装配。"""
    import re

    from app.api import ROUTERS
    main_src = Path(__file__).resolve().parent.parent.joinpath(
        "app", "main.py").read_text()
    assert not re.search(r"^@app\.(get|post|put|delete|patch)\(", main_src, re.M)
    assert len(main_src.splitlines()) <= 100
    assert intake_router_mod.router in ROUTERS
    router_src = Path(intake_router_mod.__file__).read_text()
    assert "def wb_intake_pdf_ocr_pages" in router_src
    assert "def uw_commercial_intake_pdf_ocr_pages" in router_src
