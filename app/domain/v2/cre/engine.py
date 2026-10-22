"""引擎入口：输入 → 逐租约展开 → 按月物业现金流 → 债务 → 退出 → 无杠杆 / 有杠杆收益 → 瀑布。

时间约定：分析起点（第 0 月月初）交割；第 k 年 = 第 (k-1)×12 … k×12-1 月；持有 N 年后在第 N×12-1 月月末出售，
售价 = 第 N+1 年 NOI ÷ 退出资本化率（行业惯例用下一年 NOI），扣卖方成本，偿清贷款余额。
年度 IRR 用年度现金流；另给按月现金流折算的年化 IRR（机构常用的更精确口径）。缺数或无解保持 None，不编数。
"""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.domain.v2.cre import cashflow, debt, leases, multifamily
from app.domain.v2.cre.inputs import CreInputs
from app.domain.v2.cre.returns import equity_multiple, irr, npv
from app.domain.v2.cre.waterfall import annual as annual_series
from app.domain.v2.cre.waterfall import distribute

JSON = dict[str, Any]
ENGINE = "cre-1.0"


class CreInputError(ValueError):
    pass


def parse(inputs: JSON) -> CreInputs:
    try:
        return CreInputs.model_validate(inputs)
    except ValidationError as e:
        parts = [f"[{'.'.join(str(x) for x in err.get('loc', ()))}] {err.get('msg', '')}" for err in e.errors()]
        raise CreInputError("；".join(parts)) from e


def _years(series: list[float], n_years: int) -> list[float]:
    return [sum(series[y * 12:(y + 1) * 12]) for y in range(n_years)]


def _pct(x: float | None) -> float | None:
    return None if x is None else x * 100


def _div(a: float, b: float) -> float | None:
    return a / b if b else None


def _stabilized_noi(cre: CreInputs, annual: dict[str, list[float]], y: int) -> float:
    """第 y 年的稳定化 NOI：这栋楼在该年满租运转时的 NOI。

    按潜在收入（在租合同租金 + 回收、空置面积按市场应收）收足，不计周转空置与免租，
    再按一般空置率、信用损失率、管理费率重算；费用（税、保险、CAM）照实际计。
    """
    if cre.property_type == "multifamily":
        return _stabilized_noi_mf(cre, annual, y)
    pot = annual["potential_rent"][y]
    gv = cre.general_vacancy_pct / 100 * pot
    egr = (pot - gv) * (1 - cre.credit_loss_pct / 100)
    mgmt = cre.opex.mgmt_fee_pct_egr / 100 * egr
    return egr + annual["opex_recoverable"][y] + annual["opex_non_recoverable"][y] - mgmt


def _stabilized_noi_mf(cre: CreInputs, annual: dict[str, list[float]], y: int) -> float:
    """多户公寓：加回翻新停用损失（停用户按市场租金收），优惠、空置、坏账、管理费按同一费率重算；其他收入不变。"""
    base = annual["base_rent"][y] - annual["turnover_vacancy"][y]
    mf = cre.mfa()
    vac, conc, bad = cre.general_vacancy_pct / 100, mf.concessions_pct / 100, cre.credit_loss_pct / 100
    other = annual["recoveries"][y]
    egr = (base * (1 - conc - vac) + other) * (1 - bad)
    mgmt = cre.opex.mgmt_fee_pct_egr / 100 * egr
    return egr + annual["opex_recoverable"][y] + annual["opex_non_recoverable"][y] - mgmt


def _unit_mix(cre: CreInputs) -> list[JSON]:
    return [{"name": u.name, "units": u.units, "avg_sf": u.avg_sf, "in_place_rent": u.in_place_rent,
             "market_rent": u.market_rent, "loss_to_lease_pct": (u.market_rent - u.in_place_rent) / u.market_rent * 100,
             "renovate_units": u.renovate_units, "reno_cost_per_unit": u.reno_cost_per_unit,
             "reno_premium": u.reno_premium} for u in cre.unit_mix]


def _waterfall(cre: CreInputs, lev: list[float], lev_m: list[float]) -> JSON | None:
    """按年瀑布用年度现金流；按月瀑布用按月现金流，LP / GP 再汇总成年度（lp_annual / gp_annual）与年度现金流对齐。"""
    w = cre.waterfall
    if w is None:
        return None
    out = distribute(w, lev_m, periods_per_year=12) if w.frequency == "monthly" else distribute(w, lev)
    out["lp_annual"] = annual_series(out["lp"], out["periods_per_year"])
    out["gp_annual"] = annual_series(out["gp"], out["periods_per_year"])
    return out


def run(inputs: JSON) -> JSON:
    cre = parse(inputs)
    hold_m = cre.hold_years * 12
    months = hold_m + 12  # 多算一年：退出要用下一年 NOI
    is_mf = cre.property_type == "multifamily"
    chains = [] if is_mf else leases.expand(cre, months)
    cf = multifamily.project(cre, months) if is_mf else cashflow.project(cre, chains, months)
    ds = debt.schedule(cre.debt, cre.purchase_price, months)
    lines = cf.lines
    debt_service = [i + p for i, p in zip(ds.interest, ds.principal, strict=True)]

    annual = {k: _years(v, cre.hold_years + 1) for k, v in lines.items() if k != "occupancy_pct"}
    annual["occupancy_pct"] = [sum(lines["occupancy_pct"][y * 12:(y + 1) * 12]) / 12 for y in range(cre.hold_years + 1)]
    annual["debt_service"] = _years(debt_service, cre.hold_years + 1)
    annual["cf_after_debt"] = [a - b for a, b in zip(annual["cf_before_debt"], annual["debt_service"], strict=True)]

    fwd_noi_raw = annual["noi"][cre.hold_years]
    stab_noi = _stabilized_noi(cre, annual, cre.hold_years)
    fwd_noi = stab_noi if cre.exit_noi_basis == "stabilized" else fwd_noi_raw
    sale = fwd_noi / (cre.exit_cap_pct / 100)
    selling = sale * cre.selling_costs_pct / 100
    payoff = ds.payoff(hold_m - 1)
    acquisition = cre.purchase_price * (1 + cre.closing_costs_pct / 100)
    equity = acquisition + ds.orig_fee - ds.amount

    unlev = [-acquisition, *annual["cf_before_debt"][:cre.hold_years]]
    unlev[-1] += sale - selling
    lev = [-equity, *annual["cf_after_debt"][:cre.hold_years]]
    lev[-1] += sale - selling - payoff
    lev_m = [-equity] + [lines["cf_before_debt"][m] - debt_service[m] for m in range(hold_m)]
    lev_m[-1] += sale - selling - payoff
    unlev_m = [-acquisition, *lines["cf_before_debt"][:hold_m]]
    unlev_m[-1] += sale - selling

    def annualized(monthly: float | None) -> float | None:
        return None if monthly is None else (1 + monthly) ** 12 - 1

    noi1 = annual["noi"][0]
    dscr = [_div(n, s) for n, s in zip(annual["noi"][:cre.hold_years], annual["debt_service"], strict=False)]
    dscr_known = [x for x in dscr if x is not None]
    disc = cre.discount_rate_pct / 100
    metrics: JSON = {
        "going_in_cap_pct": _pct(_div(noi1, cre.purchase_price)),
        "yield_on_cost_pct": _pct(_div(noi1, acquisition)),
        "exit_value": sale, "exit_cap_pct": cre.exit_cap_pct, "forward_noi": fwd_noi,
        "forward_noi_unadjusted": fwd_noi_raw, "forward_noi_stabilized": stab_noi,
        "unlevered_irr_pct": _pct(irr(unlev)), "unlevered_irr_monthly_pct": _pct(annualized(irr(unlev_m))),
        "levered_irr_pct": _pct(irr(lev)), "levered_irr_monthly_pct": _pct(annualized(irr(lev_m))),
        "unlevered_multiple": equity_multiple(unlev), "levered_multiple": equity_multiple(lev),
        "unlevered_npv": npv(disc, unlev), "levered_npv": npv(disc, lev),
        "equity": equity, "loan_amount": ds.amount,
        "ltv_pct": _pct(_div(ds.amount, cre.purchase_price)),
        "debt_yield_pct": _pct(_div(noi1, ds.amount)),
        "dscr_year1": dscr[0] if dscr else None, "dscr_min": min(dscr_known) if dscr_known else None,
        "cash_on_cash_year1_pct": _pct(_div(annual["cf_after_debt"][0], equity)),
        "avg_occupancy_pct": sum(annual["occupancy_pct"][:cre.hold_years]) / cre.hold_years,
        "leasing_costs_total": abs(sum(annual["ti"][:cre.hold_years]) + sum(annual["lc"][:cre.hold_years])),
        "capex_total": abs(sum(annual["capex"][:cre.hold_years])),
        "units": float(sum(u.units for u in cre.unit_mix)) if is_mf else None,
        "price_per_unit": cre.purchase_price / sum(u.units for u in cre.unit_mix) if is_mf else None,
    }
    return {
        "engine": ENGINE,
        "metrics": metrics,
        "annual": annual,
        "monthly": {"noi": lines["noi"][:hold_m], "cf_before_debt": lines["cf_before_debt"][:hold_m],
                    "debt_service": debt_service[:hold_m], "occupancy_pct": lines["occupancy_pct"][:hold_m],
                    "rate_pct": ds.rate_pct[:hold_m]},
        "flows": {"unlevered": unlev, "levered": lev},
        "exit": {"sale_price": sale, "selling_costs": selling, "loan_payoff": payoff,
                 "net_proceeds_levered": sale - selling - payoff},
        "rent_roll": [{"tenant": s.tenant, "suite": s.suite, "sf": s.sf, "start": s.start, "end": s.end,
                       "rent_psf": s.rent_psf, "speculative": s.speculative, "downtime_before": s.downtime_before,
                       "ti": s.ti, "lc": s.lc} for chain in chains for s in chain if s.start < hold_m],
        "unit_mix": _unit_mix(cre) if is_mf else None,
        "waterfall": _waterfall(cre, lev, lev_m),
    }
