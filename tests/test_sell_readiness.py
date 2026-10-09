"""卖方动机分 Sell-readiness Score（台账 2026-10-09 第 3 项，学自 Reonomy Top5）测试。

覆盖：规则层（持有年限/区域热度/DOB 未关闭判定/日期解析）/
无数据信号诚实 unavailable / 编排（mock TopHap + DOB）/
地址解析（门牌号+街道归一化）/ 降级路径。
"""
from datetime import date

import pytest

from app import sell_readiness as sr


_TODAY = date(2026, 10, 9)


# ---------- 日期/持有年限 ----------

@pytest.mark.parametrize("s,expected", [
    ("2010-05-01", date(2010, 5, 1)),
    ("20100501", date(2010, 5, 1)),
    ("05/01/2010", date(2010, 5, 1)),
    ("2010/05/01", date(2010, 5, 1)),
    ("", None),
    (None, None),
    ("not-a-date", None),
])
def test_parse_date(s, expected):
    assert sr._parse_date(s) == expected


def test_holding_years():
    assert sr.holding_years("2010-05-01", _TODAY) == pytest.approx(16.4, abs=0.1)
    assert sr.holding_years("2024-01-01", _TODAY) < 3
    assert sr.holding_years("", _TODAY) is None
    assert sr.holding_years("garbage", _TODAY) is None


# ---------- 区域热度 ----------

def test_sales_trend_hit():
    hit, note = sr.sales_trend_hit([
        {"year": 2023, "sale_count": 100},
        {"year": 2024, "sale_count": 120},
    ])
    assert hit is True
    assert "2023" in note and "2024" in note


def test_sales_trend_miss():
    hit, _ = sr.sales_trend_hit([
        {"year": 2023, "sale_count": 100},
        {"year": 2024, "sale_count": 105},
    ])
    assert hit is False


def test_sales_trend_insufficient():
    hit, note = sr.sales_trend_hit([{"year": 2024, "sale_count": 50}])
    assert hit is None
    assert "无法判断" in note
    hit, _ = sr.sales_trend_hit(None)
    assert hit is None


# ---------- DOB 未关闭判定 ----------

def test_dob_open_count():
    v = [
        {"violation_category": "V*-DOB VIOLATION - ACTIVE", "disposition_date": ""},
        {"violation_category": "V*-DOB VIOLATION - DISMISSED", "disposition_date": ""},
        {"violation_category": "V*-DOB VIOLATION - Resolved", "disposition_date": "20150608"},
        {"violation_category": "V*-DOB VIOLATION - ACTIVE", "disposition_date": "20100101"},
    ]
    open_n, total = sr.dob_open_count(v)
    assert (open_n, total) == (1, 4)


def test_dob_open_count_none():
    assert sr.dob_open_count(None) == (None, 0)


# ---------- 地址解析 ----------

@pytest.mark.parametrize("addr,num,toks", [
    ("450 W 44th St, New York, NY 10036", "450", ["WEST", "44", "STREET"]),
    ("1500 Atlantic Ave, Brooklyn, NY 11213", "1500", ["ATLANTIC", "AVENUE"]),
    ("222 4th Ave", "222", ["4", "AVENUE"]),
    ("1 Wall St", "1", ["WALL", "STREET"]),
])
def test_parse_house_street(addr, num, toks):
    assert sr.parse_house_street(addr) == (num, toks)


def test_parse_house_street_bad():
    assert sr.parse_house_street("") == ("", [])
    assert sr.parse_house_street("Main St") == ("", [])


def test_street_match():
    assert sr._street_match("WEST 44 STREET", ["WEST", "44", "STREET"])
    assert not sr._street_match("EAST 144 STREET", ["WEST", "44", "STREET"])
    assert not sr._street_match("WEST 45 STREET", ["WEST", "44", "STREET"])


# ---------- 规则层：满分/零分/无数据 ----------

def _full_data():
    return {
        "last_sale_date": "2008-03-15",
        "distress": True,
        "pre_foreclosure": [{"x": 1}],
        "dob_violations": [
            {"violation_category": "V*-DOB VIOLATION - ACTIVE", "disposition_date": ""}],
        "market_trend": [
            {"year": 2023, "sale_count": 100},
            {"year": 2024, "sale_count": 130}],
    }


def test_score_full_signals():
    out = sr.score(_full_data(), _TODAY)
    assert out["ok"] is True
    # 持有 25 + 违规 20 + 热度 10 = 55；贷款/再融资 unavailable
    assert out["score"] == 55
    assert out["available_points"] == 55
    assert out["tier"] == "中"
    by_id = {s["id"]: s for s in out["signals"]}
    assert by_id["holding_years"]["status"] == "hit"
    assert by_id["mortgage_maturity"]["status"] == "unavailable"
    assert by_id["refinance"]["status"] == "unavailable"
    assert by_id["lien_violation"]["earned"] == 20
    assert by_id["zip_sales_trend"]["status"] == "hit"


def test_score_all_miss():
    out = sr.score({
        "last_sale_date": "2024-06-01",
        "distress": False,
        "pre_foreclosure": [],
        "dob_violations": [],
        "market_trend": [
            {"year": 2023, "sale_count": 100},
            {"year": 2024, "sale_count": 102}],
    }, _TODAY)
    assert out["score"] == 0
    assert out["tier"] == "低"
    by_id = {s["id"]: s for s in out["signals"]}
    assert by_id["holding_years"]["status"] == "miss"
    assert by_id["lien_violation"]["status"] == "miss"
    assert by_id["zip_sales_trend"]["status"] == "miss"


def test_score_empty_data():
    out = sr.score({}, _TODAY)
    assert out["ok"] is True
    assert out["score"] == 0
    # 留置权信号部分可用（TopHap distress/法拍预警口径），其余全 unavailable
    assert out["available_points"] == 20
    by_id = {s["id"]: s for s in out["signals"]}
    assert by_id["lien_violation"]["status"] == "miss"
    assert by_id["lien_violation"]["earned"] == 0
    assert by_id["holding_years"]["status"] == "unavailable"
    assert by_id["mortgage_maturity"]["status"] == "unavailable"
    assert by_id["refinance"]["status"] == "unavailable"
    assert by_id["zip_sales_trend"]["status"] == "unavailable"
    assert any("无数据" in c or "暂无数据" in c for c in out["caveats"])


def test_score_dob_not_queried():
    """DOB 未查询（非 NYC）时违规信号仅基于 TopHap，且必须有 caveat。"""
    out = sr.score({
        "last_sale_date": "2008-01-01", "distress": False,
        "pre_foreclosure": [], "dob_violations": None,
        "market_trend": None,
    }, _TODAY)
    by_id = {s["id"]: s for s in out["signals"]}
    assert by_id["lien_violation"]["status"] == "miss"
    assert any("DOB" in c for c in out["caveats"])


def test_tier_thresholds():
    assert sr.tier_of(100) == "高" and sr.tier_of(70) == "高"
    assert sr.tier_of(69) == "中" and sr.tier_of(40) == "中"
    assert sr.tier_of(39) == "低"


# ---------- 编排（mock 数据源） ----------

def _mock_tophap_ok(address):
    return {"ok": True, "fields": [
        {"key": "last_sale_date", "value": "2005-09-20"},
        {"key": "distress", "value": False},
        {"key": "pre_foreclosure", "value": []},
        {"key": "tophap_market_trend", "value": [
            {"year": 2023, "sale_count": 80},
            {"year": 2024, "sale_count": 100}]},
    ], "note": "mock"}


def _mock_dob_ok(address):
    return {"ok": True, "violations": [], "note": "mock DOB：0 条"}


def test_score_for_address_full():
    out = sr.score_for_address("450 W 44th St, New York, NY 10036",
                               tophap_fetch=_mock_tophap_ok,
                               dob_fetch=_mock_dob_ok)
    assert out["ok"] is True
    assert out["address"].startswith("450 W 44th St")
    # 持有(2005)>10年 25 + 热度 80→100(+25%) 10 = 35
    assert out["score"] == 35
    assert out["tier"] == "低"


def test_score_for_address_empty():
    out = sr.score_for_address("", tophap_fetch=_mock_tophap_ok,
                               dob_fetch=_mock_dob_ok)
    assert out["ok"] is False


def test_score_for_address_tophap_down():
    def down(addr):
        return {"ok": False, "fields": [], "note": "token 过期"}
    out = sr.score_for_address("450 W 44th St, New York, NY 10036",
                               tophap_fetch=down, dob_fetch=_mock_dob_ok)
    assert out["ok"] is True
    by_id = {s["id"]: s for s in out["signals"]}
    assert by_id["holding_years"]["status"] == "unavailable"
    assert any("TopHap 不可用" in c for c in out["caveats"])


def test_score_for_address_dob_down():
    def dob_fail(addr):
        return {"ok": False, "violations": [], "note": "DOB 超时"}
    out = sr.score_for_address("450 W 44th St, New York, NY 10036",
                               tophap_fetch=_mock_tophap_ok,
                               dob_fetch=dob_fail)
    assert out["ok"] is True
    by_id = {s["id"]: s for s in out["signals"]}
    # DOB 失败 → 违规信号仅基于 TopHap（本例无压力 → miss）
    assert by_id["lien_violation"]["status"] == "miss"
    assert any("DOB 超时" in c for c in out["caveats"])


def test_score_for_address_non_ny():
    out = sr.score_for_address("1600 Pennsylvania Ave, Washington, DC 20500",
                               tophap_fetch=_mock_tophap_ok,
                               dob_fetch=_mock_dob_ok)
    assert out["ok"] is True
    assert any("仅支持纽约市" in c for c in out["caveats"])
