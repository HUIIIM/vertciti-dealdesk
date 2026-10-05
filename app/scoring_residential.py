"""住宅线评分引擎 —— 严格实现 buyer-box.md v2.3.

100 分构成：现金流 30 / 贷款条款 25 / 首付 15 / 市场 15 / 风险逆向扣分 15.
分级：>=80 A / 65-79 B / 50-64 C / <50 D；任一硬否决 => 等级"否决".
（打分等级为 A/B/C/D 档；verdict 另看 verdict 口径。）
v2.2（Miao 亲定 2026-09-28 晚）：subject-to 首付浮动制——≤10% 为正常区间，
首付评分按 deal 质量浮动（基础分随首付比例递减＋现金流强度上浮最高 15 分），
删除 subject-to 首付在 8%/10% 的任何硬否决。
v2.3（CEO 终裁，Miao 授权）：负净值不再单独否决，改"负净值入场"风险旗＋补偿条件制
（补偿条件由现金流/DSCR/储备金/退出预案现有否决项覆盖）。
"""

from __future__ import annotations

from .finance import clamp, floating_down_payment_score, lin_map, monthly_payment, safe_div

STRUCTURE_LABELS = {
    "standard": "普通购买",
    "new_loan": "贷款购买（新办贷款）",
    "subject_to": "Subject-to（承接现有贷款）",
    "seller_financing": "Seller financing（卖方融资）",
    "loan_assumption": "Loan assumption（银行正式承接）",
    "lease_option": "Lease option（租购）",
    "novation": "Novation（新约替代）",
    "wholesale": "折价批发/转合同",
}

RISK_FLAG_LABELS = {
    "rural": "偏远/rural 市场",
    "insurance_volatile": "保险市场动荡州（保费不可获得/暴涨）",
    "high_property_tax": "房产税异常高且无对冲",
    "old_property": "房龄 >40 年（维修/CapEx 超预期风险）",
    "flood_zone": "洪水区/灾害高风险区",
    "hoa_litigation": "HOA 纠纷/诉讼中",
    "low_reserves": "储备金不足 6 个月 PITI",
    "thin_market": "市场流动性薄（转售周期长）",
    "negative_equity": "负净值入场（v2.3 起不再单独否决，挂风险旗）",
}


def compute_metrics(d: dict) -> dict:
    """F3/F4/F5/F6/F7/F8/F9: 住宅现金流全口径测算."""
    price = d["price"]
    loan_balance = d.get("loan_balance", 0)
    rate = d.get("rate", 0)
    term = d.get("term_years_remaining", 30)

    monthly_pi = monthly_payment(loan_balance, rate, term)
    piti = monthly_pi + d.get("taxes_annual", 0) / 12 + d.get("insurance_annual", 0) / 12

    gross = d.get("monthly_rent", 0) + d.get("other_income_monthly", 0)
    vacancy = d.get("vacancy_pct", 8) / 100
    egi = gross * (1 - vacancy)

    opex = (
        d.get("taxes_annual", 0) / 12
        + d.get("insurance_annual", 0) / 12
        + d.get("hoa_monthly", 0)
        + d.get("utilities_owner_monthly", 0)
        + gross * d.get("maint_pct", 8) / 100
        + gross * d.get("capex_pct", 8) / 100
        + egi * d.get("mgmt_pct", 10) / 100
    )
    noi = egi - opex
    cash_flow = noi - monthly_pi
    units = max(d.get("units", 1), 1)
    per_door = cash_flow / units

    cash_invested = d.get("down_payment", 0) + d.get("closing_costs", 0) + d.get("initial_repairs", 0)
    coc = safe_div(cash_flow * 12, cash_invested)
    dscr = safe_div(noi, monthly_pi)
    cap_rate = safe_div(noi * 12, price)
    equity = price - loan_balance - d.get("other_liens", 0)
    dp_pct = safe_div(d.get("down_payment", 0), price)
    # 全口径现金需求（一级字段）：首付+交割费+初期维修+储备金（Miao 硬约束口径）
    reserves_cash = d.get("reserves_months_piti", 0) * piti
    total_cash_required = cash_invested + reserves_cash

    return {
        "monthly_pi": round(monthly_pi, 2),
        "piti": round(piti, 2),
        "egi": round(egi, 2),
        "opex": round(opex, 2),
        "noi_monthly": round(noi, 2),
        "cash_flow_monthly": round(cash_flow, 2),
        "cash_flow_per_door": round(per_door, 2),
        "cash_invested": round(cash_invested, 2),
        "reserves_cash": round(reserves_cash, 2),
        "total_cash_required": round(total_cash_required, 2),
        "cash_to_close": round(total_cash_required, 2),  # 一级字段（v1.1）
        "cash_on_cash": round(coc, 4) if coc is not None else None,
        "dscr": round(dscr, 3) if dscr is not None else None,
        "cap_rate": round(cap_rate, 4) if cap_rate is not None else None,
        "equity": round(equity, 2),
        "down_pct": round(dp_pct, 4) if dp_pct is not None else None,
    }


def check_vetoes(d: dict, m: dict) -> list[dict]:
    """buyer-box.md 第七节：硬否决项（v2.3：负净值不再单独否决，改风险旗＋补偿条件制）。"""
    vetoes = []
    if d.get("rate_type") != "fixed":
        vetoes.append({"code": "floating_rate", "message": "浮动/可调利率否决：只做固定利率（Miao 亲定）"})
    balloon = d.get("balloon_years")
    if balloon is not None and balloon < 5:
        vetoes.append({"code": "short_balloon", "message": f"短期 balloon 否决：{balloon} 年内到期 balloon（Miao 亲定）"})
    # P0-2（Phase 5）：退出 / due-on-sale 否决仅在 structure=subject_to 时参与 verdict；
    # 普通购买/贷款购买结构下永不出现。单一"退出策略"输入即可解除对应否决
    # （备选路径硬性要求取消——前端只有一个退出策略入口，选了即解除）。
    if d.get("structure") == "subject_to" and not d.get("exit_primary"):
        vetoes.append({"code": "no_exit",
                       "message": "无退出预案否决：subject-to 须先选定退出策略（出售/refi/转租购/持有收租）"})
    if d.get("structure") == "subject_to" and not d.get("due_on_sale_plan"):
        vetoes.append({"code": "no_dos_plan", "message": "无 due-on-sale 备用预案否决：subject-to 必须能 refi/出售/转租购三选一落地"})
    if d.get("seller_delinquent_days", 0) > 90 and not d.get("has_discount_hedge"):
        vetoes.append({"code": "delinquent", "message": "卖方贷款逾期 >90 天且无深度折价对冲"})
    if not d.get("insurance_available", True):
        vetoes.append({"code": "no_insurance", "message": "房子买不到保险/无保险路径"})
    # P0-1（Phase 5）：删除"卖方拒绝签 authorization to release"无条件一票否决——
    # 后端无输入源能证明"拒绝"，属幻觉式否决。改为 Zone 7 交割 checklist 的一项
    # （"交割前向卖方索取 authorization to release"，状态未验证），永不自动否决。
    if d.get("rent_source") == "proforma":
        vetoes.append({"code": "proforma_rent", "message": "租金是 pro-forma 自嗨、无 comps 支撑"})
    if d.get("hoa_arrears_severe") or d.get("title_defect"):
        vetoes.append({"code": "title_hoa", "message": "HOA 巨额欠费 / title 硬伤清不掉"})
    if d.get("fraud_flag"):
        vetoes.append({"code": "fraud", "message": "要求虚假陈述/结构明显欺诈"})
    return vetoes


def score(d: dict) -> dict:
    """满分 100 评分，返回 {total, grade, dimensions, vetoes, metrics, checks}."""
    m = compute_metrics(d)
    vetoes = check_vetoes(d, m)
    dims = []

    # --- 维度1: 现金流 30 分（整套现金流/DSCR/CoC 综合）---
    # Phase 5 第六轮微修复 #7（newbie）：住宅小白不懂"单门"黑话→"整套"；
    # #8：负号放 $ 前面（-$7,585/月），不许 $-7585/月
    per_door = m["cash_flow_per_door"]
    _pd_txt = ("-$" if per_door < 0 else "$") + f"{abs(per_door):,.0f}/月"
    if per_door >= 500:
        cf_s = 1.0
    elif per_door >= 300:
        cf_s = 0.5 + 0.5 * (per_door - 300) / 200
    elif per_door > 0:
        cf_s = 0.5 * per_door / 300
    else:
        cf_s = 0.0
    coc = m["cash_on_cash"]
    if coc is None:
        coc_s = 0.0
    elif coc >= 0.15:
        coc_s = 1.0
    elif coc >= 0.12:
        coc_s = 0.5 + 0.5 * (coc - 0.12) / 0.03
    elif coc > 0:
        coc_s = 0.5 * coc / 0.12
    else:
        coc_s = 0.0
    dscr = m["dscr"]
    if dscr is None:
        dscr_s = 0.0
    elif dscr >= 1.5:
        dscr_s = 1.0
    elif dscr >= 1.25:
        dscr_s = 0.5 + 0.5 * (dscr - 1.25) / 0.25
    elif dscr >= 1.0:
        dscr_s = 0.5 * (dscr - 1.0) / 0.25
    else:
        dscr_s = 0.0
    cashflow_pts = 30 * (0.6 * cf_s + 0.2 * coc_s + 0.2 * dscr_s)
    if coc is not None:
        cf_detail = f"整套现金流 {_pd_txt}，CoC {coc*100:.1f}%"
    else:
        cf_detail = f"整套现金流 {_pd_txt}，CoC 未计算"
    cf_detail += f"，DSCR {dscr:.2f}" if dscr is not None else "，DSCR 未计算"
    dims.append({"key": "cashflow", "label": "现金流指标", "weight": 30,
                 "points": round(cashflow_pts, 1), "detail": cf_detail})

    # --- 维度2: 贷款条款 25 分 ---
    rate = d.get("rate", 0)
    if rate <= 3:
        rate_pts = 15.0
    elif rate < 6:
        rate_pts = 15 - 7 * (rate - 3) / 3
    elif rate < 8:
        rate_pts = 8 - 8 * (rate - 6) / 2
    else:
        rate_pts = 0.0
    term = d.get("term_years_remaining", 30)
    if term >= 25:
        term_pts = 10.0
    elif term >= 20:
        term_pts = 8.0
    elif term >= 15:
        term_pts = 6.0
    elif term >= 10:
        term_pts = 5.0
    elif term >= 5:
        term_pts = 3.0
    else:
        term_pts = 0.0
    loan_pts = rate_pts + term_pts + (2.0 if d.get("is_assumption") else 0.0)
    loan_pts = clamp(loan_pts, 0, 25)
    dims.append({"key": "loan_terms", "label": "贷款条款质量", "weight": 25,
                 "points": round(loan_pts, 1),
                 "detail": f"固定利率 {rate:.2f}%，剩余 {term:.0f} 年"
                           + ("，银行正式承接（无 due-on-sale 风险）" if d.get("is_assumption") else "")})

    # --- 维度3: 首付 15 分（v2.2 浮动制：基础分随首付比例递减＋现金流强度上浮最高 15 分）---
    dp = (m["down_pct"] or 0) * 100
    strength = clamp(dims[0]["points"] / 30, 0, 1)  # 现金流维度得分率
    dp_score100, dp_base, dp_bonus = floating_down_payment_score(dp, strength)
    dp_pts = dp_score100 * 0.15
    dims.append({"key": "down_payment", "label": "首付比例", "weight": 15,
                 "points": round(dp_pts, 1),
                 "detail": f"首付 {dp:.1f}%（浮动制：基础 {dp_base:.0f} 分＋现金流强度上浮 {dp_bonus:.0f} 分；"
                           f"≤10% 为正常区间，deal 越好、可承受首付越高）"
                           + ("（>10% 需 RE-0 特批）" if dp > 10 else "")})

    # --- 维度4: 市场 15 分（未评估=0，不编造）---
    market_pts = (d.get("market_pop", 0) + d.get("market_employment", 0)
                  + d.get("market_inventory", 0) + d.get("market_appreciation", 0))
    market_pts = clamp(market_pts, 0, 15)
    dims.append({"key": "market", "label": "市场与升值空间", "weight": 15,
                 "points": round(market_pts, 1),
                 "detail": "人口流入/就业/库存/历史增值四项打分" if market_pts > 0 else "未评估（0 分，不编造）"})

    # --- 维度5: 风险逆向扣分 15 分 ---
    flags = list(d.get("risk_flags", []))
    if d.get("reserves_months_piti", 0) < 6 and "low_reserves" not in flags:
        flags.append("low_reserves")
    if m["equity"] < 0 and "negative_equity" not in flags:
        flags.append("negative_equity")  # v2.3：负净值不再否决，挂风险旗
    risk_pts = clamp(15 - 3 * len(flags), 0, 15)
    dims.append({"key": "risk", "label": "风险（逆向扣分）", "weight": 15,
                 "points": round(risk_pts, 1),
                 "detail": ("无实质风险旗" if not flags
                            else f"{len(flags)} 个风险旗："
                                 + "、".join(RISK_FLAG_LABELS.get(f, f) for f in flags))})

    total = round(sum(x["points"] for x in dims), 1)
    if vetoes:
        grade = "否决"
    elif total >= 80:
        grade = "A"
    elif total >= 65:
        grade = "B"
    elif total >= 50:
        grade = "C"
    else:
        grade = "D"

    checks = [
        {"label": "储备金 ≥6 个月 PITI", "ok": d.get("reserves_months_piti", 0) >= 6,
         "note": f"当前 {d.get('reserves_months_piti', 0):.1f} 个月"},
        {"label": "整套现金流 ≥$300/月", "ok": per_door >= 300,
         "note": f"当前 {_pd_txt}"},
        {"label": "CoC ≥12%（A 档 ≥15%）", "ok": (coc or 0) >= 0.12,
         "note": f"当前 {coc*100:.1f}%" if coc is not None else "未计算"},
        {"label": "DSCR ≥1.25", "ok": (dscr or 0) >= 1.25,
         "note": f"当前 {dscr:.2f}" if dscr is not None else "未计算"},
        {"label": "租金有 comps 支撑", "ok": d.get("rent_source") != "proforma",
         "note": {"comps_verified": "实测 comps", "estimated": "估算（未核实不进 A 档）",
                  "proforma": "pro-forma（否决）"}.get(d.get("rent_source"), "")},
        {"label": "净值（负净值挂风险旗，不再单独否决）", "ok": True,
         "note": f"交割净值 ${m['equity']:,.0f}"
                 + ("（负净值入场风险旗：需现金流为正＋DSCR＋储备金＋可行退出同时成立）" if m["equity"] < 0 else "")},
        {"label": "subject-to 首付浮动制（≤10% 正常区间，>10% 需 RE-0 特批）",
         "ok": d.get("structure") != "subject_to" or (m["down_pct"] or 0) * 100 <= 10,
         "note": f"当前 {((m['down_pct'] or 0) * 100):.1f}%（deal 越好、可承受首付越高）"},
        {"label": "全口径现金需求 cash-to-close（一级字段）", "ok": True,
         "note": f"${m['cash_to_close']:,.0f} = 首付＋交割费＋初期维修＋储备金；金额硬上限待确认"},
    ]
    return {"total": total, "grade": grade, "dimensions": dims,
            "vetoes": vetoes, "downgrades": [], "metrics": m, "checks": checks,
            "structure_label": STRUCTURE_LABELS.get(d.get("structure"), "")}
