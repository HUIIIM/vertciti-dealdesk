"""机构级投委会备忘录 PDF（reportlab，A4 横向）。

章节：交易概要（关键指标 + 淘汰条件 + 事实要点）→ 租金表与到期分布 → 逐年现金流 → 资本结构、债务与退出 →
收益与 GP / LP 分配 → 敏感性（重跑引擎，不是线性外推）→ 主要假设 → 方法与局限。
所有数字来自 cre-1.0 引擎（与工作台、Excel 同一次测算）；缺数或无解渲染“—”，不编数。
"""
from __future__ import annotations

import copy
import io
from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from reportlab.lib.colors import Color, HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core import brand
from app.domain.v2.cre import engine
from app.domain.v2.cre.waterfall import describe as describe_waterfall
from app.services.render import pdf_uw
from app.services.render.cre_excel import month_label

JSON = dict[str, Any]
_ET = ZoneInfo("America/New_York")
PAGE = landscape(A4)
CW = PAGE[0] - 28 * mm  # 正文宽
MAX_YEARS = 10  # 现金流表最多列 10 年，更长的看 Excel

INK = HexColor(brand.INK)
MUTED = HexColor(brand.STONE)
GRID = HexColor(brand.LINE)
PANEL = HexColor(brand.MIST)
ACCENT = HexColor(brand.ORANGE_TEXT)
PAPER = HexColor(brand.PAPER)
GOOD, BAD, WARN = HexColor(brand.GREEN), HexColor(brand.RED), HexColor(brand.AMBER_TEXT)
BASE_BG = HexColor(brand.YELLOW_TINT)

RECOVERY = {"nnn": "NNN", "gross": "毛租", "base_year": "基年"}
KILL_STATE = {"triggered": ("触发", BAD), "ok": ("通过", GOOD), "unknown": ("无法判定", WARN)}


# ---------------------------------------------------------------- 格式化（缺数一律“—”）
def money(v: float | None) -> str:
    if v is None:
        return "—"
    return f"(${abs(v):,.0f})" if v < 0 else f"${v:,.0f}"


def pct(v: float | None, d: int = 2) -> str:
    return "—" if v is None else f"{v:.{d}f}%"


def mult(v: float | None) -> str:
    return "—" if v is None else f"{v:.2f}x"


def _p(text: str, size: float = 8.5, color: Color = INK, bold: bool = False, align: int = 0) -> Paragraph:
    font = pdf_uw.FONT
    body = pdf_uw._esc(text)
    return Paragraph(f"<b>{body}</b>" if bold else body,
                     ParagraphStyle(f"m{size}{bold}{align}{color}", fontName=font, fontSize=size, leading=size * 1.35,
                                    textColor=color, alignment=align))


def _num(text: str, bold: bool = False, color: Color = INK) -> Paragraph:
    return _p(text, 8, color, bold, align=2)


def _table(rows: list[list[Any]], widths: list[float], header: bool = True, bold_rows: tuple[int, ...] = (),
           extra: list[tuple[Any, ...]] | None = None) -> Table:
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style: list[tuple[Any, ...]] = [
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), INK), ("LINEBELOW", (0, 0), (-1, 0), 0, INK)]
    for r in bold_rows:
        style.append(("BACKGROUND", (0, r), (-1, r), PANEL))
    t.setStyle(TableStyle(style + (extra or [])))
    return t


def _hdr_row(labels: list[str], first_left: bool = True) -> list[Paragraph]:
    return [_p(x, 8, PAPER, True, 0 if (i == 0 and first_left) else 2) for i, x in enumerate(labels)]


def _h1(text: str) -> list[Any]:
    bar = Table([[_p(text, 12, INK, True)]], colWidths=[CW])
    bar.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 1.6, INK), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return [Spacer(1, 3 * mm), bar, Spacer(1, 2.5 * mm)]


def _note(text: str) -> Paragraph:
    return _p(text, 7.2, MUTED)


# ---------------------------------------------------------------- 事实计算（只用引擎输入与结果）
def _months_from_start(start: str, ym: str) -> int:
    return (int(ym[:4]) - int(start[:4])) * 12 + int(ym[5:7]) - int(start[5:7])


def walt_years(cre: JSON) -> float | None:
    """按面积加权的剩余租期（年），只算分析起点仍在租的已签约租约。"""
    s = cre["analysis_start"]
    live = [(lease["sf"], _months_from_start(s, lease["end"]) + 1) for lease in cre["leases"]
            if _months_from_start(s, lease["end"]) >= 0]
    total = sum(sf for sf, _ in live)
    return sum(sf * m for sf, m in live) / total / 12 if total else None


def expiry_schedule(cre: JSON) -> list[tuple[int, float]]:
    """持有期内每个分析年到期的已签约面积（SF）。"""
    s, n = cre["analysis_start"], cre["hold_years"]
    out = [0.0] * n
    for lease in cre["leases"]:
        m = _months_from_start(s, lease["end"])
        if 0 <= m < n * 12:
            out[m // 12] += lease["sf"]
    return list(enumerate(out, start=1))


def _is_mf(cre: JSON) -> bool:
    return bool(cre.get("property_type") == "multifamily")


def _facts_mf(cre: JSON, r: JSON) -> list[str]:
    m, a, mix = r["metrics"], r["annual"], cre["unit_mix"]
    units = sum(u["units"] for u in mix)
    in_place = sum(u["units"] * u["in_place_rent"] for u in mix) / units
    market = sum(u["units"] * u["market_rent"] for u in mix) / units
    reno = sum(u["renovate_units"] for u in mix)
    out = [f"{units} 户，每户价格 {money(cre['purchase_price'] / units)}；平均在租月租 {money(in_place)}、"
           f"市场月租 {money(market)}，在租低于市场 {(market - in_place) / market * 100:.1f}%（loss-to-lease）。",
           f"持有期平均出租率 {pct(m['avg_occupancy_pct'], 1)}（含空置率、翻新停用与不产生租金的户）。"]
    if reno:
        mf = cre["multifamily"]
        months = -(-reno // mf["reno_units_per_month"])
        out.append(f"翻新 {reno} 户（{reno / units * 100:.0f}%），持有期翻新支出 {money(m['capex_total'])}；"
                   f"从第 {mf['reno_start_month']} 月起每月 {mf['reno_units_per_month']} 户，约 {months} 个月完成，"
                   f"翻新后溢价合计第 {cre['hold_years']} 年 {money(a['premium'][cre['hold_years'] - 1])}。")
    noi = a["noi"]
    out.append(f"NOI 首年 {money(noi[0])}，退出年（第 {cre['hold_years'] + 1} 年）{money(noi[cre['hold_years']])}。")
    drag = exit_year_drag(cre, r)
    if drag:
        basis = "稳定化 NOI（已加回）" if cre["exit_noi_basis"] == "stabilized" else "该年 NOI（未加回）"
        out.append(f"退出年仍有翻新停用损失 {money(drag)}；售价按{basis}计。")
    return out


def _facts(cre: JSON, r: JSON) -> list[str]:
    if _is_mf(cre):
        return _facts_mf(cre, r)
    area, m = cre["area_sf"], r["metrics"]
    leased = sum(lease["sf"] for lease in cre["leases"] if _months_from_start(cre["analysis_start"], lease["end"]) >= 0)
    roll = sum(sf for _, sf in expiry_schedule(cre))
    w = walt_years(cre)
    biggest = max(cre["leases"], key=lambda x: x["sf"], default=None)
    out = [f"分析起点出租率 {leased / area * 100:.1f}%（{leased:,.0f} / {area:,.0f} SF）；"
           f"持有期平均出租率 {pct(m['avg_occupancy_pct'], 1)}。",
           f"WALT {w:.1f} 年；持有期内到期 {roll:,.0f} SF，占可租面积 {roll / area * 100:.1f}%。" if w is not None
           else "分析起点没有在租的已签约租约。",
           f"持有期 TI + LC 合计 {money(m['leasing_costs_total'])}（{m['leasing_costs_total'] / area:,.2f} $/SF）。"]
    if biggest is not None:
        out.append(f"最大租户 {biggest['tenant']}：{biggest['sf']:,.0f} SF，占 {biggest['sf'] / area * 100:.1f}%，"
                   f"到期 {biggest['end']}。")
    noi = r["annual"]["noi"]
    out.append(f"NOI 首年 {money(noi[0])}，退出年（第 {cre['hold_years'] + 1} 年）{money(noi[cre['hold_years']])}。")
    drag = exit_year_drag(cre, r)
    if drag and cre["exit_noi_basis"] == "stabilized":
        out.append(f"退出年有租约周转（周转空置 + 免租 {money(drag)}）；售价按稳定化 NOI "
                   f"{money(r['metrics']['forward_noi_stabilized'])} 计（未调整为 {money(r['metrics']['forward_noi_unadjusted'])}），"
                   "未扣买方承担的续租成本。")
    elif drag:
        out.append(f"注意：退出年有租约周转（周转空置 + 免租 {money(drag)}），按该年 NOI 定价会压低售价约 "
                   f"{money(drag / (cre['exit_cap_pct'] / 100))}；买方通常会就此议价，敏感性也会因此不单调。")
    return out


def exit_year_drag(cre: JSON, r: JSON) -> float:
    """退出年（第 N+1 年）周转空置与免租的合计损失（正数）；没有周转时为 0。一般空置已扣过周转空置，这里不再加回。"""
    a, n = r["annual"], cre["hold_years"]
    if _is_mf(cre):  # 多户公寓的优惠是常态，不算周转损失；只看翻新停用
        return -float(a["turnover_vacancy"][n])
    return -float(a["turnover_vacancy"][n] + a["free_rent"][n])


# ---------------------------------------------------------------- 敏感性：逐格重跑引擎
def _rerun(cre: JSON, edit: Callable[[JSON], None]) -> float | None:
    c = copy.deepcopy(cre)
    edit(c)
    try:
        v: float | None = engine.run(c)["metrics"]["levered_irr_pct"]
    except engine.CreInputError:
        return None
    return v


def _sensitivity_mf(cre: JSON, caps: list[float], rents: list[float]) -> dict[str, JSON]:
    g0, v0 = cre["multifamily"]["rent_growth_pct"], cre["general_vacancy_pct"]
    growth = sorted({g0 + d for d in (-2.0, -1.0, 0.0, 1.0, 2.0)})
    vacs = sorted({max(0.0, v0 + d) for d in (-2.0, 0.0, 2.0, 4.0)})
    base = [u["market_rent"] for u in cre["unit_mix"]]

    def cap_rent(cap: float, dr: float) -> Callable[[JSON], None]:
        def f(c: JSON) -> None:
            c["exit_cap_pct"] = cap
            for u, b in zip(c["unit_mix"], base, strict=True):
                u["market_rent"] = b * (1 + dr / 100)
        return f

    def growth_vac(g: float, v: float) -> Callable[[JSON], None]:
        def f(c: JSON) -> None:
            c["multifamily"]["rent_growth_pct"] = g
            c["general_vacancy_pct"] = v
        return f

    return {
        "cap_rent": {"rows": caps, "cols": rents,
                     "grid": [[_rerun(cre, cap_rent(cap, dr)) for dr in rents] for cap in caps]},
        "growth_vac": {"rows": growth, "cols": vacs,
                       "grid": [[_rerun(cre, growth_vac(g, v)) for v in vacs] for g in growth]},
    }


def sensitivity(cre: JSON) -> dict[str, JSON]:
    caps = [cre["exit_cap_pct"] + d for d in (-0.5, -0.25, 0.0, 0.25, 0.5)]
    rents = [-10.0, -5.0, 0.0, 5.0, 10.0]
    if _is_mf(cre):
        return _sensitivity_mf(cre, caps, rents)
    p0, d0 = cre["market"]["renewal_prob_pct"], cre["market"]["downtime_months"]
    renew = sorted({min(100.0, max(0.0, p0 + d)) for d in (-20.0, -10.0, 0.0, 10.0, 20.0)})
    downs = sorted({min(36.0, max(0.0, d0 + d)) for d in (-6.0, -3.0, 0.0, 3.0, 6.0)})
    base_rent = cre["market"]["rent_psf_yr"]

    def cap_rent(cap: float, dr: float) -> Callable[[JSON], None]:
        def f(c: JSON) -> None:
            c["exit_cap_pct"] = cap
            c["market"]["rent_psf_yr"] = base_rent * (1 + dr / 100)
        return f

    def renew_down(p: float, dt: float) -> Callable[[JSON], None]:
        def f(c: JSON) -> None:
            c["market"]["renewal_prob_pct"] = p
            c["market"]["downtime_months"] = dt
        return f

    return {
        "cap_rent": {"rows": caps, "cols": rents,
                     "grid": [[_rerun(cre, cap_rent(cap, dr)) for dr in rents] for cap in caps]},
        "renew_down": {"rows": renew, "cols": downs,
                       "grid": [[_rerun(cre, renew_down(p, dt)) for dt in downs] for p in renew]},
    }


def _grid(title: str, row_lbl: Callable[[float], str], col_lbl: Callable[[float], str], s: JSON,
          base: tuple[float, float], corner: str) -> list[Any]:
    rows = [[_p(corner, 7.5, PAPER, True), *[_p(col_lbl(c), 8, PAPER, True, 2) for c in s["cols"]]]]
    extra: list[tuple[Any, ...]] = []
    for i, (rv, line) in enumerate(zip(s["rows"], s["grid"], strict=True), start=1):
        rows.append([_p(row_lbl(rv), 8, INK, True), *[_num(pct(v)) for v in line]])
        for j, cv in enumerate(s["cols"], start=1):
            if abs(rv - base[0]) < 1e-9 and abs(cv - base[1]) < 1e-9:
                extra.append(("BACKGROUND", (j, i), (j, i), BASE_BG))
    w = (CW / 2 - 6 * mm)
    return [_p(title, 9, INK, True), Spacer(1, 1.5 * mm),
            _table(rows, [w * 0.28] + [w * 0.72 / len(s["cols"])] * len(s["cols"]), extra=extra)]


# ---------------------------------------------------------------- 各章节
def _cover(cre: JSON, r: JSON, meta: JSON, kill: JSON | None) -> list[Any]:
    m = r["metrics"]
    story: list[Any] = []
    brandbar = Table([[_p("vertciti · DealDesk", 9, PAPER, True), _p("机构级投委会备忘录", 9, PAPER, True, 2)]],
                     colWidths=[CW / 2, CW / 2])
    brandbar.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), INK), ("TOPPADDING", (0, 0), (-1, -1), 6),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                                  ("RIGHTPADDING", (0, 0), (-1, -1), 8)]))
    story += [brandbar, Spacer(1, 4 * mm), _p(meta.get("name") or "机构级交易", 20, INK, True),
              _p(meta.get("address") or "", 10, MUTED), Spacer(1, 1 * mm),
              _p(f"第 {meta.get('version_no', '—')} 版承销 · 引擎 {r['engine']} · {meta.get('date', '')}（美东）· "
                 f"分析起点 {cre['analysis_start']} · 持有 {cre['hold_years']} 年 · 可租面积 {cre['area_sf']:,.0f} SF",
                 8.5, MUTED)]
    story += _h1("一、交易概要")
    tiles = [
        ("收购价", money(cre["purchase_price"])), (("每户价格", money(m["price_per_unit"])) if _is_mf(cre) else
                                               ("单价 $/SF", f"${cre['purchase_price'] / cre['area_sf']:,.0f}")),
        ("进入资本化率", pct(m["going_in_cap_pct"])), ("成本收益率", pct(m["yield_on_cost_pct"])),
        ("无杠杆 IRR", pct(m["unlevered_irr_pct"])), ("有杠杆 IRR", pct(m["levered_irr_pct"])),
        ("有杠杆倍数", mult(m["levered_multiple"])), ("股权投入", money(m["equity"])),
        ("LTV", pct(m["ltv_pct"], 1)), ("债务收益率", pct(m["debt_yield_pct"])),
        ("最小 DSCR", mult(m["dscr_min"])), ("平均出租率", pct(m["avg_occupancy_pct"], 1)),
    ]
    cells = [[_p(lbl, 7.5, MUTED), _p(val, 13, INK, True)] for lbl, val in tiles]
    tw = CW / 6
    grid = Table([[c for c in cells[i:i + 6]] for i in (0, 6)], colWidths=[tw] * 6)
    grid.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, GRID), ("INNERGRID", (0, 0), (-1, -1), 0.6, GRID),
                              ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                              ("LEFTPADDING", (0, 0), (-1, -1), 7), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(grid)
    story.append(Spacer(1, 1.5 * mm))
    story.append(_note("IRR 为年度现金流口径；按月现金流年化：无杠杆 "
                       f"{pct(m['unlevered_irr_monthly_pct'])}、有杠杆 {pct(m['levered_irr_monthly_pct'])}。"
                       "DSCR 取持有期最差年（贷款条款看最差年）。"))
    left: list[Any] = [_p("淘汰条件", 9, INK, True), Spacer(1, 1.5 * mm)]
    rows = kill.get("items", []) if kill else []
    if rows:
        body = [[_p("条件", 8, PAPER, True), _p("当前", 8, PAPER, True, 2), _p("结果", 8, PAPER, True, 2)]]
        for k in rows:
            word, color = KILL_STATE[k["state"]]
            v = k["value"]
            body.append([_p(k["text"], 8), _num("—" if v is None else f"{v:,.2f}"), _num(word, True, color)])
        left.append(_table(body, [CW * 0.27, CW * 0.08, CW * 0.08]))
    else:
        left.append(_note("没有设置淘汰条件。"))
    right: list[Any] = [_p("事实要点", 9, INK, True), Spacer(1, 1.5 * mm)]
    right += [_p("· " + f, 8.5) for f in _facts(cre, r)]
    two = Table([[left, right]], colWidths=[CW * 0.45, CW * 0.55])
    two.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                             ("RIGHTPADDING", (0, 0), (0, 0), 6 * mm)]))
    story += [Spacer(1, 4 * mm), two]
    return story


def _unit_mix(cre: JSON) -> list[Any]:
    story = _h1("二、户型表与翻新计划")
    rows: list[list[Any]] = [_hdr_row(["户型", "户数", "户均面积 SF", "在租月租", "市场月租", "Loss-to-lease",
                                       "市场 $/SF/月", "翻新户数", "每户成本", "溢价 / 月"])]
    mix = cre["unit_mix"]
    for u in mix:
        psf = u["market_rent"] / u["avg_sf"] if u["avg_sf"] else None
        rows.append([_p(u["name"], 8, INK, True), _num(str(u["units"])), _num(f"{u['avg_sf']:,.0f}" if u["avg_sf"] else "—"),
                     _num(money(u["in_place_rent"])), _num(money(u["market_rent"])),
                     _num(f"{(u['market_rent'] - u['in_place_rent']) / u['market_rent'] * 100:.1f}%"),
                     _num("—" if psf is None else f"${psf:,.2f}"), _num(str(u["renovate_units"])),
                     _num(money(u["reno_cost_per_unit"])), _num(money(u["reno_premium"]))])
    n = sum(u["units"] for u in mix)
    ip = sum(u["units"] * u["in_place_rent"] for u in mix) / n
    mk = sum(u["units"] * u["market_rent"] for u in mix) / n
    rows.append([_p("合计 / 加权", 8, INK, True), _num(str(n), True), _num("—"), _num(money(ip), True), _num(money(mk), True),
                 _num(f"{(mk - ip) / mk * 100:.1f}%", True), _num("—"), _num(str(sum(u["renovate_units"] for u in mix)), True),
                 _num("—"), _num("—")])
    story.append(_table(rows, [CW * x for x in (0.13, 0.07, 0.1, 0.1, 0.1, 0.1, 0.1, 0.08, 0.11, 0.11)],
                        bold_rows=(len(rows) - 1,)))
    mf = cre["multifamily"]
    story += [Spacer(1, 1.5 * mm), _note(
        f"在租租约按 {mf['lease_term_months']} 个月租期均匀到期，到期即调到当月市场租金（loss-to-lease 逐步消化）。"
        f"翻新从交割后第 {mf['reno_start_month']} 月开始，每月 {mf['reno_units_per_month']} 户，每户停用 "
        f"{mf['reno_downtime_months']} 个月，复租按市场租金 + 溢价（溢价随市场租金增长）。不产生租金的户 {mf['non_revenue_units']} 户。")]
    return story


def _rent_roll(cre: JSON) -> list[Any]:
    if _is_mf(cre):
        return _unit_mix(cre)
    area = cre["area_sf"]
    story = _h1("二、租金表（已签约）与到期分布")
    head = _hdr_row(["租户", "单元", "面积 SF", "占比", "起租", "到期", "租金 $/SF/年", "年递增", "剩余免租月", "回收方式"])
    rows: list[list[Any]] = [head]
    for lease in sorted(cre["leases"], key=lambda x: x["end"]):
        rows.append([_p(lease["tenant"], 8), _p(lease["suite"] or "—", 8), _num(f"{lease['sf']:,.0f}"),
                     _num(f"{lease['sf'] / area * 100:.1f}%"), _num(lease["start"]), _num(lease["end"]),
                     _num(f"{lease['rent_psf_yr']:,.2f}"), _num(f"{lease['escalation_pct']:g}%"),
                     _num(str(lease["free_rent_months"])), _num(RECOVERY[lease["recovery"]])])
    leased = sum(lease["sf"] for lease in cre["leases"])
    if area - leased > 0.5:
        rows.append([_p("（空置）", 8, MUTED), _p("—", 8), _num(f"{area - leased:,.0f}"),
                     _num(f"{(area - leased) / area * 100:.1f}%"), _num("—"), _num("—"),
                     _num(f"市场 {cre['market']['rent_psf_yr']:,.2f}", color=MUTED), _num("—"), _num("—"), _num("—")])
    w = CW
    story.append(_table(rows, [w * x for x in (0.22, 0.07, 0.09, 0.07, 0.08, 0.08, 0.12, 0.08, 0.09, 0.10)]))
    wy = walt_years(cre)
    story += [Spacer(1, 1.5 * mm), _note(f"WALT（按面积加权剩余租期）：{'—' if wy is None else f'{wy:.1f} 年'}。"
                                         "空置面积在分析开始按新租招租（续租概率 0）。")]
    exp = expiry_schedule(cre)
    if exp:
        hdr = _hdr_row(["到期", *[f"第{y}年" for y, _ in exp]])
        cum, cums = 0.0, []
        for _, sf in exp:
            cum += sf
            cums.append(cum)
        sf_row = [_p("到期面积 SF", 8, INK, True), *[_num(f"{sf:,.0f}" if sf else "—") for _, sf in exp]]
        pct_row = [_p("占可租面积", 8), *[_num(f"{sf / area * 100:.1f}%" if sf else "—") for _, sf in exp]]
        cum_row = [_p("累计", 8), *[_num(f"{c / area * 100:.1f}%") for c in cums]]
        n = len(exp)
        story += [Spacer(1, 3 * mm), _p("持有期到期分布", 9, INK, True), Spacer(1, 1.5 * mm),
                  _table([hdr, sf_row, pct_row, cum_row], [CW * 0.16] + [CW * 0.84 / n] * n)]
    return story


_CF_LINES = [
    ("potential_rent", "潜在租金", False), ("turnover_vacancy", "周转空置", False), ("free_rent", "免租", False),
    ("recoveries", "费用回收", False), ("general_vacancy", "一般空置", False), ("credit_loss", "信用损失", False),
    ("egr", "有效总收入", True), ("opex", "运营费用", False), ("noi", "NOI", True), ("ti", "TI", False),
    ("lc", "LC", False), ("reserves", "资本储备", False), ("cf_before_debt", "债前现金流", True),
    ("debt_service", "还本付息", False), ("cf_after_debt", "债后现金流", True),
]


_CF_LINES_MF = [
    ("potential_rent", "潜在租金 GPR", False), ("loss_to_lease", "Loss-to-lease", False), ("premium", "翻新溢价", False),
    ("turnover_vacancy", "翻新停用", False), ("non_revenue", "不产生租金的户", False), ("base_rent", "在租租金", True),
    ("free_rent", "租金优惠", False), ("general_vacancy", "空置", False), ("credit_loss", "坏账", False),
    ("recoveries", "其他收入", False), ("egr", "有效总收入", True), ("opex", "运营费用", False), ("noi", "NOI", True),
    ("capex", "翻新支出", False), ("reserves", "资本储备", False), ("cf_before_debt", "债前现金流", True),
    ("debt_service", "还本付息", False), ("cf_after_debt", "债后现金流", True),
]


def _cash_flow(cre: JSON, r: JSON) -> list[Any]:
    n = min(cre["hold_years"], MAX_YEARS)
    a = r["annual"]
    story = _h1("三、逐年现金流（美元）")
    years = [f"第{y}年" for y in range(1, n + 1)]
    rows: list[list[Any]] = [_hdr_row(["科目", *years])]
    rows.append([_p("年度起始", 7.5, MUTED), *[_num(month_label(cre["analysis_start"], y * 12)) for y in range(n)]])
    bold: list[int] = []
    for key, label, is_bold in (_CF_LINES_MF if _is_mf(cre) else _CF_LINES):
        sign = -1 if key == "debt_service" else 1
        rows.append([_p(label, 8, INK, is_bold), *[_num(money(sign * a[key][y]), is_bold) for y in range(n)]])
        if is_bold:
            bold.append(len(rows) - 1)
    dscr = [a["noi"][y] / a["debt_service"][y] if a["debt_service"][y] else None for y in range(n)]
    rows.append([_p("DSCR", 8), *[_num(mult(v)) for v in dscr]])
    rows.append([_p("平均出租率", 8), *[_num(pct(a["occupancy_pct"][y], 1)) for y in range(n)]])
    story.append(_table(rows, [CW * 0.14] + [CW * 0.86 / n] * n, bold_rows=tuple(bold)))
    tail = "" if cre["hold_years"] <= MAX_YEARS else f"持有 {cre['hold_years']} 年，表中只列前 {MAX_YEARS} 年，完整见 Excel 模型。"
    story += [Spacer(1, 1.5 * mm),
              _note(("按户型逐月测算后按年汇总；括号为负数。在租租金 = GPR − loss-to-lease + 翻新溢价 − 翻新停用 − 不产生租金的户。"
                     if _is_mf(cre) else "物业层逐租约、按月测算后按年汇总；括号为负数。一般空置已扣除建模的周转空置。") + tail)]
    return story


def _capital(cre: JSON, r: JSON) -> list[Any]:
    m, ex = r["metrics"], r["exit"]
    story = _h1("四、资本结构、债务与退出")
    acq_close = cre["purchase_price"] * cre["closing_costs_pct"] / 100
    fee = m["equity"] - cre["purchase_price"] - acq_close + m["loan_amount"] + m["mezz_amount"]
    total = cre["purchase_price"] + acq_close + fee
    su = [_hdr_row(["资金来源与用途", "金额", "占比"])]
    for label, v in (("收购价", cre["purchase_price"]), ("交割成本", acq_close), ("贷款开办费", fee)):
        su.append([_p(label, 8), _num(money(v)), _num(f"{v / total * 100:.1f}%")])
    su.append([_p("用途合计", 8, INK, True), _num(money(total), True), _num("100.0%", True)])
    sources = [("优先贷款", m["loan_amount"]), *([("夹层", m["mezz_amount"])] if m["mezz_amount"] else []),
               ("股权", m["equity"])]
    for label, v in sources:
        su.append([_p(label, 8), _num(money(v)), _num(f"{v / total * 100:.1f}%")])
    left = [_table(su, [CW * 0.2, CW * 0.13, CW * 0.08], bold_rows=(4,))]

    d = cre.get("debt")
    terms: list[tuple[str, str]]
    if d:
        rate = (f"固定 {d['rate_pct']:g}%" if d["rate_type"] == "fixed" else
                f"浮动 SOFR + {d['spread_bps']:g}bp" + (f"，SOFR 上限 {d['cap_strike_pct']:g}%"
                                                       if d.get("cap_strike_pct") is not None else "，无利率上限"))
        terms = [("利率", rate), ("只付息", f"{d['io_months']} 个月"), ("摊还", f"{d['amort_years']} 年"),
                 ("开办费", f"{d['orig_fee_pct']:g}%"), ("LTV", pct(m["ltv_pct"], 1)),
                 ("首年 / 最小 DSCR", f"{mult(m['dscr_year1'])} / {mult(m['dscr_min'])}"),
                 ("债务收益率", pct(m["debt_yield_pct"])), ("退出时余额", money(ex["loan_payoff"]))]
        if d["rate_type"] == "floating":
            terms.insert(1, ("SOFR 曲线（逐年）", "、".join(f"{x:g}%" for x in d["sofr_curve_pct"])))
    else:
        terms = [("优先贷款", "无")] if cre.get("mezz") else [("贷款", "无（全股权）")]
    if cre.get("mezz"):
        terms += [("夹层", f"{money(m['mezz_amount'])}，固定 {cre['mezz']['rate_pct']:g}%，只付息"),
                  ("合计 LTV", pct(m["combined_ltv_pct"], 1)), ("优先贷款最小 DSCR", mult(m["dscr_senior_min"]))]
    dt = [_hdr_row(["贷款条款", ""])] + [[_p(k, 8), _num(v)] for k, v in terms]
    ext = [_hdr_row(["退出", ""]),
           [_p(f"退出年 NOI（第 {cre['hold_years'] + 1} 年{'，稳定化' if cre['exit_noi_basis'] == 'stabilized' else ''}）", 8),
            _num(money(m["forward_noi"]))],
           [_p("退出资本化率", 8), _num(pct(cre["exit_cap_pct"]))],
           [_p("售价", 8, INK, True), _num(money(ex["sale_price"]), True)],
           ([_p("每户售价", 8), _num(money(ex["sale_price"] / m["units"]))] if _is_mf(cre) else
            [_p("单价 $/SF", 8), _num(f"${ex['sale_price'] / cre['area_sf']:,.0f}")]),
           [_p(f"卖方成本（{cre['selling_costs_pct']:g}%）", 8), _num(money(-ex["selling_costs"]))],
           [_p("偿还贷款", 8), _num(money(-ex["loan_payoff"]))],
           [_p("股权净回款", 8, INK, True), _num(money(ex["net_proceeds_levered"]), True)]]
    three = Table([[left, _table(dt, [CW * 0.13, CW * 0.17]), _table(ext, [CW * 0.15, CW * 0.11])]],
                  colWidths=[CW * 0.41 + 4 * mm, CW * 0.30 + 4 * mm, CW * 0.26])
    three.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(three)
    refi = r.get("refinance")
    if refi:
        lim = "、".join(f"{_SIZED[k]} {money(v)}" for k, v in refi["limits"].items())
        rows = [_hdr_row(["再融资（第 {0} 月）".format(refi["month"]), ""]),
                [_p("届时 12 个月 NOI", 8), _num(money(refi["noi_12m"]))],
                [_p(f"估值（资本化率 {cre['refinance']['value_cap_pct']:g}%）", 8), _num(money(refi["value"]))],
                [_p("新贷款", 8, INK, True), _num(f"{money(refi['amount'])}（按{_SIZED[refi['sized_by']]}）", True)],
                [_p("偿还原贷款" + ("与夹层" if cre["refinance"]["repay_mezz"] and cre.get("mezz") else ""), 8),
                 _num(money(-refi["repaid"]))],
                [_p("再融资费用", 8), _num(money(-refi["costs"]))],
                [_p("股权净所得", 8, INK, True), _num(money(refi["net"]), True)]]
        story += [Spacer(1, 3 * mm), _table(rows, [CW * 0.2, CW * 0.2]),
                  Spacer(1, 1.5 * mm), _note(f"各限额：{lim}。取最小值。新贷款利率 {refi['rate_pct']:g}%。"
                                             + ("净所得为负：再融资需要股权补钱。" if refi["net"] < 0 else ""))]
    return story


_SIZED = {"ltv": "LTV", "dscr": "最低 DSCR", "debt_yield": "最低债务收益率"}


def _returns(cre: JSON, r: JSON) -> list[Any]:
    m, fl = r["metrics"], r["flows"]
    n = cre["hold_years"]
    story = _h1("五、收益与 GP / LP 分配")
    shown = min(n, MAX_YEARS)
    yrs = list(range(shown + 1))
    rows: list[list[Any]] = [_hdr_row(["现金流", *[f"第{y}年" for y in yrs]])]
    rows.append([_p("无杠杆", 8, INK, True), *[_num(money(fl["unlevered"][y])) for y in yrs]])
    rows.append([_p("有杠杆", 8, INK, True), *[_num(money(fl["levered"][y])) for y in yrs]])
    wf = r.get("waterfall")
    if wf:
        rows.append([_p("LP", 8), *[_num(money(wf["lp_annual"][y])) for y in yrs]])
        rows.append([_p("GP", 8), *[_num(money(wf["gp_annual"][y])) for y in yrs]])
    story.append(_table(rows, [CW * 0.1] + [CW * 0.9 / len(yrs)] * len(yrs)))
    if n > MAX_YEARS:
        story.append(_note(f"只列前 {MAX_YEARS} 年；最后一年含出售回款，完整见 Excel 模型。"))
    ret = [_hdr_row(["收益", "无杠杆", "有杠杆"]),
           [_p("IRR（年度）", 8), _num(pct(m["unlevered_irr_pct"])), _num(pct(m["levered_irr_pct"]), True)],
           [_p("IRR（按月年化）", 8), _num(pct(m["unlevered_irr_monthly_pct"])), _num(pct(m["levered_irr_monthly_pct"]))],
           [_p("权益倍数", 8), _num(mult(m["unlevered_multiple"])), _num(mult(m["levered_multiple"]))],
           [_p(f"NPV（折现率 {cre['discount_rate_pct']:g}%）", 8), _num(money(m["unlevered_npv"])),
            _num(money(m["levered_npv"]))],
           [_p("首年现金回报", 8), _num("—"), _num(pct(m["cash_on_cash_year1_pct"]))]]
    blocks: list[Any] = [_table(ret, [CW * 0.16, CW * 0.12, CW * 0.12])]
    if wf:
        w = cre["waterfall"]
        wrows = [_hdr_row(["分配瀑布", "LP", "GP"]),
                 [_p("IRR", 8), _num(pct(wf["lp_irr_pct"]), True), _num(pct(wf["gp_irr_pct"]), True)],
                 [_p("权益倍数", 8), _num(mult(wf["lp_multiple"])), _num(mult(wf["gp_multiple"]))],
                 [_p("GP promote", 8), _num("—"), _num(money(wf["gp_promote"]))],
                 *([[_p("回拨（clawback）", 8), _num("—"), _num(money(-wf["clawback"]))]] if wf["clawback"] else [])]
        blocks.append([_table(wrows, [CW * 0.14, CW * 0.11, CW * 0.11]), Spacer(1, 1.5 * mm),
                       _note(describe_waterfall(w))])
    else:
        blocks.append(_note("未设置分配瀑布。"))
    t = Table([blocks], colWidths=[CW * 0.42, CW * 0.58])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [Spacer(1, 3 * mm), t]
    return story


def _sensitivity(cre: JSON, sens: JSON) -> list[Any]:
    story = _h1("六、敏感性：有杠杆 IRR（每格重跑整套引擎）")
    if _is_mf(cre):
        return story + _sensitivity_mf_section(cre, sens)
    mk = cre["market"]
    a = _grid("退出资本化率 × 市场租金水平", lambda c: f"退出 {c:.2f}%", lambda d: f"租金 {d:+.0f}%",
              sens["cap_rent"], (cre["exit_cap_pct"], 0.0), "退出 cap ＼ 市场租金")
    b = _grid("续租概率 × 新租空置月数", lambda p: f"续租 {p:g}%", lambda dt: f"空置 {dt:g} 月",
              sens["renew_down"], (mk["renewal_prob_pct"], mk["downtime_months"]), "续租 ＼ 空置")
    t = Table([[a, b]], colWidths=[CW / 2, CW / 2])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [t, Spacer(1, 1.5 * mm),
              _note("黄底 = 基准假设。市场租金按分析起点水平整体上下浮动，影响续租 / 新租段与空置面积的租金，"
                    "不改已签约合同租金。空置月数会推移后续租约的到期时点：若到期落进或移出退出年，退出 NOI 与售价随之跳动，"
                    "IRR 可能不单调。“—”= 该组合下 IRR 无解。")]
    return story


def _sensitivity_mf_section(cre: JSON, sens: JSON) -> list[Any]:
    a = _grid("退出资本化率 × 市场租金水平", lambda c: f"退出 {c:.2f}%", lambda d: f"租金 {d:+.0f}%",
              sens["cap_rent"], (cre["exit_cap_pct"], 0.0), "退出 cap ＼ 市场租金")
    b = _grid("市场租金增长 × 空置率", lambda g: f"增长 {g:g}%", lambda v: f"空置 {v:g}%",
              sens["growth_vac"], (cre["multifamily"]["rent_growth_pct"], cre["general_vacancy_pct"]), "增长 ＼ 空置")
    t = Table([[a, b]], colWidths=[CW / 2, CW / 2])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    return [t, Spacer(1, 1.5 * mm), _note("黄底 = 基准假设。市场租金按分析起点水平整体上下浮动（各户型同比例），"
                                         "在租租约到期后才调到新市场租金。“—”= 该组合下 IRR 无解。")]


def _assumptions_mf(cre: JSON) -> list[Any]:
    mf, ox = cre["multifamily"], cre["opex"]
    story = _h1("七、主要假设")
    rev = [("市场租金增长", f"{mf['rent_growth_pct']:g}% / 年"), ("租期", f"{mf['lease_term_months']} 个月"),
           ("空置 / 坏账", f"{cre['general_vacancy_pct']:g}% / {cre['credit_loss_pct']:g}%"),
           ("租金优惠", f"{mf['concessions_pct']:g}%"), ("不产生租金的户", f"{mf['non_revenue_units']} 户"),
           ("其他收入", f"{money(mf['other_income_per_unit'])} /户/月，年增 {mf['other_income_growth_pct']:g}%"),
           ("翻新节奏", f"第 {mf['reno_start_month']} 月起每月 {mf['reno_units_per_month']} 户，停用 {mf['reno_downtime_months']} 个月")]
    op = [("运营费用", f"{money(mf['opex_per_unit_yr'])} /户/年"), ("房产税 / 保险", f"{money(mf['taxes_yr'])} / {money(mf['insurance_yr'])}"),
          ("换租 / 翻房", f"{mf['turnover_pct']:g}% / {money(mf['make_ready_per_turn'])} 每次"),
          ("费用年增", f"{ox['growth_pct']:g}%"), ("管理费", f"{ox['mgmt_fee_pct_egr']:g}% × 有效总收入"),
          ("资本储备", f"{money(mf['reserves_per_unit_yr'])} /户/年"),
          ("交割成本 / 卖方成本", f"{cre['closing_costs_pct']:g}% / {cre['selling_costs_pct']:g}%"),
          ("退出 NOI 口径", "稳定化" if cre["exit_noi_basis"] == "stabilized" else "第 N+1 年原值")]

    def block(title: str, items: list[tuple[str, str]]) -> Table:
        return _table([_hdr_row([title, ""])] + [[_p(k, 8), _num(v)] for k, v in items], [CW * 0.2, CW * 0.26])

    t = Table([[block("收入假设", rev), block("费用与其他", op)]], colWidths=[CW / 2, CW / 2])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(t)
    return story


def _assumptions(cre: JSON) -> list[Any]:
    if _is_mf(cre):
        return _assumptions_mf(cre)
    mk, ox = cre["market"], cre["opex"]
    story = _h1("七、主要假设")
    mla = [("市场租金", f"${mk['rent_psf_yr']:,.2f} /SF/年，年增 {mk['rent_growth_pct']:g}%"),
           ("续租概率", f"{mk['renewal_prob_pct']:g}%"), ("新租空置", f"{mk['downtime_months']:g} 个月"),
           ("免租（新 / 续）", f"{mk['free_rent_new_months']:g} / {mk['free_rent_renew_months']:g} 个月"),
           ("TI（新 / 续）", f"${mk['ti_new_psf']:g} / ${mk['ti_renew_psf']:g} /SF"),
           ("LC（新 / 续）", f"{mk['lc_new_pct']:g}% / {mk['lc_renew_pct']:g}%"),
           ("新租期 / 递增", f"{mk['lease_term_years']} 年 / {mk['escalation_pct']:g}%")]
    op = [("可回收费用", f"${ox['recoverable_psf_yr']:,.2f} /SF/年"),
          ("不可回收费用", f"${ox['non_recoverable_psf_yr']:,.2f} /SF/年"), ("费用年增", f"{ox['growth_pct']:g}%"),
          ("管理费", f"{ox['mgmt_fee_pct_egr']:g}% × 有效总收入"), ("资本储备", f"${ox['reserves_psf_yr']:,.2f} /SF/年"),
          ("一般空置 / 信用损失", f"{cre['general_vacancy_pct']:g}% / {cre['credit_loss_pct']:g}%"),
          ("交割成本 / 卖方成本", f"{cre['closing_costs_pct']:g}% / {cre['selling_costs_pct']:g}%"),
          ("退出 NOI 口径", "稳定化" if cre["exit_noi_basis"] == "stabilized" else "第 N+1 年原值")]

    def block(title: str, items: list[tuple[str, str]]) -> Table:
        return _table([_hdr_row([title, ""])] + [[_p(k, 8), _num(v)] for k, v in items], [CW * 0.2, CW * 0.26])

    t = Table([[block("市场租赁假设（MLA）", mla), block("费用与其他", op)]], colWidths=[CW / 2, CW / 2])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(t)
    return story


_METHOD = [
    "逐租约按月测算：已签约段到期后按市场租赁假设续上；续租与新租按续租概率加权成一条路径（Argus 默认口径）——"
    "空置月与免租月加权后取整，TI / LC 按金额加权。",
    "费用回收：NNN 按面积占比分摊可回收费用；毛租不回收；基年租约只回收超过基年的部分。免租只免基本租金。",
    "一般空置按潜在总收入计提，先扣除已建模的周转空置，不低于 0。管理费按有效总收入计、不回收。",
    "售价 = 第 N+1 年 NOI ÷ 退出资本化率，扣卖方成本（可选稳定化 NOI：加回该年周转空置与免租、按潜在收入重算一般空置）；贷款按退出当月余额偿清。浮动利率 = min(SOFR, 上限) + 利差。",
    "本版不建模：CPI 递增、百分比租金、费用上限 / gross-up、施工贷、开发期、按概率分叉的续租树、"
    "欧式（整只基金）瀑布。",
    "续上的租约段是假设，不是签约事实；本备忘录只基于录入的输入，不构成投资建议。",
]


_METHOD_MF = [
    "按户型逐月测算：潜在租金 GPR 按全部户的市场租金计；在租租约按租期均匀到期、到期即调到当月市场租金，"
    "两者之差为 loss-to-lease。市场租金按分析年阶梯增长，所以续约租金比市场滞后。",
    "翻新：按户型顺序、每月固定户数开工；停用期不收租（计翻新停用），复租按市场租金 + 溢价；翻新成本在开工当月计入 NOI 之下的资本支出。"
    "翻新后的户按当月租金计，不计续约滞后（简化）。",
    "空置、优惠按在租租金计；其他收入按在线户数 × (1 − 空置率) 计；坏账按收入合计计。管理费按有效总收入计。",
    "售价 = 第 N+1 年 NOI ÷ 退出资本化率，扣卖方成本（可选稳定化 NOI：加回退出年翻新停用损失）；贷款按退出当月余额偿清。",
    "本版不建模：按户逐份租约、续约涨幅上限、租金管制、短租、欧式（整只基金）瀑布、施工贷。",
    "本备忘录只基于录入的输入，不构成投资建议。",
]


def build_cre_memo(cre: JSON, r: JSON, meta: JSON, kill: JSON | None = None) -> bytes:
    """cre = 已校验的引擎输入（含默认值），r = engine.run(cre)，meta = {name, address, version_no, date}，kill = 淘汰条件判定。"""
    pdf_uw._register_fonts()
    meta = {**meta, "date": meta.get("date") or datetime.now(_ET).strftime("%Y-%m-%d")}
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=PAGE, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=11 * mm,
                            bottomMargin=13 * mm, title=f"IC Memo - {meta.get('name') or ''}",
                            author="DealDesk · vertciti")
    story: list[Any] = []
    story += _cover(cre, r, meta, kill)
    story.append(PageBreak())
    story += _rent_roll(cre)
    story.append(PageBreak())
    story += _cash_flow(cre, r)
    story += [KeepTogether(_capital(cre, r))]
    story.append(PageBreak())
    story += _returns(cre, r)
    story += [KeepTogether(_sensitivity(cre, sensitivity(cre)))]
    story.append(PageBreak())
    story += _assumptions(cre)
    story += _h1("八、方法与局限")
    story += [_p(f"{i}. {t}", 8.5) for i, t in enumerate(_METHOD_MF if _is_mf(cre) else _METHOD, start=1)]
    footer = f"{meta.get('name') or ''} · 机构级投委会备忘录 · 第 {meta.get('version_no', '—')} 版 · 机密"

    def deco(canvas: Any, d: Any) -> None:
        canvas.saveState()
        canvas.setFont(pdf_uw.FONT, 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(14 * mm, 7 * mm, footer)
        canvas.drawRightString(PAGE[0] - 14 * mm, 7 * mm, f"第 {d.page} 页")
        canvas.restoreState()

    doc.build(story, onFirstPage=deco, onLaterPages=deco)
    return buf.getvalue()
