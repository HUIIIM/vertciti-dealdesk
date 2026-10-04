"""Comps 独立模块测试：三态归一化 / CSV 新列 / TopHap CMA 一键拉取（全部 mock，不碰公网）."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from app import tophap, workbench
from app.main import app
from app.workbench import WbComp, normalize_comp_status, parse_comps_csv, pull_comps

client = TestClient(app)


# ---------- 状态归一化 ----------

def test_status_normalize():
    assert normalize_comp_status("sold") == "sold"
    assert normalize_comp_status("SOLD") == "sold"
    assert normalize_comp_status("active") == "for_sale"   # 旧口径兼容
    assert normalize_comp_status("under_contract") == "under_contract"
    assert normalize_comp_status("for_sale") == "for_sale"
    assert normalize_comp_status("junk") == "sold"          # 未知兜底
    assert normalize_comp_status("") == "sold"
    assert normalize_comp_status(None) == "sold"


def test_wbcomp_status_validator_and_cap_rate():
    c = WbComp(address="a", status="active", price=1_000_000, noi_annual=60_000)
    assert c.status == "for_sale"
    assert abs(c.cap_rate - 0.06) < 1e-9
    c2 = WbComp(address="b", price=500_000)
    assert c2.status == "sold"
    assert c2.cap_rate is None  # 无 NOI → N/A，不编造
    c3 = WbComp(address="c", status="under_contract", price=800_000,
                sale_date="2026-05-01", source="Redfin")
    assert c3.sale_date == "2026-05-01" and c3.source == "Redfin"


# ---------- CSV 新列 ----------

def test_parse_csv_new_columns():
    csv_text = ("address,status,price,sale_date,sf,distance_miles,adjustment_pct,"
                "noi_annual,source,note\n"
                "123 Main St,sold,485000,2026-03-01,1500,0.5,0,30000,Redfin,good\n"
                "456 Oak Ave,active,520000,,1600,1.2,-5,,手动录入,\n"
                "bad row,missing fields\n")
    d = parse_comps_csv(csv_text)
    assert len(d["rows"]) == 2
    r0 = d["rows"][0]
    assert r0["sale_date"] == "2026-03-01" and r0["source"] == "Redfin"
    assert r0["noi_annual"] == 30000
    assert d["rows"][1]["status"] == "for_sale"  # active 兼容
    assert d["rows"][1]["source"] == "手动录入"
    assert len(d["errors"]) == 1


# ---------- 一键拉取（mock TopHap） ----------

_FAKE_CMA_FIELDS = [
    {"key": "tophap_comps", "value": [
        {"address": "461 W 47TH ST, NEW YORK", "price": 1400000.0,
         "date": "2026-06-04", "price_per_sqft": 347.0, "sqft": 4037.0,
         "year_built": 1910.0, "distance_mi": 0.18},
        {"address": "533 9TH AVE, NEW YORK", "price": 2833187.0,
         "date": "2026-06-29", "price_per_sqft": 708.0, "sqft": 4000.0,
         "year_built": 1900.0, "distance_mi": 0.23},
        {"address": "223 W 29TH ST, NEW YORK", "price": 6563107.0,
         "date": "2025-07-17", "price_per_sqft": 1390.0, "sqft": 4721.0,
         "year_built": 1920.0, "distance_mi": 0.82},
        {"address": "318 LEXINGTON AVE, NEW YORK", "price": 2500000.0,
         "date": "2026-07-09", "price_per_sqft": None, "sqft": 5165.0,
         "year_built": 1910.0, "distance_mi": 1.13},
        {"address": "no price row", "price": 0, "date": "", "sqft": 0},
    ]},
    {"key": "other_field", "value": "ignored"},
]


def _fake_enrich_ok(address, log=None):
    return {"ok": True, "fields": _FAKE_CMA_FIELDS, "note": "fake"}


def test_pull_comps_ok(monkeypatch):
    monkeypatch.setattr(tophap, "enrich_address", _fake_enrich_ok)
    r = pull_comps("450 W 44th St, New York, NY 10036")
    assert r["ok"] is True
    assert r["count"] == 4  # price=0 的脏行被剔除
    for row in r["rows"]:
        assert row["status"] == "sold"
        assert "TopHap" in row["source"]          # 来源必填且带标签
        assert row["price"] > 0
    # price_per_sqft 缺失时自动回算
    lex = next(x for x in r["rows"] if "LEXINGTON" in x["address"])
    assert abs(lex["price_per_sf"] - 2500000.0 / 5165.0) < 0.01
    assert lex["sale_date"] == "2026-07-09"
    assert lex["distance_miles"] == 1.13


def test_pull_comps_empty_address():
    r = pull_comps("   ")
    assert r["ok"] is False and "空" in r["error"]


def test_pull_comps_degraded(monkeypatch):
    monkeypatch.setattr(tophap, "enrich_address",
                        lambda address, log=None: {"ok": False, "note": "token 已过期"})
    r = pull_comps("450 W 44th St")
    assert r["ok"] is False and "token" in r["error"]


def test_pull_comps_no_rows(monkeypatch):
    monkeypatch.setattr(tophap, "enrich_address",
                        lambda address, log=None: {"ok": True, "fields": [], "note": "fake"})
    r = pull_comps("450 W 44th St")
    assert r["ok"] is False and "CMA" in r["error"]


# ---------- 端点 ----------

def test_endpoint_pull_ok(monkeypatch):
    monkeypatch.setattr(workbench, "pull_comps",
                        lambda addr: {"ok": True, "rows": [{"address": "a", "status": "sold",
                                                           "price": 1, "source": "TopHap CMA"}],
                                      "count": 1, "source": "TopHap CMA",
                                      "fetched_at": "2026-10-04", "note": "n"})
    r = client.post("/api/wb/comps/pull", json={"address": "450 W 44th St"})
    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_endpoint_pull_empty_address_422():
    r = client.post("/api/wb/comps/pull", json={"address": "   "})
    assert r.status_code == 422


def test_endpoint_pull_degraded_502(monkeypatch):
    monkeypatch.setattr(workbench, "pull_comps",
                        lambda addr: {"ok": False, "error": "token 已过期"})
    r = client.post("/api/wb/comps/pull", json={"address": "450 W 44th St"})
    assert r.status_code == 502


def test_valuate_accepts_three_statuses():
    # 估值端到端：三态 + 新字段不炸
    comps = [
        {"address": "a", "status": "sold", "price": 1_000_000, "sf": 2000,
         "distance_miles": 0.5, "source": "TopHap CMA"},
        {"address": "b", "status": "under_contract", "price": 1_100_000, "sf": 2200,
         "distance_miles": 0.8, "source": "Redfin"},
        {"address": "c", "status": "active", "price": 1_200_000, "sf": 2400,
         "distance_miles": 1.0, "source": "手动录入"},  # 旧 active 兼容
    ]
    r = client.post("/api/wb/valuate", json={
        "property": {"address": "x"}, "comps": comps,
        "income_noi_annual": None, "income_cap_rate_pct": None, "comp_weight": 0.5})
    assert r.status_code == 200
    d = r.json()
    assert d["comps"]["count"] == 3
    assert d["comps"]["estimate"] > 0
