"""一键 Tear Sheet（投资一页纸）。

台账待做第 1 项（学自 Dealpath，Top2）：intake 完成后自动生成 deal 一页纸 ——
关键字段（价格/NOI/cap rate/全口径现金需求/月供/DSCR）＋ 3 条 highlights ＋
1 条下一步建议；进 PDF 备忘录封面页。

口径诚实铁律（与全端统一）：缺数 → None → 渲染 "—"，绝不印 0.00×/0% 冒充。
"""
from __future__ import annotations

import io
import math
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

_ET = ZoneInfo("America/New_York")

_FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
_FONT_READY = False
FONT = "Helvetica"


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


# 浅色专业版式（Dealpath 式一页纸）
INK = HexColor("#1a2332")
MUTED = HexColor("#5a6678")
GRID = HexColor("#d5dbe3")
HDR_BG = HexColor("#1a2332")
HDR_FG = HexColor("#ffffff")
ACCENT = HexColor("#b7791f")
PANEL = HexColor("#f4f6f9")
GOOD = HexColor("#1e7e34")
WARN = HexColor("#b7791f")
BAD = HexColor("#b3261e")


def _ok(v) -> bool:
    """有限数字才算有效输入/结果；None/NaN/inf → False。"""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return False
    return not (math.isnan(v) or math.isinf(v))


def _money(v) -> str:
    if not _ok(v):
        return "—"
    v = float(v)
    return f"(${abs(v):,.0f})" if v < 0 else f"${v:,.0f}"


def _pct(v, digits=2) -> str:
    if not _ok(v):
        return "—"
    return f"{float(v) * 100:.{digits}f}%"


def _x(v, digits=2) -> str:
    if not _ok(v):
        return "—"
    return f"{float(v):.{digits}f}×"


def _esc(t) -> str:
    return (str(t).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


# ---------------------------------------------------------------- 数据
def build_tearsheet_data(r: dict, deal: dict | None = None) -> dict:
    """从 compute_all() 结果生成一页纸数据。

    metrics：价格/NOI/cap/全口径现金需求/月供/DSCR（缺数= None）。
    highlights：恰好 3 条，按严重度排序（危 > 警 > 好）。
    next_step：1 条规则建议。
    """
    deal = deal or {}
    prop = r.get("property", {}) or {}
    an = r.get("analysis", {}) or {}
    pro = r.get("proforma", {}) or {}
    gaps = r.get("data_gaps", {}) or {}
    tier_s = gaps.get("tier_s", []) or []
    tier_a = gaps.get("tier_a", []) or []
    tier_s_ok = bool(r.get("tier_s_ok"))
    has_rr = bool(deal.get("has_rent_roll")) or bool((r.get("rent_roll", {}) or {}).get("rows"))

    purchase = float(an.get("purchase_price")) if tier_s_ok else None
    debt = float(an.get("annual_debt_service") or 0.0)
    liq = float(an.get("net_liquidity") or 0.0)

    noi_in = float(an.get("inplace_noi")) if has_rr else None
    noi_pro = float(an.get("projected_noi")) if has_rr else None
    cap_in = (noi_in / purchase) if (_ok(noi_in) and _ok(purchase) and purchase) else None
    market_cap = float(an.get("market_cap_rate")) if _ok(an.get("market_cap_rate")) else None
    proj = an.get("projected", {}) or {}
    inp = an.get("inplace", {}) or {}
    dscr_pro = float(proj.get("dscr")) if (debt > 0 and has_rr) else None
    dscr_in = float(inp.get("dscr")) if (debt > 0 and has_rr) else None
    monthly = (debt / 12.0) if (debt > 0 and tier_s_ok) else None
    cash_needed = liq if tier_s_ok else None
    breakeven = float(an.get("breakeven_occupancy")) if (has_rr and _ok(an.get("breakeven_occupancy"))) else None
    coc_pro = float(proj.get("cash_on_cash")) if has_rr else None
    ex = an.get("exit", {}) or {}
    irr = float(ex.get("irr")) if _ok(ex.get("irr")) else None
    em = float(ex.get("equity_multiple")) if _ok(ex.get("equity_multiple")) else None
    hold_years = ex.get("hold_years")

    metrics = [
        ("收购价", _money(purchase)),
        ("在手 NOI", _money(noi_in)),
        ("预测 NOI", _money(noi_pro)),
        ("在手 Cap Rate", _pct(cap_in)),
        ("全口径现金需求", _money(cash_needed)),
        ("月供（本息）", _money(monthly)),
        ("DSCR（预测）", _x(dscr_pro)),
        ("DSCR（在手）", _x(dscr_in)),
        ("盈亏平衡出租率", _pct(breakeven, 1)),
        ("预测现金回报", _pct(coc_pro, 1)),
        ("持有期 IRR", _pct(irr, 1)),
        ("股本倍数", _x(em) if _ok(em) else "—"),
    ]

    # ---------------------------------------------------------- 3 highlights
    hl = []  # (severity_rank, level_label, text); rank: 0 危 / 1 警 / 2 好
    if tier_s:
        _cn = {"purchase_price": "收购价", "net_rentable_sf": "可租面积",
               "property_type": "物业类型"}
        names = "、".join(_cn.get(g, g) for g in tier_s)
        hl.append((0, "危", f"数据不足：缺少{names}，以下关键数字不可用，先补数再做判断"))
    if _ok(dscr_pro) and dscr_pro < 1.0:
        hl.append((0, "危", f"偿付告警：预测 DSCR {_x(dscr_pro)} < 1.0×，现金流覆盖不了月供"))
    elif _ok(dscr_pro) and dscr_pro < 1.25:
        hl.append((1, "警", f"DSCR {_x(dscr_pro)} 低于银行常规口径 1.25×，融资条件可能收紧"))
    if _ok(breakeven) and breakeven > 0.90:
        hl.append((1, "警", f"盈亏平衡出租率 {_pct(breakeven, 1)}，出租率安全垫薄"))
    if _ok(cap_in) and _ok(market_cap):
        bps = (cap_in - market_cap) * 10000
        if bps >= 100:
            hl.append((2, "好", f"定价折价：在手 cap 高出市场约 {bps:.0f}bps"))
        elif bps <= -100:
            hl.append((1, "警", f"定价偏贵：在手 cap 低于市场约 {abs(bps):.0f}bps"))
    if _ok(coc_pro) and coc_pro < 0.05:
        hl.append((1, "警", f"预测现金回报 {_pct(coc_pro, 1)} 偏低（<5%）"))
    if _ok(irr) and irr < 0.08:
        hl.append((1, "警", f"持有期 IRR {_pct(irr, 1)} 低于 8% 常见门槛"))
    if _ok(dscr_pro) and dscr_pro >= 1.35:
        hl.append((2, "好", f"偿付覆盖强劲：预测 DSCR {_x(dscr_pro)}"))
    if _ok(irr) and irr >= 0.12:
        hl.append((2, "好", f"持有期 IRR {_pct(irr, 1)}（{hold_years} 年）达标"))
    if tier_a and not tier_s:
        hl.append((1, "警", f"Tier A 缺口 {len(tier_a)} 项（含 {tier_a[0]}），部分模块为估算口径"))
    hl.sort(key=lambda t: t[0])
    highlights = [{"level": lv, "text": tx} for _, lv, tx in hl[:3]]
    while len(highlights) < 3:
        highlights.append({"level": "好", "text": "基础字段齐全，可进入下一步核保"})

    # ---------------------------------------------------------- 下一步建议
    if tier_s:
        next_step = f"先补齐缺失字段（{names}），再做 go/no-go 判断"
    elif _ok(dscr_pro) and dscr_pro < 1.0:
        next_step = "放弃或重谈价格：当前预测现金流无法覆盖月供，降价或卖方融资是唯二出路"
    elif _ok(dscr_pro) and dscr_pro < 1.20:
        next_step = "与 lender 确认 DSCR 计算口径，同时要求卖方降价或提供过渡期租金担保"
    elif _ok(breakeven) and breakeven > 0.90:
        next_step = "核实出租率假设：逐户核对租约到期日与市场租金，安排实地尽调"
    elif _ok(cap_in) and _ok(market_cap) and (cap_in - market_cap) * 10000 <= -100:
        next_step = "定价高于市场：用可比成交压价，或转向备选标的"
    elif tier_a:
        next_step = f"补齐 Tier A 缺口（{tier_a[0]} 等），消除估算口径后做正式核保"
    else:
        next_step = "进入正式尽调：核实 rent roll 与租约、第三方查验维修项，锁定融资条款后出 LOI"

    name = deal.get("name") or prop.get("name") or "未命名物业"
    addr = deal.get("address") or prop.get("address") or ""
    return {
        "name": name, "address": addr,
        "generated_at": datetime.now(_ET).strftime("%Y-%m-%d %H:%M ET"),
        "metrics": metrics, "highlights": highlights, "next_step": next_step,
        "tier_s_ok": tier_s_ok, "data_gaps": {"tier_s": tier_s, "tier_a": tier_a},
    }


# ---------------------------------------------------------------- 渲染
def _dp(text, size=9, color=INK, bold=False, align="left", leading=None):
    align_i = {"left": 0, "center": 1, "right": 2}[align]
    return Paragraph(
        f"<font face='{FONT}' size='{size}' color='{color}'>"
        f"{'<b>' if bold else ''}{_esc(text)}{'</b>' if bold else ''}</font>",
        ParagraphStyle(f"ts{size}{color}{bold}{align}", alignment=align_i,
                       leading=leading or size * 1.45, fontName=FONT,
                       textColor=color, fontSize=size),
    )


def tearsheet_story(data: dict, cw: float) -> list:
    """一页纸的 platypus story（供备忘录封面页合并复用）。"""
    story = []
    story.append(_dp("DEAL TEAR SHEET · 投资一页纸", 15, INK, True))
    sub = data["name"]
    if data["address"] and data["address"] != data["name"]:
        sub += f"（{data['address']}）"
    story.append(_dp(sub, 10, MUTED))
    story.append(_dp(f"DealDesk 自动生成 · {data['generated_at']}", 8, MUTED))
    story.append(Spacer(1, 3 * mm))

    # 关键指标网格（2 列 × 6 行）
    rows = []
    ms = data["metrics"]
    for i in range(0, len(ms), 2):
        pair = ms[i:i + 2]
        cells = []
        for label, val in pair:
            cells.append(_dp(label, 8, MUTED))
            cells.append(_dp(val, 11, INK, True))
        while len(cells) < 4:
            cells += [_dp("", 8), _dp("", 8)]
        rows.append(cells)
    t = Table(rows, colWidths=[cw * 0.25, cw * 0.25, cw * 0.25, cw * 0.25])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("BOX", (0, 0), (-1, -1), 0.5, GRID),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 4 * mm))

    story.append(_dp("关键信号", 11, INK, True))
    story.append(Spacer(1, 1.5 * mm))
    for h in data["highlights"]:
        lv = h["level"]
        col = BAD if lv == "危" else (WARN if lv == "警" else GOOD)
        story.append(_dp(f"[{lv}]  {h['text']}", 9.5, col))
        story.append(Spacer(1, 1 * mm))
    story.append(Spacer(1, 2.5 * mm))

    story.append(_dp("下一步建议", 11, INK, True))
    story.append(Spacer(1, 1.5 * mm))
    nt = Table([[_dp("→  " + data["next_step"], 10, INK, True)]],
               colWidths=[cw])
    nt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("BOX", (0, 0), (-1, -1), 0.5, GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(nt)
    story.append(Spacer(1, 4 * mm))
    story.append(_dp("基于当前输入的初步测算，非投资建议；数字随输入实时更新。缺数项以 — 标注，不做估算。",
                     7.5, MUTED))
    return story


def build_tearsheet_pdf(r: dict, deal: dict | None = None) -> bytes:
    """独立一页纸 PDF（A4，严格一页）。"""
    _register_fonts()
    data = build_tearsheet_data(r, deal)
    buf = io.BytesIO()
    W, _H = A4
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=12 * mm,
                            title=f"Tear Sheet - {data['name']}",
                            author="DealDesk · vertciti")
    cw = W - 32 * mm
    doc.build(tearsheet_story(data, cw))
    return buf.getvalue()
