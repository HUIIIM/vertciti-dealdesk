"""全面分析工作台 API 测试：测算 / 估值 / 预测 / 市场调查 / 打分映射."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.workbench import (forecast, property_metrics, reconcile, series_stats,
                           valuate_comps, valuate_income, WbComp, WbProperty,
                           WbScenario)

client = TestClient(app)


def _prop(**kw):
    base = dict(address="test", asking_price=500000, down_payment=0,
                loan_balance=298000, rate=8.25, term_years=30,
                monthly_rent=3500, taxes_annual=6000, insurance_annual=2400)
    base.update(kw)
    return base


def test_wb_markets():
    r = client.get("/api/wb/markets")
    assert r.status_code == 200
    d = r.json()
    assert set(m["key"] for m in d["markets"]) >= {"us", "nyc", "phoenix", "tampa", "dallas", "atlanta"}
    # 每个市场必须带来源与更新日期
    for m in d["markets"]:
        assert m.get("source"), m["key"]
        assert m.get("vintage"), m["key"]
    assert d["public_sources"], "公开数据源链接不能为空"
    assert "methodology" in d


def test_wb_metrics():
    r = client.post("/api/wb/metrics", json={"property": _prop()})
    assert r.status_code == 200
    m = r.json()["metrics"]
    assert m["noi_annual"] > 0
    assert m["cash_flow_monthly"] < m["noi_monthly"]  # 有贷款月供
    assert m["dscr"] is not None and m["dscr"] > 0
    assert m["cash_to_close"] >= 0


def test_wb_valuate_comps_and_income():
    payload = {
        "property": _prop(),
        "comps": [
            {"address": "a", "status": "sold", "price": 480000, "sf": 2000, "distance_miles": 0.5},
            {"address": "b", "status": "sold", "price": 520000, "sf": 2100, "distance_miles": 1.0},
        ],
        "income_noi_annual": 30000,
        "income_cap_rate_pct": 6.0,
        "comp_weight": 0.5,
    }
    r = client.post("/api/wb/valuate", json=payload)
    assert r.status_code == 200
    d = r.json()
    assert d["tag"] == "估算"
    assert d["comps"]["count"] == 2
    assert d["comps"]["estimate"] > 0
    assert d["income"]["value"] == 30000 / 0.06
    rec = d["reconciled"]
    assert rec["reconciled"] is not None
    assert rec["range"][0] <= rec["reconciled"] <= rec["range"][1]


def test_wb_valuate_empty_comps():
    r = client.post("/api/wb/valuate", json={"property": _prop(), "comps": []})
    assert r.status_code == 200
    assert r.json()["comps"]["count"] == 0


def test_wb_forecast_disclaimer():
    r = client.post("/api/wb/forecast", json={
        "base_value": 500000, "years": 3,
        "scenarios": [{"name": "base", "label": "基准", "annual_rate_pct": 3.0}],
    })
    assert r.status_code == 200
    d = r.json()
    assert d["tag"] == "情景预测"
    assert "不是承诺" in d["disclaimer"]
    s = d["scenarios"][0]
    assert len(s["value_path"]) == 3
    assert abs(s["value_path"][-1] - 500000 * 1.03 ** 3) < 1


def test_wb_series():
    pts = [{"q": f"2025Q{i}", "value": 500 + i * 5} for i in range(1, 5)] + [{"q": "2026Q1", "value": 525}]
    r = client.post("/api/wb/series", json={"points": pts})
    assert r.status_code == 200
    d = r.json()
    assert d["count"] == 5
    assert d["yoy_pct"] is not None
    assert d["cumulative_pct"] > 0


def test_wb_comps_parse():
    csv_text = "address,status,price,sf,distance_miles,adjustment_pct,note\na,sold,480000,2000,0.5,0,\nbad,sold,0,0,0,0,"
    r = client.post("/api/wb/comps/parse", json={"csv": csv_text})
    assert r.status_code == 200
    d = r.json()
    assert len(d["rows"]) == 1
    assert len(d["errors"]) == 1


def test_wb_score_uses_existing_engine():
    r = client.post("/api/wb/score", json={"track": "residential", "property": _prop()})
    assert r.status_code == 200
    d = r.json()
    assert "total" in d["score"] and "grade" in d["score"]
    assert "v2.3" in d["note"]


def test_wb_score_bad_track():
    r = client.post("/api/wb/score", json={"track": "nope", "property": _prop()})
    assert r.status_code == 400


def test_wb_research_and_report():
    payload = {"research": {
        "address": "tampa test", "market_key": "tampa",
        "vacancy_note": "空置率 6%", "vacancy_source": "https://example.com",
    }}
    r = client.post("/api/wb/research", json=payload)
    assert r.status_code == 200
    d = r.json()
    assert d["completeness"]["sourced"] == 1
    assert d["market"]["key"] == "tampa"
    r2 = client.post("/api/wb/research/report", json=payload)
    assert r2.status_code == 200
    html = r2.text
    assert "市场调查报告" in html
    assert "情景预测" in html or "预测" in html
    assert "window.print" in html


# ---- 纯函数单元测试 ----

def test_valuate_comps_weighting():
    comps = [WbComp(address="near", price=400000, distance_miles=0.1),
             WbComp(address="far", price=600000, distance_miles=10.0)]
    d = valuate_comps(comps)
    assert d["estimate"] < 500000  # 近的权重更高


def test_valuate_income_invalid():
    assert valuate_income(30000, 0)["value"] is None


def test_reconcile_single_method():
    d = reconcile(500000, None)
    assert d["reconciled"] == 500000


def test_property_metrics_no_loan():
    m = property_metrics(WbProperty(asking_price=300000, monthly_rent=2500))
    assert m["dscr"] is None
    assert m["cash_flow_monthly"] == m["noi_monthly"]


def test_forecast_defaults():
    d = forecast(100000, [WbScenario(name="x", annual_rate_pct=0)])
    assert d["scenarios"][0]["value_path"] == [100000.0, 100000.0, 100000.0]


def test_series_stats_sorted():
    pts = [{"q": "2026Q1", "value": 110}, {"q": "2025Q1", "value": 100}]
    d = series_stats(pts)
    assert d["first"]["q"] == "2025Q1"
    assert d["cumulative_pct"] == 10.0
