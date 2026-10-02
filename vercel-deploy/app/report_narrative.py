"""打分报告文案：导语段 + 结论段（HTML 版与 PDF 版共用同一口径）.

调用方传入两个格式化函数：
- B(raw): 加粗原文（内部自行转义；HTML 版 <b>，PDF 版 ReportLab <b>）
- T(raw): 普通原文（内部自行转义）

纪律：数字全部来自 score/metrics，不编造；缺数标"—"；
"不构成投资建议"与字段来源标注保留在各报告的免责声明区，这里只写诚实提醒。
"""

from __future__ import annotations


def _money(x):
    return "—" if x is None else f"${x:,.0f}"


def _pct(x, digits=1):
    return "—" if x is None else f"{x * 100:.{digits}f}%"


def _num(x, digits=2):
    return "—" if x is None else f"{x:.{digits}f}"


GRADE_SENTENCE = {
    "A": "各项硬指标都在安全区内，这是一笔可以直接推进尽调的交易。",
    "B": "基本面成立，但有明确的失分项——先补短板，再谈推进。",
    "C": "先放进观察名单；等条件变化（降价、条款松动）再拿出来重算。",
    "不收录": "按当前条件数字算不过来，不建议推进；除非重谈价格或结构。",
    "否决": "触发了一票否决项，按当前结构这笔交易不能做。",
}

RENT_SOURCE_LABEL = {
    "comps_verified": "实测 comps",
    "estimated": "估算（未核实，不进 A 级）",
    "proforma": "pro-forma（卖方自嗨）",
}


def _track_cn(track: str) -> str:
    return "住宅" if track == "residential" else "商业"


def _struct_label(s: dict) -> str:
    return s.get("structure_label") or s.get("asset_label") or ""


def lead_paragraphs(p: dict, B, T) -> list:
    """导语：这笔交易是什么 + 关键数字 + 评分定性。"""
    s = p["score"]
    m = s["metrics"]
    track = p["track"]
    d_in = p.get("input") or {}
    struct = _struct_label(s)
    price = _money(d_in.get("price"))

    if track == "residential":
        cf_txt = f"月净现金流{T(_money(m.get('cash_flow_monthly')))}"
    else:
        cf_txt = f"年净现金流{T(_money(m.get('net_cf_annual')))}"

    p1 = (
        f"{T('这是一笔位于')}{B(p['address'])}{T('的' + _track_cn(track) + '交易')}"
        + (f"{T('（' + struct + '）')}" if struct else "")
        + f"{T('，要价')}{B(price)}{T('。按保守全口径测算：全口径现金需求')}"
        + f"{B(_money(m.get('total_cash_required')))}"
        + f"{T('，' + cf_txt + '，DSCR ' + _num(m.get('dscr')) + '，Cash-on-cash ' + _pct(m.get('cash_on_cash')) + '。')}"
    )
    grade = s["grade"]
    p2 = (
        f"{T('DealDesk 综合评分')}{B(str(s['total']) + ' 分')}{T('（' + grade + '）。')}"
        f"{T(GRADE_SENTENCE.get(grade, ''))}"
        f"{T('下面先看否决项与测算，再看这一分一分是怎么拿到的。')}"
    )
    return [p1, p2]


def _worst_dimension(s: dict):
    dims = s.get("dimensions") or []
    if not dims:
        return None
    return max(dims, key=lambda d: (d.get("weight") or 0) - (d.get("points") or 0))


def conclusion_paragraphs(p: dict, B, T) -> list:
    """结论： verdict + 丢分在哪 + 下一步 + 诚实提醒。"""
    s = p["score"]
    grade = s["grade"]
    vetoes = s.get("vetoes") or []
    dgs = s.get("downgrades") or []
    out = []

    if grade == "否决":
        msgs = "；".join(v["message"] for v in vetoes[:3])
        out.append(
            f"{B('结论：一票否决，不推进。')}"
            f"{T('硬伤：' + msgs + '。在这些问题解决之前，不谈价、不进场。')}"
        )
    elif grade == "A":
        tail = ""
        if dgs:
            tail = T("降级提示有 " + "；".join(d["message"] for d in dgs[:2]) + "，进场前逐项关掉。")
        out.append(
            f"{B('结论：推进。')}"
            f"{T('无否决项，现金流与条款都在安全区。建议进日报头条，并行推进：约卖方谈排他、约 title 查产权、把测算里的假设项列成尽调清单逐项验证。')}"
            f"{tail}"
        )
    elif grade == "B":
        out.append(
            f"{B('结论：值得跟，先补短板。')}"
            f"{T('基本面成立，但失分项明确（见下）。把短板补上或谈下来，再进日报收录；补不上就降到观察名单。')}"
        )
    elif grade == "C":
        out.append(
            f"{B('结论：先观察，不主动推进。')}"
            f"{T('当前条件够不上收录线。设个价格/条款闹钟：卖方松动（降价、降首付、延长账期）时再拿出来重算。')}"
        )
    else:  # 不收录
        out.append(
            f"{B('结论：按当前条件放弃。')}"
            f"{T('数字算不过来，硬推进只会亏时间。除非价格或结构重谈，否则不回头。')}"
        )

    worst = _worst_dimension(s)
    if worst and grade != "否决":
        lost = (worst.get("weight") or 0) - (worst.get("points") or 0)
        out.append(
            f"{T('丢分最多的维度是「' + worst.get('label', '') + '」（')}"
            f"{B(str(worst.get('points')) + ' / ' + str(worst.get('weight')) + ' 分')}"
            f"{T('，少拿 ' + ('%.0f' % lost) + ' 分）。' + worst.get('detail', ''))}"
        )

    # 诚实提醒：数据来源
    d_in = p.get("input") or {}
    src_bits = []
    rs = d_in.get("rent_source")
    if rs:
        src_bits.append("租金依据：" + RENT_SOURCE_LABEL.get(rs, rs))
    noi_ev = d_in.get("noi_evidence")
    if noi_ev:
        src_bits.append("NOI 依据：" + str(noi_ev))
    if src_bits:
        out.append(T("数据来源提醒：" + "；".join(src_bits) + "。标“估算”的数字只是测算假设，未核实项不得作为决策依据。"))
    return out
