"""Commercial real-estate underwriting engine for DealDesk.

Faithful port of the user's most-used Excel underwriting template
(3 linked sheets: Rent Roll -> Cash Flow -> Analysis), with the
template's broken/hardcoded links repaired so every number is live:

  Rent Roll tenant monthly rent
    -> annual rent (x12) -> section totals
    -> Cash Flow Base Rents (Historical <- lease rents,
                             Pro Forma <- underwritten rents)
      -> Total Potential Income -> EGI -> NOI -> Cash Flow Avail.
      -> Cap Rate
    -> Analysis: In-Place / Projected NOI
      -> cap rates, resale value, net gains, ROI,
         net cash flow, cash-on-cash

New fields beyond the template (all clearly marked NEW):
  vacancy_pct, amortizing loan schedule, abatements, DSCR,
  break-even occupancy, per-SF metrics, hold/exit analysis
  (sale proceeds, IRR, equity multiple).
"""
from __future__ import annotations

import math


def _f(x, default=0.0) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    if math.isnan(v) or math.isinf(v):
        return default
    return v


def _div(a, b) -> float:
    b = _f(b)
    if b == 0:
        return 0.0
    return _f(a) / b


# ---------------------------------------------------------------- Rent Roll
def compute_rent_roll(tenants: list[dict], vacant_sf: float = 0.0) -> dict:
    rows = []
    for t in tenants or []:
        sf = _f(t.get("sf"))
        monthly = _f(t.get("monthly_rent"))
        annual = monthly * 12.0
        uw_annual = _f(t.get("underwritten_annual"), annual)
        rows.append({
            "suite": t.get("suite", ""),
            "tenant": t.get("tenant", ""),
            "sf": sf,
            "monthly_rent": monthly,
            "monthly_per_sf": _div(monthly, sf),
            "annual_rent": annual,
            "annual_per_sf": _div(annual, sf),
            "underwritten_annual": uw_annual,
            "uw_per_sf": _div(uw_annual, sf),
        })
    total_sf = sum(r["sf"] for r in rows)
    total_monthly = sum(r["monthly_rent"] for r in rows)
    total_annual_lease = sum(r["annual_rent"] for r in rows)   # -> Cash Flow Historical
    total_annual_uw = sum(r["underwritten_annual"] for r in rows)  # -> Cash Flow Pro Forma
    vacant_sf = _f(vacant_sf)
    prop_sf = total_sf + vacant_sf
    for r in rows:
        r["pct_of_total_lease"] = _div(r["annual_rent"], total_annual_lease)
        r["pct_of_total_uw"] = _div(r["underwritten_annual"], total_annual_uw)
    return {
        "tenants": rows,
        "total_sf_existing": total_sf,
        "total_monthly": total_monthly,
        "total_annual_lease": total_annual_lease,   # = 'Rent Roll'!G-total
        "total_annual_uw": total_annual_uw,         # = 'Rent Roll'!K-total
        "vacant_sf": vacant_sf,
        "total_sf_property": prop_sf,
        "occupancy": _div(total_sf, prop_sf),
    }


# ---------------------------------------------------------------- Cash Flow
EXPENSE_KEYS = [
    "service_contracts", "cam", "general_admin", "repairs_maintenance",
    "janitor", "security", "utilities", "payroll", "management_fee",
    "property_tax", "insurance", "landscape",  # landscape: F2 模板实例特有
]


def compute_scenario(inp: dict, base_rents: float, net_sf: float,
                     purchase_price: float) -> dict:
    """One Cash Flow column (Historical or Pro Forma)."""
    inp = inp or {}
    cam_rec = _f(inp.get("cam_recovery"))
    parking = _f(inp.get("parking_income"))
    other = _f(inp.get("other_income"))
    total_potential = base_rents + cam_rec + parking + other
    vacancy_pct = _f(inp.get("vacancy_pct"))          # NEW (template hardcoded 0)
    vacancy_loss = total_potential * vacancy_pct
    egi = total_potential - vacancy_loss
    expenses = {k: _f(inp.get(k)) for k in EXPENSE_KEYS}
    total_expenses = sum(expenses.values())
    noi = egi - total_expenses
    ti = _f(inp.get("tenant_improvements"))
    capex = _f(inp.get("capex"))
    lc = _f(inp.get("leasing_commissions"))
    cash_flow_avail = noi - ti - capex - lc           # =B36/E36 in template
    # Template's "Cash Flow" row convention: NOI + Other Income (was hardcoded
    # 2,299,048 / 1,299,048 in the template; now a live formula).
    cash_flow_gross = noi + other
    return {
        "base_rents": base_rents,
        "cam_recovery": cam_rec,
        "parking_income": parking,
        "other_income": other,
        "total_potential": total_potential,
        "vacancy_pct": vacancy_pct,
        "vacancy_loss": vacancy_loss,
        "egi": egi,
        "expenses": expenses,
        "total_expenses": total_expenses,
        "noi": noi,
        "tenant_improvements": ti,
        "capex": capex,
        "leasing_commissions": lc,
        "cash_flow_avail": cash_flow_avail,
        "cash_flow_gross": cash_flow_gross,
        "cap_rate": _div(noi, purchase_price),
        # per-SF + % breakdowns (template columns)
        "rev_pct": {k: _div(v, total_potential) for k, v in
                    {"base_rents": base_rents, "cam_recovery": cam_rec,
                     "parking_income": parking, "other_income": other}.items()},
        "exp_pct": {k: _div(v, total_expenses) for k, v in expenses.items()},
        "per_sf": {
            "base_rents": _div(base_rents, net_sf),
            "egi": _div(egi, net_sf),
            "total_expenses": _div(total_expenses, net_sf),
            "noi": _div(noi, net_sf),
            "cash_flow_avail": _div(cash_flow_avail, net_sf),
        },
    }


# ---------------------------------------------------------------- Analysis
def amort_payment(loan: float, annual_rate: float, amort_years: float) -> float:
    """Annual debt service for a fully amortizing loan."""
    loan, annual_rate = _f(loan), _f(annual_rate)
    n = int(round(_f(amort_years)))
    if loan <= 0 or n <= 0:
        return 0.0
    if annual_rate <= 0:
        return loan / n
    r = annual_rate
    return loan * r / (1.0 - (1.0 + r) ** -n)


def remaining_balance(loan: float, annual_rate: float, amort_years: float,
                      payment: float, after_years: int) -> float:
    """Outstanding principal after k annual payments (annual compounding)."""
    bal = _f(loan)
    r = _f(annual_rate)
    for _ in range(max(0, after_years)):
        bal = bal * (1.0 + r) - payment
    return max(0.0, bal)


def compute_analysis(a: dict, hist: dict, pro: dict) -> dict:
    a = a or {}
    purchase = _f(a.get("purchase_price"))
    repairs = _f(a.get("building_repairs"))
    reserve = _f(a.get("capital_reserve"))
    lender_fees = _f(a.get("lender_fees"))
    closing = _f(a.get("closing_costs"))
    total_uses = purchase + repairs + reserve + lender_fees + closing

    down_pct = _f(a.get("down_pct"))
    rate = _f(a.get("rate"))
    amort_type = (a.get("amort_type") or "IO").upper()   # IO | AMORTIZING (NEW)
    amort_years = _f(a.get("amort_years"), 30)
    loan_bal = purchase * (1.0 - down_pct)
    if amort_type == "AMORTIZING":
        annual_debt = amort_payment(loan_bal, rate, amort_years)
    else:
        annual_debt = loan_bal * rate                     # template: =C23*C25
    financed = -loan_bal                                  # template: =-C23
    net_liquidity = total_uses + financed                 # template: =SUM(C13:C17)+C20

    inplace_noi = _f(a.get("underwritten_noi")) or hist["noi"]   # F13 手工，空=取现金流
    projected_noi = _f(a.get("projected_noi")) or pro["noi"]     # F15 手工，空=取现金流
    inplace_noi_cf = _f(a.get("inplace_noi_cf")) or hist["noi"]  # I24 手工，空=取现金流
    inplace_cap = _div(inplace_noi, purchase)             # template: =F13/C13
    market_cap = _f(a.get("market_cap_rate"))
    projected_resale = _div(projected_noi, market_cap)   # template: =F15/F16
    acquisition_fees = repairs + reserve + lender_fees + closing  # =SUM(C14:C17)
    exit_fee_pct = _f(a.get("exit_fee_pct"), 0.04)
    exit_fees = projected_resale * exit_fee_pct          # template: =F17*0.04
    net_gains = projected_resale - (purchase + acquisition_fees + exit_fees)
    roi = _div(net_gains, net_liquidity)                 # template: =F20/C21

    abatements = _f(a.get("abatements"))                  # NEW (template blank)

    def coc(noi_v: float, other_income: float) -> dict:
        net_cf = noi_v - abatements - annual_debt
        return {
            "noi": noi_v,
            "cash_flow_gross": noi_v + other_income,
            "abatements": abatements,
            "debt_service": annual_debt,
            "net_cash_flow": net_cf,
            "cash_on_cash": _div(net_cf, net_liquidity),
            "dscr": _div(noi_v, annual_debt),            # NEW
        }

    proj = coc(projected_noi, pro["other_income"])
    inp = coc(inplace_noi_cf, hist["other_income"])  # I24 口径（F2 证明可与 F13 不同）

    # NEW: break-even occupancy (pro forma basis)
    breakeven_occ = _div(pro["total_expenses"] + annual_debt,
                         pro["total_potential"])

    # NEW: hold / exit analysis
    hold = compute_exit(a, pro, loan_bal, rate, amort_type, amort_years,
                        annual_debt, net_liquidity, purchase)

    return {
        "purchase_price": purchase,
        "building_repairs": repairs,
        "capital_reserve": reserve,
        "lender_fees": lender_fees,
        "closing_costs": closing,
        "total_uses": total_uses,
        "down_pct": down_pct,
        "rate": rate,
        "amort_type": amort_type,
        "amort_years": amort_years,
        "loan_bal": loan_bal,
        "annual_debt_service": annual_debt,
        "financed": financed,
        "net_liquidity": net_liquidity,
        "inplace_noi": inplace_noi,
        "inplace_cap": inplace_cap,
        "projected_noi": projected_noi,
        "inplace_noi_cf": inplace_noi_cf,
        # 血缘标记：手工锁定 vs 现金流实时
        "noi_sources": {
            "underwritten_noi": "manual" if _f(a.get("underwritten_noi")) else "cashflow",
            "projected_noi": "manual" if _f(a.get("projected_noi")) else "cashflow",
            "inplace_noi_cf": "manual" if _f(a.get("inplace_noi_cf")) else "cashflow",
        },
        "market_cap_rate": market_cap,
        "projected_resale": projected_resale,
        "acquisition_fees": acquisition_fees,
        "exit_fee_pct": exit_fee_pct,
        "exit_fees": exit_fees,
        "net_gains": net_gains,
        "roi": roi,
        "projected": proj,
        "inplace": inp,
        "breakeven_occupancy": breakeven_occ,            # NEW
        "exit": hold,                                    # NEW
    }


def compute_exit(a: dict, pro: dict, loan_bal: float, rate: float,
                 amort_type: str, amort_years: float, annual_debt: float,
                 net_liquidity: float, purchase: float) -> dict:
    """Hold-period exit: sale proceeds, IRR, equity multiple. NEW."""
    hold_years = int(round(_f(a.get("hold_years"), 5)))
    noi_growth = _f(a.get("noi_growth"), 0.02)
    exit_cap = _f(a.get("exit_cap_rate"), 0.05)
    exit_fee_pct = _f(a.get("exit_fee_pct"), 0.04)
    abatements = _f(a.get("abatements"))
    if hold_years <= 0 or net_liquidity <= 0:
        return {"hold_years": hold_years, "irr": 0.0, "equity_multiple": 0.0,
                "sale_price": 0.0, "sale_proceeds": 0.0, "cash_flows": []}
    base_noi = pro["noi"]
    flows = [-net_liquidity]
    for y in range(1, hold_years + 1):
        noi_y = base_noi * (1.0 + noi_growth) ** (y - 1)
        flows.append(noi_y - abatements - annual_debt)
    # sale at end of hold
    noi_exit = base_noi * (1.0 + noi_growth) ** hold_years
    sale_price = _div(noi_exit, exit_cap)
    if amort_type == "AMORTIZING":
        rem = remaining_balance(loan_bal, rate, amort_years, annual_debt, hold_years)
    else:
        rem = loan_bal
    sale_proceeds = sale_price - rem - sale_price * exit_fee_pct
    flows[-1] += sale_proceeds
    irr = _irr(flows)
    total_in = sum(f for f in flows[1:] if f > 0)
    em = _div(total_in, net_liquidity)
    return {
        "hold_years": hold_years,
        "noi_growth": noi_growth,
        "exit_cap_rate": exit_cap,
        "sale_price": sale_price,
        "remaining_loan": rem,
        "sale_proceeds": sale_proceeds,
        "cash_flows": flows,
        "irr": irr,
        "equity_multiple": em,
    }


def _irr(flows: list[float], lo: float = -0.99, hi: float = 10.0,
         iters: int = 100) -> float:
    def npv(r: float) -> float:
        return sum(cf / (1.0 + r) ** i for i, cf in enumerate(flows))
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return 0.0
    for _ in range(iters):
        mid = (lo + hi) / 2.0
        if f_lo * npv(mid) <= 0:
            hi = mid
            f_hi = npv(hi)
        else:
            lo = mid
            f_lo = npv(lo)
    return (lo + hi) / 2.0


# ---------------------------------------------------------------- top-level
def default_inputs() -> dict:
    """Blank project shaped exactly like the template."""
    return {
        "property": {
            "name": "", "address": "", "city": "", "state": "", "zip": "",
            "county": "", "property_type": "Retail", "net_rentable_sf": 0,
            "land_acres": 0, "parking_spaces": 0, "year_built": "",
            "year_renovated": "", "buildings": "", "floors": "",
            "occupancy_as_of": "",
        },
        "tenants": [],
        "vacant_sf": 0,
        "historical": {
            "cam_recovery": 0, "parking_income": 0, "other_income": 0,
            "vacancy_pct": 0,
            **{k: 0 for k in EXPENSE_KEYS},
            "tenant_improvements": 0, "capex": 0, "leasing_commissions": 0,
        },
        "proforma": {
            "cam_recovery": 0, "parking_income": 0, "other_income": 0,
            "vacancy_pct": 0,
            **{k: 0 for k in EXPENSE_KEYS},
            "tenant_improvements": 0, "capex": 0, "leasing_commissions": 0,
        },
        "analysis": {
            "purchase_price": 0, "building_repairs": 0, "capital_reserve": 0,
            "lender_fees": 0, "closing_costs": 0,
            "down_pct": 0.30, "rate": 0.06, "amort_type": "IO",
            "amort_years": 30, "market_cap_rate": 0.04, "exit_fee_pct": 0.04,
            "abatements": 0,
            # 模板血缘：F13/F15/F24/I24 是手工承保假设（非公式）。
            # 空=None 时自动取 Cash Flow 实时值；一旦手填就锁定为手工口径。
            "underwritten_noi": None,   # F13 在手 NOI（驱动在手 Cap）
            "projected_noi": None,      # F15 预测 NOI（驱动转售价值）
            "inplace_noi_cf": None,     # I24 现金流块的在手 NOI
            "hold_years": 5, "noi_growth": 0.02, "exit_cap_rate": 0.05,
        },
    }


def example_39_main() -> dict:
    """The template's own worked example: 39-09 Main St, Flushing NY."""
    d = default_inputs()
    d["property"].update({
        "name": "39-09 Main St", "address": "39-09 Main St",
        "city": "Flushing", "state": "NY", "zip": "11354",
        "property_type": "Retail", "net_rentable_sf": 17042, "land_acres": 0.11,
    })
    d["tenants"] = [{
        "suite": "1", "tenant": "Carat & Co", "sf": 17042,
        "monthly_rent": 83333.34, "underwritten_annual": 2000000,
    }]
    d["historical"].update({
        "other_income": 299048, "property_tax": 299048,
        "tenant_improvements": 0, "leasing_commissions": 0,
    })
    d["proforma"].update({
        "other_income": 299048, "property_tax": 299048,
    })
    # pro forma NOI must equal template's 2,000,000:
    # base rents 2,000,000 + other 299,048 - property tax 299,048 = 2,000,000 ✓
    # historical NOI must equal template's 1,000,000:
    # base rents 1,000,000.08 + 299,048 - 299,048 = 1,000,000.08 ✓
    d["analysis"].update({
        "purchase_price": 42000000, "lender_fees": 420000,
        "closing_costs": 864000, "down_pct": 0.30, "rate": 0.06,
        "amort_type": "IO", "market_cap_rate": 0.04, "exit_fee_pct": 0.04,
    })
    return d


def compute_all(data: dict) -> dict:
    data = data or {}
    prop = data.get("property", {}) or {}
    net_sf = _f(prop.get("net_rentable_sf"))
    rent = compute_rent_roll(data.get("tenants"), data.get("vacant_sf", 0))
    purchase = _f((data.get("analysis") or {}).get("purchase_price"))
    hist = compute_scenario(data.get("historical"), rent["total_annual_lease"],
                            net_sf, purchase)
    pro = compute_scenario(data.get("proforma"), rent["total_annual_uw"],
                           net_sf, purchase)
    analysis = compute_analysis(data.get("analysis"), hist, pro)
    # per-SF headline metrics (NEW)
    per_sf = {
        "price_per_sf": _div(purchase, net_sf),
        "rent_per_sf_hist": _div(rent["total_annual_lease"], net_sf),
        "rent_per_sf_pro": _div(rent["total_annual_uw"], net_sf),
        "expense_per_sf": _div(pro["total_expenses"], net_sf),
        "noi_per_sf": _div(pro["noi"], net_sf),
    }
    # template-faithful computed property metric: =F6/(F4/1000)
    prop_out = dict(prop)
    prop_out["parking_per_1000sf"] = _div(_f(prop.get("parking_spaces")), net_sf / 1000.0)
    return {
        "property": prop_out,
        "rent_roll": rent,
        "historical": hist,
        "proforma": pro,
        "analysis": analysis,
        "per_sf": per_sf,
    }
