"""商业核保 PDF 导出：双版本。

经典版（classic）：1:1 复刻 Manny Khoshbin 模板的三表版式
（PROPERTY OVERVIEW / Analysis / Cash Flow / Rent Roll），
Miao 一眼能认出来；数值全部由 DealDesk 引擎实时重算（已修
模板里的硬编码断链）。
增强版（enhanced）：DealDesk 新增指标版（DSCR/IRR/盈亏平衡/持有退出）。

输入：uw_commercial.compute_all() 的 result dict（即商业核保页
实时 state 计算后的结果，不依赖入库）。
"""

from __future__ import annotations

import io
import math
import os
from datetime import datetime
from zoneinfo import ZoneInfo

# Phase 5 第七轮 #6/#9（xiaobai/R8）：所有时间戳统一 America/New_York（美东时间）——
# 服务器在 UTC，datetime.now() 会印出"明天"的日期。
_ET = ZoneInfo("America/New_York")


def _now_et() -> str:
    return datetime.now(_ET).strftime("%Y-%m-%d %H:%M")

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

# ---------------------------------------------------------------- 字体
# 惰性注册：serverless 未打包字体时降级内置字体，保证不崩。
_FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
_FONT_READY = False
FONT = "WQY"


def _register_fonts() -> str:
    global _FONT_READY, FONT
    if not _FONT_READY:
        fp = os.path.join(_FONT_DIR, "WQY-MicroHei.ttf")
        if os.path.exists(fp):
            try:
                pdfmetrics.registerFont(TTFont("WQY", fp))
                FONT = "WQY"
            except Exception:
                FONT = "Helvetica"
        else:
            FONT = "Helvetica"
        _FONT_READY = True
    return FONT


# 经典版配色：贴近 Excel 的素色网格
INK = HexColor("#1a1a1a")
MUTED = HexColor("#595959")
GRID = HexColor("#bfbfbf")
HDR_BG = HexColor("#d9d9d9")
TITLE_BG = HexColor("#404040")
TITLE_FG = HexColor("#ffffff")

# 增强版配色：DealDesk 深色机构风
DK_BG = HexColor("#101418")
DK_PANEL = HexColor("#1a2027")
GOLD = HexColor("#e8a33d")
DK_GRID = HexColor("#2c343d")
DK_MUT = HexColor("#8a94a0")
WHITE = HexColor("#ffffff")


# ---------------------------------------------------------------- 假设标签
# Phase 5 第二轮 item 12：PDF/Excel 的"假设"区一律用中文标签，不许泄露英文内部字段名
_ASSUMP_LABELS = {
    "structure": "交易结构", "exitStrategy": "退出策略", "ask": "收购价/要价 $",
    "rent": "月租金 $", "rate": "年利率 %", "down": "首付 $", "vac": "空置率 %",
    "tax": "年房产税 $", "ins": "年保险 $", "loanBal": "承接贷款余额 $",
    "rentA": "年租金总收入 $", "downPct": "首付比例 %", "down_pct": "首付比例 %", "amort": "摊销年数",    "capMkt": "市场 cap %", "loanAmt": "拟贷款额 $",
    "price": "收购价 $", "monthly_rent": "月租金 $", "down_payment": "首付 $",
    "loan_balance": "贷款余额 $", "vacancy_pct": "空置率 %",
    "taxes_annual": "年房产税 $", "insurance_annual": "年保险 $",
    "exit_primary": "退出策略", "due_on_sale_plan": "due-on-sale 备用预案",
    "annual_base_rent": "年租金总收入 $", "market_cap_rate_pct": "市场 cap %",
    "vacant_sf": "空置面积 SF",  # Phase 5 第三轮：商业 Excel 富输入顶层标量，不许泄露英文 key
}
_ASSUMP_VALUE_LABELS = {
    "structure": {"standard": "普通购买", "new_loan": "贷款购买（新办贷款）",
                  "subject_to": "subject-to（承接现有贷款）"},
    # Phase 5 第三轮 A3/D10：英文内部值→中文（PDF/Excel 同源，不许泄露英文 key）
    "property_type": {"commercial": "商业", "residential": "住宅",
                      "office": "写字楼", "retail": "零售", "multifamily": "多户",
                      "industrial": "工业"},
}


# ---------------------------------------------------------------- 格式化
def _esc(t) -> str:
    return (str(t).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _bad(v) -> bool:
    """None / NaN / inf → 渲染为 --（诚实标注，不编造 0）。"""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return True
    return math.isnan(v) or math.isinf(v)


def _f(x, default=0.0) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    if math.isnan(v) or math.isinf(v):
        return default
    return v


def _money(v) -> str:
    if _bad(v):
        return "—"
    v = float(v)
    return f"(${abs(v):,.0f})" if v < 0 else f"${v:,.0f}"


def _pct(v, digits=2) -> str:
    if _bad(v):
        return "—"
    return f"{float(v) * 100:.{digits}f}%"


def _num(v) -> str:
    if _bad(v):
        return "—"
    return f"{float(v):,.0f}"


def _money2(v) -> str:
    if _bad(v):
        return "—"
    return f"${float(v):,.2f}"


def _comp_dup_key(c: dict) -> str:
    """Phase 5 第七轮 R10（remote）：重复 comps 检测键（同地址＋同成交日＋同价）。"""
    addr = " ".join(str(c.get("address") or "").lower().split())
    return f"{addr}|{c.get('sale_date') or ''}|{c.get('price') or 0}"


def _comp_dup_set(comps: list) -> set:
    counts = {}
    for c in (comps or []):
        k = _comp_dup_key(c)
        counts[k] = counts.get(k, 0) + 1
    return {k for k, n in counts.items() if n > 1}


def _p(text, size=9, color=INK, bold=False, align="left"):
    align_i = {"left": 0, "center": 1, "right": 2}[align]
    return Paragraph(
        f"<font face='{FONT}' size='{size}' color='{color}'>"
        f"{'<b>' if bold else ''}{_esc(text)}{'</b>' if bold else ''}</font>",
        ParagraphStyle(f"s{size}{color}{bold}{align}", alignment=align_i,
                       leading=size * 1.35, fontName=FONT, textColor=color,
                       fontSize=size),
    )


def _grid_table(data, col_widths, hdr_bg=HDR_BG):
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("BACKGROUND", (0, 0), (-1, 0), hdr_bg),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def _section_title(text, width):
    t = Table([[_p(text, 11, TITLE_FG, bold=True)]], colWidths=[width])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), TITLE_BG),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def _footer_canvas(page_text):
    def _draw(canvas, doc):
        canvas.saveState()
        canvas.setFont(FONT, 7)
        canvas.setFillColor(MUTED)
        canvas.drawCentredString(A4[0] / 2, 10 * mm, page_text)
        canvas.drawRightString(A4[0] - 14 * mm, 10 * mm, f"第 {doc.page} 页")
        canvas.restoreState()
    return _draw


# ============================================================ 经典版
def build_classic_pdf(r: dict) -> bytes:
    _register_fonts()
    prop = r.get("property", {})
    an = r.get("analysis", {})
    hist = r.get("historical", {})
    pro = r.get("proforma", {})
    rr = r.get("rent_roll", {})

    buf = io.BytesIO()
    W, _H = A4
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=12 * mm, bottomMargin=14 * mm,
                            title="Commercial Underwriting (Classic) - "
                                  f"{prop.get('name', '')}",
                            author="DealDesk · vertciti")
    cw = W - 28 * mm
    story = []
    now = _now_et()

    city_state = " ".join(x for x in [prop.get("city", ""),
                                      prop.get("state", "")] if x).strip()

    # ---- PROPERTY OVERVIEW（模板 row3-7 双栏） ----
    story.append(_section_title("PROPERTY OVERVIEW", cw))
    story.append(Spacer(1, 3 * mm))
    ov = [
        [_p("Property Name", 8.5, MUTED), _p(str(prop.get("name", "")), 8.5, INK, True),
         _p("Property Type", 8.5, MUTED), _p(str(prop.get("property_type", "")), 8.5, INK, True)],
        [_p("Address", 8.5, MUTED), _p(str(prop.get("address", "")), 8.5, INK),
         _p("Net Rentable Square Feet", 8.5, MUTED), _p(_num(prop.get("net_rentable_sf")), 8.5, INK)],
        [_p("City, State", 8.5, MUTED), _p(city_state, 8.5, INK),
         _p("Land Area (acres)", 8.5, MUTED), _p(str(prop.get("land_acres", "") or "—"), 8.5, INK)],
        [_p("County", 8.5, MUTED), _p(str(prop.get("county", "") or "—"), 8.5, INK),
         _p("# of Parking Spaces", 8.5, MUTED), _p(_num(prop.get("parking_spaces")), 8.5, INK)],
        [_p("Zip Code", 8.5, MUTED), _p(str(prop.get("zip", "")), 8.5, INK),
         _p("Parking Spaces / 1000 SF", 8.5, MUTED),
         _p(f"{float(prop.get('parking_per_1000sf') or 0):.2f}", 8.5, INK)],
    ]
    story.append(_grid_table(ov, [cw * 0.22, cw * 0.28, cw * 0.24, cw * 0.26]))
    story.append(Spacer(1, 5 * mm))

    # ---- Analysis：左 Source & Use，右 Returns（模板 B:C / E:F） ----
    story.append(_section_title("ANALYSIS", cw))
    story.append(Spacer(1, 3 * mm))

    def L(label, val):
        return [_p(label, 8.5, INK), _p(val, 8.5, INK, align="right")]

    left = [
        [_p("Source & Use of Proceeds:", 9, INK, True), _p("", 9)],
        L("Purchase price", _money(an.get("purchase_price"))),
        L("(+) Building Repairs", _money(an.get("building_repairs"))),
        L("(+) Capital Cost Reserve", _money(an.get("capital_reserve"))),
        L("(+) Lender Fees", _money(an.get("lender_fees"))),
        L("(+) Closing Costs", _money(an.get("closing_costs"))),
        L("Financed", _money(an.get("financed"))),
        L("Net liquidity needed", _money(an.get("net_liquidity"))),
        [_p("", 9), _p("", 9)],
        L("Loan bal.", _money(an.get("loan_bal"))),
        L("% Down", _pct(an.get("down_pct"))),
        L("Rate", _pct(an.get("rate"))),
        L("Annual payments", _money(an.get("annual_debt_service"))),
    ]
    right = [
        [_p("Returns:", 9, INK, True), _p("", 9)],
        L("Underwritten NOI", _money(an.get("inplace_noi"))),
        L("Capitalization Rate", _pct(an.get("inplace_cap"))),
        L("Projected NOI", _money(an.get("projected_noi"))),
        L("Market Cap rate", _pct(an.get("market_cap_rate"))),
        L("Projected Resale Value", _money(an.get("projected_resale"))),
        L("Acquisition fees", _money(an.get("acquisition_fees"))),
        L("Exit fees (4%)", _money(an.get("exit_fees"))),
        L("Net Gains before taxes", _money(an.get("net_gains"))),
        L("Return on investment %", _pct(an.get("roi"))),
        [_p("", 9), _p("", 9)],
        [_p("Cash Flow:", 9, INK, True), _p("Projected / In-place", 8, MUTED, align="right")],
        [_p("Net Cash flow", 8.5, INK),
         _p(f"{_money(an.get('projected', {}).get('net_cash_flow'))} / "
            f"{_money(an.get('inplace', {}).get('net_cash_flow'))}", 8.5, INK, align="right")],
        [_p("Cash on Cash return %", 8.5, INK),
         _p(f"{_pct(an.get('projected', {}).get('cash_on_cash'))} / "
            f"{_pct(an.get('inplace', {}).get('cash_on_cash'))}", 8.5, INK, align="right")],
    ]
    lt = Table(left, colWidths=[cw * 0.30, cw * 0.18])
    lt.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, GRID),
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]))
    rt = Table(right, colWidths=[cw * 0.30, cw * 0.20])
    rt.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, GRID),
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]))
    outer = Table([[lt, rt]], colWidths=[cw * 0.49, cw * 0.51])
    outer.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(outer)
    story.append(Spacer(1, 5 * mm))

    # ---- CASH FLOW（模板 Historical / Pro Forma 双栏） ----
    story.append(_section_title("HISTORICAL AND PRO-FORMA CASH FLOW", cw))
    story.append(Spacer(1, 3 * mm))

    def crow(label, hv, pv, bold=False):
        return [_p(label, 8.5, INK, bold), _p(_money(hv), 8.5, INK, bold, "right"),
                _p(_money(pv), 8.5, INK, bold, "right")]

    cf = [[_p("Revenue:", 9, INK, True), _p("HISTORICAL", 8.5, TITLE_FG, True, "right"),
           _p("PRO FORMA", 8.5, TITLE_FG, True, "right")]]
    for lbl, k in [("Base Rents", "base_rents"), ("CAM Recovery", "cam_recovery"),
                   ("Parking Income", "parking_income"), ("Other Income", "other_income")]:
        cf.append(crow(lbl, hist.get(k), pro.get(k)))
    cf.append(crow("Total Potential Income", hist.get("total_potential"), pro.get("total_potential"), True))
    cf.append(crow("Less: Vacancy/Collection Loss", hist.get("vacancy_loss"), pro.get("vacancy_loss")))
    cf.append(crow("Total Effective Gross Income", hist.get("egi"), pro.get("egi"), True))
    cf.append([_p("Expenses:", 9, INK, True), _p("", 9), _p("", 9)])
    exp_labels = {"service_contracts": "Service Contracts", "cam": "CAM",
                  "general_admin": "General & Admin", "repairs_maintenance": "Repairs & Maintenance",
                  "janitor": "Janitor", "security": "Security", "utilities": "Utilities",
                  "payroll": "Payroll", "management_fee": "Management Fee",
                  "property_tax": "Property Tax", "insurance": "Insurance",
                  "landscape": "Landscape"}
    for k, lbl in exp_labels.items():
        cf.append(crow(lbl, hist.get("expenses", {}).get(k), pro.get("expenses", {}).get(k)))
    cf.append(crow("Total Expenses", hist.get("total_expenses"), pro.get("total_expenses"), True))
    cf.append(crow("Net Operating Income", hist.get("noi"), pro.get("noi"), True))
    for lbl, k in [("Tenant Improvements", "tenant_improvements"),
                   ("Capital Expenditures", "capex"),
                   ("Leasing Commissions", "leasing_commissions")]:
        cf.append(crow(lbl, hist.get(k), pro.get(k)))
    cf.append(crow("Cash Flow Avail for Debt Serv.", hist.get("cash_flow_avail"),
                   pro.get("cash_flow_avail"), True))
    cf.append([_p("CAP Rate", 8.5, INK, True), _p(_pct(hist.get("cap_rate")), 8.5, INK, True, "right"),
               _p(_pct(pro.get("cap_rate")), 8.5, INK, True, "right")])

    cft = Table(cf, colWidths=[cw * 0.46, cw * 0.27, cw * 0.27])
    cft.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("BACKGROUND", (0, 0), (-1, 0), TITLE_BG),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(cft)

    # ---- RENT ROLL ----
    story.append(PageBreak())
    story.append(_section_title("RENT ROLL", cw))
    story.append(Spacer(1, 3 * mm))
    rh = [_p("Suite", 7.5, TITLE_FG, True, "center"), _p("Tenant", 7.5, TITLE_FG, True),
          _p("SF", 7.5, TITLE_FG, True, "right"), _p("Monthly Rent", 7.5, TITLE_FG, True, "right"),
          _p("Rent/SF/mo", 7.5, TITLE_FG, True, "right"), _p("Annual Rent", 7.5, TITLE_FG, True, "right"),
          _p("Rent/SF/yr", 7.5, TITLE_FG, True, "right"), _p("UW Annual", 7.5, TITLE_FG, True, "right"),
          _p("UW/SF", 7.5, TITLE_FG, True, "right"), _p("Mo. CAM", 7.5, TITLE_FG, True, "right"),
          _p("Mo. Park", 7.5, TITLE_FG, True, "right")]
    rrows = [rh]
    for t in rr.get("tenants", []):
        rrows.append([
            _p(str(t.get("suite", "")), 7.5, INK, align="center"),
            _p(str(t.get("tenant", "")), 7.5, INK),
            _p(_num(t.get("sf")), 7.5, INK, align="right"),
            _p(_money(t.get("monthly_rent")), 7.5, INK, align="right"),
            _p(_money2(t.get("monthly_per_sf")), 7.5, INK, align="right"),
            _p(_money(t.get("annual_rent")), 7.5, INK, align="right"),
            _p(_money2(t.get("annual_per_sf")), 7.5, INK, align="right"),
            _p(_money(t.get("underwritten_annual")), 7.5, INK, align="right"),
            _p(_money2(t.get("uw_per_sf")), 7.5, INK, align="right"),
            _p(_money(t.get("monthly_cam")), 7.5, INK, align="right"),
            _p(_money(t.get("monthly_parking")), 7.5, INK, align="right"),
        ])
    rrows.append([
        _p("TOTAL", 7.5, INK, True, "center"), _p("", 7.5),
        _p(_num(rr.get("total_sf_existing")), 7.5, INK, True, "right"),
        _p(_money(rr.get("total_monthly")), 7.5, INK, True, "right"),
        _p("", 7.5),
        _p(_money(rr.get("total_annual_lease")), 7.5, INK, True, "right"),
        _p("", 7.5),
        _p(_money(rr.get("total_annual_uw")), 7.5, INK, True, "right"),
        _p("", 7.5),
        _p(_money(rr.get("total_annual_cam")), 7.5, INK, True, "right"),
        _p(_money(rr.get("total_annual_parking")), 7.5, INK, True, "right"),
    ])
    rwt = [cw * 0.07, cw * 0.16, cw * 0.08, cw * 0.10, cw * 0.08, cw * 0.10,
           cw * 0.08, cw * 0.10, cw * 0.07, cw * 0.08, cw * 0.08]
    rt2 = Table(rrows, colWidths=rwt, repeatRows=1)
    rt2.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("BACKGROUND", (0, 0), (-1, 0), TITLE_BG),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(rt2)
    story.append(Spacer(1, 4 * mm))
    story.append(_p(f"Vacant SF: {_num(rr.get('vacant_sf'))}  |  "
                    f"Occupancy: {_pct(rr.get('occupancy'))}", 8, MUTED))

    doc.build(story,
              onFirstPage=_footer_canvas(f"DealDesk 生成 · {now}（美东时间） · 全部数字由引擎实时重算（非模板硬编码）"),
              onLaterPages=_footer_canvas("DealDesk · 商业核保经典版"))
    return buf.getvalue()


# ============================================================ 增强版
def build_enhanced_pdf(r: dict, deal: dict | None = None,
                       cover_tearsheet: bool = False) -> bytes:
    """商业核保增强版备忘录.

    P0-8：deal 传入时渲染当前 deal 真实数据（verdict/KPI/comps/假设），
    不再导出全零模板；deal 缺失时标题如实标注"数据未接入"。

    cover_tearsheet=True 时在正文前插入 Tear Sheet（一页纸）封面页
    （台账 2026-10-05：一键 Tear Sheet 进备忘录封面页）。
    """
    _register_fonts()
    deal = deal or {}
    # Phase 5 第三轮 A2：无 rent roll 时一切 RR 依赖指标一律"—（待 rent roll）"，
    # 不许印 0.00×（与网页 KPI 卡同口径）
    no_rr = not deal.get("has_rent_roll")
    rr_wait = "—（待 rent roll）"
    prop = r.get("property", {})
    an = r.get("analysis", {})
    pro = r.get("proforma", {})
    hist = r.get("historical", {})
    ex = an.get("exit", {})
    psf = r.get("per_sf", {})
    deal_name = deal.get("name") or deal.get("address") or prop.get("name") or ""
    deal_addr = deal.get("address") or prop.get("address") or ""

    buf = io.BytesIO()
    W, _H = A4
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=12 * mm, bottomMargin=14 * mm,
                            title="Commercial Underwriting (Enhanced) - "
                                  f"{prop.get('name', '')}",
                            author="DealDesk · vertciti")
    cw = W - 28 * mm
    story = []
    now = _now_et()

    # 一键 Tear Sheet 封面页（台账 2026-10-05）：备忘录 PDF 第一页即一页纸
    if cover_tearsheet:
        from app import tearsheet as _ts
        _ts_data = _ts.build_tearsheet_data(r, deal)
        story.extend(_ts.tearsheet_story(_ts_data, cw))
        story.append(PageBreak())

    def dp(text, size=9, color=WHITE, bold=False, align="left"):
        align_i = {"left": 0, "center": 1, "right": 2}[align]
        return Paragraph(
            f"<font face='{FONT}' size='{size}' color='{color}'>"
            f"{'<b>' if bold else ''}{_esc(text)}{'</b>' if bold else ''}</font>",
            ParagraphStyle(f"d{size}{color}{bold}{align}", alignment=align_i,
                           leading=size * 1.4, fontName=FONT, textColor=color,
                           fontSize=size),
        )

    # 顶栏：用 deal 真实地址/名称，不再"未命名物业"
    title_name = deal_name or "未命名物业"
    title_line = f"{title_name}  ·  商业·专业模式"
    if deal_addr and deal_addr != deal_name:
        title_line = f"{title_name}（{deal_addr}） · 商业·专业模式"
    story.append(_section_title(title_line, cw))
    story.append(Spacer(1, 3 * mm))

    # P0-8：结论区（verdict 真实数据）
    # Phase 5 第四轮 A1：否决态为独立第 4 状态——有否决时主词为"否决"（住宅）/
    # "VETO"（商业），红色；三档词只在无否决时使用。
    # （deal.verdict_word 由前端按同一规则生成，与网页 Zone 1 同源）
    v = deal.get("verdict") or {}
    if v.get("verdict"):
        story.append(_section_title("结论", cw))
        story.append(Spacer(1, 2 * mm))
        vword = str(deal.get("verdict_word") or v.get("verdict"))
        veto_n = int(deal.get("veto_count") or 0)
        vword_style = ParagraphStyle("vword", alignment=0, leading=15,
                                     fontName=FONT, textColor=GOLD, fontSize=11)
        if veto_n:
            # Phase 5 第四轮 A1：否决态主词红色＋"一票否决 ×N"徽标同行
            vword_para = Paragraph(
                f"<font face='{FONT}' size='11' color='#f87171'><b>{_esc(vword)}</b></font>"
                f"<font face='{FONT}' size='9' color='#f87171'><b>　"
                f"一票否决 ×{veto_n}</b></font>",
                vword_style)
        else:
            vword_para = dp(vword, 11, GOLD, True)
        vrows = [
            [dp("verdict", 8.5, DK_MUT, True), vword_para],
            [dp("一句话原因", 8.5, DK_MUT, True), dp(str(v.get("one_liner") or ""), 8.5, WHITE)],
        ]
        for reason in (v.get("reasons") or [])[:4]:
            vrows.append([dp("依据", 8.5, DK_MUT), dp("· " + str(reason), 8.5, WHITE)])
        # Phase 5 第二轮 item 7④：PDF 必须带 USPAP 用途限制声明（网页/Excel 都有，
        # PDF 正是会被转发的那份）
        vrows.append([dp("用途限制", 8.5, DK_MUT, True),
                      dp("投资筛选用，非 USPAP 合规评估报告，不能用于贷款/诉讼；"
                         "未实地勘察、未审阅租约原件。", 8.5, WHITE)])
        vt = Table(vrows, colWidths=[cw * 0.22, cw * 0.78])
        vt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), DK_PANEL),
                                ("GRID", (0, 0), (-1, -1), 0.5, DK_GRID),
                                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("TOPPADDING", (0, 0), (-1, -1), 4),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 6)]))
        story.append(vt)
        # Phase 5 第六轮微修复 #4（broker P1）：rent-roll 路径同一备忘录两个 DSCR
        #（一句话原因的在手·银行口径 vs 否决依据的打分口径）＋两个阈值
        #（1.0 生死线 vs 机构承销底线）无口径说明→加注。
        # verdict 文案本身不许改（红线），只加口径注。
        _dscr_bank_v = deal.get("dscr_trailing")
        _score_m = (deal.get("score") or {}).get("metrics") or {}
        _dscr_score_v = _score_m.get("dscr")
        if (_dscr_bank_v is not None and _dscr_score_v is not None
                and not _bad(_dscr_bank_v) and not _bad(_dscr_score_v)
                and abs(float(_dscr_bank_v) - float(_dscr_score_v)) > 0.005):
            _req_thr = _score_m.get("required_dscr") or 1.25
            story.append(Spacer(1, 2 * mm))
            story.append(dp(
                "注：本备忘录出现两个 DSCR（口径不同）：一句话原因引用在手·银行口径 DSCR "
                f"{float(_dscr_bank_v):.2f}×（rent roll 实测 NOI 经买方标准化调整 ÷ 年还贷），"
                "阈值 1.0 为生死线（<1.0 即贴钱持有）；否决依据引用打分口径 DSCR "
                f"{float(_dscr_score_v):.2f}×（评分模型 NOI，未做银行标准化调整），"
                f"阈值 {float(_req_thr):.2f} 为机构承销底线（低于即直接否决）。两个口径的分子不同，"
                "数字本来就不一样，不是笔误。", 7.5, DK_MUT))
        story.append(Spacer(1, 4 * mm))

        # P0-8：comps（真实选中 comps）
        comps = deal.get("comps") or []
        _dups = _comp_dup_set(comps)
        if comps:
            story.append(_section_title("可比成交 comps", cw))
            story.append(Spacer(1, 2 * mm))
            crows = [[dp("地址", 8.5, DK_MUT, True), dp("成交价", 8.5, DK_MUT, True, "right"),
                      dp("面积 SF", 8.5, DK_MUT, True, "right"), dp("$/SF", 8.5, DK_MUT, True, "right")]]
            for c in comps[:12]:
                _addr = str(c.get("address") or "")
                # Phase 5 第七轮 R10（remote）：重复抓取的 comps 标注"（重复）"
                if _comp_dup_key(c) in _dups:
                    _addr += "（重复）"
                crows.append([dp(_addr, 8, WHITE),
                          dp(_money(c.get("adjusted_price") or c.get("price")), 8, WHITE, False, "right"),
                          dp(f"{(c.get('sf') or 0):,.0f}", 8, WHITE, False, "right"),
                          dp(_money2(c.get("price_per_sf")), 8, WHITE, False, "right")])
            ct = Table(crows, colWidths=[cw * 0.46, cw * 0.2, cw * 0.17, cw * 0.17])
            ct.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), DK_PANEL),
                                    ("GRID", (0, 0), (-1, -1), 0.5, DK_GRID),
                                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                                    ("RIGHTPADDING", (0, 0), (-1, -1), 6)]))
            story.append(ct)
        # Phase 5 第五轮 C9（broker 必验 #4）：网页 Zone 1 的估值结论必须进备忘录——
        # 放贷人必看的一行。valuation_display 由前端 valuationDisplay() 同源传入。
        _val_disp = str(deal.get("valuation_display") or "").strip()
        if _val_disp and "待计算" not in _val_disp:
            story.append(Spacer(1, 2 * mm))
            story.append(dp(_val_disp, 9, GOLD, True))
        story.append(Spacer(1, 4 * mm))

    # P0-8：假设（真实输入假设）
    # Phase 5 第二轮 item 12：内部字段名一律换中文标签，不许泄露英文 key
    # Phase 5 第四轮 B2：关键假设栏必须列出所有实际使用的假设（含默认值，标"默认"）——
    # 用 deal.effective_assumptions（前端 effectiveAssumptions()＋后端补持有年数/退出 cap）；
    # 无该字段时回退旧口径（只列用户填过的）。
    _eff_assumps = deal.get("effective_assumptions") or []
    assumps = deal.get("assumptions") or {}
    if _eff_assumps or assumps:
        story.append(_section_title("关键假设", cw))
        story.append(Spacer(1, 2 * mm))
        arows = []
        # B2："*" 标记——凡用了默认假设算出的数字旁加"*"，注"按默认假设测算"
        _def_keys = {str(x.get("key")) for x in _eff_assumps if x.get("is_default")}
        if _eff_assumps:
            for x in _eff_assumps:
                _disp = str(x.get("display") or x.get("value"))
                if x.get("is_default") and "（默认）" not in _disp and "（联动" not in _disp:
                    _disp += "（默认）"
                arows.append([dp(str(x.get("label") or x.get("key")), 8.5, DK_MUT),
                              dp(_disp, 8.5, WHITE, False, "right")])
        else:
            for k, val in list(assumps.items())[:14]:
                label = _ASSUMP_LABELS.get(str(k), str(k))
                disp_val = _ASSUMP_VALUE_LABELS.get(str(k), {}).get(str(val), val)
                arows.append([dp(label, 8.5, DK_MUT),
                              dp(str(disp_val), 8.5, WHITE, False, "right")])
        at = Table(arows, colWidths=[cw * 0.55, cw * 0.45])
        at.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), DK_PANEL),
                                ("GRID", (0, 0), (-1, -1), 0.5, DK_GRID),
                                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                ("TOPPADDING", (0, 0), (-1, -1), 3),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 6)]))
        story.append(at)
        story.append(Spacer(1, 4 * mm))
    else:
        _def_keys = set()

    # KPI 横排（6 指标，每列上下结构；P0-8：未计算出的指标显示"—"，不许 $0 误导）
    # Phase 5 第二轮 item 7⑤：退出类指标（转售/净收益/ROI）无市场 cap 时无意义——
    # 直接显示"—"并注记，不许出现 ROI -333.33% 这类垃圾行
    def _m0(x):
        return "—" if _bad(x) or not x else _money(x)
    resale_ok = _f(an.get("projected_resale")) > 0
    kpis = [
        ("预测转售价值", _m0(an.get("projected_resale"))),
        ("税前净收益", _money(an.get("net_gains")) if resale_ok else "—"),
        ("投资回报 ROI", _pct(an.get("roi")) if resale_ok else "—"),
        # Phase 5 第三轮 A2（remote R3）：退出 IRR/股本倍数同样依赖市场 cap 证据，
        # 缺失时显示"—"（此前 ROI 改了这两处漏网，印 0.00%）
        ("退出 IRR", _pct(ex.get("irr")) if resale_ok else "—"),
        ("股本倍数", ("—" if _bad(ex.get("equity_multiple"))
         else f"{float(ex.get('equity_multiple')):.2f}×") if resale_ok else "—"),
        ("预测净现金流/年", _m0(an.get("projected", {}).get("net_cash_flow"))),
    ]
    kflat = []
    for k, v in kpis:
        inner = Table([[dp(k, 8, DK_MUT, align="center")],
                       [dp(v, 13, GOLD, True, "center")]],
                      colWidths=[cw / 6 - 2])
        inner.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"),
                                   ("TOPPADDING", (0, 0), (-1, -1), 3),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        kflat.append(inner)
    kt = Table([kflat], colWidths=[cw / 6] * 6)
    kt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), DK_PANEL),
        ("GRID", (0, 0), (-1, -1), 0.5, DK_GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(kt)
    story.append(Spacer(1, 2 * mm))
    if not resale_ok:
        story.append(dp("注：退出类指标需市场 cap 证据；缺失时显示'—'，不编造。", 7.5, DK_MUT))
        story.append(Spacer(1, 2 * mm))
    else:
        story.append(Spacer(1, 2 * mm))

    def drow(label, hv, pv, bold=False):
        return [dp(label, 8.5, DK_MUT, bold),
                dp(hv, 8.5, WHITE, bold, "right"),
                dp(pv, 8.5, WHITE, bold, "right")]

    # 现金流对比
    story.append(_section_title("现金流（历史 / 预测）", cw))
    story.append(Spacer(1, 2 * mm))
    cf = [[dp("项目", 8.5, DK_MUT, True), dp("历史", 8.5, DK_MUT, True, "right"),
           dp("预测", 8.5, DK_MUT, True, "right")]]

    def _expense_money(v):
        # Phase 5 第二轮 item 7③：费用 $0 必须标注"待接/未填"，不许零披露
        if _bad(v) or not _f(v):
            return "$0（待接/未填）"
        return _money(v)

    # Phase 5 第三轮 A2（remote R3）：历史列 $0 同样标注"待接/未填"——
    # 无 rent roll 时历史现金流根本没数，不许裸 $0
    # Phase 5 第六轮微修复 #3（remote N3）：预测列同样——无数据时预测列 5 行裸 $0，
    # 与历史列口径对齐，缺数即"$0（待接/未填）"
    for lbl, k, hfmt, pfmt in [
            ("基础租金", "base_rents", _expense_money, _expense_money),
            ("有效总收入 EGI", "egi", _expense_money, _expense_money),
            ("总费用", "total_expenses", _expense_money, _expense_money),
            ("NOI", "noi", _expense_money, _expense_money),
            ("可用于还贷现金流", "cash_flow_avail", _expense_money, _expense_money),
            ("CAP 率", "cap_rate", None, _pct)]:
        hv = rr_wait if (k == "cap_rate" and no_rr) else (
            hfmt(hist.get(k)) if hfmt else _pct(hist.get(k)))
        # Phase 5 第四轮 B4：预测 CAP 率无数据时显示"—"，不许"0.00%"
        pv = ("—" if (k == "cap_rate" and (_bad(pro.get(k)) or not _f(pro.get(k))))
              else pfmt(pro.get(k)))
        cf.append(drow(lbl, hv, pv, lbl == "NOI"))
    cft = Table(cf, colWidths=[cw * 0.4, cw * 0.3, cw * 0.3])
    cft.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), DK_PANEL),
                             ("GRID", (0, 0), (-1, -1), 0.5, DK_GRID),
                             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                             ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]))
    story.append(cft)
    story.append(Spacer(1, 4 * mm))

    # 新增风险指标
    story.append(_section_title("新增风险指标", cw))
    story.append(Spacer(1, 2 * mm))

    def _dscr(v) -> str:
        return "—" if _bad(v) else f"{float(v):.2f}×"

    # Phase 5 第二轮 item 6：三端统一用银行口径 NOI——PDF 的 DSCR（在手）必须与网页
    # KPI 卡（compute-plus trailing，银行口径）同数；前端经 deal.dscr_trailing 传入，
    # 缺失时（无 rent roll）诚实显示"—"，不许拿现金流口径硬凑
    _dscr_bank = deal.get("dscr_trailing")
    # Phase 5 第六轮微修复 #5（broker P1）：proforma 路径 verdict 引用打分口径 DSCR
    #（如 0.82），但备忘录风险指标区显示"—（待 rent roll）"→备忘录也显示该数并注口径。
    # verdict 文案不许改（红线）。只有打分口径 DSCR 为真实正数时才显示，
    # 0/None 仍为"—（待 rent roll）"（缺数不是实数）。
    _score_m5 = (deal.get("score") or {}).get("metrics") or {}
    _dscr_score5 = _score_m5.get("dscr")
    if _dscr_bank is not None and not _bad(_dscr_bank):
        _dscr_inhand_row = ("DSCR（在手·银行口径）", _dscr(_dscr_bank))
    elif (_dscr_score5 is not None and not _bad(_dscr_score5)
          and float(_dscr_score5) > 0):
        _dscr_inhand_row = ("DSCR（打分口径·预测）", _dscr(_dscr_score5))
    else:
        _dscr_inhand_row = ("DSCR（在手·银行口径）", "—（待 rent roll）")
    # Phase 5 第四轮 B2："*" 标记——用了默认假设算出的数字旁加"*"，注"按默认假设测算"
    def _star(keys):
        return "*" if _def_keys & set(keys) else ""
    # Phase 5 第四轮 B4：退出 Cap 率默认值加"默认"标记（来源见关键假设栏）
    _exit_cap_item = next((x for x in _eff_assumps if str(x.get("key")) == "exit_cap_rate"), None)
    _exit_cap_disp = (str(_exit_cap_item.get("display")) if _exit_cap_item
                      else _pct(ex.get("exit_cap_rate")))
    # Phase 5 第五轮 A1（remote R1）：NOI $/SF 是 NOI 的衍生数——NOI 本身为
    # $0（待接/未填）时不许裸印 $0.00，与 NOI 行同注"—"
    _sf_known = _f((r.get("property") or {}).get("net_rentable_sf")) > 0
    _noi_psf_known = _sf_known and bool(_f(psf.get("noi_per_sf")))
    newm = [
        ("DSCR（预测）", rr_wait if no_rr else _dscr(an.get("projected", {}).get("dscr"))),
        _dscr_inhand_row,
        ("盈亏平衡出租率", rr_wait if no_rr else _pct(an.get("breakeven_occupancy"))),
        ("持有年数", str(ex.get("hold_years", ""))),
        ("退出 Cap 率", _exit_cap_disp),
        ("年还贷额", _money(an.get("annual_debt_service")) + _star({"rate", "downPct", "amort"})),
        ("自有资金", _money(an.get("net_liquidity")) + _star({"downPct"})),
        ("贷款余额", _money(an.get("loan_bal")) + _star({"downPct"})),
        ("单价 $/SF", _money2(psf.get("price_per_sf")) if _sf_known else "—"),
        ("NOI $/SF", _money2(psf.get("noi_per_sf")) if _noi_psf_known else "—"),
    ]
    nrows = []
    for i in range(0, len(newm), 2):
        row = []
        for k, v in newm[i:i + 2]:
            row += [dp(k, 8.5, DK_MUT), dp(v, 8.5, WHITE, True, "right")]
        nrows.append(row)
    nt = Table(nrows, colWidths=[cw * 0.28, cw * 0.22, cw * 0.28, cw * 0.22])
    nt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), DK_PANEL),
                            ("GRID", (0, 0), (-1, -1), 0.5, DK_GRID),
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]))
    story.append(nt)
    if _def_keys:
        story.append(Spacer(1, 2 * mm))
        story.append(dp("注：标 * 的数字按默认假设测算（假设取值见上方关键假设栏）。", 7.5, DK_MUT))
    story.append(Spacer(1, 4 * mm))

    # 持有期现金流（退出分析）
    story.append(_section_title("持有期现金流与退出", cw))
    story.append(Spacer(1, 2 * mm))
    flows = ex.get("cash_flows", []) or []
    ef = [[dp("年份", 8.5, DK_MUT, True), dp("年度现金流", 8.5, DK_MUT, True, "right"),
           dp("备注", 8.5, DK_MUT, True)]]
    shown = flows[: ex.get("hold_years", 0) + 2]
    for i, f in enumerate(shown):
        # Phase 5 第四轮 B3：退出净所得为"—"（resale_ok 假）时不许写"含退出净所得"
        note = ("初始投入" if i == 0
                else (("含退出净所得" if resale_ok else "不含退出（退出假设缺失）")
                      if i == len(shown) - 1 else ""))
        # Phase 5 第五轮 A3（remote R3）：第 5 年 = 年还贷＋退出剩余贷款（无退出时），
        # 两个组分（$48,210* / $538,845*）都有星，合计行同样标"*"
        _y5_star = (_star({"rate", "downPct", "amort", "hold_years"})
                    if (i == len(shown) - 1 and i > 0) else "")
        ef.append(drow(f"第 {i} 年", _money(f) + _y5_star, note))
    exit_rows = [
        # Phase 5 第三轮 A2（remote R3）：无市场 cap 证据时退出售价/净所得不许
        # 拿 $0 退出价硬算——显示"—"，与 KPI 条脚注"缺失时显示'—'，不编造"一致
        drow("退出售价", _money(ex.get("sale_price")) if resale_ok else "—", ""),
        # Phase 5 第四轮 B2：退出剩余贷款由默认假设算出时同样标"*"
        drow("退出剩余贷款",
             _money(ex.get("remaining_loan")) + _star({"rate", "amort", "hold_years"}), ""),
        drow("退出净所得", _money(ex.get("sale_proceeds")) if resale_ok else "—", ""),
        drow("股本倍数", ("—" if _bad(ex.get("equity_multiple"))
             else f"{float(ex.get('equity_multiple')):.2f}×") if resale_ok else "—", ""),
        drow("退出 IRR", _pct(ex.get("irr")) if resale_ok else "—", ""),
    ]
    eft = Table(ef + exit_rows, colWidths=[cw * 0.2, cw * 0.35, cw * 0.45])
    eft.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), DK_PANEL),
                             ("GRID", (0, 0), (-1, -1), 0.5, DK_GRID),
                             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                             ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]))
    story.append(eft)
    # Phase 5 第五轮 C8（broker 必验 #3）：同一备忘录两个卖价必须有口径脚注——
    # 预测转售价值 = 当期预测 NOI ÷ 市场 cap（当期口径）；
    # 退出售价 = 持有期末 NOI ÷ 退出 cap（期末口径）。两者口径不同，放贷人不许混用。
    story.append(Spacer(1, 2 * mm))
    story.append(dp("注：预测转售价值 = 当期预测 NOI ÷ 市场 cap（当期口径）；"
                    "退出售价 = 持有期末 NOI ÷ 退出 cap（期末口径）——"
                    "两个口径不同，不是同一个数字。",
                    7.5, DK_MUT))
    story.append(Spacer(1, 6 * mm))
    # "商业核保"是旧版命名残留，新线叫"商业·专业模式"（panel2 remote #11）
    story.append(dp(f"DealDesk 生成 · {now}（美东时间） · 数据来自商业·专业模式实时计算", 7.5, DK_MUT, align="center"))

    # 深色底
    def _bg(canvas, doc):
        canvas.saveState()
        # Tear Sheet 封面页（第 1 页）用白底：浅色一页纸版式在深底上不可读
        if cover_tearsheet and getattr(doc, "page", 0) == 1:
            canvas.setFillColor(WHITE)
        else:
            canvas.setFillColor(DK_BG)
        canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
        canvas.restoreState()

    doc.build(story, onFirstPage=_bg, onLaterPages=_bg)
    return buf.getvalue()


# ---------------------------------------------------------------- 统一入口
def build_uw_pdf(r: dict, variant: str = "classic", deal: dict | None = None,
                 cover_tearsheet: bool = False) -> bytes:
    """r = compute_all() 结果；variant ∈ {classic, enhanced}。

    deal（可选）：当前 deal 真实数据 {name/address/verdict/score/comps/assumptions}，
    enhanced 版用它渲染结论＋comps＋假设（P0-8），不再导出全零模板。
    cover_tearsheet：enhanced 版前插 Tear Sheet 封面页（备忘录 PDF 专用）。
    """
    _register_fonts()
    if variant == "enhanced":
        return build_enhanced_pdf(r, deal=deal, cover_tearsheet=cover_tearsheet)
    return build_classic_pdf(r)
