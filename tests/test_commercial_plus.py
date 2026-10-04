"""commercial_plus 接线层 + sensitivity 档位参数化 + condition_adjust 测试."""

from app import commercial_plus as cp
from app import condition_adjust as ca
from app import sensitivity, uw_commercial


class TestCommercialPlus:
    def _data(self):
        return uw_commercial.example_39_main()

    def test_base_keys_preserved(self):
        out = cp.compute_plus(self._data(), with_stress=False)
        for k in ("property", "rent_roll", "historical", "proforma", "analysis", "per_sf"):
            assert k in out, k
        assert "plus" in out

    def test_debt_yield(self):
        out = cp.compute_plus(self._data(), with_stress=False)
        loan = out["analysis"]["loan_bal"]
        bank = out["plus"]["noi_bank_bridge"]["bank_noi"]
        assert abs(out["plus"]["debt_yield"] - bank / loan) < 1e-4

    def test_debt_yield_loan_override(self):
        out = cp.compute_plus(self._data(), loan_amount=20_000_000, with_stress=False)
        bank = out["plus"]["noi_bank_bridge"]["bank_noi"]
        assert abs(out["plus"]["debt_yield"] - bank / 20_000_000) < 1e-4

    def test_dscr_dual_labels(self):
        out = cp.compute_plus(self._data(), with_stress=False)
        d = out["plus"]["dscr_dual"]
        assert d["trailing"]["primary"] and not d["proforma"]["primary"]
        assert "银行口径 NOI" in d["trailing"]["label"]
        assert "PF" in d["proforma"]["label"]

    def test_bank_bridge_waterfall(self):
        out = cp.compute_plus(self._data(), with_stress=False)
        b = out["plus"]["noi_bank_bridge"]
        items = [r["item"] for r in b["rows"]]
        assert items[0].startswith("卖方口径 NOI")
        assert items[-1] == "银行口径 NOI"
        assert any("管理费" in i for i in items)
        assert any("reserve" in i for i in items)
        assert any("空置" in i for i in items)
        assert b["bank_noi"] <= b["seller_noi"]

    def test_ltv_dual_with_range(self):
        out = cp.compute_plus(self._data(), with_stress=False,
                              valuation_range={"lo": 30_000_000, "hi": 40_000_000})
        ltv = out["plus"]["ltv"]
        loan = out["analysis"]["loan_bal"]
        assert abs(ltv["at_range_lo"] - loan / 30_000_000) < 1e-9
        assert abs(ltv["at_range_hi"] - loan / 40_000_000) < 1e-9

    def test_ltv_fallback_purchase(self):
        out = cp.compute_plus(self._data(), with_stress=False)
        ltv = out["plus"]["ltv"]
        assert "at_purchase" in ltv and "待估值接入" in ltv["note"]

    def test_p0_gaps_no_rentroll(self):
        d = self._data()
        d["tenants"] = []
        out = cp.compute_plus(d, with_stress=False)
        assert any("rent roll" in g for g in out["plus"]["p0_gaps"])
        assert not out["plus"]["has_rent_roll"]

    def test_stress_table_shape(self):
        out = cp.compute_plus(self._data(), with_stress=True)
        s = out["plus"]["stress"]
        labels = [r["scenario"] for r in s["rows"]]
        assert "基准" in labels
        assert any("+200bps" in l for l in labels)
        assert any("+300bps" in l for l in labels)
        assert any("组合" in l for l in labels)
        row = s["rows"][0]
        assert {"dscr_trailing", "debt_yield", "breakeven", "breaks"} <= set(row)

    def test_stress_worsens_dscr(self):
        out = cp.compute_plus(self._data(), with_stress=True)
        rows = {r["scenario"]: r for r in out["plus"]["stress"]["rows"]}
        assert rows["利率 +200bps"]["dscr_trailing"] <= rows["基准"]["dscr_trailing"]

    def test_endpoint(self):
        from fastapi.testclient import TestClient
        from app.main import app
        c = TestClient(app)
        r = c.post("/api/uw/compute-plus", json={"input": self._data()})
        assert r.status_code == 200
        assert "plus" in r.json()


class TestSensitivityTiers:
    def _d(self):
        return {"price": 500000, "monthly_rent": 3200, "rate": 6.5,
                "vacancy_pct": 8}

    def test_legacy_unchanged(self):
        out = sensitivity.run("residential", self._d())
        assert len(out["rent_table"]) == 5
        assert len(out["rate_table"]) == 5
        assert out["rent_table"][2]["label"] == "+0%"
        assert "vacancy_table" not in out

    def test_tiered(self):
        out = sensitivity.run("residential", self._d(), tiers={})
        labels = [r["label"] for r in out["rate_table"]]
        assert "+100bps" in labels and "+300bps" in labels
        assert "vacancy_table" in out and out["combo"] is not None
        assert any(r["label"] == "+2pp" for r in out["vacancy_table"])

    def test_endpoint_tiers(self):
        from fastapi.testclient import TestClient
        from app.main import app
        c = TestClient(app)
        r = c.post("/api/sensitivity", json={
            "track": "residential", "input": self._d(), "tiers": {}})
        assert r.status_code == 200
        assert "vacancy_table" in r.json()
        # 不带 tiers → 旧行为
        r2 = c.post("/api/sensitivity", json={"track": "residential", "input": self._d()})
        assert len(r2.json()["rate_table"]) == 5


class TestConditionAdjust:
    def test_adjacent(self):
        r = ca.adjust("Average", "Fair", 500_000, "翻新成本 $45/SF × 12,000 SF")
        assert r["applied"] and r["steps"] == 1
        assert 0.03 <= r["rate"] <= 0.08
        assert r["adjustment"] > 0  # comp 更破，上调

    def test_two_tiers(self):
        r = ca.adjust("Average", "Poor", 500_000, "$45/SF × 12,000 SF")
        assert r["steps"] == 2 and 0.08 <= r["rate"] <= 0.15

    def test_no_basis_no_adjust(self):
        r = ca.adjust("Average", "Fair", 500_000, "")
        assert not r["applied"]
        assert "无调整依据" in r["reason"]

    def test_same_tier(self):
        r = ca.adjust("Good", "Good", 500_000, "x")
        assert not r["applied"] and r["adjustment"] == 0

    def test_endpoint(self):
        from fastapi.testclient import TestClient
        from app.main import app
        c = TestClient(app)
        r = c.post("/api/condition/adjust", json={
            "subject_tier": "Average", "comp_tier": "Fair",
            "comp_price": 500000, "basis": "$45/SF × 12,000 SF"})
        assert r.status_code == 200
        assert r.json()["applied"]
