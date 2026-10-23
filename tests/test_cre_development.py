"""开发 / 施工期与施工贷：每条口径一个可手算的用例。"""
from __future__ import annotations

import pytest

from app.domain.v2.cre.development import cost_schedule, weights
from app.domain.v2.cre.engine import CreInputError, run
from app.domain.v2.cre.example import ground_up_multifamily
from app.domain.v2.cre.inputs import Development

QUIET = {"recoverable_psf_yr": 0, "non_recoverable_psf_yr": 0, "growth_pct": 0, "mgmt_fee_pct_egr": 0, "reserves_psf_yr": 0}


def dev_office(**over) -> dict:
    """土地 100 万；硬成本 120 万、施工 2 个月平均支出；1 万 SF 竣工后空置招租（空置 0 月、市场 40、零增长零费用）。"""
    d = {"analysis_start": "2026-01", "hold_years": 3, "area_sf": 10_000, "purchase_price": 1_000_000,
         "closing_costs_pct": 0, "leases": [],
         "market": {"rent_psf_yr": 40, "rent_growth_pct": 0, "renewal_prob_pct": 0, "downtime_months": 0,
                    "free_rent_new_months": 0, "ti_new_psf": 0, "lc_new_pct": 0, "lease_term_years": 5, "escalation_pct": 0},
         "opex": dict(QUIET), "general_vacancy_pct": 0, "credit_loss_pct": 0, "exit_cap_pct": 8, "selling_costs_pct": 0,
         "development": {"construction_months": 2, "hard_costs": 1_200_000, "soft_costs": 0, "contingency_pct": 0,
                         "draw_curve": "straight"}}
    d.update(over)
    return d


def test_cost_curve_contingency_and_soft_upfront():
    dev = Development(construction_months=4, hard_costs=1_000, soft_costs=200, soft_upfront_pct=25, contingency_pct=10,
                      draw_curve="straight")
    sched = cost_schedule(dev, 6)
    assert sched[0] == pytest.approx(50 + (1_100 + 150) / 4)      # 先付软成本 25% = 50
    assert sched[1:4] == pytest.approx([(1_100 + 150) / 4] * 3) and sched[4:] == [0, 0]
    assert sum(sched) == pytest.approx(1_300)
    s = weights(4, "s_curve")
    assert sum(s) == pytest.approx(1) and s[0] == pytest.approx(s[3]) and s[1] > s[0]


def test_construction_period_has_no_operations_and_lease_up_starts_at_completion():
    r = run(dev_office())
    mo, a = r["monthly"], r["annual"]
    assert mo["noi"][:2] == [0, 0] and mo["occupancy_pct"][:2] == [0, 0]
    assert mo["cf_before_debt"][:2] == pytest.approx([-600_000, -600_000])
    assert mo["noi"][2] == pytest.approx(40 * 10_000 / 12)          # 第 2 月竣工即起租（空置 0 月）
    assert a["dev_costs"][0] == pytest.approx(-1_200_000)
    m = r["metrics"]
    assert m["total_project_cost"] == pytest.approx(2_200_000)
    assert m["going_in_cap_pct"] is None and m["yield_on_cost_pct"] is None
    # 稳定月默认 = 竣工后 12 个月：第 14 … 25 月 NOI 合计 = 40 万
    assert m["stabilized_noi"] == pytest.approx(400_000)
    assert m["development_yield_pct"] == pytest.approx(400_000 / 2_200_000 * 100)
    assert m["value_creation"] == pytest.approx(400_000 / 0.08 - 2_200_000)


def test_construction_loan_equity_first_then_draws_with_capitalized_interest():
    """LTC 50% → 承诺 110 万，股权先投 110 万：土地 100 万全股权；第 0 月成本 60 万 = 股权 10 万 + 提款 50 万；
    第 1 月：先按 1%（12% / 12）对 50 万计息 0.5 万并资本化，再提款 60 万 → 余额 110.5 万；第 2 月竣工，利息 1.105 万改为现金支付。"""
    r = run(dev_office(construction_loan={"ltc_pct": 50, "rate_pct": 12, "orig_fee_pct": 0}))
    c = r["construction"]
    assert c["commitment"] == pytest.approx(1_100_000) and c["equity_required"] == pytest.approx(1_100_000)
    assert c["capitalized_interest"] == pytest.approx(5_000) and c["peak_balance"] == pytest.approx(1_105_000)
    mo = r["monthly"]["debt_service"]
    assert mo[:2] == [0, 0] and mo[2] == pytest.approx(11_050)
    assert r["annual"]["construction_draws"][0] == pytest.approx(1_100_000)
    assert r["metrics"]["equity"] == pytest.approx(1_000_000)
    assert r["exit"]["loan_payoff"] == pytest.approx(1_105_000)       # 没有再融资：出售时偿清
    assert r["metrics"]["dscr_min"] is not None and r["metrics"]["dscr_year1"] is None  # 施工与去化年不算 DSCR


def test_refinance_takes_out_the_construction_loan():
    d = dev_office(construction_loan={"ltc_pct": 50, "rate_pct": 12, "orig_fee_pct": 0},
                   refinance={"month": 14, "value_cap_pct": 8, "ltv_pct": 70, "min_dscr": None, "rate_pct": 6, "costs_pct": 0})
    r = run(d)
    rf = r["refinance"]
    assert rf["amount"] == pytest.approx(0.7 * 400_000 / 0.08)
    assert rf["repaid"] == pytest.approx(1_105_000)
    assert rf["net"] == pytest.approx(3_500_000 - 1_105_000)


def test_multifamily_absorption_after_completion():
    """竣工后每月去化 15 户：竣工第 1 个月 15 / 200 在租，第 13 个月起 95%（稳定空置率 5%）为止。"""
    r = run(ground_up_multifamily())
    occ = r["monthly"]["occupancy_pct"]
    assert occ[19] == 0 and occ[20] == pytest.approx(15 / 200 * 100) and occ[21] == pytest.approx(30 / 200 * 100)
    assert occ[40] == pytest.approx(95)
    m = r["metrics"]
    assert m["development_yield_pct"] == pytest.approx(7.378, abs=1e-3)
    assert m["levered_irr_pct"] == pytest.approx(19.307, abs=1e-3)
    assert r["construction"]["capitalized_interest"] > 0 and r["refinance"]["sized_by"] == "dscr"
    a = r["annual"]
    assert 0 < m["dscr_min"] < 1                                  # 稳定年仍在付 8.5% 施工贷利息：如实低于 1
    assert a["noi"][3] / a["debt_service"][3] > 1.25               # 再融资后（第 4 年）按 DSCR 限额定的贷款


@pytest.mark.parametrize(("patch", "fragment"), [
    ({"construction_loan": {"ltc_pct": 60}, "development": None}, "开发计划"),
    ({"debt": {"ltv_pct": 50}}, "不填优先贷款"),
    ({"leases": [{"tenant": "Early", "sf": 100, "start": "2026-01", "end": "2030-12", "rent_psf_yr": 30}]}, "竣工后起租"),
    ({"development": {"construction_months": 36, "hard_costs": 1}}, "短于持有期"),
])
def test_rejects_inconsistent_development_inputs(patch, fragment):
    with pytest.raises(CreInputError, match=fragment):
        run({**dev_office(), **patch})
