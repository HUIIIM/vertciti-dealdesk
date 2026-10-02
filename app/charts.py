"""DealDesk 报告图表：SVG（HTML 报告内联）+ Pillow 手绘 PNG（PDF 嵌入）.

三张图：
1. 现金流回本测算 — 10 年累计净现金流折线（按当前年化现金流线性外推）
2. 敏感性分析 — 租金 ±10% / 利率 ±2% 五档对月净现金流的影响（复用 sensitivity 引擎）
3. 评分构成 — 各维度得分 / 权重横向条形图

纪律：只用 scoring / sensitivity 已有计算结果，不编数；缺数渲染"—"占位。
配色沿用 pdf_report.py 的 token（INK / TEAL / MUTED / HAIRLINE / 否决红），不引入新色。
不依赖 matplotlib（Vercel serverless 保持轻量）；Pillow 仅用于服务端 PNG 手绘。
"""

from __future__ import annotations

import io
import os

# ---------------------------------------------------------------- 配色（与 pdf_report.py 一致）
INK = "#16202e"
TEAL = "#0f766e"
MUTED = "#64748b"
HAIRLINE = "#dbe3ec"
RED = "#b91c1c"          # GRADE_COLORS["否决"]
TRACK_BG = "#eef2f6"

_RGB = {
    INK: (22, 32, 46),
    TEAL: (15, 118, 110),
    MUTED: (100, 116, 139),
    HAIRLINE: (219, 227, 236),
    RED: (185, 28, 28),
    TRACK_BG: (238, 242, 246),
    "#ffffff": (255, 255, 255),
}

_FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "WQY-MicroHei.ttf")


# ---------------------------------------------------------------- 数据准备
def prep_cashflow(track: str, metrics: dict) -> dict | None:
    """10 年累计现金流序列。None 表示数据不足。"""
    m = metrics or {}
    if track == "residential":
        cf_m = m.get("cash_flow_monthly")
    else:
        cf_m = m.get("net_cf_monthly")
        if cf_m is None and m.get("net_cf_annual") is not None:
            cf_m = m["net_cf_annual"] / 12
    cash_invested = m.get("cash_invested")
    if cf_m is None or cash_invested is None:
        return None
    annual = cf_m * 12
    years = list(range(0, 11))
    cumulative = [-cash_invested + annual * y for y in years]
    breakeven = None
    if cumulative[0] >= 0:
        breakeven = 0.0
    else:
        for i in range(1, len(years)):
            if cumulative[i] >= 0 > cumulative[i - 1]:
                span = cumulative[i] - cumulative[i - 1]
                breakeven = (i - 1) + (0 - cumulative[i - 1]) / span if span else float(i)
                break
    return {
        "years": years, "cumulative": cumulative, "breakeven": breakeven,
        "annual_cf": annual, "cash_invested": cash_invested,
    }


def prep_sensitivity(track: str, sens: dict | None) -> dict | None:
    """租金 / 利率五档对月净现金流的影响。None 表示数据不足。"""
    if not sens:
        return None
    cf_key = "cash_flow_monthly" if track == "residential" else "net_cf_monthly"

    def norm_label(lbl: str) -> str:
        return "基准" if lbl == "+0%" else lbl

    def steps(table):
        out = []
        for row in table:
            v = row.get(cf_key)
            out.append({"label": norm_label(row.get("label", "")), "value": v})
        return out

    rent = steps(sens.get("rent_table") or [])
    rate = steps(sens.get("rate_table") or [])
    if len(rent) != 5 or len(rate) != 5:
        return None
    if all(r["value"] is None for r in rent + rate):
        return None
    return {"rent": rent, "rate": rate, "unit": "月净现金流"}


def prep_dimensions(dimensions: list) -> list:
    out = []
    for d in dimensions or []:
        w = d.get("weight") or 0
        pts = d.get("points") or 0
        ratio = max(0.0, min(1.0, (pts / w) if w else 0))
        out.append({"label": d.get("label", ""), "weight": w,
                    "points": pts, "ratio": ratio})
    return out


# ---------------------------------------------------------------- 格式化小工具
def _fmt_k(v: float) -> str:
    if v is None:
        return "—"
    av = abs(v)
    if av >= 1000:
        s = f"${v / 1000:,.0f}k"
    else:
        s = f"${v:,.0f}"
    return s.replace("$-", "-$")


def _fmt_money(v: float) -> str:
    if v is None:
        return "—"
    s = f"${v:,.0f}"
    return s.replace("$-", "-$")


# ---------------------------------------------------------------- SVG（HTML 报告内联，矢量零依赖）
_SVG_HEAD = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
             'width="100%" role="img" aria-label="{label}">')
_SVG_FONT = "font-family=\"-apple-system,'PingFang SC','Microsoft YaHei',sans-serif\""


def svg_placeholder(title: str, w: int = 760, h: int = 120) -> str:
    return (
        _SVG_HEAD.format(w=w, h=h, label=title)
        + f'<rect x="1" y="1" width="{w-2}" height="{h-2}" rx="6" fill="#f6f9fb" stroke="{HAIRLINE}"/>'
        + f'<text x="{w/2}" y="{h/2+6}" text-anchor="middle" font-size="15" fill="{MUTED}" {_SVG_FONT}>'
        + f'— {title}：数据不足，暂无图表</text></svg>'
    )


def svg_cashflow(prep: dict | None) -> str:
    """累计现金流回本测算折线图。"""
    if not prep:
        return svg_placeholder("现金流回本测算")
    W, H = 760, 300
    L, R, T, B = 64, 18, 18, 40
    pw, ph = W - L - R, H - T - B
    cum = prep["cumulative"]
    lo = min(0.0, min(cum))
    hi = max(0.0, max(cum))
    span = (hi - lo) or 1.0
    lo -= span * 0.08
    hi += span * 0.08

    def X(i):
        return L + i / 10 * pw

    def Y(v):
        return T + (1 - (v - lo) / (hi - lo)) * ph

    parts = [_SVG_HEAD.format(w=W, h=H, label="累计现金流回本测算")]
    # 网格 + Y 轴
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        y = Y(v)
        parts.append(f'<line x1="{L}" y1="{y:.1f}" x2="{W-R}" y2="{y:.1f}" stroke="{HAIRLINE}"/>')
        parts.append(f'<text x="{L-8}" y="{y+4:.1f}" text-anchor="end" font-size="11" '
                     f'fill="{MUTED}" {_SVG_FONT}>{_fmt_k(v)}</text>')
    # 零线
    if lo < 0 < hi:
        y0 = Y(0)
        parts.append(f'<line x1="{L}" y1="{y0:.1f}" x2="{W-R}" y2="{y0:.1f}" '
                     f'stroke="{MUTED}" stroke-dasharray="5 4" stroke-width="1"/>')
    # X 轴年份
    for yr in (0, 2, 4, 6, 8, 10):
        parts.append(f'<text x="{X(yr):.1f}" y="{H-16}" text-anchor="middle" font-size="11" '
                     f'fill="{MUTED}" {_SVG_FONT}>{yr} 年</text>')
    # 面积 + 折线
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(cum))
    parts.append(f'<polygon points="{L},{Y(0):.1f} {pts} {W-R},{Y(0):.1f}" '
                 f'fill="{TEAL}" fill-opacity="0.08"/>')
    parts.append(f'<polyline points="{pts}" fill="none" stroke="{TEAL}" stroke-width="2.5"/>')
    # 回本点
    be = prep["breakeven"]
    if be is not None:
        i0 = int(be)
        frac = be - i0
        if i0 >= 10:
            bx, bv = X(10), cum[10]
        else:
            bx = X(i0) + frac * (X(i0 + 1) - X(i0))
            bv = cum[i0] + frac * (cum[i0 + 1] - cum[i0])
        by = Y(bv)
        parts.append(f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="5" fill="{TEAL}"/>')
        tag = "首年即回本" if be == 0 else f"约 {be:.1f} 年回本"
        tx = min(max(bx + 10, L + 60), W - R - 120)
        parts.append(f'<text x="{tx:.1f}" y="{by-12:.1f}" font-size="12" font-weight="700" '
                     f'fill="{TEAL}" {_SVG_FONT}>{tag}</text>')
    else:
        parts.append(f'<text x="{W-R}" y="{T+16}" text-anchor="end" font-size="12" '
                     f'fill="{RED}" {_SVG_FONT}>10 年内未回本（按当前现金流线性外推）</text>')
    parts.append(f'<text x="{L}" y="{T-4}" font-size="11" fill="{MUTED}" {_SVG_FONT}>'
                 f'累计净现金流（含初始投入 -{_fmt_money(prep["cash_invested"])} 起点）</text>')
    parts.append("</svg>")
    return "".join(parts)


def _sens_bars_svg(parts: list, rows: list, title: str, ox: int, pw: int,
                   T: int, B: int, H: int, gmin: float, gmax: float) -> None:
    top, bot = T, H - B
    ph = bot - top
    n = len(rows)
    slot = pw / n
    bw = slot * 0.62

    def Y(v):
        return top + (1 - (v - gmin) / (gmax - gmin)) * ph

    parts.append(f'<text x="{ox + pw/2:.1f}" y="{T-22}" text-anchor="middle" font-size="13" '
                 f'font-weight="700" fill="{INK}" {_SVG_FONT}>{title}</text>')
    y0 = Y(0)
    parts.append(f'<line x1="{ox}" y1="{y0:.1f}" x2="{ox+pw}" y2="{y0:.1f}" '
                 f'stroke="{MUTED}" stroke-dasharray="5 4"/>')
    for i, r in enumerate(rows):
        cx = ox + slot * i + slot / 2
        v = r["value"]
        if v is None:
            parts.append(f'<text x="{cx:.1f}" y="{(top+bot)/2:.1f}" text-anchor="middle" '
                         f'font-size="12" fill="{MUTED}" {_SVG_FONT}>—</text>')
        else:
            yv = Y(v)
            y_top, y_bot = (yv, y0) if v >= 0 else (y0, yv)
            color = TEAL if r["label"] == "基准" else (RED if v < 0 else MUTED)
            parts.append(f'<rect x="{cx-bw/2:.1f}" y="{y_top:.1f}" width="{bw:.1f}" '
                         f'height="{max(y_bot-y_top, 1.5):.1f}" rx="3" fill="{color}"/>')
            ly = y_top - 8 if v >= 0 else y_bot + 16
            parts.append(f'<text x="{cx:.1f}" y="{ly:.1f}" text-anchor="middle" font-size="10.5" '
                         f'fill="{INK}" {_SVG_FONT}>{_fmt_money(v)}</text>')
        parts.append(f'<text x="{cx:.1f}" y="{bot+20:.1f}" text-anchor="middle" font-size="11" '
                     f'fill="{MUTED}" {_SVG_FONT}>{r["label"]}</text>')


def svg_sensitivity(prep: dict | None) -> str:
    """租金 / 利率五档对月净现金流的影响（分组柱状）。"""
    if not prep:
        return svg_placeholder("敏感性分析")
    W, H = 760, 340
    T, B = 52, 44
    gap, side = 24, 24
    pw = (W - side * 2 - gap) / 2
    vals = [r["value"] for r in prep["rent"] + prep["rate"] if r["value"] is not None]
    gmin = min(0.0, min(vals))
    gmax = max(0.0, max(vals))
    span = (gmax - gmin) or 1.0
    gmin -= span * 0.12
    gmax += span * 0.12
    parts = [_SVG_HEAD.format(w=W, h=H, label="敏感性分析")]
    _sens_bars_svg(parts, prep["rent"], "租金变动 → 月净现金流", side, pw, T, B, H, gmin, gmax)
    _sens_bars_svg(parts, prep["rate"], "利率变动 → 月净现金流", side + pw + gap, pw,
                   T, B, H, gmin, gmax)
    parts.append("</svg>")
    return "".join(parts)


def svg_dimensions(prep: list) -> str:
    """各维度得分 / 权重横向条形图。"""
    if not prep:
        return svg_placeholder("评分构成")
    W = 760
    top, row_h, bottom = 12, 46, 12
    H = int(top + len(prep) * row_h + bottom)
    label_w, val_w = 168, 120
    tx0, tx1 = label_w + 8, W - val_w - 8
    parts = [_SVG_HEAD.format(w=W, h=H, label="评分构成")]
    for i, d in enumerate(prep):
        y = top + i * row_h
        cy = y + row_h / 2
        parts.append(f'<text x="{label_w-8}" y="{cy+5:.1f}" text-anchor="end" font-size="13" '
                     f'fill="{INK}" {_SVG_FONT}>{d["label"]}</text>')
        parts.append(f'<rect x="{tx0}" y="{cy-9:.1f}" width="{tx1-tx0}" height="18" '
                     f'rx="4" fill="{TRACK_BG}"/>')
        fw = (tx1 - tx0) * d["ratio"]
        if fw > 0.5:
            parts.append(f'<rect x="{tx0}" y="{cy-9:.1f}" width="{fw:.1f}" height="18" '
                         f'rx="4" fill="{TEAL}"/>')
        txt = (f"{d['points']:.0f}" if float(d['points']).is_integer()
               else f"{d['points']:.1f}") + f" / {d['weight']:.0f}"
        parts.append(f'<text x="{tx1+10}" y="{cy+5:.1f}" font-size="13" fill="{INK}" '
                     f'{_SVG_FONT}>{txt}</text>')
    parts.append("</svg>")
    return "".join(parts)
