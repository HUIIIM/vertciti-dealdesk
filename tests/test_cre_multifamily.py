"""机构级多户公寓（按户型逐月）：每条口径一个可手算的用例。"""
from __future__ import annotations

import pytest

from app.domain.v2.cre.engine import CreInputError, run
from app.domain.v2.cre.example import garden_multifamily

QUIET = {"rent_growth_pct": 0, "lease_term_months": 12, "concessions_pct": 0, "non_revenue_units": 0,
         "other_income_per_unit": 0, "turnover_pct": 0, "make_ready_per_turn": 0, "opex_per_unit_yr": 0,
         "taxes_yr": 0, "insurance_yr": 0, "reserves_per_unit_yr": 0}


def mf(unit: dict | None = None, **over) -> dict:
    """10 户、在租 = 市场 = 1000 / 月、零增长零费用零空置：NOI = 10 × 1000 × 12 = 12 万，按 8% 买卖 IRR = 8%。"""
    d = {"property_type": "multifamily", "analysis_start": "2026-01", "hold_years": 5, "area_sf": 8_000,
         "purchase_price": 1_500_000, "closing_costs_pct": 0,
         "unit_mix": [{"name": "1B", "units": 10, "in_place_rent": 1_000, "market_rent": 1_000, **(unit or {})}],
         "multifamily": dict(QUIET), "opex": {"growth_pct": 0, "mgmt_fee_pct_egr": 0},
         "general_vacancy_pct": 0, "credit_loss_pct": 0, "exit_cap_pct": 8, "selling_costs_pct": 0}
    for k, v in over.items():
        d[k] = {**d[k], **v} if isinstance(v, dict) and isinstance(d.get(k), dict) else v
    return d


def test_closed_form_irr_equals_cap_rate():
    r = run(mf())
    assert r["annual"]["noi"][0] == pytest.approx(120_000)
    assert r["metrics"]["going_in_cap_pct"] == pytest.approx(8.0)
    assert r["metrics"]["unlevered_irr_pct"] == pytest.approx(8.0, abs=1e-6)
    assert r["metrics"]["price_per_unit"] == 150_000 and r["metrics"]["units"] == 10
    assert r["rent_roll"] == [] and r["unit_mix"][0]["loss_to_lease_pct"] == 0


def test_loss_to_lease_burns_off_as_leases_roll():
    """在租 900、市场 1000、12 个月租期均匀到期：第 m 月已续 m 批 → 月租 900 + 100 × m / 12；
    首年合计 = 12 × 900 + 100 × (0 + 1 + … + 11) / 12 = 11,350 / 户；次年全部到市场 = 12,000 / 户。"""
    r = run(mf({"in_place_rent": 900}))
    a = r["annual"]
    assert a["base_rent"][0] == pytest.approx(10 * 11_350)
    assert a["loss_to_lease"][0] == pytest.approx(-10 * 650)
    assert a["base_rent"][1] == pytest.approx(10 * 12_000) and a["loss_to_lease"][1] == pytest.approx(0)
    assert r["unit_mix"][0]["loss_to_lease_pct"] == pytest.approx(10)


def test_market_growth_reaches_rents_with_a_lag():
    """市场租金年增 10%：第 12 月（次年第 1 月）只有第 11 批在当月续约拿到 1100，其余 11 批仍是去年续的 1000。"""
    r = run(mf(multifamily={"rent_growth_pct": 10}, hold_years=2))
    first_month_y2 = 10 * (11 * 1_000 + 1_100) / 12
    assert r["monthly"]["noi"][12] == pytest.approx(first_month_y2)
    assert r["annual"]["potential_rent"][1] == pytest.approx(10 * 1_100 * 12)


def test_renovation_downtime_premium_and_cost():
    """翻新 4 户、每月开工 2 户、停用 1 个月、溢价 100、每户 5000：
    第 0 月 2 户停用 → 基本租金 8 × 1000；第 1 月 2 户完工 2 户停用 → 6 × 1000 + 2 × 1100；第 2 月起 6 × 1000 + 4 × 1100。"""
    r = run(mf({"renovate_units": 4, "reno_premium": 100, "reno_cost_per_unit": 5_000},
               multifamily={"reno_units_per_month": 2, "reno_downtime_months": 1, "reno_start_month": 0}))
    mo = r["monthly"]
    assert mo["noi"][:3] == pytest.approx([8_000, 8_200, 10_400])
    assert mo["cf_before_debt"][:3] == pytest.approx([8_000 - 10_000, 8_200 - 10_000, 10_400])
    assert mo["occupancy_pct"][:3] == pytest.approx([80, 80, 100])
    a = r["annual"]
    assert a["capex"][0] == pytest.approx(-20_000) and r["metrics"]["capex_total"] == pytest.approx(20_000)
    assert a["turnover_vacancy"][0] == pytest.approx(-4_000)
    # 科目对得上：基本租金 = 潜在租金 + loss-to-lease + 溢价 + 停用损失 + 不产生租金
    for y in range(6):
        bridge = (a["potential_rent"][y] + a["loss_to_lease"][y] + a["premium"][y] + a["turnover_vacancy"][y]
                  + a["non_revenue"][y])
        assert bridge == pytest.approx(a["base_rent"][y])


def test_revenue_deductions_other_income_and_opex():
    """1 户不产生租金；优惠 1%、空置 5%、坏账 1%；其他收入 50 / 户 / 月；税 1.2 万、保险 0.6 万、每户运营 3000、
    换租 50% × 每次 600、管理费 3%、储备 250 / 户。"""
    r = run(mf(multifamily={"non_revenue_units": 1, "concessions_pct": 1, "other_income_per_unit": 50, "taxes_yr": 12_000,
                            "insurance_yr": 6_000, "opex_per_unit_yr": 3_000, "turnover_pct": 50,
                            "make_ready_per_turn": 600, "reserves_per_unit_yr": 250},
               general_vacancy_pct=5, credit_loss_pct=1, opex={"mgmt_fee_pct_egr": 3}))
    a = r["annual"]
    base = 9 * 12_000
    other = 50 * 9 * 12 * 0.95
    gross = base * (1 - 0.01 - 0.05) + other
    egr = gross * 0.99
    assert a["base_rent"][0] == pytest.approx(base) and a["non_revenue"][0] == pytest.approx(-12_000)
    assert a["recoveries"][0] == pytest.approx(other)
    assert a["egr"][0] == pytest.approx(egr)
    opex = 18_000 + 30_000 + 0.5 * 9 * 600 + 0.03 * egr
    assert a["opex"][0] == pytest.approx(-opex)
    assert a["noi"][0] == pytest.approx(egr - opex)
    assert a["reserves"][0] == pytest.approx(-2_500)
    assert a["occupancy_pct"][0] == pytest.approx(9 / 10 * 95)


def test_stabilized_exit_adds_back_renovation_downtime():
    """持有 1 年、退出年（第 2 年）开工翻新 2 户、停用 1 个月：稳定化加回这 2 户 × 1 个月 × 1000。"""
    d = mf({"renovate_units": 2}, hold_years=1, multifamily={"reno_start_month": 12, "reno_units_per_month": 2})
    raw = run(d)["metrics"]
    stab = run({**d, "exit_noi_basis": "stabilized"})["metrics"]
    assert raw["forward_noi_unadjusted"] == pytest.approx(120_000 - 2_000)
    assert stab["forward_noi"] == pytest.approx(120_000)


def test_example_runs_and_is_plausible():
    m = run(garden_multifamily())["metrics"]
    assert m["going_in_cap_pct"] == pytest.approx(5.523, abs=1e-3)
    assert m["levered_irr_pct"] == pytest.approx(15.43, abs=1e-2)
    assert m["capex_total"] == pytest.approx(120 * 12_000)
    assert m["avg_occupancy_pct"] == pytest.approx(93.423, abs=1e-3)


@pytest.mark.parametrize(("patch", "fragment"), [
    ({"unit_mix": []}, "户型表"),
    ({"leases": [{"tenant": "A", "sf": 100, "start": "2025-01", "end": "2030-01", "rent_psf_yr": 10}]}, "不填逐份租约"),
    ({"unit_mix": [{"name": "1B", "units": 2, "in_place_rent": 1, "market_rent": 1, "renovate_units": 3}]}, "超过户数"),
    ({"multifamily": {**QUIET, "non_revenue_units": 10}}, "不少于总户数"),
])
def test_rejects_bad_multifamily_inputs(patch, fragment):
    with pytest.raises(CreInputError, match=fragment):
        run({**mf(), **patch})


def test_commercial_still_requires_market():
    d = {k: v for k, v in mf().items() if k not in ("unit_mix", "multifamily")}
    with pytest.raises(CreInputError, match="市场租赁假设"):
        run({**d, "property_type": "commercial"})


def test_example_endpoint_serves_both_kinds(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    monkeypatch.setenv("DEALDESK_DB", str(tmp_path / "v2.db"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DEALDESK_AUTH", raising=False)
    c = TestClient(app)
    assert c.get("/api/v2/cre/example").json()["leases"]
    mf_ex = c.get("/api/v2/cre/example?kind=multifamily").json()
    assert mf_ex["property_type"] == "multifamily"
    r = c.post("/api/v2/cre/run", json=mf_ex).json()
    assert r["unit_mix"][0]["name"] == "1B1B" and r["metrics"]["units"] == 240
