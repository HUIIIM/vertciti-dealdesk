"""机构级承销引擎：每条都用能手算的基准用例锁定口径（闭式解或逐月手算），再加性质测试与输入校验。"""
from __future__ import annotations

import copy

import pytest

from app.domain.v2.cre.engine import CreInputError, run
from app.domain.v2.cre.inputs import Waterfall
from app.domain.v2.cre.waterfall import distribute

AREA = 10_000
QUIET = {"recoverable_psf_yr": 10, "non_recoverable_psf_yr": 0, "growth_pct": 0, "mgmt_fee_pct_egr": 0,
         "reserves_psf_yr": 0}


def base(**over) -> dict:
    """单一 NNN 租户包整栋、租期覆盖持有期、零增长零成本：NOI = 租金，IRR 必须等于资本化率。"""
    d = {"analysis_start": "2026-01", "hold_years": 5, "area_sf": AREA, "purchase_price": 5_000_000,
         "closing_costs_pct": 0, "market": {"rent_psf_yr": 40, "rent_growth_pct": 0},
         "opex": dict(QUIET), "general_vacancy_pct": 0, "credit_loss_pct": 0, "exit_cap_pct": 8,
         "selling_costs_pct": 0, "discount_rate_pct": 8,
         "leases": [{"tenant": "A", "sf": AREA, "start": "2025-01", "end": "2040-12", "rent_psf_yr": 40}]}
    d.update(over)
    return d


def test_closed_form_irr_equals_cap_rate():
    m = run(base())["metrics"]
    assert m["going_in_cap_pct"] == pytest.approx(8.0)
    assert m["unlevered_irr_pct"] == pytest.approx(8.0, abs=1e-6)
    assert m["unlevered_irr_monthly_pct"] == pytest.approx(((1 + 0.08 / 12) ** 12 - 1) * 100, abs=1e-6)
    assert m["unlevered_npv"] == pytest.approx(0, abs=1e-4)
    assert m["unlevered_multiple"] == pytest.approx(1.4)  # 5 年 × 8% 收入 + 原价卖出
    assert m["leasing_costs_total"] == 0 and m["avg_occupancy_pct"] == 100


def test_recovery_types():
    gross = base(leases=[{**base()["leases"][0], "recovery": "gross"}])
    assert run(gross)["annual"]["noi"][0] == pytest.approx(400_000 - 100_000)  # 毛租约：业主承担可回收费用
    by = base(opex={**QUIET, "growth_pct": 10},
              leases=[{**base()["leases"][0], "recovery": "base_year", "base_year_opex_psf": 10}])
    rec = run(by)["annual"]["recoveries"]
    assert rec[0] == pytest.approx(0)                       # 基年当年：不回收
    assert rec[1] == pytest.approx((11 - 10) * AREA)        # 次年：只回收超出基年的 $1/SF
    assert rec[2] == pytest.approx((12.1 - 10) * AREA)


def test_rollover_to_new_tenant_downtime_free_rent_ti_lc():
    d = base(market={"rent_psf_yr": 40, "rent_growth_pct": 5, "renewal_prob_pct": 0, "downtime_months": 6,
                     "free_rent_new_months": 3, "ti_new_psf": 30, "lc_new_pct": 6, "lease_term_years": 5,
                     "escalation_pct": 0},
             leases=[{"tenant": "A", "sf": AREA, "start": "2023-01", "end": "2027-12", "rent_psf_yr": 40}])
    r = run(d)
    mo = r["monthly"]
    assert all(x > 0 for x in mo["noi"][:24])
    assert mo["occupancy_pct"][24:30] == [0.0] * 6           # 第 25–30 月空置
    seg = next(s for s in r["rent_roll"] if s["speculative"])
    assert (seg["start"], seg["downtime_before"]) == (30, 6)
    assert seg["rent_psf"] == pytest.approx(40 * 1.05 ** 2)  # 起租在第 3 个分析年：市场租金涨了两次
    assert seg["ti"] == pytest.approx(30 * AREA)
    assert seg["lc"] == pytest.approx(0.06 * 40 * 1.05 ** 2 * AREA * 5)
    a = r["annual"]
    assert a["ti"][2] == pytest.approx(-30 * AREA)           # TI 在新租起租当月（第 3 年）支出
    assert a["free_rent"][2] == pytest.approx(-3 * 40 * 1.05 ** 2 * AREA / 12)
    assert a["turnover_vacancy"][2] < 0


def test_renewal_certain_means_no_downtime_and_renewal_costs():
    d = base(market={"rent_psf_yr": 40, "rent_growth_pct": 0, "renewal_prob_pct": 100, "downtime_months": 6,
                     "free_rent_renew_months": 1, "ti_renew_psf": 10, "lc_renew_pct": 3, "escalation_pct": 0},
             leases=[{"tenant": "A", "sf": AREA, "start": "2023-01", "end": "2027-12", "rent_psf_yr": 40}])
    r = run(d)
    seg = next(s for s in r["rent_roll"] if s["speculative"])
    assert (seg["start"], seg["downtime_before"], seg["ti"]) == (24, 0, 10 * AREA)
    assert min(r["monthly"]["occupancy_pct"]) == 100


def test_blended_mla_weights_downtime_and_costs():
    d = base(market={"rent_psf_yr": 40, "rent_growth_pct": 0, "renewal_prob_pct": 70, "downtime_months": 6,
                     "ti_new_psf": 30, "ti_renew_psf": 10, "escalation_pct": 0},
             leases=[{"tenant": "A", "sf": AREA, "start": "2023-01", "end": "2027-12", "rent_psf_yr": 40}])
    seg = next(s for s in run(d)["rent_roll"] if s["speculative"])
    assert seg["downtime_before"] == 2                       # 0.3 × 6 = 1.8 → 2 个月
    assert seg["ti"] == pytest.approx((0.7 * 10 + 0.3 * 30) * AREA)


def test_general_vacancy_is_reduced_by_modeled_turnover_vacancy():
    full = run(base(general_vacancy_pct=5))["annual"]
    assert full["general_vacancy"][0] == pytest.approx(-0.05 * (400_000 + 100_000))
    d = base(general_vacancy_pct=5, market={"rent_psf_yr": 40, "rent_growth_pct": 0, "renewal_prob_pct": 0,
                                             "downtime_months": 12},
             leases=[{"tenant": "A", "sf": AREA, "start": "2023-01", "end": "2026-12", "rent_psf_yr": 40}])
    assert run(d)["annual"]["general_vacancy"][1] == pytest.approx(0)  # 整年周转空置已远超 5%：不再重复扣


def test_vacant_space_leases_up_after_downtime():
    d = base(area_sf=15_000, market={"rent_psf_yr": 40, "rent_growth_pct": 0, "downtime_months": 6})
    r = run(d)
    occ = r["monthly"]["occupancy_pct"]
    assert occ[0] == pytest.approx(AREA / 15_000 * 100) and occ[6] == pytest.approx(100)
    assert any(s["tenant"] == "（空置）" and s["start"] == 6 for s in r["rent_roll"])


def test_fixed_debt_interest_only_then_amortizing():
    loan, rate = 3_000_000, 6.0
    r = run(base(debt={"amount": loan, "rate_pct": rate, "io_months": 24, "amort_years": 30, "orig_fee_pct": 1}))
    mo, m = r["monthly"], r["metrics"]
    assert mo["debt_service"][0] == pytest.approx(loan * rate / 100 / 12)
    i = rate / 100 / 12
    pmt = loan * i / (1 - (1 + i) ** -360)
    assert mo["debt_service"][24] == pytest.approx(pmt)
    assert m["dscr_year1"] == pytest.approx(400_000 / (loan * rate / 100))
    assert m["debt_yield_pct"] == pytest.approx(400_000 / loan * 100)
    assert m["equity"] == pytest.approx(5_000_000 + 30_000 - loan)
    assert r["exit"]["loan_payoff"] < loan
    assert m["levered_irr_pct"] > m["unlevered_irr_pct"]       # 8% 资产、6% 借款：正杠杆


def test_floating_rate_with_cap():
    r = run(base(debt={"ltv_pct": 50, "rate_type": "floating", "sofr_curve_pct": [3, 6], "spread_bps": 250,
                       "cap_strike_pct": 4, "io_months": 120}))
    assert r["monthly"]["rate_pct"][0] == pytest.approx(5.5)
    assert r["monthly"]["rate_pct"][12] == pytest.approx(6.5)  # SOFR 6% 被 4% 上限截住
    assert r["monthly"]["rate_pct"][59] == pytest.approx(6.5)  # 曲线最后一年向后沿用


def test_exit_uses_forward_noi_and_selling_costs():
    r = run(base(market={"rent_psf_yr": 40, "rent_growth_pct": 0}, selling_costs_pct=2,
                 leases=[{"tenant": "A", "sf": AREA, "start": "2025-01", "end": "2040-12", "rent_psf_yr": 40,
                          "escalation_pct": 3}]))
    fwd = r["annual"]["noi"][5]
    assert r["metrics"]["forward_noi"] == pytest.approx(fwd)
    assert r["exit"]["sale_price"] == pytest.approx(fwd / 0.08)
    assert r["exit"]["selling_costs"] == pytest.approx(fwd / 0.08 * 0.02)


def test_stabilized_exit_noi_adds_back_exit_year_turnover():
    """租约在第 5 年末到期、第 6 年（退出年）换租：空置 6 月、免租 3 月。
    原值 NOI = 40 × 1 万 SF × 3/12 + 回收 10 × 1 万 × 6/12 − 费用 10 × 1 万 = 5 万（再扣一般空置净额）；
    稳定化 = 潜在收入 (40 + 10) × 1 万 = 50 万，扣 5% 一般空置 → 47.5 万，减费用 10 万 = 37.5 万。"""
    d = base(general_vacancy_pct=5,
             market={"rent_psf_yr": 40, "rent_growth_pct": 0, "renewal_prob_pct": 0, "downtime_months": 6,
                     "free_rent_new_months": 3, "ti_new_psf": 0, "lc_new_pct": 0, "escalation_pct": 0},
             leases=[{"tenant": "A", "sf": AREA, "start": "2021-01", "end": "2030-12", "rent_psf_yr": 40}])
    raw = run(d)
    stab = run({**d, "exit_noi_basis": "stabilized"})
    m = stab["metrics"]
    assert m["forward_noi_stabilized"] == pytest.approx(375_000)
    assert m["forward_noi"] == pytest.approx(375_000)
    assert stab["exit"]["sale_price"] == pytest.approx(375_000 / 0.08)
    assert raw["metrics"]["forward_noi"] == pytest.approx(raw["annual"]["noi"][5])
    assert raw["metrics"]["forward_noi"] < 100_000 < m["forward_noi"]
    assert m["levered_irr_pct"] > raw["metrics"]["levered_irr_pct"]
    # 持有期现金流不受退出口径影响
    assert stab["annual"]["noi"][:5] == raw["annual"]["noi"][:5]


def test_stabilized_equals_forward_without_exit_year_turnover():
    r = run({**base(general_vacancy_pct=5, credit_loss_pct=1,
                    opex={**QUIET, "mgmt_fee_pct_egr": 3}), "exit_noi_basis": "stabilized"})
    assert r["metrics"]["forward_noi_stabilized"] == pytest.approx(r["metrics"]["forward_noi_unadjusted"])


def test_waterfall_hand_case_and_conservation():
    w = Waterfall(lp_equity_pct=90, pref_pct=8, tiers=[], final_lp_share_pct=70)
    out = distribute(w, [-100, 120])
    assert out["lp"] == pytest.approx([-90, 105.6]) and out["gp"] == pytest.approx([-10, 14.4])
    assert out["gp_promote"] == pytest.approx(2.4)
    w2 = Waterfall(lp_equity_pct=90, pref_pct=8, tiers=[{"irr_pct": 12, "lp_share_pct": 80}], final_lp_share_pct=60)
    flows = [-1000, 50, 60, 70, 1400]
    o = distribute(w2, flows)
    for t, f in enumerate(flows):
        assert o["lp"][t] + o["gp"][t] == pytest.approx(f)    # 每期分完、不多不少
    low = distribute(w2, [-1000, 30, 30, 1000])                # LP 达不到优先回报：GP 只拿出资比例
    assert low["gp_promote"] == pytest.approx(0, abs=1e-9)
    assert low["lp_irr_pct"] < 8


def test_waterfall_in_engine_matches_levered_flows():
    r = run(base(debt={"ltv_pct": 55, "rate_pct": 5.5, "io_months": 60},
                 waterfall={"lp_equity_pct": 90, "pref_pct": 7, "tiers": [{"irr_pct": 12, "lp_share_pct": 80}]}))
    w = r["waterfall"]
    for t, f in enumerate(r["flows"]["levered"]):
        assert w["lp"][t] + w["gp"][t] == pytest.approx(f)


@pytest.mark.parametrize(("patch", "fragment"), [
    ({"area_sf": 5_000}, "超过可租面积"),
    ({"analysis_start": "2026-13"}, "YYYY-MM"),
    ({"debt": {"amount": 1, "ltv_pct": 50}}, "只能填一个"),
    ({"debt": {"rate_type": "floating"}}, "SOFR"),
    ({"waterfall": {"pref_pct": 10, "tiers": [{"irr_pct": 9, "lp_share_pct": 80}]}}, "递增"),
    ({"surprise": 1}, "(?i)extra"),
])
def test_rejects_bad_inputs(patch, fragment):
    with pytest.raises(CreInputError, match=fragment):
        run(base(**patch))


def test_deterministic_and_does_not_mutate_input():
    d = base(debt={"ltv_pct": 60})
    snap = copy.deepcopy(d)
    assert run(d) == run(d)
    assert d == snap


def test_irr_survives_long_monthly_horizons():
    """回归：30 年持有 = 360 个月现金流，求解区间下端 (1-0.9999)^360 下溢为 0，曾抛除零错误。"""
    from app.domain.v2.cre.returns import irr  # noqa: PLC0415
    flows = [-1000.0] + [6.0] * 359 + [1006.0]
    assert irr(flows) == pytest.approx(0.006, abs=1e-9)
    m = run(base(hold_years=30, leases=[{**base()["leases"][0], "end": "2060-12"}]))["metrics"]
    assert m["unlevered_irr_monthly_pct"] == pytest.approx(((1 + 0.08 / 12) ** 12 - 1) * 100, abs=1e-6)


def test_api_preview_and_example(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient  # noqa: PLC0415

    from app.main import app  # noqa: PLC0415
    monkeypatch.setenv("DEALDESK_DB", str(tmp_path / "x.db"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DEALDESK_AUTH", raising=False)
    c = TestClient(app)
    ex = c.get("/api/v2/cre/example").json()
    r = c.post("/api/v2/cre/run", json=ex)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["engine"] == "cre-1.0" and out["waterfall"]["lp_irr_pct"] < out["metrics"]["levered_irr_pct"]
    assert any(s["speculative"] for s in out["rent_roll"])  # 到期租约与空置面积都滚出了假设段
    bad = c.post("/api/v2/cre/run", json={**ex, "hold_years": 0})
    assert bad.status_code == 422 and "hold_years" in bad.json()["detail"]


def test_example_locked_numbers():
    """示例楼的结果锁定（引擎改口径时必须有意识地改这里，并在方法论文档里写明）。"""
    from app.domain.v2.cre.example import suburban_office  # noqa: PLC0415
    m = run(suburban_office())["metrics"]
    assert m["going_in_cap_pct"] == pytest.approx(7.255, abs=1e-3)
    assert m["unlevered_irr_pct"] == pytest.approx(11.845, abs=1e-3)
    assert m["levered_irr_pct"] == pytest.approx(16.903, abs=1e-3)
    assert m["dscr_min"] == pytest.approx(1.765, abs=1e-3)


# ---------------------------------------------------------------- 瀑布：catch-up / 按月 / 回拨（都可手算）
def _w(**kw) -> Waterfall:
    return Waterfall(**{"lp_equity_pct": 90, "pref_pct": 8, "final_lp_share_pct": 80, **kw})


def test_catch_up_brings_gp_to_target_share_of_profit():
    """[-100, 150]：优先回报 108（LP 97.2 / GP 10.8）→ catch-up：利润 LP 7.2、GP 0.8，要补到 GP = 20% × 利润合计，
    100% 给 GP 时需 x = (0.2 × 8 − 0.8) / (1 − 0.2) = 1.0 → 剩 41 按 80 / 20：LP 130、GP 20，利润 40 / 10 正好 80 / 20。"""
    r = distribute(_w(catch_up_target_pct=20), [-100, 150])
    assert r["lp"][1] == pytest.approx(130) and r["gp"][1] == pytest.approx(20)
    assert r["gp_promote"] == pytest.approx(20 - 15)
    partial = distribute(_w(catch_up_target_pct=20), [-100, 108.5])        # 钱不够补完：剩下的 0.5 全给 GP
    assert partial["lp"][1] == pytest.approx(97.2) and partial["gp"][1] == pytest.approx(11.3)
    half = distribute(_w(catch_up_target_pct=20, catch_up_rate_pct=50), [-100, 150])  # 50 / 50 catch-up：需 x = 0.8 / 0.3
    assert half["gp"][1] == pytest.approx(10.8 + 0.5 * 0.8 / 0.3 + 0.2 * (42 - 0.8 / 0.3))


def test_catch_up_sits_between_pref_and_first_tier():
    tiered = distribute(_w(catch_up_target_pct=20, tiers=[{"irr_pct": 15, "lp_share_pct": 85}], final_lp_share_pct=70),
                        [-100, 150])
    plain = distribute(_w(tiers=[{"irr_pct": 15, "lp_share_pct": 85}], final_lp_share_pct=70), [-100, 150])
    assert tiered["gp"][1] > plain["gp"][1]
    assert tiered["lp"][1] + tiered["gp"][1] == pytest.approx(150)


def test_monthly_waterfall_uses_monthly_compounded_hurdles():
    """同样的钱、同样的时点：按月（中间 11 个月为 0）与按年结果一致；门槛按 (1.08)^(1/12) 月复利。"""
    annual_r = distribute(_w(final_lp_share_pct=70), [-100, 120])
    monthly_r = distribute(_w(final_lp_share_pct=70), [-100, *[0.0] * 11, 120], periods_per_year=12)
    assert monthly_r["lp"][-1] == pytest.approx(annual_r["lp"][1]) == pytest.approx(105.6)
    assert monthly_r["lp_irr_pct"] == pytest.approx(annual_r["lp_irr_pct"], abs=1e-6)


def test_clawback_returns_promote_until_lp_reaches_pref():
    """[-100, 140, -50]：第 1 年 GP 拿 promote 6.4（20.4 − 按出资比例 14），第 2 年追加出资后 LP 远低于 8%：
    缺口 = −(−90 × 1.08² + 119.6 × 1.08 − 45) = 20.808 > 6.4 → 全部退回。"""
    r = distribute(_w(final_lp_share_pct=70, clawback=True), [-100, 140, -50])
    assert r["clawback"] == pytest.approx(6.4) and r["gp_promote"] == pytest.approx(0)
    assert r["lp"][2] == pytest.approx(-45 + 6.4) and r["gp"][2] == pytest.approx(-5 - 6.4)
    no = distribute(_w(final_lp_share_pct=70), [-100, 140, -50])
    assert no["clawback"] == 0 and no["gp_promote"] == pytest.approx(6.4)
    # 缺口小于 promote：只退缺口，LP 恰好达到 8%
    part = distribute(_w(final_lp_share_pct=70, clawback=True), [-100, 140, -30])
    assert part["clawback"] == pytest.approx(2.808)
    assert part["lp_irr_pct"] == pytest.approx(8.0, abs=1e-6)


def test_engine_monthly_waterfall_rolls_up_to_annual_flows():
    from app.domain.v2.cre.example import suburban_office
    inp = suburban_office()
    inp["waterfall"] = {**inp["waterfall"], "frequency": "monthly", "catch_up_target_pct": 20, "clawback": True}
    r = run(inp)
    wf = r["waterfall"]
    assert wf["periods_per_year"] == 12 and len(wf["lp"]) == 7 * 12 + 1
    for t, cash in enumerate(r["flows"]["levered"]):
        assert wf["lp_annual"][t] + wf["gp_annual"][t] == pytest.approx(cash)
    annual_wf = run(suburban_office())["waterfall"]
    assert annual_wf["lp_annual"] == annual_wf["lp"]


def test_catch_up_rate_must_exceed_target():
    with pytest.raises(ValueError, match="catch-up"):
        Waterfall(lp_equity_pct=90, pref_pct=8, catch_up_target_pct=20, catch_up_rate_pct=20)


def test_irr_picks_root_nearest_ten_percent_when_flows_change_sign_twice():
    """[-90, 119.6, -24.192] 有两个根（8% 和约 24.9%）：取离 10% 近的 8%；旧算法两端同号会直接返回空。"""
    from app.domain.v2.cre.returns import irr
    assert irr([-90, 119.6, -24.192]) == pytest.approx(0.08, abs=1e-9)
    assert irr([-100, 110]) == pytest.approx(0.10, abs=1e-9)
    assert irr([100, 50]) is None
