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


def _money(v) -> str:
    if _bad(v):
        return "--"
    v = float(v)
    return f"(${abs(v):,.0f})" if v < 0 else f"${v:,.0f}"


def _pct(v, digits=2) -> str:
    if _bad(v):
        return "--"
    return f"{float(v) * 100:.{digits}f}%"


def _num(v) -> str:
    if _bad(v):
        return "--"
    return f"{float(v):,.0f}"


def _money2(v) -> str:
    if _bad(v):
        return "--"
    return f"${float(v):,.2f}"


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
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

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
         _p("Land Area (acres)", 8.5, MUTED), _p(str(prop.get("land_acres", "") or "--"), 8.5, INK)],
        [_p("County", 8.5, MUTED), _p(str(prop.get("county", "") or "--"), 8.5, INK),
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
              onFirstPage=_footer_canvas(f"DealDesk 生成 · {now} · 全部数字由引擎实时重算（非模板硬编码）"),
              onLaterPages=_footer_canvas("DealDesk · 商业核保经典版"))
    return buf.getvalue()


# ============================================================ 增强版
def build_enhanced_pdf(r: dict) -> bytes:
    _register_fonts()
    prop = r.get("property", {})
    an = r.get("analysis", {})
    pro = r.get("proforma", {})
    hist = r.get("historical", {})
    ex = an.get("exit", {})
    psf = r.get("per_sf", {})

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
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    def dp(text, size=9, color=WHITE, bold=False, align="left"):
        align_i = {"left": 0, "center": 1, "right": 2}[align]
        return Paragraph(
            f"<font face='{FONT}' size='{size}' color='{color}'>"
            f"{'<b>' if bold else ''}{_esc(text)}{'</b>' if bold else ''}</font>",
            ParagraphStyle(f"d{size}{color}{bold}{align}", alignment=align_i,
                           leading=size * 1.4, fontName=FONT, textColor=color,
                           fontSize=size),
        )

    # 顶栏
    story.append(_section_title(
        f"{prop.get('name', '') or '未命名物业'}  ·  商业核保增强版", cw))
    story.append(Spacer(1, 3 * mm))

    # KPI 横排（6 指标，每列上下结构）
    kpis = [
        ("预测转售价值", _money(an.get("projected_resale"))),
        ("税前净收益", _money(an.get("net_gains"))),
        ("投资回报 ROI", _pct(an.get("roi"))),
        ("退出 IRR", _pct(ex.get("irr"))),
        ("股本倍数", "--" if _bad(ex.get("equity_multiple"))
         else f"{float(ex.get('equity_multiple')):.2f}×"),
        ("预测净现金流/年", _money(an.get("projected", {}).get("net_cash_flow"))),
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
    story.append(Spacer(1, 4 * mm))

    def drow(label, hv, pv, bold=False):
        return [dp(label, 8.5, DK_MUT, bold),
                dp(hv, 8.5, WHITE, bold, "right"),
                dp(pv, 8.5, WHITE, bold, "right")]

    # 现金流对比
    story.append(_section_title("现金流（历史 / 预测）", cw))
    story.append(Spacer(1, 2 * mm))
    cf = [[dp("项目", 8.5, DK_MUT, True), dp("历史", 8.5, DK_MUT, True, "right"),
           dp("预测", 8.5, DK_MUT, True, "right")]]
    for lbl, k, fmt in [("基础租金", "base_rents", _money), ("有效总收入 EGI", "egi", _money),
                        ("总费用", "total_expenses", _money), ("NOI", "noi", _money),
                        ("可用于还贷现金流", "cash_flow_avail", _money),
                        ("CAP 率", "cap_rate", _pct)]:
        cf.append(drow(lbl, fmt(hist.get(k)), fmt(pro.get(k)), lbl == "NOI"))
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
        return "--" if _bad(v) else f"{float(v):.2f}×"

    newm = [
        ("DSCR（预测）", _dscr(an.get("projected", {}).get("dscr"))),
        ("DSCR（在手）", _dscr(an.get("inplace", {}).get("dscr"))),
        ("盈亏平衡出租率", _pct(an.get("breakeven_occupancy"))),
        ("持有年数", str(ex.get("hold_years", ""))),
        ("退出 Cap 率", _pct(ex.get("exit_cap_rate"))),
        ("年还贷额", _money(an.get("annual_debt_service"))),
        ("自有资金", _money(an.get("net_liquidity"))),
        ("贷款余额", _money(an.get("loan_bal"))),
        ("单价 $/SF", _money2(psf.get("price_per_sf"))),
        ("NOI $/SF", _money2(psf.get("noi_per_sf"))),
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
    story.append(Spacer(1, 4 * mm))

    # 持有期现金流（退出分析）
    story.append(_section_title("持有期现金流与退出", cw))
    story.append(Spacer(1, 2 * mm))
    flows = ex.get("cash_flows", []) or []
    ef = [[dp("年份", 8.5, DK_MUT, True), dp("年度现金流", 8.5, DK_MUT, True, "right"),
           dp("备注", 8.5, DK_MUT, True)]]
    shown = flows[: ex.get("hold_years", 0) + 2]
    for i, f in enumerate(shown):
        note = "初始投入" if i == 0 else ("含退出净所得" if i == len(shown) - 1 else "")
        ef.append(drow(f"第 {i} 年", _money(f), note))
    exit_rows = [
        drow("退出售价", _money(ex.get("sale_price")), ""),
        drow("退出剩余贷款", _money(ex.get("remaining_loan")), ""),
        drow("退出净所得", _money(ex.get("sale_proceeds")), ""),
        drow("股本倍数", "--" if _bad(ex.get("equity_multiple"))
             else f"{float(ex.get('equity_multiple')):.2f}×", ""),
        drow("退出 IRR", _pct(ex.get("irr")), ""),
    ]
    eft = Table(ef + exit_rows, colWidths=[cw * 0.2, cw * 0.35, cw * 0.45])
    eft.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), DK_PANEL),
                             ("GRID", (0, 0), (-1, -1), 0.5, DK_GRID),
                             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                             ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]))
    story.append(eft)
    story.append(Spacer(1, 6 * mm))
    story.append(dp(f"DealDesk 生成 · {now} · 数据来自商业核保页实时计算", 7.5, DK_MUT, align="center"))

    # 深色底
    def _bg(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(DK_BG)
        canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
        canvas.restoreState()

    doc.build(story, onFirstPage=_bg, onLaterPages=_bg)
    return buf.getvalue()


# ---------------------------------------------------------------- 统一入口
def build_uw_pdf(r: dict, variant: str = "classic") -> bytes:
    """r = compute_all() 结果；variant ∈ {classic, enhanced}。"""
    _register_fonts()
    if variant == "enhanced":
        return build_enhanced_pdf(r)
    return build_classic_pdf(r)
