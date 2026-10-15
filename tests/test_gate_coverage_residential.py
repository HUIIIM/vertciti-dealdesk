"""门覆盖补齐（台账第 4 项，2026-10-15）测试。

覆盖两路此前盲区：
1. 截图 intake：pending 队列视觉提取结果（image_intake.get_extracted）
   此前原样返回、无 quality_gate；住宅截图此前无同步 OCR 文本路。
2. 住宅页（d.html）导出：备忘录 PDF / 住宅 Excel 此前不过门，
   现 gate_fields 显式送达时 blocked → 422 硬拦。

验收口径（台账原文）：截图/住宅两路各喂一份矛盾材料，
fail 正确拦截并标黄（yellow_fields）。
"""

from __future__ import annotations

import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from app import image_intake, pdf_intake
from app.main import app, score_input

client = TestClient(app)

JPG_MIN = b"\xff\xd8\xff\xe0" + b"\x00" * 100 + b"\xff\xd9"

RES_INPUT = {"price": 750000, "monthly_rent": 4500, "rate": 6.5,
             "down_payment": 150000, "vacancy_pct": 8,
             "taxes_annual": 9000, "insurance_annual": 2400}

# 住宅矛盾材料：面积 50 SF 物理不可能（schema 硬区间 <100）＋建造年份未来
CONTRADICTORY_RES_FIELDS = {"asking_price": 750000, "building_sf": 50,
                            "monthly_rent": 4500, "year_built": 2099}
CLEAN_RES_FIELDS = {"asking_price": 750000, "building_sf": 3200,
                    "monthly_rent": 4500, "year_built": 1998}


def _tmp_pending(monkeypatch, tmp_path):
    d = tmp_path / "pending"
    d.mkdir()
    monkeypatch.setattr(image_intake, "PENDING_DIR", str(d))
    return str(d)


def _write_extracted(pending_dir, tid, payload):
    task_dir = os.path.join(pending_dir, tid)
    os.makedirs(task_dir, exist_ok=True)
    with open(os.path.join(task_dir, "extracted.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f)


# ---------- 1) 截图路：pending 视觉提取结果附门 ----------

def test_screenshot_extracted_residential_contradiction_blocked(monkeypatch, tmp_path):
    pending = _tmp_pending(monkeypatch, tmp_path)
    r = client.post("/api/wb/intake/image",
                    files={"file": ("shot.jpg", io.BytesIO(JPG_MIN), "image/jpeg")})
    tid = r.json()["task_id"]
    _write_extracted(pending, tid, {
        "mode": "screenshot", "filename": "shot.jpg",
        "fields": [
            {"key": "asking_price", "label": "挂牌价", "value": 750000,
             "source": "screenshot", "confidence": "截图提取"},
            {"key": "building_sf", "label": "建筑面积", "value": 50,
             "source": "screenshot", "confidence": "截图提取"},
            {"key": "year_built", "label": "建造年份", "value": 2099,
             "source": "screenshot", "confidence": "截图提取"},
        ],
        "fetched_at": "2026-10-15 08:00", "claim_notice": "截图提取、待验证"})
    r2 = client.get(f"/api/wb/intake/extracted/{tid}")
    assert r2.status_code == 200
    d = r2.json()
    assert "quality_gate" in d, "截图提取结果必须附 quality_gate"
    g = d["quality_gate"]
    assert g["deal_type"] == "residential"
    assert g["schema_version"] == "residential-v1"
    assert g["blocked"] is True, g["summary"]
    assert "building_sf" in g["yellow_fields"], "fail 命中的面积字段必须标黄"
    assert "year_built" in g["yellow_fields"]


def test_screenshot_extracted_commercial_contradiction_blocked(monkeypatch, tmp_path):
    pending = _tmp_pending(monkeypatch, tmp_path)
    r = client.post("/api/wb/intake/image",
                    files={"file": ("shot.jpg", io.BytesIO(JPG_MIN), "image/jpeg")})
    tid = r.json()["task_id"]
    _write_extracted(pending, tid, {
        "mode": "screenshot", "filename": "om.jpg",
        "fields": [
            {"key": "analysis.purchase_price", "label": "购买价格", "value": 4350000,
             "source": "screenshot", "confidence": "截图提取"},
            {"key": "analysis.underwritten_noi", "label": "在手 NOI", "value": 285000,
             "source": "screenshot", "confidence": "截图提取"},
            {"key": "property.net_rentable_sf", "label": "可租面积", "value": 12500,
             "source": "screenshot", "confidence": "截图提取"},
        ],
        "tenants": [{"suite": "101", "tenant": "A", "sf": 6000, "monthly_rent": 8500},
                    {"suite": "102", "tenant": "B", "sf": 5000, "monthly_rent": 7200}],
        "fetched_at": "2026-10-15 08:00", "claim_notice": "截图提取、待验证"})
    d = client.get(f"/api/wb/intake/extracted/{tid}").json()
    g = d["quality_gate"]
    assert g["deal_type"] == "commercial"
    assert g["blocked"] is True, g["summary"]
    # NOI 285k > 两租户年化毛租金 188.4k → fail
    assert any(c["rule"] == "xfield.noi_vs_gross_rent" for c in g["fails"])
    assert "analysis.underwritten_noi" in g["yellow_fields"]


def test_screenshot_extracted_clean_passes_gate(monkeypatch, tmp_path):
    pending = _tmp_pending(monkeypatch, tmp_path)
    r = client.post("/api/wb/intake/image",
                    files={"file": ("shot.jpg", io.BytesIO(JPG_MIN), "image/jpeg")})
    tid = r.json()["task_id"]
    _write_extracted(pending, tid, {
        "mode": "screenshot", "filename": "shot.jpg",
        "fields": [
            {"key": "asking_price", "label": "挂牌价", "value": 750000,
             "source": "screenshot", "confidence": "截图提取"},
            {"key": "building_sf", "label": "建筑面积", "value": 3200,
             "source": "screenshot", "confidence": "截图提取"},
            {"key": "monthly_rent", "label": "月租金", "value": 4500,
             "source": "screenshot", "confidence": "截图提取"},
        ],
        "fetched_at": "2026-10-15 08:00", "claim_notice": "截图提取、待验证"})
    g = client.get(f"/api/wb/intake/extracted/{tid}").json()["quality_gate"]
    assert g["blocked"] is False


# ---------- 1b) 住宅截图 OCR 文本路（新端点） ----------

def test_residential_image_text_contradiction_blocked():
    # 50 SF 与住宅要价同现 → 面积硬区间 fail，门拦截＋标黄
    text = ("FOR SALE $750,000\n50 sq ft\n4 bd 3 ba\nRent $4,500/mo\n"
            "Beautiful home, great location, must see!")
    r = client.post("/api/wb/intake/image-text",
                    json={"text": text, "filename": "listing.png"})
    assert r.status_code == 200, r.text[:300]
    d = r.json()
    assert d["mode"] == "image"
    assert "截图 OCR" in d["claim_notice"]
    g = d["quality_gate"]
    assert g["schema_version"] == "residential-v1"
    assert g["blocked"] is True, g["summary"]
    assert "building_sf" in g["yellow_fields"]


def test_residential_image_text_clean_not_blocked():
    text = ("FOR SALE $750,000\n3,200 sq ft\n4 bd 3 ba\nRent $4,500/mo\n"
            "Beautiful home, great location, must see!")
    d = pdf_intake.run_residential_image_ocr_text(text, "listing.png")
    assert not d.get("error"), d
    assert d["quality_gate"]["blocked"] is False
    srcs = {f["source"] for f in d["fields"]}
    assert any(s.startswith("截图OCR:") for s in srcs)


def test_residential_image_text_too_short_422():
    r = client.post("/api/wb/intake/image-text", json={"text": "hi", "filename": "x.png"})
    assert r.status_code == 422


# ---------- 2) 住宅导出过门：gate_fields 硬拦 ----------

def test_gate_endpoint_residential_contradiction():
    r = client.post("/api/wb/intake/gate", json={
        "deal_type": "residential", "fields": CONTRADICTORY_RES_FIELDS})
    g = r.json()
    assert g["blocked"] is True
    assert "building_sf" in g["yellow_fields"]


def _memo_payload(gate_fields):
    score = score_input("residential", dict(RES_INPUT))
    return {"track": "residential", "name": "450 W 44th St",
            "address": "450 W 44th St, New York, NY",
            "input": dict(RES_INPUT), "score": score,
            "gate_fields": gate_fields, "gate_deal_type": "residential"}


def test_memo_pdf_residential_contradiction_422():
    r = client.post("/api/memo/pdf", json=_memo_payload(CONTRADICTORY_RES_FIELDS))
    assert r.status_code == 422, r.text[:300]
    assert "质量门拦截" in r.text


def test_memo_pdf_residential_clean_200():
    r = client.post("/api/memo/pdf", json=_memo_payload(CLEAN_RES_FIELDS))
    assert r.status_code == 200, r.text[:300]
    assert r.headers["content-type"].startswith("application/pdf")


def test_memo_pdf_without_gate_fields_backward_compatible():
    p = _memo_payload(None)
    del p["gate_fields"]
    r = client.post("/api/memo/pdf", json=p)
    assert r.status_code == 200, r.text[:300]


def _res_xlsx_payload(gate_fields):
    score = score_input("residential", dict(RES_INPUT))
    return {"score": score, "input": dict(RES_INPUT),
            "address": "450 W 44th St, New York, NY",
            "gate_fields": gate_fields, "gate_deal_type": "residential"}


def test_res_xlsx_contradiction_422():
    r = client.post("/api/res/report/xlsx",
                    json=_res_xlsx_payload(CONTRADICTORY_RES_FIELDS))
    assert r.status_code == 422, r.text[:300]


def test_res_xlsx_clean_200():
    r = client.post("/api/res/report/xlsx",
                    json=_res_xlsx_payload(CLEAN_RES_FIELDS))
    assert r.status_code == 200, r.text[:300]


# ---------- 3) 住宅页静态接线 ----------

def test_dashboard_has_gate_panel_and_export_wiring():
    base = os.path.join(os.path.dirname(__file__), "..", "static")
    html = open(os.path.join(base, "d.html"), encoding="utf-8").read()
    js = open(os.path.join(base, "d.js"), encoding="utf-8").read()
    css = open(os.path.join(base, "d.css"), encoding="utf-8").read()
    assert 'id="gatePanel"' in html
    assert "gateCheckForExport" in js
    assert "buildGatePayload" in js and "renderGate" in js
    assert "gate_fields" in js, "导出必须把门字段送服务端硬拦"
    # 三个导出入口都过门
    assert js.count("gateCheckForExport(") >= 4  # 定义 1 + 备忘录/商业PDF/Excel 调用 3
    assert ".gate-panel" in css and ".gate-yellow" in css
