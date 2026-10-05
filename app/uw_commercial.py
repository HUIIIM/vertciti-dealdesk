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


# ---------------------------------------------------------------- 单位口径铁律
# 商业核保数据标准 v1.0 §1.1（CEO 2026-10-05 终裁①）：
#   [PCT] 百分制（0-100）= 人类输入口径；[DEC] 小数制（0-1）= 计算口径。
#   /api/uw/* 的输入层一律 [PCT]（vacancy_pct / down_pct / rate / market_cap_rate /
#   exit_cap_rate / noi_growth），计算层一律 [DEC]，边界经 normalize_pct() 归一化。
#   compute_* 的输出回显为 [DEC]（Excel PCT 格式格 / PDF _pct() / dscr 双轨标注
#   均按小数消费——输出口径不变，下游零改动）。
#   唯一例外：compute_scenario 回显的 vacancy_pct 保持输入 [PCT] 原样
#  （commercial_plus.noi_bank_bridge 按百分制消费）。

def _f(x, default=0.0) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    if math.isnan(v) or math.isinf(v):
        return default
    return v


def normalize_pct(x) -> float:
    """[PCT] → [DEC] 边界归一化：百分制输入 ÷100 转小数。

    输入层唯一允许的归一化点；业务公式里禁止散落 /100（LINT-01）。
    缺失/非法 → 0.0（调用方负责 N/A 链，见 TIER_S / TIER_A）。
    """
    return _f(x) / 100.0


# LINT-06：魔法数字集中声明（来源注记）
EXIT_FEE_PCT = 4.0            # [PCT] 退出费用率（2026-10-01 Miao 决定锁定，不开放调节）
DEFAULT_NOI_GROWTH_PCT = 2.0  # [PCT] NOI 年增长率默认（bank/agency 口；bridge 口强制 0，标准 §4）
DEFAULT_EXIT_CAP_PCT = 5.0    # [PCT] 退出 cap 硬默认（exit_cap_source="默认" 时标注）
DEFAULT_HOLD_YEARS = 5         # 持有年数默认（钳制 1-50）


# 标准 §1.2 N/A 分级：字段注册表（LINT-08 扫描用）
TIER_S = ("purchase_price", "net_rentable_sf", "property_type")  # 缺一 → 全报告"数据不足"
TIER_A = ("vacancy_pct", "down_pct", "rate", "amort_years", "market_cap_rate",
          "exit_cap_rate", "noi_growth",
          "lease_start", "lease_end", "expense_structure")        # 缺失 → 模块 N/A＋verdict 降级


def _div(a, b) -> float:
    b = _f(b)
    if b == 0:
        return 0.0
    return _f(a) / b


# ---------------------------------------------------------------- Rent Roll
def compute_rent_roll(tenants: list[dict], vacant_sf: float = 0.0) -> dict:
    rows = []
    for t in tenants or []:
        if not isinstance(t, dict):
            continue  # 脏行（字符串/数字/null）跳过，不 500
        sf = _f(t.get("sf"))
        monthly = _f(t.get("monthly_rent"))
        annual = monthly * 12.0
        uw_annual = _f(t.get("underwritten_annual"), annual)
        # 模板 T/U 列：租户级月 CAM / 月停车费（两实例均空置未用，现接通）
        m_cam = _f(t.get("monthly_cam"))
        m_pkg = _f(t.get("monthly_parking"))
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
            "monthly_cam": m_cam,
            "monthly_parking": m_pkg,
            "annual_cam": m_cam * 12.0,
            "annual_parking": m_pkg * 12.0,
            # P0-13：租期字段必须透传，否则 WALT/到期分析全空
            "lease_start": str(t.get("lease_start") or "")[:10],
            "lease_end": str(t.get("lease_end") or "")[:10],
            "escalation": str(t.get("escalation") or ""),
            "expense_structure": str(t.get("expense_structure") or ""),
        })
    total_sf = sum(r["sf"] for r in rows)
    total_monthly = sum(r["monthly_rent"] for r in rows)
    total_annual_lease = sum(r["annual_rent"] for r in rows)   # -> Cash Flow Historical
    total_annual_uw = sum(r["underwritten_annual"] for r in rows)  # -> Cash Flow Pro Forma
    total_annual_cam = sum(r["annual_cam"] for r in rows)      # -> Cash Flow CAM（模板 T 列）
    total_annual_parking = sum(r["annual_parking"] for r in rows)  # -> Cash Flow Parking（模板 U 列）
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
        "total_annual_cam": total_annual_cam,       # = 'Rent Roll'!T-total
        "total_annual_parking": total_annual_parking,  # = 'Rent Roll'!U-total
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
                     purchase_price: float, auto_cam: float = 0.0,
                     auto_parking: float = 0.0) -> dict:
    """One Cash Flow column (Historical or Pro Forma)."""
    inp = inp or {}
    # 模板血缘：T/U 列求和应流入此处；两实例均手填。空=自动取租户表明细，手填=覆盖。
    cam_manual = _f(inp.get("cam_recovery"))
    pkg_manual = _f(inp.get("parking_income"))
    cam_rec = cam_manual or _f(auto_cam)
    parking = pkg_manual or _f(auto_parking)
    other = _f(inp.get("other_income"))
    total_potential = base_rents + cam_rec + parking + other
    # 标准 v1.0 §1.1：vacancy_pct 输入 [PCT]，边界 normalize → [DEC] 再进乘法（P0-1 锁死点）
    vacancy_pct = normalize_pct(inp.get("vacancy_pct"))       # NEW (template hardcoded 0)
    vacancy_loss = total_potential * vacancy_pct
    egi = total_potential - vacancy_loss
    expenses = {k: _f(inp.get(k)) for k in EXPENSE_KEYS}
    total_expenses = sum(expenses.values())
    noi = egi - total_expenses
    ti = _f(inp.get("tenant_improvements"))
    capex = _f(inp.get("capex"))
    lc = _f(inp.get("leasing_commissions"))
    # 终裁②：盈亏平衡出租率分子含储备金（与 Excel 标注一致）
    replacement_reserve = _f(inp.get("replacement_reserve"))
    cash_flow_avail = noi - ti - capex - lc           # =B36/E36 in template
    # Template's "Cash Flow" row convention: NOI + Other Income (was hardcoded
    # 2,299,048 / 1,299,048 in the template; now a live formula).
    cash_flow_gross = noi + other
    return {
        "base_rents": base_rents,
        "cam_recovery": cam_rec,
        "parking_income": parking,
        "other_income": other,
        "income_sources": {
            "cam_recovery": "manual" if cam_manual else ("rent_roll" if _f(auto_cam) else "none"),
            "parking_income": "manual" if pkg_manual else ("rent_roll" if _f(auto_parking) else "none"),
        },
        "total_potential": total_potential,
        # 回显输入 [PCT] 原样（commercial_plus.noi_bank_bridge 按百分制消费）；计算已用小数
        "vacancy_pct": _f(inp.get("vacancy_pct")),
        "vacancy_loss": vacancy_loss,
        "egi": egi,
        "expenses": expenses,
        "total_expenses": total_expenses,
        "noi": noi,
        "tenant_improvements": ti,
        "capex": capex,
        "leasing_commissions": lc,
        "replacement_reserve": replacement_reserve,
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
    """Annual debt service for a fully amortizing loan（银行标准口径）.

    按月摊还：月复利等额本息月供 × 12。此前为按年摊还（年复利），
    DSCR 分母系统性偏大约 1.2%（2026-10-04 panel2 broker 实证：
    $2.24M/6.5%/25年 按年 $183,638.52 vs 按月 $181,495.68）。
    annual_rate 为小数（如 0.065）。
    """
    from app.finance import monthly_payment as _mp
    loan, annual_rate = _f(loan), _f(annual_rate)
    n = int(round(_f(amort_years)))
    if loan <= 0 or n <= 0:
        return 0.0
    if annual_rate <= 0:
        return loan / n
    return _mp(loan, annual_rate * 100.0, n) * 12.0


def remaining_balance(loan: float, annual_rate: float, amort_years: float,
                      payment: float, after_years: int) -> float:
    """Outstanding principal after k years（按月摊还，月复利；与 amort_payment 同口径）.

    payment 参数保留做兼容（现按月供内部重算，不再使用传入的年供额）。
    """
    from app.finance import remaining_balance as _rbm
    return _rbm(_f(loan), _f(annual_rate) * 100.0, _f(amort_years), after_years)


def compute_analysis(a: dict, hist: dict, pro: dict) -> dict:
    a = a or {}
    purchase = _f(a.get("purchase_price"))
    repairs = _f(a.get("building_repairs"))
    reserve = _f(a.get("capital_reserve"))
    lender_fees = _f(a.get("lender_fees"))
    closing = _f(a.get("closing_costs"))
    total_uses = purchase + repairs + reserve + lender_fees + closing

    # 标准 v1.0 §1.1（终裁①）：输入层 [PCT] → 边界 normalize → 计算层 [DEC]。
    # 命名违规迁移（附录 B）：down_pct=0.30/rate=0.06/market_cap_rate=0.04 的小数输入
    # 口径已废止；现输入 30 / 6.5 / 6 表示 30% / 6.5% / 6%。
    down_pct = normalize_pct(a.get("down_pct"))
    rate = normalize_pct(a.get("rate"))
    # P0-4（Phase 5）：默认全额本息摊还（AMORTIZING）。此前默认 IO（纯利息）但前端标注
    # "全额本息"，口径不诚实（1.42x vs 真实 1.16x）。显式选 IO 时标注必须同步改为纯利息。
    amort_type = (a.get("amort_type") or "AMORTIZING").upper()   # AMORTIZING | IO
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
    market_cap = normalize_pct(a.get("market_cap_rate"))
    projected_resale = _div(projected_noi, market_cap)   # template: =F15/F16
    acquisition_fees = repairs + reserve + lender_fees + closing  # =SUM(C14:C17)
    exit_fee_pct = EXIT_FEE_PCT / 100.0  # [DEC] 模板固定 4%（2026-10-01 Miao 决定锁定，不开放调节）
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
    # 终裁②：分子含储备金 —— (OpEx + debt_service + annual_reserve) ÷ TPI，
    # 与 Excel 总览标注"(费用＋还本付息＋储备金) ÷ 满租有效总收入"一致
    annual_reserve = _f(pro.get("replacement_reserve"))
    breakeven_occ = _div(pro["total_expenses"] + annual_debt + annual_reserve,
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
        # 输出回显一律 [DEC]（小数）：Excel PCT 格式格 / PDF _pct() / dscr 双轨标注
        # 均按小数消费。输入是 [PCT]，此处是归一化后的计算口径。
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
    """Hold-period exit: sale proceeds, IRR, equity multiple. NEW.

    输入层 [PCT]：a["noi_growth"] / a["exit_cap_rate"] / a["market_cap_rate"] 均为
    百分制（2 表示 2%），此处 normalize → [DEC]。位置参数 loan_bal / rate /
    annual_debt / net_liquidity 为内部 [DEC]，不归一化。
    """
    hold_years = int(round(_f(a.get("hold_years"), DEFAULT_HOLD_YEARS)))
    hold_years = max(1, min(hold_years, 50))  # 钳制 1-50 年：防极大值 DoS
    hold_years_is_default = not _f(a.get("hold_years"))
    # 标准 §4 分歧③裁决：bank/agency 口默认 2%（规则估算）；bridge/hard money 口
    # 强制 0% 由调用方在输入层置 noi_growth=0 实现（本函数不猜 funding-type）
    noi_growth = normalize_pct(a.get("noi_growth", DEFAULT_NOI_GROWTH_PCT))
    # Phase 5 第四轮 B4：退出 cap 联动用户输入——显式填了退出 cap 用显式值；
    # 没填但填了市场 cap 则联动市场 cap；都没填才用 5% 硬默认（PDF 标"默认"）。
    # 此前永远 5% 且无标记（pro-investor：填了市场 cap 5.5% 仍印 5.00%）。
    _exit_cap_raw = _f(a.get("exit_cap_rate"))
    _mkt_cap_raw = _f(a.get("market_cap_rate"))
    if _exit_cap_raw > 0:
        exit_cap, exit_cap_source = normalize_pct(a.get("exit_cap_rate")), "用户输入"
    elif _mkt_cap_raw > 0 and not a.get("market_cap_rate_is_default"):
        exit_cap, exit_cap_source = normalize_pct(a.get("market_cap_rate")), "联动市场cap"
    else:
        exit_cap, exit_cap_source = DEFAULT_EXIT_CAP_PCT / 100.0, "默认"
    exit_fee_pct = EXIT_FEE_PCT / 100.0  # [DEC] 模板固定 4%（2026-10-01 Miao 决定锁定，不开放调节）
    abatements = _f(a.get("abatements"))
    if hold_years <= 0 or net_liquidity <= 0:
        # LINT-04：退化输入不许用 0.0 冒充结果 —— IRR/EM/出售价一律 None（N/A 链）
        return {"hold_years": hold_years,
                "hold_years_is_default": hold_years_is_default,
                "irr": None, "equity_multiple": None,
                "sale_price": None, "sale_proceeds": None,
                "remaining_loan": None, "cash_flows": [],
                "exit_cap_rate": exit_cap, "exit_cap_source": exit_cap_source,
                "noi_growth": noi_growth}
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
        "hold_years_is_default": hold_years_is_default,
        "noi_growth": noi_growth,
        "exit_cap_rate": exit_cap,
        "exit_cap_source": exit_cap_source,   # 用户输入 | 联动市场cap | 默认
        "sale_price": sale_price,
        "remaining_loan": rem,
        "sale_proceeds": sale_proceeds,
        "cash_flows": flows,
        "irr": irr,                            # 不收敛 → None（终裁⑤，禁 0.0 冒充）
        "equity_multiple": em,
    }


def _irr(flows: list[float], lo: float = -0.99, hi: float = 10.0,
         iters: int = 100) -> float | None:
    """IRR 二分求解。终裁⑤：不收敛 → None（N/A 链），禁止返回 0.0
    （0% IRR 会被误读为"保本"）。"""
    def npv(r: float) -> float:
        return sum(cf / (1.0 + r) ** i for i, cf in enumerate(flows))
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
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
            # 标准 v1.0 §1.1：以下输入一律 [PCT]（百分制），计算层经 normalize_pct() 转小数
            "down_pct": 30, "rate": 6.5, "amort_type": "IO",
            "amort_years": 30, "market_cap_rate": 6,
            "abatements": 0,
            # 模板血缘：F13/F15/F24/I24 是手工承保假设（非公式）。
            # 空=None 时自动取 Cash Flow 实时值；一旦手填就锁定为手工口径。
            "underwritten_noi": None,   # F13 在手 NOI（驱动在手 Cap）
            "projected_noi": None,      # F15 预测 NOI（驱动转售价值）
            "inplace_noi_cf": None,     # I24 现金流块的在手 NOI
            "hold_years": 5, "noi_growth": 2, "exit_cap_rate": 5,
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
        "closing_costs": 864000, "down_pct": 30, "rate": 6,
        "amort_type": "IO", "market_cap_rate": 4,
    })
    return d


def compute_all(data: dict) -> dict:
    data = data or {}
    prop = data.get("property", {}) or {}
    net_sf = _f(prop.get("net_rentable_sf"))
    rent = compute_rent_roll(data.get("tenants"), data.get("vacant_sf", 0))
    purchase = _f((data.get("analysis") or {}).get("purchase_price"))
    hist = compute_scenario(data.get("historical"), rent["total_annual_lease"],
                            net_sf, purchase,
                            rent["total_annual_cam"], rent["total_annual_parking"])
    pro = compute_scenario(data.get("proforma"), rent["total_annual_uw"],
                           net_sf, purchase,
                           rent["total_annual_cam"], rent["total_annual_parking"])
    analysis = compute_analysis(data.get("analysis"), hist, pro)
    # 标准 §1.2 / LINT-08：Tier S/A 缺失不许静默默认 —— 显式缺口清单。
    # 缺失字段的计算链仍按 0 参与（不抛错），但调用方必须检查 data_gaps / tier_s_ok。
    _an_in = data.get("analysis") or {}
    _gaps_s = [k for k in TIER_S
               if k == "purchase_price" and not _f(_an_in.get("purchase_price"))]
    _gaps_s += [k for k in TIER_S if k != "purchase_price"
                and not str(prop.get(k) or "").strip()
                and not _f(prop.get(k))]
    _gaps_a = []
    for _sec, _d in (("historical", data.get("historical") or {}),
                     ("proforma", data.get("proforma") or {})):
        if _d.get("vacancy_pct") in (None, ""):
            _gaps_a.append(f"{_sec}.vacancy_pct")
    for k in ("down_pct", "rate", "amort_years", "market_cap_rate"):
        if _an_in.get(k) in (None, ""):
            _gaps_a.append(f"analysis.{k}")
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
        # 标准 §1.2：Tier S 缺一 → "数据不足"，Tier A 缺失 → 模块 N/A＋verdict 降级
        "data_gaps": {"tier_s": _gaps_s, "tier_a": _gaps_a},
        "tier_s_ok": not _gaps_s,
    }
