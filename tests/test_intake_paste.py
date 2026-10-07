"""商业粘贴文本 intake 测试（台账 2026-10-07）：粘贴 OM/flyer 文本 → 提取字段 → 卖方口径 + 质量门."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from app import pdf_intake
from app.main import app

client = TestClient(app)

OM_TEXT = """
1500 Atlantic Ave, Brooklyn, NY 11213
Offering Price: $4,350,000
Mixed-use retail building, 12,500 SF
In-Place NOI: $285,000
Pro Forma NOI: $340,000
Cap Rate 6.55%
Built 1928
Suite 1A  Laundromat  3,200 SF  $8,500
Suite 2B  Pizzeria    2,800 SF  $7,200
Value-add upside. Motivated seller.
"""

CONFIRM_LABEL = "卖方材料口径、待独立验证"


def _flat(fields):
    return {f["key"]: f for f in fields}


def test_parse_text_basic_fields():
    d = pdf_intake.run_commercial_text_upload(OM_TEXT)
    f = _flat(d["fields"])
    assert f["analysis.purchase_price"]["value"] == 4350000
    assert f["property.net_rentable_sf"]["value"] == 12500
    assert f["analysis.underwritten_noi"]["value"] == 285000
    assert f["analysis.projected_noi"]["value"] == 340000
    assert f["property.address"]["value"] == "1500 Atlantic Ave"
    assert len(d["tenants"]) == 2
    assert d["tenants"][0]["tenant"] == "Laundromat"
    assert d["tenants"][1]["monthly_rent"] == 7200
    assert d["mode"] == "paste"


def test_all_fields_marked_seller_claimed():
    d = pdf_intake.run_commercial_text_upload(OM_TEXT)
    for fld in d["fields"]:
        assert fld["seller_claimed"] is True, fld["key"]
        assert fld["confidence"] == "卖方口径"
        assert fld["source"] == "粘贴文本"
    assert CONFIRM_LABEL in d["claim_notice"]


def test_quality_gate_attached():
    d = pdf_intake.run_commercial_text_upload(OM_TEXT)
    g = d["quality_gate"]
    assert g is not None
    assert g["status"] in ("pass", "warn", "blocked")


def test_contradictory_text_triggers_gate():
    # 宣称 cap rate 1.0% vs 价格/NOI 隐含 5%（>300bps 偏差）→ 门应拦截/告警
    bad = "Asking price $1,000,000. 100,000 SF. In-Place NOI $50,000. cap rate 1.0%."
    d = pdf_intake.run_commercial_text_upload(bad)
    g = d["quality_gate"]
    assert g["status"] in ("warn", "blocked")
    rules = [c["rule"] for c in g.get("fails", []) + g.get("warns", [])]
    assert any("cap" in r for r in rules), rules


def test_endpoint_ok():
    r = client.post("/api/uw-commercial/intake/text", json={"text": OM_TEXT})
    assert r.status_code == 200
    d = r.json()
    f = _flat(d["fields"])
    assert f["analysis.purchase_price"]["value"] == 4350000
    assert "quality_gate" in d
    assert "tenants" in d


def test_endpoint_empty_text_400():
    for body in [{}, {"text": ""}, {"text": "   "}]:
        r = client.post("/api/uw-commercial/intake/text", json=body)
        assert r.status_code == 400, body


def test_endpoint_too_long_400():
    r = client.post("/api/uw-commercial/intake/text", json={"text": "x" * 600_000})
    assert r.status_code == 400


def test_chinese_text_extracts():
    d = pdf_intake.run_commercial_text_upload("售价 $2,300,000，面积 8,000 SF，当前 NOI $150,000")
    f = _flat(d["fields"])
    assert f["analysis.purchase_price"]["value"] == 2300000
    assert f["property.net_rentable_sf"]["value"] == 8000
