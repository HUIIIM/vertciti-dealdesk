"""DealDesk 投资筛选备忘录：服务端一键生成专业 PDF（ReportLab）.

版式：A4 机构备忘录 — 顶栏 / 项目头 / 结论面板(L0) / 核心指标 /
一票否决 / 评分明细 / 阈值对照 / 页脚免责声明。
字体：Noto Sans SC 子集（app/fonts/），Vercel serverless 可用（纯 Python）。
"""

from __future__ import annotations

import io
import os
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle)

# ---------------------------------------------------------------- 字体
# 文泉驿微米黑子集（原生 TrueType，ReportLab 可读；3MB，Vercel 友好）。
# 单字重：层级用字号 / 色彩 / 版式线实现（机构备忘录风格）。
_FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
_FONTS_REGISTERED = False


def _register_fonts() -> None:
    global _FONTS_REGISTERED, FONT
    if _FONTS_REGISTERED:
        return
    fp = os.path.join(_FONT_DIR, "WQY-MicroHei.ttf")
    if os.path.exists(fp):
        try:
            pdfmetrics.registerFont(TTFont("WQY", fp))
            FONT = "WQY"
        except Exception:
            FONT = "Helvetica"  # 注册失败降级
    else:
        # serverless 未打包字体时降级为内置字体，保证 PDF 不崩（中文显示为方框）
        FONT = "Helvetica"
    _FONTS_REGISTERED = True


FONT = "WQY"  # _register_fonts() 会按实际可用情况重设


# ---------------------------------------------------------------- 配色（v3 机构气质，打印友好浅底）
INK = HexColor("#16202e")
TEAL = HexColor("#0f766e")
TEAL_DARK = HexColor("#115e59")
MUTED = HexColor("#64748b")
HAIRLINE = HexColor("#dbe3ec")
PANEL_BG = HexColor("#f6f9fb")
GRADE_COLORS = {
    "A": HexColor("#15803d"),
    "B": HexColor("#1d4ed8"),
    "C": HexColor("#b45309"),
    "否决": HexColor("#b91c1c"),
    "不收录": HexColor("#64748b"),
}
GRADE_BG = {
    "A": HexColor("#e8f5ec"),
    "B": HexColor("#e8eefc"),
    "C": HexColor("#fbf3e4"),
    "否决": HexColor("#fbe9e9"),
    "不收录": HexColor("#eef1f5"),
}
GRADE_LABELS = {"A": "A 级 · 收录（日报头条）", "B": "B 级 · 收录（日报收录）",
                "C": "C 级 · 观察名单", "不收录": "不收录（<50 分）", "否决": "一票否决"}

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN


# ---------------------------------------------------------------- 格式化
def _pct(x, digits=1):
    return "—" if x is None else f"{x * 100:.{digits}f}%"


def _money(x):
    return "—" if x is None else f"${x:,.0f}"


def _num(x, digits=2):
    return "—" if x is None else f"{x:.{digits}f}"


def _key_metrics(track: str, m: dict) -> list[tuple[str, str]]:
    """(标签, 值) × 6，L0 级核心指标。"""
    if track == "residential":
        return [
            ("全口径现金需求", _money(m.get("total_cash_required"))),
            ("月净现金流", _money(m.get("cash_flow_monthly"))),
            ("DSCR", _num(m.get("dscr"))),
            ("Cap rate", _pct(m.get("cap_rate"))),
            ("Cash-on-cash", _pct(m.get("cash_on_cash"))),
            ("月 NOI", _money(m.get("noi_monthly"))),
        ]
    return [
        ("全口径现金需求", _money(m.get("total_cash_required"))),
        ("年净现金流", _money(m.get("net_cf_annual"))),
        ("DSCR", _num(m.get("dscr"))),
        ("入场 Cap rate", _pct(m.get("entry_cap"), 2)),
        ("Spread", f"{m['spread_bps']:.0f} bps" if m.get("spread_bps") is not None else "—"),
        ("Cash-on-cash", _pct(m.get("cash_on_cash"))),
    ]


# ---------------------------------------------------------------- 样式
def _styles() -> dict:
    base = {"fontName": FONT, "textColor": INK, "leading": 15}
    return {
        "h1": ParagraphStyle("h1", fontName=FONT, fontSize=20,
                             leading=26, textColor=INK, spaceAfter=2),
        "subtitle": ParagraphStyle("subtitle", fontName=FONT, fontSize=9.5,
                                   leading=13, textColor=MUTED),
        "section": ParagraphStyle("section", fontName=FONT, fontSize=12,
                                 leading=16, textColor=INK, spaceBefore=14, spaceAfter=6,
                                 borderPadding=(0, 0, 4, 0)),
        "body": ParagraphStyle("body", fontName=FONT, fontSize=9.5,
                               leading=14, textColor=INK),
        "small": ParagraphStyle("small", fontName=FONT, fontSize=8.5,
                                leading=12, textColor=MUTED),
        "metric_label": ParagraphStyle("ml", fontName=FONT, fontSize=8,
                                      leading=11, textColor=MUTED),
        "metric_value": ParagraphStyle("mv", fontName=FONT, fontSize=13,
                                      leading=16, textColor=INK),
        "score_num": ParagraphStyle("sn", fontName=FONT, fontSize=44,
                                    leading=44, textColor=INK),
        "verdict": ParagraphStyle("vd", fontName=FONT, fontSize=11,
                                  leading=15, textColor=INK),
        "cell": ParagraphStyle("cell", fontName=FONT, fontSize=9,
                               leading=12.5, textColor=INK),
        "cell_b": ParagraphStyle("cellb", fontName=FONT, fontSize=9,
                                 leading=12.5, textColor=INK),
        "cell_m": ParagraphStyle("cellm", fontName=FONT, fontSize=8.5,
                                 leading=11.5, textColor=MUTED),
    }


# ---------------------------------------------------------------- 页眉页脚
def _header_footer(canvas, doc):
    canvas.saveState()
    # 页眉
    canvas.setFont(FONT, 8)
    canvas.setFillColor(INK)
    canvas.drawString(MARGIN, PAGE_H - 13 * mm, "DEALDESK")
    canvas.setFont(FONT, 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN + 62, PAGE_H - 13 * mm, "vertciti 房地产收购部 · 投资筛选备忘录")
    canvas.setFont(FONT, 7.5)
    canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 13 * mm, doc.report_date)
    canvas.setStrokeColor(HAIRLINE)
    canvas.setLineWidth(0.6)
    canvas.line(MARGIN, PAGE_H - 15.2 * mm, PAGE_W - MARGIN, PAGE_H - 15.2 * mm)
    # 页脚
    canvas.setFont(FONT, 7)
    canvas.setFillColor(MUTED)
    footer = "本报告为筛选工具输出，不构成投资建议。每笔真实交易签约 / 交割 / 报税前，必须经持牌本地房地产律师、CPA / 税务师、title company 审查。"
    canvas.drawCentredString(PAGE_W / 2, 12 * mm, footer)
    canvas.drawRightString(PAGE_W - MARGIN, 7.5 * mm, f"第 {doc.page} 页")
    canvas.setStrokeColor(TEAL)
    canvas.setLineWidth(1.2)
    canvas.line(MARGIN, 14.6 * mm, MARGIN + 28, 14.6 * mm)
    canvas.restoreState()


# ---------------------------------------------------------------- 组件
def _section_title(st: dict, text: str):
    """带 teal 左线的小节标题。"""
    t = Table([[Paragraph(f"<font color=\"#0f766e\">▍</font> {text}", st["section"])]],
              colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


def _verdict_panel(st: dict, s: dict) -> Table:
    """L0 结论面板：巨型分数 + 等级徽章 + 结论。"""
    grade = s["grade"]
    gc = GRADE_COLORS.get(grade, MUTED)
    gbg = GRADE_BG.get(grade, PANEL_BG)
    total = s["total"]

    score_cell = [
        Paragraph(f"<font size=44><b>{total}</b></font>"
                  f"<font size=14 color=\"#64748b\"> / 100</font>", st["score_num"]),
    ]
    badge = Table([[Paragraph(f"<b>{grade}</b>",
                              ParagraphStyle("bd", fontName=FONT,
                                             fontSize=15, leading=18,
                                             textColor=gc, alignment=1))]],
                  colWidths=[64])
    badge.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), gbg),
        ("BOX", (0, 0), (-1, -1), 0.8, gc),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("ROUNDEDCORNERS", [3, 3, 3, 3]),
    ]))
    left = Table([[score_cell[0]], [badge]], colWidths=[150])
    left.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))

    verdict_lines = [
        Paragraph(GRADE_LABELS.get(grade, grade), st["verdict"]),
    ]
    if s.get("vetoes"):
        for v in s["vetoes"]:
            verdict_lines.append(Paragraph(
                f"<font color=\"#b91c1c\">✕ {v['message']}</font>", st["body"]))
    else:
        dg = s.get("downgrades") or []
        for d in dg:
            verdict_lines.append(Paragraph(
                f"<font color=\"#b45309\">▲ {d['message']}</font>", st["body"]))
        if not dg:
            verdict_lines.append(Paragraph(
                "<font color=\"#15803d\">✓ 无否决项、无降级提示</font>", st["body"]))
    right_data = [[p] for p in verdict_lines]
    right = Table(right_data, colWidths=[CONTENT_W - 170])
    right.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 12),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))

    panel = Table([[left, right]], colWidths=[170, CONTENT_W - 170])
    panel.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL_BG),
        ("BOX", (0, 0), (-1, -1), 0.7, HAIRLINE),
        ("LINEBELOW", (0, 0), (-1, 0), 2.2, TEAL),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
    ]))
    return panel


def _metrics_grid(st: dict, track: str, m: dict) -> Table:
    """3×2 核心指标网格。"""
    items = _key_metrics(track, m)
    cells = []
    for label, value in items:
        inner = Table([
            [Paragraph(label, st["metric_label"])],
            [Paragraph(f"<b>{value}</b>", st["metric_value"])],
        ], colWidths=[(CONTENT_W - 16) / 3])
        inner.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.white),
            ("BOX", (0, 0), (-1, -1), 0.6, HAIRLINE),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("ROUNDEDCORNERS", [3, 3, 3, 3]),
        ]))
        cells.append(inner)
    rows = [cells[i:i + 3] for i in range(0, 6, 3)]
    grid = Table(rows, colWidths=[CONTENT_W / 3] * 3, spaceBefore=2, spaceAfter=2)
    grid.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return grid


def _check_list(st: dict, title: str, items: list, ok_color: str) -> list:
    """✓/✕ 列表（否决检查用）。"""
    flow = [_section_title(st, title)]
    if not items:
        flow.append(Paragraph(f"<font color=\"{ok_color}\">✓ 无</font>", st["body"]))
        return flow
    rows = []
    for it in items:
        msg = it["message"] if isinstance(it, dict) else str(it)
        rows.append([Paragraph(f"<font color=\"#b91c1c\">✕</font>", st["cell"]),
                     Paragraph(msg, st["cell"])])
    t = Table(rows, colWidths=[16, CONTENT_W - 16])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#fdf2f2")),
        ("BOX", (0, 0), (-1, -1), 0.6, HexColor("#f3c2c2")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROUNDEDCORNERS", [3, 3, 3, 3]),
    ]))
    flow.append(t)
    return flow


def _dimensions_table(st: dict, dims: list) -> Table:
    """评分明细：维度 | 权重 | 得分 | 得分条 | 说明。"""
    header = [Paragraph("<b>维度</b>", st["cell_b"]),
              Paragraph("<b>权重</b>", st["cell_b"]),
              Paragraph("<b>得分</b>", st["cell_b"]),
              Paragraph("<b>说明</b>", st["cell_b"])]
    rows = [header]
    for d in dims:
        w = d["weight"]
        pts = d["points"]
        ratio = max(0.0, min(1.0, (pts / w) if w else 0))
        bar_w = 52
        fill = int(bar_w * ratio)
        bar = (f"<font color=\"#0f766e\">█</font>" * fill
               + f"<font color=\"#dbe3ec\">█</font>" * (bar_w - fill))
        rows.append([
            Paragraph(d["label"], st["cell_b"]),
            Paragraph(f"{w} 分", st["cell"]),
            Paragraph(f"<b>{pts}</b> <font color=\"#64748b\">/ {w}</font>", st["cell"]),
            Paragraph(f"{bar}<br/><font size=8 color=\"#64748b\">{d['detail']}</font>",
                      st["cell_m"]),
        ])
    col_w = [92, 44, 70, CONTENT_W - 92 - 44 - 70]
    t = Table(rows, colWidths=col_w, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), PANEL_BG),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, TEAL),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, HAIRLINE),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, HexColor("#fafbfc")]),
    ]
    t.setStyle(TableStyle(style))
    return t


def _checks_table(st: dict, checks: list) -> Table:
    """阈值对照表。"""
    rows = [[Paragraph("<b>检查项</b>", st["cell_b"]),
             Paragraph("<b>状态</b>", st["cell_b"]),
             Paragraph("<b>备注</b>", st["cell_b"])]]
    for c in checks:
        mark = ("<font color=\"#15803d\">✓</font>" if c["ok"]
                else "<font color=\"#b91c1c\">✕</font>")
        rows.append([Paragraph(f"{mark} {c['label']}", st["cell"]),
                     Paragraph("通过" if c["ok"] else "未通过", st["cell"]),
                     Paragraph(c["note"], st["cell_m"])])
    t = Table(rows, colWidths=[150, 52, CONTENT_W - 202], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PANEL_BG),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, TEAL),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, HAIRLINE),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, HexColor("#fafbfc")]),
    ]))
    return t


# ---------------------------------------------------------------- 主入口
def build_pdf(project: dict) -> bytes:
    """生成投资筛选备忘录 PDF，返回字节串。"""
    _register_fonts()
    st = _styles()
    p = project
    s = p["score"]
    m = s["metrics"]
    track = p["track"]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    struct = s.get("structure_label") or s.get("asset_label") or ""

    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=20 * mm, bottomMargin=18 * mm,
        title=f"DealDesk 打分报告 - {p['name']}",
        author="DealDesk · vertciti",
    )
    doc.report_date = now
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")
    doc.addPageTemplates([PageTemplate(id="p", frames=[frame],
                                       onPage=_header_footer)])

    story = []
    # 项目头
    story.append(Paragraph(p["name"], st["h1"]))
    meta_line = (f"{p['address']} &nbsp;·&nbsp; {'住宅' if track == 'residential' else '商业'}赛道"
                 + (f" &nbsp;·&nbsp; {struct}" if struct else ""))
    story.append(Paragraph(meta_line, st["subtitle"]))
    story.append(Spacer(1, 6))

    # L0 结论面板
    story.append(_verdict_panel(st, s))
    story.append(Spacer(1, 4))

    # 核心指标
    story.append(_section_title(st, "核心指标（保守全口径）"))
    story.append(_metrics_grid(st, track, m))

    # 一票否决
    story.extend(_check_list(st, "一票否决检查", s.get("vetoes") or [], "#15803d"))
    dg = s.get("downgrades") or []
    if dg:
        flow = [_section_title(st, "降级提示（封顶降级，非一票否决）")]
        rows = [[Paragraph(f"<font color=\"#b45309\">▲</font>", st["cell"]),
                 Paragraph(d["message"], st["cell"])] for d in dg]
        t = Table(rows, colWidths=[16, CONTENT_W - 16])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), HexColor("#fffbeb")),
            ("BOX", (0, 0), (-1, -1), 0.6, HexColor("#f0d9a8")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROUNDEDCORNERS", [3, 3, 3, 3]),
        ]))
        flow.append(t)
        story.extend(flow)

    # 评分明细
    story.append(_section_title(st, "评分明细（100 分制）"))
    story.append(_dimensions_table(st, s["dimensions"]))

    # 阈值对照
    story.append(_section_title(st, "阈值对照"))
    story.append(_checks_table(st, s.get("checks") or []))

    # 口径注脚
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "评分口径：住宅线 buyer-box.md v2.3；商业线 buyer-box-commercial.md v1.3（2026-09-28）。"
        "所有“估算”数字以标注假设为准，未核实项不得作为决策依据。",
        st["small"]))

    doc.build(story)
    return buf.getvalue()
