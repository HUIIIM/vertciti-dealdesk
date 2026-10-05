"""商业线评分引擎 —— 严格实现 buyer-box-commercial.md v1.3.

100 分构成：NOI/DSCR 30 / 租约质量 20 / 贷款条款 15 / 首付 10 / 市场 10 / 风险逆向扣分 15.
分级：>=80 A / 65-79 B / 50-64 C / <50 D；任一硬否决 => 等级"否决".
（打分等级为 A/B/C/D 档；verdict 另看 verdict 口径：值得买/再看看/别碰 · BUY/HOLD/PASS。）
DSCR <1.25 直接否决不参与打分（酒店 ≥1.35）。
v1.1 新增：office / hotel 纳入 in scope（专项保守核保）；value-add 预租 ≥70% 进 A 档门禁；
cash-to-close 为一级字段。
v1.2（Miao 亲定 2026-09-28 晚）：subject-to 首付浮动制——≤10% 为正常区间，
首付评分按 deal 质量浮动（基础分随首付比例递减＋现金流强度上浮最高 15 分）。
v1.3（Miao 亲定 2026-09-28 晚＋CEO 终裁）：
① 删除"只能靠短期高价抛售解套"硬否决——高价抛售可接受（需 refi 能独立成立、
refi 后能拿出钱）；只有退出完全依赖短期高价抛售且 refi/持有皆不成立时才否决
（无可行退出 no_viable_exit）；凡退出含抛售成分挂"退出依赖高价抛售"风险旗；
② 负净值不再单独否决，改"负净值入场"风险旗＋补偿条件制。
降级机制：downgrades 列表记录"封顶降级"（如 office 压力测试失败最高 C 档），
与 vetoes（一票否决）区分展示。
"""

from __future__ import annotations

from .finance import clamp, floating_down_payment_score, lin_map, monthly_payment, safe_div

ASSET_LABELS = {
    "small_bay_industrial": "Small-bay industrial（小单间工业）",
    "retail_strip": "Retail strip（零售带状商业）",
    "mixed_use": "Mixed-use（商住混合）",
    "small_multifamily_5plus": "Small multifamily 5+（5单元以上小多户）",
    "office": "Office（办公，v1.1 纳入）",
    "hotel": "Hotel（酒店，v1.1 纳入）",
    "other": "其他（商业线范围外）",
}

STRUCTURE_LABELS = {
    "standard": "普通购买",
    "new_loan": "贷款购买（新办贷款）",
    "seller_financing": "Seller financing（卖方融资）",
    "master_lease": "Master lease / lease-option（主租约）",
    "subject_to": "Subject-to（承接现有商业贷款）",
    "loan_assumption": "Loan assumption（银行正式承接）",
    "seller_carryback_2nd": "Seller carryback 二顺位",
}

# 第六节：重置储备按类别（$/年）；hotel 用 FF&E（营收口径）单独计算
RESERVE_RULES = {
    "small_bay_industrial": ("psf", 0.15),
    "retail_strip": ("psf", 0.30),
    "mixed_use": ("psf", 0.30),
    "small_multifamily_5plus": ("unit", 300.0),
    "office": ("psf", 0.30),
    "hotel": ("psf", 0.30),  # 占位：hotel 实际走 FF&E 口径
    "other": ("psf", 0.30),
}

# 第五节：默认空置/坏账假设；office 强制下限 12%（v1.1）
DEFAULT_VACANCY = {
    "small_bay_industrial": 5.0,
    "retail_strip": 8.0,
    "mixed_use": 8.0,
    "small_multifamily_5plus": 5.0,
    "office": 12.0,
    "hotel": 0.0,  # 酒店不设固定空置率，改按 RevPAR 保守取值＋淡季覆盖测试
    "other": 8.0,
}

RISK_FLAG_LABELS = {
    "insurance_unavailable": "保险买不到/暴涨的市场",
    "tax_reassessment": "房产税重估激进的县",
    "single_industry": "单一产业依赖度过高的城市",
    "weak_tenant_mix": "弱租户占比 >30%（无担保无押金）",
    "no_escalation": "无递增条款租约占比 >50%",
    "gross_no_hedge": "纯 gross 租约无费用对冲",
    "high_ti_lc": "TI/LC 敞口偏高",
    "low_reserves": "储备金不足（<6 个月 debt service；value-add <12 个月）",
    "env_watch": "环境需持续监测项",
    "refi_risk": "退出 refi 可行性存疑",
    # v1.1 新增
    "hotel_opex_missing": "酒店未填部门/固定费用（NOI 可能高估）",
    "franchise_term": "特许经营协议 <10 年且无续期权",
    "low_season_gap": "淡季月份现金流未覆盖当月 debt service",
    "ti_lc_not_itemized": "Office TI/LC 未逐项核算",
    # v1.3 新增
    "negative_equity": "负净值入场（v1.3 起不再单独否决，挂风险旗）",
    "exit_flip_dependent": "退出依赖高价抛售（v1.3 起不再单独否决，挂风险旗呈报 Miao）",
}


def required_dscr_for(d: dict) -> float:
    """DSCR 门槛：酒店 1.35（v1.1 专项），其余 1.25。"""
    return 1.35 if d.get("asset_class") == "hotel" else 1.25


def compute_metrics(d: dict, with_stress: bool = True) -> dict:
    """F3/F5/F8/F12/F13/F14/F15: 商业 NOI 全口径测算（buyer-box-commercial §4/§6，v1.1 专项口径）.

    hotel：不设固定空置率，用保守 RevPAR 口径的年总营收；管理费 ≥5% revenue；
    FF&E reserve ≥4% revenue 全额计入现金流；部门/固定费用按 P&L 录入。
    office：空置/坏账强制下限 12%；租金下调 10% 压力测试（with_stress=False 时跳过，
    供压力测试内部递归调用）。
    cash_to_close（一级字段）= 现金首付＋交割费＋储备金＋首年 capex/TI-LC（＋酒店 PIP capex）。
    金额硬上限不硬编码（待确认）。
    """
    asset = d.get("asset_class", "retail_strip")
    is_hotel = asset == "hotel"
    is_office = asset == "office"

    if is_hotel:
        # 酒店：RevPAR 保守取值由录入人完成（trailing 12m 与 3 年平均孰低），引擎用年总营收
        revenue = d.get("hotel_revenue_annual", 0)
        vacancy_used = 0.0
        egi = revenue
        tax = d.get("tax_annual", 0) * 1.10
        mgmt = revenue * max(d.get("hotel_mgmt_pct", 5), 5) / 100
        ff_e = revenue * max(d.get("hotel_ff_e_pct", 4), 4) / 100
        dept_opex = d.get("hotel_opex_annual", 0)
        opex = tax + d.get("insurance_annual", 0) + dept_opex + mgmt
        opex_detail = {
            "tax_with_reassessment": round(tax, 2),
            "insurance": round(d.get("insurance_annual", 0), 2),
            "management": round(mgmt, 2),
            "departmental_opex": round(dept_opex, 2),
            "cam_gap": round(d.get("utilities_cam_gap_annual", 0), 2),
        }
        noi = egi - opex
        reserves = ff_e  # 酒店重置储备 = FF&E（v1.1 专项）
    else:
        default_vac = DEFAULT_VACANCY.get(asset, 8.0)
        vacancy = d.get("vacancy_pct", default_vac) / 100
        if is_office:
            vacancy = max(vacancy, 0.12)  # office 空置/坏账假设 ≥12%（v1.1）
        vacancy_used = vacancy
        gross = d.get("annual_base_rent", 0) + d.get("other_income_annual", 0)
        egi = gross * (1 - vacancy)

        # OpEx：税按重估风险上浮 10%；管理费 >=8% EGI；维修 >=5%（房龄>20 按 7%）
        tax = d.get("tax_annual", 0) * 1.10
        mgmt = egi * max(d.get("mgmt_pct", 8), 8) / 100
        maint_pct = d.get("maint_pct", 5)
        if d.get("property_age_years", 0) > 20:
            maint_pct = max(maint_pct, 7)
        maint = egi * maint_pct / 100
        opex = (tax + d.get("insurance_annual", 0) + mgmt + maint
                + d.get("utilities_cam_gap_annual", 0))
        opex_detail = {
            "tax_with_reassessment": round(tax, 2),
            "insurance": round(d.get("insurance_annual", 0), 2),
            "management": round(mgmt, 2),
            "maintenance": round(maint, 2),
            "cam_gap": round(d.get("utilities_cam_gap_annual", 0), 2),
        }
        noi = egi - opex

        # 重置储备：类别规则 vs 5% EGI 孰高（F15）
        kind, val = RESERVE_RULES.get(asset, ("psf", 0.30))
        if kind == "psf":
            rule_reserve = d.get("building_sf", 0) * val
        else:
            rule_reserve = d.get("units", 0) * val
        reserves = max(rule_reserve, 0.05 * egi)

    # 全部杠杆的年还本付息
    annual_ds = 0.0
    tranche_info = []
    for t in d.get("tranches", []):
        pmt = monthly_payment(t.get("balance", 0), t.get("rate", 0), t.get("term_years", 30))
        annual_ds += pmt * 12
        tranche_info.append({**t, "payment_monthly": round(pmt, 2)})

    ti_lc = d.get("ti_lc_annual_amort", 0)
    ff_e_annual = ff_e if is_hotel else 0.0
    net_cf_annual = noi - annual_ds - reserves - ti_lc
    net_cf_monthly = net_cf_annual / 12

    pip = d.get("pip_capex", 0) if is_hotel else 0.0  # 品牌 PIP capex 全额计入收购成本
    total_cost = d.get("price", 0) + d.get("closing_costs", 0) + d.get("capex_y1", 0) + pip
    entry_cap = safe_div(noi, total_cost)  # F13
    market_cap = d.get("market_cap_rate_pct", 0) / 100
    spread_bps = (entry_cap - market_cap) * 10000 if entry_cap is not None else None
    dscr = safe_div(noi, annual_ds)  # F8

    cash_invested = d.get("down_payment", 0) + d.get("closing_costs", 0) + d.get("capex_y1", 0) + pip
    coc = safe_div(net_cf_annual, cash_invested)
    dp_pct = safe_div(d.get("down_payment", 0), d.get("price", 0))
    equity = d.get("as_is_appraisal", 0) - d.get("price", 0) if d.get("as_is_appraisal") else None

    # 全口径现金需求（一级字段）：首付+交割费+首年capex/PIP+储备金+TI/LC
    monthly_ds = annual_ds / 12
    reserves_cash = d.get("reserves_months_ds", 0) * monthly_ds
    total_cash_required = cash_invested + reserves_cash + ti_lc

    # office 租金压力测试：租金下调 10% 后重算 DSCR（内部递归，with_stress=False 防循环）
    stressed_dscr = None
    if is_office and with_stress:
        stressed = dict(d)
        stressed["annual_base_rent"] = d.get("annual_base_rent", 0) * 0.9
        sm = compute_metrics(stressed, with_stress=False)
        stressed_dscr = sm["dscr"]

    return {
        "egi": round(egi, 2),
        "opex": round(opex, 2),
        "opex_detail": opex_detail,
        "noi": round(noi, 2),
        "reserves_annual": round(reserves, 2),
        "ff_e_annual": round(ff_e_annual, 2),
        "annual_debt_service": round(annual_ds, 2),
        "net_cf_annual": round(net_cf_annual, 2),
        "net_cf_monthly": round(net_cf_monthly, 2),
        "entry_cap": round(entry_cap, 4) if entry_cap is not None else None,
        "market_cap": round(market_cap, 4),
        "spread_bps": round(spread_bps, 0) if spread_bps is not None else None,
        "dscr": round(dscr, 3) if dscr is not None else None,
        "required_dscr": required_dscr_for(d),
        "stressed_dscr": round(stressed_dscr, 3) if stressed_dscr is not None else None,
        "cash_on_cash": round(coc, 4) if coc is not None else None,
        "cash_invested": round(cash_invested, 2),
        "reserves_cash": round(reserves_cash, 2),
        "total_cash_required": round(total_cash_required, 2),
        "cash_to_close": round(total_cash_required, 2),  # 一级字段（v1.1）
        "down_pct": round(dp_pct, 4) if dp_pct is not None else None,
        "equity": round(equity, 2) if equity is not None else None,
        "tranches": tranche_info,
        "vacancy_used_pct": round(vacancy_used * 100, 1),
    }


def check_vetoes(d: dict, m: dict) -> list[dict]:
    """buyer-box-commercial.md 第九节：硬否决项（v1.3：负净值改风险旗；抛售退出软化）。"""
    vetoes = []
    asset = d.get("asset_class", "retail_strip")
    is_office = asset == "office"
    is_hotel = asset == "hotel"
    if asset == "other":
        vetoes.append({"code": "out_of_scope",
                       "message": "资产类别不在商业线范围内（开发用地/ground lease/机构级NNN/1-4单元除外；office、酒店 v1.1 已纳入）"})
    if is_office:
        # v1.1 office 专项门槛：纯投机性空置办公不看
        if d.get("occupancy_pct", 0) < 80:
            vetoes.append({"code": "office_low_occupancy",
                           "message": "Office 在租率 <80% 否决：纯投机性空置办公不看（v1.1 专项口径）"})
        if d.get("walt_years", 0) < 4:
            vetoes.append({"code": "office_walt",
                           "message": "Office WALT <4 年否决（v1.1 专项口径）"})
    if is_hotel:
        if not d.get("has_operating_history", True):
            vetoes.append({"code": "hotel_no_history",
                           "message": "无经营记录的新建/烂尾酒店（一票否决，v1.1 专项口径）"})
        if d.get("revpar_source") == "proforma":
            vetoes.append({"code": "hotel_proforma_revpar",
                           "message": "卖方 pro-forma RevPAR 不许用（v1.1 专项口径）"})
    # v1.3：负净值（成交价高于 as-is 评估值）不再单独否决，改风险旗＋补偿条件制（见风险维度）
    # 补偿条件（现金流/DSCR/储备金/退出预案）由对应否决项覆盖。
    for t in d.get("tranches", []):
        if t.get("rate_type") != "fixed":
            vetoes.append({"code": "floating_rate", "message": "浮动/可调利率否决：只做固定利率（Miao 亲定）"})
            break
        b = t.get("balloon_years")
        if b is not None and b < 5:
            vetoes.append({"code": "short_balloon",
                           "message": f"短期 balloon 否决：{b} 年内到期 balloon（Miao 亲定）"})
            break
    # P0-2（Phase 5）：退出 / due-on-sale 否决仅在 structure=subject_to 时参与 verdict；
    # 普通购买/贷款购买/其他结构下永不出现。单一"退出策略"输入即可解除对应否决。
    if d.get("structure") == "subject_to" and not d.get("exit_primary"):
        vetoes.append({"code": "no_exit",
                       "message": "无退出预案否决：subject-to 须先选定退出策略（出售/refi/转租购/持有收租）"})
    if d.get("structure") == "subject_to" and not (d.get("exit_backup") or d.get("due_on_sale_plan")):
        vetoes.append({"code": "no_dos_plan",
                       "message": "subject-to 无 due-on-sale 备用预案（须能 refi/出售/转租购三选一落地）"})
    if not d.get("phase1_clear", True):
        vetoes.append({"code": "environmental", "message": "环境红旗否决：Phase I 有未解决红旗"})
    if d.get("ti_lc_unfunded_over_12mo"):
        vetoes.append({"code": "ti_lc", "message": "TI/LC 否决：单个租约未摊销 TI/LC 超 12 个月租金且无资金覆盖"})
    walt = d.get("walt_years", 0)
    if walt < 2 and d.get("concentration_12mo_pct", 0) > 40:
        vetoes.append({"code": "rollover_cliff",
                       "message": "Rollover 悬崖否决：WALT<2 年且 12 个月内到期租金 >40%"})
    if d.get("noi_evidence") == "proforma":
        vetoes.append({"code": "proforma_noi", "message": "卖方 pro-forma NOI 无 rent roll/租约支撑"})
    # P0-1（Phase 5）：删除"卖方拒绝签 authorization to release"无条件一票否决——
    # 后端无输入源能证明"拒绝"，属幻觉式否决。改为 Zone 7 交割 checklist 的一项
    # （"交割前向卖方索取 authorization to release"，状态未验证），永不自动否决。
    if not d.get("zoning_ok", True):
        vetoes.append({"code": "zoning", "message": "Zoning 不合规且无 variance 路径"})
    if d.get("fraud_flag"):
        vetoes.append({"code": "fraud", "message": "要求虚假陈述/结构明显欺诈"})
    # v1.3 高价抛售退出软化（Miao 亲定 2026-09-28 晚）：不再单独否决；
    # 只有退出完全依赖短期高价抛售、且 refi/持有收租皆不成立时，才否决（无可行退出）。
    # 持有收租不成立的情形：DSCR 不达标（已有 low_dscr 否决）或扣储备/TI-LC 后现金流为负。
    if d.get("exit_flip_dependent_only"):
        hold_viable = (m["dscr"] is not None and m["dscr"] >= m["required_dscr"]
                       and m["net_cf_annual"] > 0)
        if not d.get("refi_cashout_viable", False) and not hold_viable:
            vetoes.append({"code": "no_viable_exit",
                           "message": "无可行退出否决：退出完全依赖短期高价抛售，且 refi/持有收租皆不成立"})
    dscr = m["dscr"]
    req = m["required_dscr"]
    if dscr is not None and dscr < req:
        # Phase 5 第二轮 item 3：无 rent roll 时 DSCR 算不出是"待接数据"不是 0.00——
        # 否决理由必须如实写"无 rent roll，DSCR 无法核保（待接数据）"，不许出现 0.00x 当硬数字
        if not d.get("has_rent_roll"):
            vetoes.append({"code": "low_dscr",
                           "message": "无 rent roll，DSCR 无法核保（待接数据）"})
        else:
            vetoes.append({"code": "low_dscr",
                           "message": f"DSCR {dscr:.2f} < {req:.2f}，直接否决不参与打分"
                                      + ("（酒店专项 ≥1.35）" if is_hotel else "")})
    return vetoes


def score(d: dict) -> dict:
    m = compute_metrics(d)
    vetoes = check_vetoes(d, m)
    dims = []
    asset = d.get("asset_class", "retail_strip")
    is_office = asset == "office"
    is_hotel = asset == "hotel"

    # --- v1.1 封顶降级（downgrades）：不是一票否决，但封顶等级 ---
    # 等级序：D < C < B < A
    downgrades = []
    if is_office and m["stressed_dscr"] is not None and m["stressed_dscr"] < 1.25:
        downgrades.append({"code": "office_rent_stress", "cap": "C",
                           "message": f"Office 租金下调 10% 压力测试 DSCR {m['stressed_dscr']:.2f} <1.25：最高降级为 C"})
    if d.get("is_value_add_vacant") and d.get("pre_lease_pct", 0) < 70:
        downgrades.append({"code": "value_add_prelease", "cap": "B",
                           "message": f"Value-add 预租率 {d.get('pre_lease_pct', 0):.0f}% <70%：最高 B 档"})
    if is_hotel and not d.get("low_season_covers_ds", False):
        downgrades.append({"code": "hotel_low_season", "cap": "B",
                           "message": "酒店淡季覆盖测试未通过（淡季月份现金流未覆盖当月 debt service）：最高 B 档"})

    # --- 维度1: NOI 与 DSCR 30 分 ---
    cap = (m["entry_cap"] or 0) * 100
    if cap >= 8.5:
        cap_pts = 20.0
    elif cap >= 7.5:
        cap_pts = 10 + 10 * (cap - 7.5)
    elif cap >= 6.5:
        cap_pts = 10 * (cap - 6.5)
    else:
        cap_pts = 0.0
    spread = m["spread_bps"] or 0
    spread_pts = 5.0 if spread >= 150 else (3.0 if spread >= 100 else 0.0)
    dscr = m["dscr"] or 0
    dscr_pts = 5.0 if dscr >= 1.35 else 3.0  # 低于 required_dscr 已否决（酒店 1.35 / 其余 1.25）
    noi_pts = cap_pts + spread_pts + dscr_pts
    dims.append({"key": "noi_dscr", "label": "NOI 与 DSCR", "weight": 30,
                 "points": round(noi_pts, 1),
                 "detail": f"入场 cap {cap:.2f}%（市场 {m['market_cap']*100:.2f}%），spread {spread:.0f}bps，DSCR {dscr:.2f}"})

    # --- 维度2: 租约质量 20 分 ---
    walt = d.get("walt_years", 0)
    if walt >= 5:
        walt_pts = 10.0
    elif walt >= 3:
        walt_pts = 4 + 6 * (walt - 3) / 2
    else:
        walt_pts = 0.0
    quality_pts = ((4.0 if d.get("all_nnn") else 0.0)
                   + (3.0 if d.get("concentration_12mo_pct", 100) <= 30 else 0.0)
                   + (3.0 if d.get("tenant_quality_ok") else 0.0))
    lease_pts = walt_pts + quality_pts
    dims.append({"key": "lease", "label": "租约质量", "weight": 20,
                 "points": round(lease_pts, 1),
                 "detail": f"WALT {walt:.1f} 年"
                           + ("，全 NNN" if d.get("all_nnn") else "")
                           + ("，有租金递增条款" if d.get("escalations_ok") else "")})

    # --- 维度3: 贷款/交易条款 15 分 ---
    terms = [t.get("term_years", 0) for t in d.get("tranches", [])]
    max_term = max(terms) if terms else 0
    if max_term >= 10:
        term_pts = 8.0
    elif max_term >= 7:
        term_pts = 6.0
    elif max_term >= 5:
        term_pts = 4.0
    else:
        term_pts = 0.0
    balloons = [t.get("balloon_years") for t in d.get("tranches", []) if t.get("balloon_years")]
    min_balloon = min(balloons) if balloons else None
    if min_balloon is None:
        balloon_pts = 4.0
    elif min_balloon >= 10:
        balloon_pts = 4.0
    elif min_balloon >= 7:
        balloon_pts = 3.0
    else:
        balloon_pts = 2.0  # 5-7 年；<5 已否决
    struct_bonus = 3.0 if d.get("structure") == "seller_financing" else 0.0
    loan_pts = clamp(term_pts + balloon_pts + struct_bonus, 0, 15)
    dims.append({"key": "loan_terms", "label": "贷款/交易条款", "weight": 15,
                 "points": round(loan_pts, 1),
                 "detail": f"最长剩余期限 {max_term:.0f} 年"
                           + (f"，最近 balloon {min_balloon:.0f} 年后" if min_balloon else "，无 balloon 压力")})

    # --- 维度4: 首付 10 分（v1.2 浮动制：基础分随首付比例递减＋现金流强度上浮最高 15 分）---
    dp = (m["down_pct"] or 0) * 100
    strength = clamp(dims[0]["points"] / 30, 0, 1)  # NOI/DSCR 维度得分率
    dp_score100, dp_base, dp_bonus = floating_down_payment_score(dp, strength)
    dp_pts = dp_score100 * 0.10
    dims.append({"key": "down_payment", "label": "首付比例", "weight": 10,
                 "points": round(dp_pts, 1),
                 "detail": f"现金首付 {dp:.1f}%（浮动制：基础 {dp_base:.0f} 分＋现金流强度上浮 {dp_bonus:.0f} 分；"
                           f"≤10% 为正常区间，deal 越好、可承受首付越高）"
                           + ("（>20% 不进日报，需 RE-0 特批）" if dp > 20 else "")})

    # --- 维度5: 市场基本面 10 分 ---
    market_pts = clamp(d.get("market_pop_employment", 0) + d.get("market_vacancy_trend", 0)
                       + d.get("market_rent_trend", 0) + d.get("market_landlord_friendly", 0), 0, 10)
    dims.append({"key": "market", "label": "市场基本面", "weight": 10,
                 "points": round(market_pts, 1),
                 "detail": "人口/就业/类别空置趋势/租金走势/房东友好度" if market_pts > 0 else "未评估（0 分，不编造）"})

    # --- 维度6: 风险逆向扣分 15 分 ---
    flags = list(d.get("risk_flags", []))
    need = 12 if d.get("is_value_add_vacant") else 6
    if d.get("reserves_months_ds", 0) < need and "low_reserves" not in flags:
        flags.append("low_reserves")
    if is_hotel and d.get("hotel_opex_annual", 0) <= 0 and "hotel_opex_missing" not in flags:
        flags.append("hotel_opex_missing")
    if is_hotel and not d.get("franchise_term_ok", True) and "franchise_term" not in flags:
        flags.append("franchise_term")
    if is_hotel and not d.get("low_season_covers_ds", False) and "low_season_gap" not in flags:
        flags.append("low_season_gap")
    if is_office and not d.get("ti_lc_itemized", False) and "ti_lc_not_itemized" not in flags:
        flags.append("ti_lc_not_itemized")
    # v1.3：负净值挂风险旗（不再单独否决）；退出含抛售成分挂风险旗（不再单独否决）
    if m["equity"] is not None and m["equity"] < 0 and "negative_equity" not in flags:
        flags.append("negative_equity")
    if d.get("exit_flip_dependent_only") and "exit_flip_dependent" not in flags:
        flags.append("exit_flip_dependent")
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
    # v1.1 封顶降级：downgrades 只降级不否决（等级序：D < C < B < A）
    if not vetoes and downgrades:
        order = {"D": 0, "C": 1, "B": 2, "A": 3}
        for dg in downgrades:
            if order.get(grade, 0) > order.get(dg["cap"], 0):
                grade = dg["cap"]

    req_dscr = m["required_dscr"]
    dscr_label = f"DSCR ≥{req_dscr:.2f}" + ("（酒店专项）" if is_hotel else "（A 档 ≥1.35）")
    checks = [
        {"label": "入场 cap ≥7.5%（A 档 ≥8.5%）", "ok": cap >= 7.5, "note": f"当前 {cap:.2f}%"},
        {"label": "spread ≥ 市场+100bps", "ok": spread >= 100, "note": f"当前 {spread:.0f}bps"},
        {"label": dscr_label, "ok": dscr >= req_dscr, "note": f"当前 {dscr:.2f}"},
        {"label": "月净现金流 ≥$1,000（A 档 ≥$2,000）", "ok": m["net_cf_monthly"] >= 1000,
         "note": f"当前 ${m['net_cf_monthly']:,.0f}/月"},
        {"label": "CoC ≥12%（A 档 ≥15%）", "ok": (m["cash_on_cash"] or 0) >= 0.12,
         "note": f"当前 {(m['cash_on_cash'] or 0)*100:.1f}%"},
        {"label": "WALT ≥3 年（A 档 ≥5 年；office ≥4 年）", "ok": walt >= (4 if is_office else 3),
         "note": f"当前 {walt:.1f} 年"},
        {"label": "储备金 ≥6 个月 debt service", "ok": d.get("reserves_months_ds", 0) >= need,
         "note": f"当前 {d.get('reserves_months_ds', 0):.1f} 个月（要求 ≥{need}）"},
        {"label": "净值（负净值挂风险旗，不再单独否决）", "ok": True,
         "note": (f"交割净值 ${m['equity']:,.0f}"
                  + ("（负净值入场风险旗：需现金流为正＋DSCR＋储备金＋可行退出同时成立）" if m["equity"] < 0 else ""))
                 if m["equity"] is not None else "未填评估值"},
        {"label": "全口径现金需求 cash-to-close（一级字段）", "ok": True,
         "note": f"${m['cash_to_close']:,.0f} = 首付＋交割费＋储备金＋首年 capex/TI-LC"
                 + ("＋PIP capex" if is_hotel and d.get("pip_capex", 0) else "")
                 + "；金额硬上限待确认"},
    ]
    if is_office:
        checks.append({"label": "Office 在租率 ≥80%", "ok": d.get("occupancy_pct", 0) >= 80,
                       "note": f"当前 {d.get('occupancy_pct', 0):.0f}%"})
        checks.append({"label": "Office 租金 -10% 压力测试 DSCR ≥1.25", "ok": (m["stressed_dscr"] or 0) >= 1.25,
                       "note": f"压力测试 DSCR {m['stressed_dscr']:.2f}" if m["stressed_dscr"] is not None else "未计算"})
    if is_hotel:
        checks.append({"label": "酒店 RevPAR 按孰低口径取值", "ok": d.get("revpar_source") != "proforma",
                       "note": "trailing 12m 与 3 年平均孰低" if d.get("revpar_source") != "proforma" else "pro-forma（否决）"})
        checks.append({"label": "酒店 FF&E ≥4% revenue", "ok": d.get("hotel_ff_e_pct", 4) >= 4,
                       "note": f"当前 {d.get('hotel_ff_e_pct', 4):.1f}%，年 ${m['ff_e_annual']:,.0f}"})
    if d.get("is_value_add_vacant"):
        checks.append({"label": "Value-add 预租率 ≥70%（进 A 档门禁）",
                       "ok": d.get("pre_lease_pct", 0) >= 70,
                       "note": f"当前 {d.get('pre_lease_pct', 0):.0f}%"})
    return {"total": total, "grade": grade, "dimensions": dims,
            "vetoes": vetoes, "downgrades": downgrades, "metrics": m, "checks": checks,
            "asset_label": ASSET_LABELS.get(d.get("asset_class"), ""),
            "structure_label": STRUCTURE_LABELS.get(d.get("structure"), "")}
