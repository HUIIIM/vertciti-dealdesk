"""打分报告：中文可打印 HTML（浏览器打印另存为 PDF）."""

from __future__ import annotations

import html
from datetime import datetime

from . import charts, report_narrative, sensitivity

GRADE_LABELS = {"A": "A 级（日报头条）", "B": "B 级（日报收录）", "C": "C 级（观察名单）",
                "不收录": "不收录（<50 分）", "否决": "一票否决"}


def _pct(x, digits=1):
    return "—" if x is None else f"{x*100:.{digits}f}%"


def _money(x):
    return "—" if x is None else f"${x:,.0f}"


def render(project: dict) -> str:
    p = project
    s = p["score"]
    m = s["metrics"]
    track = p["track"]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    grade = s["grade"]

    def row(k, v):
        return f"<tr><th>{html.escape(k)}</th><td>{v}</td></tr>"

    if track == "residential":
        metric_rows = "".join([
            row("月供 P&I", _money(m["monthly_pi"])),
            row("月 PITI", _money(m["piti"])),
            row("有效租金收入 EGI/月", _money(m["egi"])),
            row("营业费用/月", _money(m["opex"])),
            row("月 NOI", _money(m["noi_monthly"])),
            row("月净现金流", _money(m["cash_flow_monthly"])),
            row("单门月现金流", _money(m["cash_flow_per_door"])),
            row("Cash-on-cash", _pct(m["cash_on_cash"])),
            row("DSCR", m["dscr"] if m["dscr"] is not None else "—"),
            row("Cap rate", _pct(m["cap_rate"])),
            row("现金总投入", _money(m["cash_invested"])),
            row("全口径现金需求（含储备）", _money(m["total_cash_required"])),
            row("交割净值", _money(m["equity"])),
        ])
    else:
        metric_rows = "".join([
            row("有效租金收入 EGI/年", _money(m["egi"])),
            row("营业费用 OpEx/年", _money(m["opex"])),
            row("NOI/年（保守重算）", _money(m["noi"])),
            row("重置储备/年", _money(m["reserves_annual"])),
            row("年还本付息", _money(m["annual_debt_service"])),
            row("年净现金流", _money(m["net_cf_annual"])),
            row("月净现金流", _money(m["net_cf_monthly"])),
            row("入场 cap rate", _pct(m["entry_cap"], 2)),
            row("市场 cap rate", _pct(m["market_cap"], 2)),
            row("Spread", f"{m['spread_bps']:.0f}bps" if m["spread_bps"] is not None else "—"),
            row("DSCR", m["dscr"] if m["dscr"] is not None else "—"),
            row("Cash-on-cash", _pct(m["cash_on_cash"])),
            row("现金总投入", _money(m["cash_invested"])),
            row("全口径现金需求（含储备/TI-LC）", _money(m["total_cash_required"])),
            row("交割净值", _money(m["equity"])),
        ])

    dim_rows = "".join(
        f"<tr><td>{html.escape(x['label'])}</td><td>{x['weight']} 分</td>"
        f"<td><b>{x['points']}</b></td><td>{html.escape(x['detail'])}</td></tr>"
        for x in s["dimensions"]
    )
    veto_html = ("<p class='ok'>无否决项</p>" if not s["vetoes"] else
                 "<ul class='veto'>" + "".join(
                     f"<li>{html.escape(v['message'])}</li>" for v in s["vetoes"]) + "</ul>")
    dg = s.get("downgrades") or []
    dg_html = ("" if not dg else
               "<h2>降级提示（封顶降级，非一票否决）</h2><ul class='downgrade'>" + "".join(
                   f"<li>{html.escape(v['message'])}</li>" for v in dg) + "</ul>")
    check_rows = "".join(
        f"<tr><td>{'✅' if c['ok'] else '❌'} {html.escape(c['label'])}</td>"
        f"<td>{html.escape(c['note'])}</td></tr>" for c in s["checks"]
    )
    struct = html.escape(s.get("structure_label", "") or s.get("asset_label", ""))
    B = lambda t: f"<b>{html.escape(t)}</b>"
    T = html.escape
    lead_html = "".join(f"<p>{para}</p>" for para in
                        report_narrative.lead_paragraphs(p, B, T))
    concl_html = "".join(f"<p>{para}</p>" for para in
                         report_narrative.conclusion_paragraphs(p, B, T))

    # 敏感性分析（复用 sensitivity 引擎；失败则图表占位"—"）
    try:
        sens = sensitivity.run(track, p.get("input") or {})
    except Exception:
        sens = None
    sens_prep = charts.prep_sensitivity(track, sens)
    sens_rows = ""
    if sens_prep:
        for i in range(5):
            r, t2 = sens_prep["rent"][i], sens_prep["rate"][i]
            sens_rows += ("<tr>"
                          f"<td>{html.escape(r['label'])}</td><td class='num'>{_money(r['value'])}</td>"
                          f"<td>{html.escape(t2['label'])}</td><td class='num'>{_money(t2['value'])}</td>"
                          "</tr>")

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>DealDesk 打分报告 - {html.escape(p['name'])}</title>
<style>
 body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; max-width: 900px; margin: 24px auto; padding: 0 20px; color: #1a1a1a; }}
 h1 {{ font-size: 22px; }} h2 {{ font-size: 17px; border-bottom: 2px solid #222; padding-bottom: 4px; margin-top: 28px; }}
 table {{ width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 14px; }}
 th, td {{ border: 1px solid #ccc; padding: 6px 10px; text-align: left; }}
 th {{ background: #f4f4f4; width: 34%; }}
 .grade {{ font-size: 40px; font-weight: 800; }}
 .grade.A {{ color: #0a7a2f; }} .grade.B {{ color: #1a56db; }} .grade.C {{ color: #b45309; }}
 .grade.否决 {{ color: #c00; }}
 .veto li {{ color: #c00; font-weight: 600; }} .ok {{ color: #0a7a2f; font-weight: 600; }}
 .downgrade li {{ color: #b45309; font-weight: 600; }}
 .meta {{ color: #555; font-size: 13px; }}
 .lead {{ background: #f6f9fb; border-left: 4px solid #0f766e; padding: 12px 16px; margin: 18px 0 4px; font-size: 14.5px; line-height: 1.75; }}
 .lead p {{ margin: 6px 0; }}
 figure.chart {{ margin: 14px 0 6px; }}
 figure.chart svg {{ display: block; }}
 figcaption {{ font-size: 12.5px; color: #64748b; margin-top: 6px; line-height: 1.6; }}
 .conclusion {{ background: #f6f9fb; border: 1px solid #dbe3ec; border-radius: 8px; padding: 12px 18px; margin: 10px 0; font-size: 14.5px; line-height: 1.8; }}
 .conclusion p {{ margin: 8px 0; }}
 td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
 th.nw {{ white-space: nowrap; }}
 .disclaimer {{ font-size: 12px; color: #666; border-top: 1px solid #ccc; margin-top: 32px; padding-top: 8px; }}
 @media print {{ body {{ margin: 0; }} .noprint {{ display: none; }} }}
</style></head><body>
<p class="noprint"><button onclick="window.print()">🖨️ 打印 / 另存为 PDF</button></p>
<h1>DealDesk 打分报告</h1>
<p class="meta">vertciti 房地产收购部 · {now} · 赛道：{"住宅" if track=="residential" else "商业"}</p>
<h2>项目</h2>
<table>
{row("项目名称", html.escape(p['name']))}
{row("地址", html.escape(p['address']))}
{row("结构", struct)}
{row("总分", f"<span class='grade {html.escape(grade)}'>{s['total']} / {html.escape(grade)}</span>")}
{row("等级说明", GRADE_LABELS.get(grade, grade))}
</table>
<h2>导语</h2>
<div class="lead">{lead_html}</div>
<h2>一票否决检查</h2>
{veto_html}
{dg_html}
<h2>测算结果（保守全口径）</h2>
<table>{metric_rows}</table>
<h2>现金流回本测算</h2>
<figure class="chart">{charts.svg_cashflow(charts.prep_cashflow(track, m))}
<figcaption>按当前{('月' if track=='residential' else '年')}净现金流线性外推 10 年（不含租金增长、再融资与资产增值）。起点为初始现金投入；数据缺失处标"—"。</figcaption></figure>
<h2>敏感性分析</h2>
<figure class="chart">{charts.svg_sensitivity(sens_prep)}
<figcaption>租金 ±10%、利率 ±2% 五档对月净现金流的影响，全部用打分引擎重算（口径与测算结果一致）。深色柱为当前基准情景。</figcaption></figure>
<table><tr><th>租金情景</th><th class="num nw">月净现金流</th><th>利率情景</th><th class="num nw">月净现金流</th></tr>{sens_rows}</table>
<h2>评分明细（100 分制）</h2>
<table><tr><th>维度</th><th>权重</th><th>得分</th><th>说明</th></tr>{dim_rows}</table>
<h2>评分构成</h2>
<figure class="chart">{charts.svg_dimensions(charts.prep_dimensions(s["dimensions"]))}
<figcaption>各维度实际得分 / 权重。丢分最多的维度见下方结论。</figcaption></figure>
<h2>阈值对照</h2>
<table><tr><th>检查项</th><th>状态</th></tr>{check_rows}</table>
<h2>结论与下一步</h2>
<div class="conclusion">{concl_html}</div>
<div class="disclaimer">
本报告为筛选工具输出，不构成投资建议。所有"估算"数字以标注假设为准，未核实项不得作为决策依据。
每笔真实交易签约/交割/报税前，必须经持牌本地房地产律师、CPA/税务师、title company 审查。
评分口径：住宅线 buyer-box.md v2.3；商业线 buyer-box-commercial.md v1.3（2026-09-28）。
</div>
</body></html>"""
