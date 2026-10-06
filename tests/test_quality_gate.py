"""Intake 数据质量门（validators.py）测试。台账 2026-10-06 第 1 项。"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import pdf_intake
from app import validators as V


def _flat(**kw):
    return kw


def test_schema_type_fail():
    g = V.run_quality_gate("commercial", _flat(**{"analysis.purchase_price": "abc"}))
    assert g["status"] == "blocked"
    assert any(c["rule"] == "schema.type" for c in g["fails"])


def test_schema_range_fail():
    g = V.run_quality_gate("commercial", _flat(**{"property.net_rentable_sf": 5}))
    assert g["status"] == "blocked"
    assert any(c["rule"] == "schema.range" for c in g["fails"])


def test_schema_soft_range_warn():
    g = V.run_quality_gate("commercial", _flat(**{"analysis.purchase_price": 5000}))
    assert g["status"] == "warn"
    assert any(c["rule"] == "schema.range_soft" for c in g["warns"])


def test_schema_year_future_fail():
    g = V.run_quality_gate("commercial", _flat(**{"property.year_built": 2099}))
    assert g["status"] == "blocked"
    assert any(c["rule"] == "schema.year_future" for c in g["fails"])


def test_missing_required_warn_not_block():
    g = V.run_quality_gate("commercial", _flat(**{"analysis.purchase_price": 1_000_000}))
    assert g["status"] == "warn"
    assert any(c["rule"] == "schema.missing_required" for c in g["warns"])


def test_cap_consistency_fail():
    # 声称 8%，要价/NOI 反推 4.6% → 偏差 340bps → fail
    g = V.run_quality_gate("commercial", _flat(**{
        "analysis.purchase_price": 4_350_000,
        "analysis.underwritten_noi": 200_000,
        "analysis.market_cap_rate": 0.08,
    }))
    assert g["status"] == "blocked"
    assert any(c["rule"] == "xfield.cap_consistency" and c["severity"] == "fail"
               for c in g["fails"])
    assert "analysis.market_cap_rate" in g["yellow_fields"]


def test_cap_consistency_warn_band():
    # 声称 6.5%，反推 5.0% → 150bps → warn
    g = V.run_quality_gate("commercial", _flat(**{
        "analysis.purchase_price": 4_000_000,
        "analysis.underwritten_noi": 200_000,
        "analysis.market_cap_rate": 0.065,
    }))
    assert g["status"] == "warn"
    assert any(c["rule"] == "xfield.cap_consistency" for c in g["warns"])


def test_cap_consistency_pass():
    g = V.run_quality_gate("commercial", _flat(**{
        "analysis.purchase_price": 4_350_000,
        "analysis.underwritten_noi": 282_750,
        "analysis.market_cap_rate": 0.065,
    }))
    assert not any(c["rule"] == "xfield.cap_consistency" for c in g["fails"] + g["warns"])


def test_noi_vs_gross_rent_fail():
    g = V.run_quality_gate("commercial", _flat(**{"analysis.underwritten_noi": 300_000}),
                           tenants=[{"tenant": "A", "sf": 5000, "monthly_rent": 10000}])
    assert g["status"] == "blocked"
    assert any(c["rule"] == "xfield.noi_vs_gross_rent" for c in g["fails"])


def test_noi_vs_gross_rent_pass():
    g = V.run_quality_gate("commercial", _flat(**{"analysis.underwritten_noi": 60_000}),
                           tenants=[{"tenant": "A", "sf": 5000, "monthly_rent": 10000}])
    assert not any(c["rule"] == "xfield.noi_vs_gross_rent" for c in g["fails"] + g["warns"])


def test_rent_roll_sf_fail():
    g = V.run_quality_gate("commercial", _flat(**{"property.net_rentable_sf": 8000}),
                           tenants=[{"suite": "1", "sf": 5000, "monthly_rent": 8000},
                                    {"suite": "2", "sf": 5000, "monthly_rent": 8000}])
    assert g["status"] == "blocked"
    assert any(c["rule"] == "xfield.rent_roll_sf" and c["severity"] == "fail"
               for c in g["fails"])


def test_tenant_rent_psf_fail():
    # $1/月 ÷ 10000 SF = 0.0001 $/SF/月 → 物理不可能
    g = V.run_quality_gate("commercial", {},
                           tenants=[{"tenant": "Z", "sf": 10000, "monthly_rent": 1}])
    assert g["status"] == "blocked"
    assert any(c["rule"] == "xfield.tenant_rent_psf" for c in g["fails"])


def test_projected_below_inplace_warn():
    g = V.run_quality_gate("commercial", _flat(**{
        "analysis.underwritten_noi": 200_000, "analysis.projected_noi": 150_000}))
    assert g["status"] == "warn"
    assert any(c["rule"] == "xfield.projected_vs_inplace" for c in g["warns"])


def test_dup_price_conflict_fail():
    text = ("FOR SALE\nAsking Price: $4,350,000\n450 W 44th St\n"
            "Reduced! Now only $3,900,000 asking price. Great deal!\n"
            "In-Place NOI: $280,000\nCap rate 6.4%")
    g = V.run_quality_gate("commercial", _flat(**{"analysis.purchase_price": 4_350_000}),
                           raw_text=text)
    assert g["status"] == "blocked"
    assert any(c["rule"] == "dup.conflict" and "要价" in c["title"] for c in g["fails"])


def test_dup_no_conflict_pass():
    text = "FOR SALE\nAsking Price: $4,350,000\nSame price $4,350,000 confirmed.\nNOI $280,000"
    g = V.run_quality_gate("commercial", _flat(**{"analysis.purchase_price": 4_350_000}),
                           raw_text=text)
    assert not any(c["rule"] == "dup.conflict" for c in g["fails"])


# ---------------- 端到端：前后矛盾的 OM → 门拦截 + 标黄 ----------------

CONTRADICTORY_OM = (
    "CONFIDENTIAL OFFERING MEMORANDUM\n"
    "450 W 44th Street, New York, NY 10036\n"
    "Asking Price: $4,350,000\n"
    "PRICE REDUCED - New asking price $3,800,000! Motivated seller!\n"
    "In-Place NOI: $280,000\n"
    "Pro Forma NOI: $340,000\n"
    "Cap Rate: 8.5%\n"          # 反推 280000/4350000=6.4%，偏差 210bps → warn；按 3.8M 算 7.4% 仍超 100bps
    "Net Rentable: 12,000 SF\n"
    "Suite 101 ABC Corp 6,000 SF $9,000\n"
    "Suite 102 XYZ LLC 5,000 SF $8,000\n"   # 租约毛租金年化 204k < NOI 280k → fail
    "Year Built: 1998\n"
)


def test_contradictory_om_blocked_and_yellow():
    d = pdf_intake.parse_commercial_pdf_text(CONTRADICTORY_OM, "om.pdf", pages=[CONTRADICTORY_OM])
    g = V.run_quality_gate("commercial", d["fields"], tenants=d["tenants"],
                           raw_text=CONTRADICTORY_OM, pages=[CONTRADICTORY_OM])
    assert g["status"] == "blocked", g["summary"]
    assert g["fails_n"] >= 2, [f["title"] for f in g["fails"]]
    rules = {c["rule"] for c in g["fails"]}
    assert "dup.conflict" in rules, "两个要价 $4.35M/$3.8M 必须被拦截"
    assert "xfield.noi_vs_gross_rent" in rules, "NOI 280k > 租约毛租金 204k 必须被拦截"
    assert g["yellow_fields"], "fail 命中的字段必须标黄"
    # 页码标注
    price_f = next(f for f in d["fields"] if f["key"] == "analysis.purchase_price")
    assert price_f.get("page") == 1
    # field_report 带来源/页码/置信度
    rep = {r["key"]: r for r in g["field_report"]}
    assert rep["analysis.purchase_price"]["source"] == "PDF:om.pdf"
    assert rep["analysis.purchase_price"]["low_confidence"] is True  # 卖方口径=低置信


def test_clean_om_passes():
    text = ("FOR SALE\nAsking Price: $4,350,000\n"
            "In-Place NOI: $282,750\nCap Rate: 6.5%\n"
            "Net Rentable: 12,000 SF\n"
            "Suite 101 ABC Corp 6,000 SF $30,000\n"
            "Suite 102 XYZ LLC 5,000 SF $25,000\n"
            "Year Built: 1998\n")
    d = pdf_intake.parse_commercial_pdf_text(text, "om.pdf", pages=[text])
    g = V.run_quality_gate("commercial", d["fields"], tenants=d["tenants"],
                           raw_text=text, pages=[text])
    assert g["status"] == "pass", [c["title"] for c in g["fails"] + g["warns"]]
    assert g["schema_version"] == "commercial-v1"


def test_gate_verdict_for_state_enforces():
    state = {"property": {"net_rentable_sf": 12000},
             "analysis": {"purchase_price": 4350000, "underwritten_noi": 280000,
                          "market_cap_rate": 0.085},
             "tenants": [{"suite": "101", "sf": 6000, "monthly_rent": 9000},
                         {"suite": "102", "sf": 5000, "monthly_rent": 8000}]}
    g = V.gate_verdict_for_state(state)
    assert g["blocked"] is True
    assert g["fails_n"] >= 1


def test_gate_verdict_for_clean_state_passes():
    state = {"property": {"net_rentable_sf": 12000},
             "analysis": {"purchase_price": 4350000, "underwritten_noi": 282750,
                          "market_cap_rate": 0.065},
             "tenants": [{"suite": "101", "sf": 6000, "monthly_rent": 30000},
                         {"suite": "102", "sf": 5000, "monthly_rent": 25000}]}
    g = V.gate_verdict_for_state(state)
    assert g["blocked"] is False


def test_residential_gate_basic():
    d = pdf_intake.parse_pdf_text(
        "FOR SALE $750,000 3,200 SF 4 bd 3 ba Rent $4,500/mo Cap rate 6.5%!", "flyer.pdf")
    g = V.run_quality_gate("residential", d["fields"], raw_text="")
    assert g["schema_version"] == "residential-v1"
    # 54k 年租金 / 750k = 7.2%，正常 → 无 gross_yield warn
    assert not any(c["rule"] == "xfield.gross_yield" for c in g["warns"])
