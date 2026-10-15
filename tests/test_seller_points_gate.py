"""住宅门 seller_points 噪声消除（台账第 16 项，2026-10-15）测试。

seller_points 是 intake 产物（卖方话术要点，文本列表），本不在
residential-v1 schema 内，此前每次被 schema.unknown_field warn 并进
yellow_fields 标黄，淹没真矛盾信号。修复：schema 登记为已知非数值
字段（list_str），门内不再告警。

验收口径（台账原文）：干净住宅样本 yellow_fields 不含 seller_points、
矛盾样本标黄不变。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import pdf_intake, validators


def _res_fields(**over):
    base = [
        {"key": "asking_price", "value": 750000, "confidence": "卖方口径"},
        {"key": "building_sf", "value": 2400, "confidence": "卖方口径"},
        {"key": "monthly_rent", "value": 3200, "confidence": "卖方口径"},
        {"key": "seller_points", "value": ["Great location near schools",
                                           "Priced at $750,000 firm"],
         "confidence": "卖方口径"},
    ]
    for f in base:
        if f["key"] in over:
            f["value"] = over[f["key"]]
    return base


def test_clean_residential_sample_no_seller_points_noise():
    g = validators.run_quality_gate("residential", _res_fields())
    rules = [c["rule"] for c in g["warns"] + g["fails"]]
    assert "schema.unknown_field" not in rules
    assert "seller_points" not in g["yellow_fields"]
    # 字段仍在 field_report 里留痕（登记不等于隐藏）
    keys = [r["key"] for r in g["field_report"]]
    assert "seller_points" in keys


def test_contradiction_yellow_unchanged():
    # 价格/SF 物理不可能（$750k / 50 SF 的矛盾样本，见 #4 生产实证口径）
    g = validators.run_quality_gate("residential", _res_fields(building_sf=50))
    assert g["status"] in ("warn", "blocked")
    assert "seller_points" not in g["yellow_fields"]
    assert "building_sf" in g["yellow_fields"] or g["fails"]


def test_commercial_schema_also_registered():
    fields = [
        {"key": "analysis.purchase_price", "value": 4350000, "confidence": "卖方口径"},
        {"key": "property.net_rentable_sf", "value": 12500, "confidence": "卖方口径"},
        {"key": "analysis.underwritten_noi", "value": 285000, "confidence": "卖方口径"},
        {"key": "seller_points", "value": ["Value-add opportunity"],
         "confidence": "卖方口径"},
    ]
    g = validators.run_quality_gate("commercial", fields)
    rules = [c["rule"] for c in g["warns"] + g["fails"]]
    assert "schema.unknown_field" not in rules
    assert "seller_points" not in g["yellow_fields"]


def test_real_residential_parse_has_no_unknown_warn():
    """真实住宅解析链路：parse 产物直接过门，不再产 unknown_field。"""
    text = ("Charming 3 bed 2 bath home. Asking $750,000. 2,400 sq ft. "
            "Rent $3,200 per month. Great location near schools! "
            "Priced to sell at $750,000.")
    parsed = pdf_intake.parse_pdf_text(text, "home.pdf")
    keys = [f["key"] for f in parsed["fields"]]
    assert "seller_points" in keys  # 解析确实产出该字段，本测试才有意义
    g = validators.run_quality_gate("residential", parsed["fields"])
    rules = [c["rule"] for c in g["warns"] + g["fails"]]
    assert "schema.unknown_field" not in rules
    assert "seller_points" not in g["yellow_fields"]


def test_unknown_field_still_warns():
    """豁免只给已登记字段：真未知字段仍须告警（不许把门拆了）。"""
    fields = _res_fields() + [{"key": "some_new_field", "value": 1,
                               "confidence": "卖方口径"}]
    g = validators.run_quality_gate("residential", fields)
    rules = [c["rule"] for c in g["warns"] + g["fails"]]
    assert "schema.unknown_field" in rules
    assert "some_new_field" in g["yellow_fields"]
