"""商业核保增补接线层（spec v2 §B-9）.

接现有 uw_commercial.compute_all() —— 零逻辑改动，只在其输出上做小扩展：
  - Debt Yield = 银行口径 NOI ÷ 拟贷款额（新 KPI，"拟贷款额"可输入覆盖）
  - DSCR 双轨：trailing 主（in-place）/ pro forma 辅，每个数字强制口径标注
  - NOI 银行调整桥 waterfall：卖方 NOI → 管理费/储备金/空置/税险调整 → 银行口径 NOI
  - LTV 按估值区间下限/上限双算（无区间时按收购价并注记）
  - 压力测试表：利率 +100/+200/+300bps、空置 +2/+5/+10pp、租金 −5%/−10%/−20%、
    组合（利率+200bps & 空置+5pp）；列 DSCR / Debt Yield / Breakeven；破红线标红
  - rent roll 摘要：逐租户表、WALT（租金加权 0.1 年）、到期分布、前三集中度
  - P0 缺口清单（无 rent roll → verdict 最高 HOLD 由 verdict 引擎执行）
"""

from __future__ import annotations

import copy
import math
from datetime import date

from . import uw_commercial


def _f(x, default=0.0) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    if math.isnan(v) or math.isinf(v):
        return default
    return v


def _div(a, b) -> float | None:
    # D3（2026-10-10，D460 CEO 已定）：零分母 → None（N/A 链），禁止 0.0 冒充。
    # 调用方一律做 None 守卫；前端/报表 None → "—"，绝不渲染 0.00/0%。
    b = _f(b)
    return _f(a) / b if b else None


# ---------------------------------------------------------------- NOI 银行调整桥
def noi_bank_bridge(result: dict, market_vacancy_pct: float | None = None, lang: str = "zh") -> dict:
    """卖方 NOI → 银行口径 NOI waterfall（专家规范 §2.1）.

    每一项单独成行，带金额与一句话依据；规则估算项标 🟡。
    """
    hist = result.get("historical") or {}
    prop = result.get("property") or {}
    seller_noi = _f(hist.get("noi"))
    egi = _f(hist.get("egi"))
    total_potential = _f(hist.get("total_potential"))
    # P0-1 (2026-10-05): compute_scenario 回显的 vacancy_pct 为百分制，转小数再参与计算
    cur_vac = _f(hist.get("vacancy_pct")) / 100
    expenses = hist.get("expenses") or {}
    existing_mgmt = _f(expenses.get("management_fee"))

    rows = []
    running = seller_noi
    rows.append({"item": "Seller-basis NOI (historical)" if lang == "en" else "卖方口径 NOI（历史）",
                 "amount": round(seller_noi, 2),
                 "basis": "Per seller statements; no buyer normalization applied" if lang == "en" else "卖方报表口径，未做买方标准化调整",
                 "tag": "yellow"})

    # 管理费调整：4-5%，Fannie floor 4%；补足到 4%（现有已计足则 0）
    target_mgmt = egi * 0.04
    mgmt_adj = max(0.0, target_mgmt - existing_mgmt)
    running -= mgmt_adj
    rows.append({"item": "- Management-fee adjustment (topped up to 4%)" if lang == "en" else "− 管理费调整（补足至 4%）",
                 "amount": round(-mgmt_adj, 2),
                 "basis": ("Fannie floor 4%; current management fee ${:,.0f} — rule-based estimate".format(existing_mgmt)
                           if lang == "en" else
                           "Fannie floor 4%；现有管理费 ${:,.0f}，规则估算".format(existing_mgmt)),
                 "tag": "yellow"})

    # replacement reserve：多户 $250/门/年；办公/零售 $0.18/SF/年
    units = _f(prop.get("units")) or _f((result.get("analysis") or {}).get("units"))
    sf = _f(prop.get("net_rentable_sf"))
    ptype = str(prop.get("property_type") or "").lower()
    if "multifamily" in ptype or "apartment" in ptype or (units and units >= 5):
        reserve = units * 250.0
        basis = (f"Multifamily $250/unit/yr x {units:.0f} units (Fannie standard) — rule-based estimate"
                 if lang == "en" else f"多户 $250/门/年 × {units:.0f} 门（Fannie 标准），规则估算")
    else:
        reserve = sf * 0.18
        basis = (f"Office/retail $0.18/SF/yr x {sf:,.0f} SF — rule-based estimate"
                 if lang == "en" else f"办公/零售 $0.18/SF/年 × {sf:,.0f} SF，规则估算")
    running -= reserve
    rows.append({"item": "− Replacement reserve" if lang == "en" else "− 替换储备金（replacement reserve）", "amount": round(-reserve, 2),
                 "basis": basis, "tag": "yellow"})

    # 空置调整：取市场空置率与 5% 孰高，补足差额
    mkt_vac = _f(market_vacancy_pct) / 100 if market_vacancy_pct else 0.05
    target_vac = max(mkt_vac, 0.05)
    vac_adj = max(0.0, (target_vac - cur_vac)) * total_potential
    running -= vac_adj
    rows.append({"item": "- Vacancy adjustment (higher of market vs 5%)" if lang == "en" else "− 空置调整（取市场与 5% 孰高）",
                 "amount": round(-vac_adj, 2),
                 "basis": ("Target vacancy {:.1f}% vs current {:.1f}% — rule-based estimate".format(target_vac * 100, cur_vac * 100)
                           if lang == "en" else
                           "目标空置 {:.1f}% vs 现有 {:.1f}%，规则估算".format(target_vac * 100, cur_vac * 100)),
                 "tag": "yellow"})

    # 税/保险调整：按重估后税额、现行市价保费；无税单时 0 + 注记
    tax_adj = 0.0
    rows.append({"item": "- Tax/insurance re-estimation adjustment" if lang == "en" else "− 税/保险重估调整",
                 "amount": round(tax_adj, 2),
                 "basis": "Tax bill unverified — seller basis used (OpEx may be understated)" if lang == "en" else "税单未核验，按卖方口径（OpEx 可能低估）",
                 "tag": "yellow"})

    rows.append({"item": "Bank-basis NOI" if lang == "en" else "银行口径 NOI",
                 "amount": round(running, 2),
                 "basis": "The DSCR numerator must use this basis" if lang == "en" else "DSCR 分子必须用此口径",
                 "tag": "green"})
    return {"rows": rows, "bank_noi": round(running, 2),
            "seller_noi": round(seller_noi, 2)}


# ---------------------------------------------------------------- DSCR 双轨
def dscr_dual(result: dict, bank_noi: float | None = None, lang: str = "zh") -> dict:
    """DSCR 双轨：trailing 主 / pro forma 辅，每个数字强制口径标注（P0-4）.

    口径铁律：分子=银行口径 NOI（有则用，无则回退现金流口径并如实标注）；
    分母=年还本付息（按月摊还口径，银行标准），标注必须与实际 amort_type 一致
    （AMORTIZING→"全额本息按月摊还"，IO→"纯利息（IO），不含本金"），不许挂羊头卖狗肉。
    """
    ana = result.get("analysis") or {}
    inpl = ana.get("inplace") or {}
    proj = ana.get("projected") or {}
    ds = _f(ana.get("annual_debt_service"))
    rate = _f(ana.get("rate"))
    amort = ana.get("amort_years")
    amort_type = str(ana.get("amort_type") or "AMORTIZING").upper()
    if amort_type == "AMORTIZING":
        ds_note = ("Fully amortizing monthly P&I, {} years".format(amort) if lang == "en"
                   else "全额本息按月摊还，{} 年".format(amort))
    else:
        ds_note = "Interest-only (IO), no principal" if lang == "en" else "纯利息（IO），不含本金"
    # trailing 分子：优先银行口径 NOI
    if bank_noi:
        trailing_dscr = _div(bank_noi, ds)
        trailing_num_note = "Bank-basis NOI" if lang == "en" else "银行口径 NOI"
    else:
        # D3：全款（ds=0）或 dscr 缺失 → None（N/A 链）；禁 _f() 压成 0.0
        # （"0.00×" 会被误读为"资不抵债"）
        trailing_dscr = inpl.get("dscr")
        trailing_dscr = None if trailing_dscr is None else _f(trailing_dscr)
        trailing_num_note = ("Cash-flow-basis NOI (bank basis missing — fallback)"
                               if lang == "en" else "现金流口径 NOI（银行口径缺失，回退）")
    proforma_dscr = proj.get("dscr")
    proforma_dscr = None if proforma_dscr is None else _f(proforma_dscr)

    def _dscr_label(v):
        return "—" if v is None else "{:.2f}x".format(v)

    return {
        "trailing": {
            "dscr": trailing_dscr,
            "label": (("{} ({} / {}, {:.2f}% fixed-rate assumption)"
                       if lang == "en" else "{}（{} / {}，{:.2f}% 定息假设）")
                      .format(_dscr_label(trailing_dscr), trailing_num_note, ds_note, rate * 100)),
            "primary": True,
            "numerator": trailing_num_note,
            "amort_type": amort_type,
        },
        "proforma": {
            "dscr": proforma_dscr,
            "label": (("{} (PF: forecast-basis NOI / {}, {:.2f}% fixed-rate assumption)"
                       if lang == "en" else "{}（PF：预测口径 NOI / {}，{:.2f}% 定息假设）")
                      .format(_dscr_label(proforma_dscr), ds_note, rate * 100)),
            "primary": False,
            "amort_type": amort_type,
        },
        "annual_debt_service": ds,
        "redline": {"strong": 1.35, "agency": 1.25, "bank_floor": 1.20, "dead": 1.00},
    }


# ---------------------------------------------------------------- rent roll 摘要
def rent_roll_summary(result: dict, lang: str = "zh") -> dict:
    rr = result.get("rent_roll") or {}
    tenants = [t for t in (rr.get("tenants") or []) if isinstance(t, dict)]
    total_annual = sum(_f(t.get("annual_rent")) for t in tenants)
    rows = []
    for t in tenants:
        rows.append({
            "suite": t.get("suite", ""), "tenant": t.get("tenant", ""),
            "sf": _f(t.get("sf")), "monthly_rent": _f(t.get("monthly_rent")),
            "annual_rent": _f(t.get("annual_rent")),
            "lease_start": t.get("lease_start") or t.get("start") or "",
            "lease_end": t.get("lease_end") or t.get("end") or "",
            "escalation": t.get("escalation") or "",
            "expense_structure": t.get("expense_structure") or t.get("lease_type") or "",
        })
    # WALT：租金加权剩余租期，精确到 0.1 年
    walt = None
    today = date.today()
    num = den = 0.0
    for t in tenants:
        end = t.get("lease_end") or t.get("end")
        try:
            d = date.fromisoformat(str(end)[:10])
        except Exception:
            continue
        yrs = max(0.0, (d - today).days / 365.25)
        rent = _f(t.get("annual_rent"))
        num += rent * yrs
        den += rent
    if den > 0:
        walt = round(num / den, 1)
    # 到期分布：未来 5 年到期租金
    buckets = {y: 0.0 for y in range(today.year, today.year + 6)}
    for t in tenants:
        end = t.get("lease_end") or t.get("end")
        try:
            d = date.fromisoformat(str(end)[:10])
        except Exception:
            continue
        if d.year in buckets:
            buckets[d.year] += _f(t.get("annual_rent"))
    # 前三集中度
    by_rent = sorted(tenants, key=lambda t: _f(t.get("annual_rent")), reverse=True)
    top3 = sum(_f(t.get("annual_rent")) for t in by_rent[:3])
    conc3 = _div(top3, total_annual) if total_annual else 0.0
    return {
        "has_rent_roll": bool(tenants),
        "tenant_count": len(tenants),
        "rows": rows,
        "total_annual_rent": round(total_annual, 2),
        "walt_years": walt,
        "walt_note": (("Rent-weighted remaining lease term" if lang == "en" else "租金加权剩余租期")
                      if walt is not None else
                      ("Lease start/end dates missing — WALT cannot be computed"
                       if lang == "en" else "缺租约起止日，无法计算 WALT")),
        "expiry_buckets": {str(k): round(v, 2) for k, v in buckets.items()},
        "top3_concentration": round(conc3, 4),
        "top3_flag": conc3 > 0.6,
        "occupancy": _f(rr.get("occupancy")),
    }


# ---------------------------------------------------------------- 压力测试
STRESS_TIERS = {
    "rate_bps": [100, 200, 300],
    "vacancy_pp": [2, 5, 10],
    "rent_pct": [-5, -10, -20],
    "combo": True,  # 利率+200bps & 空置+5pp
}


def _tweak(data: dict, rate_delta: float = 0.0, vac_delta: float = 0.0,
           rent_mult: float = 1.0) -> dict:
    # 标准 v1.0 §1.1：analysis 输入层 [PCT] —— rate_delta / vac_delta 均为百分点
    d = copy.deepcopy(data)
    a = d.setdefault("analysis", {})
    a["rate"] = max(0.0, _f(a.get("rate")) + rate_delta)
    for key in ("historical", "proforma"):
        sc = d.setdefault(key, {})
        sc["vacancy_pct"] = _f(sc.get("vacancy_pct")) + vac_delta
    tenants = d.get("tenants") or []
    for t in tenants:
        if isinstance(t, dict):
            t["monthly_rent"] = _f(t.get("monthly_rent")) * rent_mult
            t["underwritten_annual"] = _f(t.get("underwritten_annual"),
                                         _f(t.get("monthly_rent")) * 12) * rent_mult
    return d


def stress_table(data: dict, loan_amount: float | None = None,
                 market_vacancy_pct: float | None = None, lang: str = "zh") -> dict:
    """压力测试表：行=档位，列=DSCR / Debt Yield / Breakeven；破红线标红."""
    scenarios = [(("Base" if lang == "en" else "基准"), {})]
    for bps in STRESS_TIERS["rate_bps"]:
        # 标准 v1.0：rate 输入 [PCT] —— 100bps = 1.0 个百分点
        scenarios.append(((f"Rate +{bps}bps" if lang == "en" else f"利率 +{bps}bps"), {"rate_delta": bps / 100}))
    for pp in STRESS_TIERS["vacancy_pp"]:
        # P0-1 (2026-10-05): _tweak 操作的是百分制输入，vac_delta 用百分点（pp），不再 /100
        scenarios.append(((f"Vacancy +{pp}pp" if lang == "en" else f"空置 +{pp}pp"), {"vac_delta": pp}))
    for pct in STRESS_TIERS["rent_pct"]:
        scenarios.append(((f"Rent {pct}%" if lang == "en" else f"租金 {pct}%"), {"rent_mult": 1 + pct / 100}))
    if STRESS_TIERS["combo"]:
        scenarios.append((("Combo: rate +200bps & vacancy +5pp" if lang == "en" else "组合：利率+200bps & 空置+5pp"),
                          {"rate_delta": 0.02, "vac_delta": 5}))
    rows = []
    for label, kw in scenarios:
        r = uw_commercial.compute_all(_tweak(data, **kw))
        bridge = noi_bank_bridge(r, market_vacancy_pct)
        bank_noi = bridge["bank_noi"]
        loan = _f(loan_amount) or _f(r["analysis"].get("loan_bal"))
        ana = r["analysis"]
        # D3：dscr/debt_yield 缺失 → None（N/A 链）；breaks 未知不判破线
        dscr_t = ana["inplace"].get("dscr")
        dscr_p = ana["projected"].get("dscr")
        dy = _div(bank_noi, loan)
        rows.append({
            "scenario": label,
            "dscr_trailing": None if dscr_t is None else round(dscr_t, 3),
            "dscr_proforma": None if dscr_p is None else round(dscr_p, 3),
            "debt_yield": None if dy is None else round(dy, 4),
            "breakeven": (None if ana.get("breakeven_occupancy") is None
                         else round(ana.get("breakeven_occupancy"), 4)),
            "breaks": {
                "dscr": dscr_t is not None and dscr_t < 1.20,
                "debt_yield": dy is not None and dy < 0.06,
                "breakeven": _f(ana.get("breakeven_occupancy")) > 1.0,
            },
        })
    return {
        "rows": rows,
        "redlines": {"dscr": "≥1.20（标准档）", "debt_yield": "≥6%",
                     "breakeven": "≤100%（>100% 满租都不够还贷）"},
    }


# ---------------------------------------------------------------- 主入口
def compute_plus(data: dict, loan_amount: float | None = None,
                 valuation_range: dict | None = None,
                 market_vacancy_pct: float | None = None,
                 with_stress: bool = True, lang: str = "zh") -> dict:
    """compute_all() 输出 ＋ 增补指标（不改 compute_all 逻辑）."""
    data = data or {}
    base = uw_commercial.compute_all(data)
    ana = base["analysis"]
    loan = _f(loan_amount) or _f(ana.get("loan_bal"))
    bridge = noi_bank_bridge(base, market_vacancy_pct, lang)
    bank_noi = bridge["bank_noi"]
    debt_yield = _div(bank_noi, loan)   # D3：loan=0 → None（N/A 链），禁 0.0 冒充

    # LTV 双算：按估值区间下限/上限；无区间时按收购价并注记
    ltv = {"loan": round(loan, 2)}
    vr = valuation_range or {}
    vlo, vhi = _f(vr.get("lo")), _f(vr.get("hi"))
    if vlo > 0 and vhi > 0:
        ltv.update({
            "at_range_lo": round(_div(loan, vlo), 4),
            "at_range_hi": round(_div(loan, vhi), 4),
            "range": [vlo, vhi],
            "note": "Banks always underwrite to the conservative value (range low)" if lang == "en" else "银行永远看保守值（区间下限）",
        })
    else:
        price = _f(ana.get("purchase_price"))
        ltv_at = _div(loan, price)   # D3：price=0 → None（N/A 链）
        ltv.update({
            "at_purchase": None if ltv_at is None else round(ltv_at, 4),
            "note": "No valuation range — computed on purchase price (dual calc once valuation is connected)" if lang == "en" else "无估值区间，按收购价计（待估值接入后双算）",
        })

    rr = rent_roll_summary(base, lang)
    p0_gaps = []
    if not rr["has_rent_roll"]:
        p0_gaps.append("No structured rent roll (WALT / expiry concentration / tenant concentration unverifiable — NOI credibility downgraded)"
                       if lang == "en" else "缺结构化 rent roll（WALT/到期集中度/租户集中度无法验证，NOI 可信度降级）")
    hist = base.get("historical") or {}
    if _f(hist.get("noi")) <= 0:
        p0_gaps.append("T-12 operating data missing (DSCR on a forecast basis)"
                       if lang == "en" else "T-12 经营数据缺失（DSCR 基于预测口径）")
    if not _f(ana.get("loan_bal")) and not loan_amount:
        p0_gaps.append("Actual loan terms not entered (DSCR on template assumptions)"
                       if lang == "en" else "真实贷款条件未输入（DSCR 按模板假设）")

    out = dict(base)
    out["plus"] = {
        "debt_yield": None if debt_yield is None else round(debt_yield, 4),
        "debt_yield_note": ("NOI (bank basis) / proposed loan amount; 8-10%+ comfortable, 7% agency multifamily floor, <6% institutional capital walks"
                            if lang == "en" else "NOI（银行口径）÷ 拟贷款额；≥8-10% 舒适，≥7% agency 多户底线，<6% 机构资金出局"),
        "dscr_dual": dscr_dual(base, bank_noi, lang),
        "noi_bank_bridge": bridge,
        "ltv": ltv,
        "rent_roll_detail": rr,
        "p0_gaps": p0_gaps,
        "has_rent_roll": rr["has_rent_roll"],
    }
    if with_stress:
        out["plus"]["stress"] = stress_table(data, loan, market_vacancy_pct, lang=lang)
    return out
