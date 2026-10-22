"""老版功能搬进 v2：导出（备忘录 / Excel / 一页纸 / 核保报告）、从已上传 PDF 提取字段、按地址搜集、导入老版项目。

每项先验证“拦得住”（没版本、赛道不对、质量门不过、扫描件、重复导入），再验证成品真能打开。
"""
from __future__ import annotations

import io

import fitz
import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.domain import uw_commercial
from app.main import app
from app.services import db as legacy_db
from app.services import research_pipeline

COM = uw_commercial.example_39_main()
RES = {"price": 400_000, "down_payment": 80_000, "loan_balance": 320_000, "rate": 6.5, "monthly_rent": 3_200,
       "taxes_annual": 6_000, "insurance_annual": 1_500, "exit_primary": "长期持有收租", "exit_backup": "卖出"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DEALDESK_DB", str(tmp_path / "v2.db"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DEALDESK_AUTH", raising=False)
    return TestClient(app)


def _deal(c: TestClient, track: str, inputs: dict | None) -> int:
    did = c.post("/api/v2/deals", json={"name": "测试交易", "track": track, "address": "39-09 Main St, Flushing, NY",
                                        "kill_criteria": []}).json()["id"]
    if inputs is not None:
        assert c.post(f"/api/v2/deals/{did}/versions", json={"inputs": inputs}).status_code == 201
    return did


def _pdf(text: str) -> bytes:
    doc = fitz.open()
    doc.new_page().insert_text((40, 60), text, fontsize=10)
    return doc.tobytes()


@pytest.mark.parametrize(("track", "inputs", "kinds"), [
    ("commercial", COM, ["memo", "model", "tearsheet", "report"]),
    ("residential", RES, ["memo", "model"]),
])
def test_exports_open_and_match_track(client, track, inputs, kinds):
    did = _deal(client, track, inputs)
    for kind in kinds:
        r = client.get(f"/api/v2/deals/{did}/export/{kind}")
        assert r.status_code == 200, (kind, r.text[:300])
        assert f"_{kind}_v1_" in r.headers["content-disposition"]
        if kind == "model":
            assert load_workbook(io.BytesIO(r.content)).sheetnames  # 真能打开的 Excel
        else:
            assert r.content.startswith(b"%PDF-") and fitz.open(stream=r.content, filetype="pdf").page_count >= 1
    assert any(e["kind"] == "exported" for e in client.get(f"/api/v2/deals/{did}/events").json())


def test_export_refuses_without_version_wrong_track_or_bad_kind(client):
    did = _deal(client, "residential", None)
    assert client.get(f"/api/v2/deals/{did}/export/memo").status_code == 422  # 还没有承销版本
    did = _deal(client, "residential", RES)
    assert client.get(f"/api/v2/deals/{did}/export/tearsheet").status_code == 422  # 一页纸只给商业
    assert client.get(f"/api/v2/deals/{did}/export/nope").status_code == 422
    assert client.get("/api/v2/deals/999/export/memo").status_code == 404


def test_extract_from_uploaded_pdf_maps_to_input_paths(client):
    did = _deal(client, "residential", RES)
    pdf = _pdf("Asking Price $1,250,000\n3 bed 2.5 bath 1,850 sq ft\nRent $4,200/mo")
    doc = client.post(f"/api/v2/deals/{did}/documents", files={"file": ("flyer.pdf", pdf, "application/pdf")}).json()
    r = client.post(f"/api/v2/deals/{did}/documents/{doc['id']}/extract")
    assert r.status_code == 200, r.text
    by = {c["key"]: c for c in r.json()["candidates"]}
    assert by["asking_price"]["path"] == "price" and by["asking_price"]["value"] == 1_250_000
    assert by["asking_price"]["confidence"] == "low" and by["asking_price"]["page"] == 1  # 卖方口径 → 低可信度
    assert by["beds"]["path"] is None  # 卧室数不是住宅承销输入：只作参考


def test_extract_refuses_non_pdf_and_other_deals_documents(client):
    a, b = _deal(client, "residential", RES), _deal(client, "residential", RES)
    doc = client.post(f"/api/v2/deals/{a}/documents", files={"file": ("x.png", b"\x89PNG....", "image/png")}).json()
    assert client.post(f"/api/v2/deals/{a}/documents/{doc['id']}/extract").status_code == 422
    assert client.post(f"/api/v2/deals/{b}/documents/{doc['id']}/extract").status_code == 404


def test_research_maps_fields_and_marks_reference_only(client, monkeypatch):
    def fake_run(mode, text):
        assert (mode, text) == ("address", "1 Main St, Austin, TX")
        return {"fields": [
            {"key": "address", "value": "1 Main St, Austin, TX 78701", "confidence": "高", "source": "county"},
            {"key": "asking_price", "value": 510_000, "confidence": "中", "source": "redfin.com"},
            {"key": "beds", "value": 3, "confidence": "中"},
        ], "manual_needed": [{"label": "月租金"}]}
    monkeypatch.setattr(research_pipeline, "run", fake_run)
    r = client.post("/api/v2/research", json={"track": "commercial", "mode": "address", "text": "1 Main St, Austin, TX"})
    assert r.status_code == 200, r.text
    out = r.json()
    by = {c["key"]: c for c in out["candidates"]}
    assert out["address"] == "1 Main St, Austin, TX 78701" and out["manual_needed"] == ["月租金"]
    assert by["asking_price"]["path"] == "analysis.purchase_price" and by["asking_price"]["confidence"] == "medium"
    assert by["address"]["path"] == "property.address" and by["beds"]["path"] is None
    assert client.post("/api/v2/research", json={"track": "commercial", "mode": "x", "text": "a"}).status_code == 422


def test_import_legacy_projects_once(client):
    client.get("/api/v2/health")  # 建库
    p = legacy_db.create_project("residential", "老版住宅", "9 Elm St", RES, {})
    u = legacy_db.create_uw_project("老版商业", COM)
    rows = {(r["kind"], r["id"]): r for r in client.get("/api/v2/legacy/projects").json()}
    assert rows[("project", p["id"])]["imported_deal_id"] is None and rows[("uw", u["id"])]["track"] == "commercial"
    r = client.post(f"/api/v2/legacy/projects/uw/{u['id']}/import")
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["deal"]["track"] == "commercial" and out["version"]["version_no"] == 1 and out["warning"] == ""
    assert out["version"]["outputs"]["metrics"]["irr_pct"] == pytest.approx(1.0294497)  # 输入原样带过来，结果一致
    assert client.post(f"/api/v2/legacy/projects/uw/{u['id']}/import").status_code == 422  # 不重复导入
    again = {(r["kind"], r["id"]): r for r in client.get("/api/v2/legacy/projects").json()}
    assert again[("uw", u["id"])]["imported_deal_id"] == out["deal"]["id"]
    assert client.post(f"/api/v2/legacy/projects/project/{p['id']}/import").json()["deal"]["address"] == "9 Elm St"
    assert client.post("/api/v2/legacy/projects/project/9999/import").status_code == 404


def test_legacy_half_finished_project_imports_without_version(client):
    client.get("/api/v2/health")
    p = legacy_db.create_project("residential", "半成品", "", {"monthly_rent": 1000}, {})  # 缺价格：老版允许存
    out = client.post(f"/api/v2/legacy/projects/project/{p['id']}/import").json()
    assert out["version"] is None and out["warning"] and out["deal"]["current_version_id"] is None
