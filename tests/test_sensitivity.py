"""敏感性分析 tiers 参数校验回归测试（P0-2，2026-10-05）。

背景：/api/sensitivity 传 tiers 标量（如 tiers:{rate_bps:200}）曾导致 500；
现 fail-closed：标量/非法 tiers → 422 中文报错，list 形式 200 不变。
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from app import sensitivity
from app.main import app

client = TestClient(app)

_BASE_RES = {"monthly_rent": 6500, "other_income_monthly": 0, "price": 1550000,
             "down_pct": 20, "rate": 7.5, "years": 30, "vacancy_pct": 8,
             "taxes_annual": 8000, "insurance_annual": 3000, "maint_pct": 8}


def _payload(tiers):
    return {"track": "residential", "input": dict(_BASE_RES), "tiers": tiers}


# ---------- 单元：_validate_tiers ----------

def test_tiers_none_is_legacy_ok():
    assert sensitivity._validate_tiers(None) is None


def test_tiers_scalar_rejected():
    # 文档曾写 tiers{rate_bps,…} 标量形式 → 必须 422，不再 500
    with pytest.raises(ValueError, match="应为数组"):
        sensitivity._validate_tiers({"rate_bps": 200, "vacancy_pp": 5,
                                     "rent_pct": -10, "combo": True})


def test_tiers_list_accepted():
    t = {"rate_bps": [100, 200, 300], "vacancy_pp": [0, 2, 5],
         "rent_pct": [-20, -10], "combo": True}
    assert sensitivity._validate_tiers(t) == t


def test_tiers_non_dict_rejected():
    with pytest.raises(ValueError, match="应为对象"):
        sensitivity._validate_tiers([100, 200])


def test_tiers_bad_combo_rejected():
    with pytest.raises(ValueError, match="combo"):
        sensitivity._validate_tiers({"rate_bps": [100], "combo": "yes"})


def test_tiers_non_numeric_list_rejected():
    with pytest.raises(ValueError, match="数字数组"):
        sensitivity._validate_tiers({"rate_bps": [100, "x"]})


# ---------- 集成：API 层 ----------

def test_api_tiers_scalar_422_not_500():
    r = client.post("/api/sensitivity", json=_payload(
        {"rate_bps": 200, "vacancy_pp": 5, "rent_pct": -10, "combo": True}))
    assert r.status_code == 422
    assert "数组" in r.json()["detail"]


def test_api_tiers_list_200():
    r = client.post("/api/sensitivity", json=_payload(
        {"rate_bps": [100, 200], "vacancy_pp": [0, 5],
         "rent_pct": [-10, 0], "combo": False}))
    assert r.status_code == 200
    d = r.json()
    assert len(d["rate_table"]) == 2 and len(d["vacancy_table"]) == 2


def test_api_no_tiers_legacy_200():
    r = client.post("/api/sensitivity",
                    json={"track": "residential", "input": dict(_BASE_RES)})
    assert r.status_code == 200
    assert "rent_table" in r.json()


def test_api_unknown_track_422_not_500():
    r = client.post("/api/sensitivity",
                    json={"track": "nope", "input": dict(_BASE_RES)})
    assert r.status_code == 422
