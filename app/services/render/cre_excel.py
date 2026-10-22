"""机构级承销模型 Excel（openpyxl）：引擎测算 + Excel 原生公式，改关键假设即在 Excel 里重算。

口径与 cre-1.0 引擎（app/domain/v2/cre/）一致：
- 物业层逐科目（租金、空置、回收、费用、TI / LC、储备）与还本付息是引擎按月测算后按年汇总的值（灰字）；
- 有效总收入、费用合计、NOI、债前 / 债后现金流、DSCR、售价、无杠杆 / 有杠杆现金流、IRR、倍数、NPV、
  资本化率、债务收益率都是 Excel 公式（黑字），引用“假设”页的可改输入（蓝字黄底）。
- 可改输入：收购价、交割成本、退出资本化率、卖方成本、折现率。贷款额与还本付息按引擎的贷款计划固定
  （浮动利率、利率上限、只付息期都在引擎里算），改贷款条款要回到 DealDesk 重跑。
“收益”页每个指标旁列出引擎结果，不改输入时两者一致（测试用 LibreOffice 重算核对）。缺数留空，不编数。
"""
from __future__ import annotations

import io
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.core import brand

JSON = dict[str, Any]

_F = "Microsoft YaHei"
HDR_FILL = PatternFill("solid", fgColor=brand.INK[1:])
HDR_FONT = Font(bold=True, color=brand.PAPER[1:], name=_F, size=10)
SUB_FILL = PatternFill("solid", fgColor=brand.MIST[1:])
SUB_FONT = Font(bold=True, color=brand.ORANGE_TEXT[1:], name=_F, size=10)
BODY = Font(name=_F, size=10)
BOLD = Font(name=_F, size=10, bold=True)
ENGINE = Font(name=_F, size=10, color=brand.STONE[1:])  # 引擎测算值
INPUT = Font(name=_F, size=10, bold=True, color="1F4E9E")  # 可改输入（蓝字，行业惯例）
INPUT_FILL = PatternFill("solid", fgColor=brand.YELLOW_TINT[1:])
NOTE = Font(name=_F, size=9, color=brand.STONE[1:])
MONEY = '#,##0;(#,##0);"-"'
PCT = "0.00%"
X = '0.00"x"'

A, CF, RET, RR, MO, WF, NOTES = "假设", "现金流", "收益", "租金表", "月度", "瀑布", "说明"


def _ref(sheet: str, cell: str) -> str:
    return f"'{sheet}'!{cell}"


def _col(i: int) -> str:
    return str(get_column_letter(i))


def _put(ws: Worksheet, row: int, col: int, value: Any, font: Font = BODY, fmt: str | None = None,
         fill: PatternFill | None = None) -> None:
    c = ws.cell(row=row, column=col, value=value)
    c.font = font
    if fmt:
        c.number_format = fmt
    if fill:
        c.fill = fill


def _hdr(ws: Worksheet, row: int, labels: list[str]) -> None:
    for i, text in enumerate(labels, start=1):
        _put(ws, row, i, text, HDR_FONT, fill=HDR_FILL)
        ws.cell(row=row, column=i).alignment = Alignment(horizontal="center" if i > 1 else "left")


def _section(ws: Worksheet, row: int, title: str, width: int) -> None:
    for i in range(1, width + 1):
        ws.cell(row=row, column=i).fill = SUB_FILL
    _put(ws, row, 1, title, SUB_FONT, fill=SUB_FILL)


def month_label(start: str, m: int) -> str:
    y, mo = int(start[:4]), int(start[5:7]) - 1 + m
    return f"{y + mo // 12}-{mo % 12 + 1:02d}"


# 假设页固定位置（其他页公式引用）：B4 收购价、B5 交割成本、B6 退出资本化率、B7 卖方成本、B8 折现率；
# B11 贷款额、B12 开办费、B13 退出时贷款余额（后三项为引擎值）


def _assumptions(ws: Worksheet, cre: JSON, r: JSON, meta: JSON) -> None:
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 54
    _put(ws, 1, 1, f"{meta.get('name') or '机构级交易'} · 承销模型", Font(name=_F, size=14, bold=True))
    _put(ws, 2, 1, f"{meta.get('address') or ''}  引擎 {r['engine']} · 第 {meta.get('version_no', '—')} 版 · "
         f"{meta.get('date', '')}", NOTE)
    _section(ws, 3, "可改输入（蓝字黄底：改这里，其余页公式自动重算）", 3)
    m = r["metrics"]
    rows = [
        ("收购价", cre["purchase_price"], MONEY, ""),
        ("交割成本（占收购价）", cre.get("closing_costs_pct", 1.5) / 100, PCT, ""),
        ("退出资本化率", cre["exit_cap_pct"] / 100, PCT, "售价 = 第 N+1 年 NOI ÷ 退出资本化率"),
        ("卖方成本（占售价）", cre.get("selling_costs_pct", 2) / 100, PCT, ""),
        ("折现率", cre.get("discount_rate_pct", 8) / 100, PCT, "用于 NPV"),
    ]
    for i, (label, v, fmt, note) in enumerate(rows, start=4):
        _put(ws, i, 1, label)
        _put(ws, i, 2, v, INPUT, fmt, INPUT_FILL)
        _put(ws, i, 3, note, NOTE)
    _section(ws, 10, "债务（引擎按月贷款计划，固定值；改贷款条款请回 DealDesk 重跑）", 3)
    # 开办费按引擎口径反推：股权 = 收购价 × (1 + 交割成本) + 开办费 − 贷款额
    fee = m["equity"] - cre["purchase_price"] * (1 + cre["closing_costs_pct"] / 100) + m["loan_amount"]
    _put(ws, 11, 1, "贷款额")
    _put(ws, 11, 2, m["loan_amount"], ENGINE, MONEY)
    _put(ws, 12, 1, "开办费")
    _put(ws, 12, 2, fee, ENGINE, MONEY)
    _put(ws, 13, 1, "退出时贷款余额")
    _put(ws, 13, 2, r["exit"]["loan_payoff"], ENGINE, MONEY)
    d = cre.get("debt")
    debt_rows: list[tuple[str, Any]] = []
    if d:
        rate = (f"固定 {d.get('rate_pct', 6.5):g}%" if d.get("rate_type", "fixed") == "fixed" else
                f"浮动：SOFR {', '.join(f'{x:g}%' for x in d['sofr_curve_pct'])} + {d.get('spread_bps', 250):g}bp"
                + (f"，上限 {d['cap_strike_pct']:g}%" if d.get("cap_strike_pct") is not None else ""))
        debt_rows = [("利率", rate), ("只付息月数", d.get("io_months", 0)), ("摊还年限", d.get("amort_years", 30))]
    else:
        debt_rows = [("贷款", "无（全股权）")]
    row = 14
    for label, v in debt_rows:
        _put(ws, row, 1, label)
        _put(ws, row, 2, v, ENGINE)
        row += 1
    row += 1
    _section(ws, row, "物业与市场假设（引擎输入，供核对）", 3)
    mk, ox = cre["market"], cre.get("opex") or {}
    info: list[tuple[str, Any, str | None]] = [
        ("分析起点（交割月）", cre["analysis_start"], None), ("持有年限", cre["hold_years"], None),
        ("退出 NOI 口径", "稳定化（加回周转空置与免租）" if cre["exit_noi_basis"] == "stabilized" else "第 N+1 年 NOI 原值", None),
        ("可租面积 SF", cre["area_sf"], MONEY), ("一般空置率", cre.get("general_vacancy_pct", 5) / 100, PCT),
        ("信用损失率", cre.get("credit_loss_pct", 1) / 100, PCT),
        ("市场租金 $/SF/年", mk["rent_psf_yr"], "0.00"), ("市场租金增长", mk.get("rent_growth_pct", 3) / 100, PCT),
        ("续租概率", mk.get("renewal_prob_pct", 70) / 100, PCT), ("新租空置月数", mk.get("downtime_months", 6), "0.0"),
        ("新租 / 续租免租月", f"{mk.get('free_rent_new_months', 3):g} / {mk.get('free_rent_renew_months', 1):g}", None),
        ("新租 / 续租 TI $/SF", f"{mk.get('ti_new_psf', 30):g} / {mk.get('ti_renew_psf', 10):g}", None),
        ("新租 / 续租 LC", f"{mk.get('lc_new_pct', 6):g}% / {mk.get('lc_renew_pct', 3):g}%", None),
        ("新租期（年）", mk.get("lease_term_years", 5), None), ("新租递增", mk.get("escalation_pct", 3) / 100, PCT),
        ("可回收费用 $/SF/年", ox.get("recoverable_psf_yr", 0), "0.00"),
        ("不可回收费用 $/SF/年", ox.get("non_recoverable_psf_yr", 0), "0.00"),
        ("费用增长", ox.get("growth_pct", 3) / 100, PCT), ("管理费（占有效总收入）", ox.get("mgmt_fee_pct_egr", 3) / 100, PCT),
        ("资本储备 $/SF/年", ox.get("reserves_psf_yr", 0.25), "0.00"),
    ]
    for label, v, info_fmt in info:
        row += 1
        _put(ws, row, 1, label)
        _put(ws, row, 2, v, ENGINE, info_fmt)


# 现金流页行号（公式互相引用）
_CF_ROWS = [
    ("potential_rent", "潜在租金（含空置面积按市场应收）", "v"),
    ("turnover_vacancy", "周转空置", "v"),
    ("base_rent", "基本租金", "v"),
    ("free_rent", "免租", "v"),
    ("recoveries", "费用回收", "v"),
    ("general_vacancy", "一般空置（已扣周转空置）", "v"),
    ("credit_loss", "信用损失", "v"),
    ("egr", "有效总收入 EGR", "=SUM({c}5:{c}9)"),
    ("opex_recoverable", "可回收费用", "v"),
    ("opex_non_recoverable", "不可回收费用", "v"),
    ("mgmt_fee", "管理费", "v"),
    ("opex", "运营费用合计", "=SUM({c}11:{c}13)"),
    ("noi", "净营业收入 NOI", "={c}10+{c}14"),
    ("ti", "租户改造 TI", "v"),
    ("lc", "租赁佣金 LC", "v"),
    ("reserves", "资本储备", "v"),
    ("cf_before_debt", "债前现金流（无杠杆）", "={c}15+{c}16+{c}17+{c}18"),
    ("debt_service", "还本付息", "v"),
    ("cf_after_debt", "债后现金流（有杠杆）", "={c}19-{c}20"),
    ("dscr", "DSCR", '=IF({c}20=0,"",{c}15/{c}20)'),
    ("occupancy_pct", "平均出租率", "v"),
]
ROW = {key: i for i, (key, _, _) in enumerate(_CF_ROWS, start=3)}


def _cashflow(ws: Worksheet, cre: JSON, r: JSON) -> None:
    n = cre["hold_years"]
    ann = r["annual"]
    _hdr(ws, 1, ["科目（美元）", *[f"第{y}年" for y in range(1, n + 1)], f"第{n + 1}年（退出用）"])
    _put(ws, 2, 1, "灰字 = 引擎测算（按月汇总）；黑字 = Excel 公式", NOTE)
    for i in range(1, n + 2):
        _put(ws, 2, i + 1, month_label(cre["analysis_start"], (i - 1) * 12), NOTE)
        ws.cell(row=2, column=i + 1).alignment = Alignment(horizontal="center")
    ws.column_dimensions["A"].width = 34
    bold_rows = {"egr", "noi", "cf_before_debt", "cf_after_debt"}
    for key, label, kind in _CF_ROWS:
        row = ROW[key]
        _put(ws, row, 1, label, BOLD if key in bold_rows else BODY)
        for y in range(n + 1):
            col = y + 2
            c = _col(col)
            if kind == "v":
                v = ann[key][y]
                fmt = PCT if key == "occupancy_pct" else MONEY
                _put(ws, row, col, v / 100 if key == "occupancy_pct" else v, ENGINE, fmt)
            else:
                _put(ws, row, col, kind.format(c=c), BOLD if key in bold_rows else BODY,
                     X if key == "dscr" else MONEY)
        if key in ("debt_service", "cf_after_debt", "dscr"):  # 第 N+1 年只用于退出 NOI，不计债务
            ws.cell(row=row, column=n + 2).value = None
    for col in range(2, n + 3):
        ws.column_dimensions[_col(col)].width = 14
    ws.freeze_panes = "B3"


def _returns(ws: Worksheet, cre: JSON, r: JSON) -> None:
    n = cre["hold_years"]
    m, ex = r["metrics"], r["exit"]
    fwd_col, hold_col = _col(n + 2), _col(n + 1)  # 现金流页：B = 第 1 年 → 第 N 年在第 n+1 列，第 N+1 年在第 n+2 列
    p, cc = _ref(A, "$B$4"), _ref(A, "$B$5")
    ws.column_dimensions["A"].width = 30
    for col in range(2, n + 3):
        ws.column_dimensions[_col(col)].width = 15
    _put(ws, 1, 1, "退出与收益", Font(name=_F, size=13, bold=True))
    _hdr(ws, 2, ["退出", "Excel 公式", "引擎结果"])
    exit_rows: list[tuple[str, str, Any, str]] = [
        (("退出年 NOI（第 N+1 年）", f"={_ref(CF, fwd_col + str(ROW['noi']))}", m["forward_noi"], MONEY)
         if cre["exit_noi_basis"] == "forward" else
         ("退出年稳定化 NOI（引擎：加回周转空置与免租）", f"={m['forward_noi']}", m["forward_noi"], MONEY)),
        ("退出资本化率", f"={_ref(A, '$B$6')}", cre["exit_cap_pct"] / 100, PCT),
        ("售价", "=B3/B4", ex["sale_price"], MONEY),
        ("卖方成本", f"=B5*{_ref(A, '$B$7')}", ex["selling_costs"], MONEY),
        ("贷款余额偿还（引擎）", f"={_ref(A, '$B$13')}", ex["loan_payoff"], MONEY),
        ("净售价（无杠杆）", "=B5-B6", ex["sale_price"] - ex["selling_costs"], MONEY),
        ("净售价（有杠杆）", "=B8-B7", ex["net_proceeds_levered"], MONEY),
    ]
    for i, (label, f, v, fmt) in enumerate(exit_rows, start=3):
        _put(ws, i, 1, label)
        _put(ws, i, 2, f, BODY, fmt)
        _put(ws, i, 3, v, ENGINE, fmt)
    # 现金流序列：B = 第 0 年，C.. = 第 1..N 年
    _hdr(ws, 11, ["现金流", *[f"第{y}年" for y in range(n + 1)]])
    acq = f"{p}*(1+{cc})"
    _put(ws, 12, 1, "无杠杆现金流", BOLD)
    _put(ws, 12, 2, f"=-{acq}", BODY, MONEY)
    _put(ws, 13, 1, "有杠杆现金流", BOLD)
    _put(ws, 13, 2, f"=-({acq}+{_ref(A, '$B$12')}-{_ref(A, '$B$11')})", BODY, MONEY)
    for y in range(1, n + 1):
        src = _col(y + 1)
        tail_u = "+$B$8" if y == n else ""
        tail_l = "+$B$9" if y == n else ""
        _put(ws, 12, y + 2, f"={_ref(CF, src + str(ROW['cf_before_debt']))}{tail_u}", BODY, MONEY)
        _put(ws, 13, y + 2, f"={_ref(CF, src + str(ROW['cf_after_debt']))}{tail_l}", BODY, MONEY)
    end = _col(n + 2)
    u, lv = f"B12:{end}12", f"B13:{end}13"
    _hdr(ws, 15, ["收益指标", "Excel 公式", "引擎结果"])
    noi1, ds1 = _ref(CF, f"B{ROW['noi']}"), _ref(CF, f"B{ROW['cf_after_debt']}")
    loan = _ref(A, "$B$11")
    rate = _ref(A, "$B$8")
    dscr_rng = _ref(CF, f"B{ROW['dscr']}:{hold_col}{ROW['dscr']}")

    def pct(x: float | None) -> float | None:
        return None if x is None else x / 100

    rows: list[tuple[str, str, Any, str]] = [
        ("无杠杆 IRR（年度）", f"=IRR({u})", pct(m["unlevered_irr_pct"]), PCT),
        ("有杠杆 IRR（年度）", f"=IRR({lv})", pct(m["levered_irr_pct"]), PCT),
        ("无杠杆 IRR（按月年化，引擎）", "", pct(m["unlevered_irr_monthly_pct"]), PCT),
        ("有杠杆 IRR（按月年化，引擎）", "", pct(m["levered_irr_monthly_pct"]), PCT),
        ("无杠杆权益倍数", f'=SUMIF({u},">0")/-SUMIF({u},"<0")', m["unlevered_multiple"], X),
        ("有杠杆权益倍数", f'=SUMIF({lv},">0")/-SUMIF({lv},"<0")', m["levered_multiple"], X),
        ("无杠杆 NPV", f"=B12+NPV({rate},C12:{end}12)", m["unlevered_npv"], MONEY),
        ("有杠杆 NPV", f"=B13+NPV({rate},C13:{end}13)", m["levered_npv"], MONEY),
        ("进入资本化率", f"={noi1}/{p}", pct(m["going_in_cap_pct"]), PCT),
        ("成本收益率", f"={noi1}/({acq})", pct(m["yield_on_cost_pct"]), PCT),
        ("债务收益率", f'=IF({loan}=0,"",{noi1}/{loan})', pct(m["debt_yield_pct"]), PCT),
        ("首年 DSCR", f"={_ref(CF, 'B' + str(ROW['dscr']))}", m["dscr_year1"], X),
        ("持有期最小 DSCR", f'=IF(COUNT({dscr_rng})=0,"",MIN({dscr_rng}))', m["dscr_min"], X),
        ("首年现金回报", f"={ds1}/-B13", pct(m["cash_on_cash_year1_pct"]), PCT),
        ("股权投入", "=-B13", m["equity"], MONEY),
    ]
    for i, (label, f, v, fmt) in enumerate(rows, start=16):
        _put(ws, i, 1, label)
        if f:
            _put(ws, i, 2, f, BOLD, fmt)
        _put(ws, i, 3, v, ENGINE, fmt)
    _put(ws, 16 + len(rows) + 1, 1, "不改输入时 Excel 公式与引擎结果一致；改了“假设”页蓝字后，引擎列保留原值供对照。", NOTE)
    ws.freeze_panes = "B3"


def _rent_roll(ws: Worksheet, cre: JSON, r: JSON) -> None:
    _hdr(ws, 1, ["租户", "单元", "面积 SF", "起租", "到期", "起租租金 $/SF/年", "性质", "此前空置月", "TI", "LC"])
    start = cre["analysis_start"]
    for i, s in enumerate(r["rent_roll"], start=2):
        vals = [s["tenant"], s["suite"], s["sf"], month_label(start, s["start"]), month_label(start, s["end"]),
                s["rent_psf"], "假设续上（MLA）" if s["speculative"] else "已签约", s["downtime_before"], s["ti"], s["lc"]]
        fmts = [None, None, MONEY, None, None, "0.00", None, "0", MONEY, MONEY]
        for c, (v, fmt) in enumerate(zip(vals, fmts, strict=True), start=1):
            _put(ws, i, c, v, ENGINE if s["speculative"] else BODY, fmt)
    for letter, w in zip("ABCDEFGHIJ", (26, 8, 11, 9, 9, 15, 15, 11, 13, 13), strict=True):
        ws.column_dimensions[letter].width = w
    ws.freeze_panes = "A2"


def _monthly(ws: Worksheet, cre: JSON, r: JSON) -> None:
    mo = r["monthly"]
    _hdr(ws, 1, ["月份", "NOI", "债前现金流", "还本付息", "债后现金流", "执行利率", "出租率"])
    for i in range(len(mo["noi"])):
        row = i + 2
        _put(ws, row, 1, month_label(cre["analysis_start"], i))
        _put(ws, row, 2, mo["noi"][i], ENGINE, MONEY)
        _put(ws, row, 3, mo["cf_before_debt"][i], ENGINE, MONEY)
        _put(ws, row, 4, mo["debt_service"][i], ENGINE, MONEY)
        _put(ws, row, 5, f"=C{row}-D{row}", BODY, MONEY)
        _put(ws, row, 6, mo["rate_pct"][i] / 100 if cre.get("debt") else None, ENGINE, PCT)
        _put(ws, row, 7, mo["occupancy_pct"][i] / 100, ENGINE, PCT)
    for c, w in zip("ABCDEFG", (10, 14, 14, 14, 14, 10, 10), strict=True):
        ws.column_dimensions[c].width = w
    ws.freeze_panes = "A2"


def _waterfall(ws: Worksheet, cre: JSON, r: JSON) -> None:
    w, wf = cre["waterfall"], r["waterfall"]
    _put(ws, 1, 1, "GP / LP 分配瀑布（按 LP IRR 门槛，年度）", Font(name=_F, size=13, bold=True))
    tiers = " → ".join([f"{w.get('pref_pct', 8):g}% 优先回报内按出资比例",
                        *(f"{t['irr_pct']:g}% 前 LP {t['lp_share_pct']:g}%" for t in w.get("tiers", [])),
                        f"之上 LP {w.get('final_lp_share_pct', 70):g}%"])
    _put(ws, 2, 1, f"LP 出资 {w.get('lp_equity_pct', 90):g}%；{tiers}", NOTE)
    _hdr(ws, 4, ["年", "有杠杆现金流", "LP", "GP", "核对 LP+GP−现金流"])
    lev = r["flows"]["levered"]
    for t in range(len(lev)):
        row = t + 5
        _put(ws, row, 1, f"第{t}年")
        _put(ws, row, 2, f"='{RET}'!{_col(t + 2)}13", BODY, MONEY)
        _put(ws, row, 3, wf["lp"][t], ENGINE, MONEY)
        _put(ws, row, 4, wf["gp"][t], ENGINE, MONEY)
        _put(ws, row, 5, f"=C{row}+D{row}-B{row}", BODY, MONEY)
    end = len(lev) + 4
    row = end + 2

    def pct(x: float | None) -> float | None:
        return None if x is None else x / 100

    for label, f, v, fmt in [
        ("LP IRR", f"=IRR(C5:C{end})", pct(wf["lp_irr_pct"]), PCT),
        ("GP IRR", f"=IRR(D5:D{end})", pct(wf["gp_irr_pct"]), PCT),
        ("LP 权益倍数", f'=SUMIF(C5:C{end},">0")/-SUMIF(C5:C{end},"<0")', wf["lp_multiple"], X),
        ("GP 权益倍数", f'=SUMIF(D5:D{end},">0")/-SUMIF(D5:D{end},"<0")', wf["gp_multiple"], X),
        ("GP promote（超出出资比例部分）", "", wf["gp_promote"], MONEY),
    ]:
        _put(ws, row, 1, label)
        if f:
            _put(ws, row, 2, f, BOLD, fmt)
        _put(ws, row, 3, v, ENGINE, fmt)
        row += 1
    _put(ws, row + 1, 1, "LP / GP 分配是引擎在原始输入下的结果；改“假设”页后现金流列会变，分配列不变（核对列会出现差额）。", NOTE)
    for c, wd in zip("ABCDE", (30, 16, 16, 16, 18), strict=True):
        ws.column_dimensions[c].width = wd


_NOTES = [
    "机构级承销模型 · 使用说明",
    "",
    "颜色：蓝字黄底 = 可改输入；黑字 = Excel 公式；灰字 = cre-1.0 引擎测算值（逐租约、按月，再按年汇总）。",
    "可改：收购价、交割成本、退出资本化率、卖方成本、折现率——售价、现金流、IRR、倍数、NPV、资本化率随之重算。",
    "不随 Excel 重算的：物业层收入与费用（来自逐租约按月测算）、贷款计划与余额（浮动利率、利率上限、只付息期）、"
    "瀑布分配。这些请改 DealDesk 输入后重新导出。",
    "时间约定：第 0 月月初交割；持有 N 年后在第 N×12 月月末出售；售价按第 N+1 年 NOI ÷ 退出资本化率。",
    "续租：到期后按市场租赁假设（MLA）续上，续租与新租按续租概率加权成一条路径（Argus 默认口径）；"
    "“租金表”页灰字行是假设续上的，不是签约事实。",
    "一般空置先扣除已建模的周转空置，避免重复扣。免租只免基本租金，费用回收照收。",
    "IRR 两种口径：年度现金流 IRR（Excel 可重算）与按月现金流折算的年化 IRR（更精确，引擎值）。",
    "本版不建模：CPI 递增、百分比租金、费用上限 / gross-up、再融资 / 夹层、开发期、GP catch-up 与回拨。",
    "完整方法论：docs/INSTITUTIONAL-ENGINE.md。",
]


def build_cre_xlsx(cre: JSON, r: JSON, meta: JSON) -> bytes:
    """cre = 引擎输入（已过校验的 dict），r = engine.run(cre) 结果，meta = {name, address, version_no, date}。"""
    wb = Workbook()
    ws = wb.active
    ws.title = A
    _assumptions(ws, cre, r, meta)
    _cashflow(wb.create_sheet(CF), cre, r)
    _returns(wb.create_sheet(RET), cre, r)
    _rent_roll(wb.create_sheet(RR), cre, r)
    _monthly(wb.create_sheet(MO), cre, r)
    if cre.get("waterfall") and r.get("waterfall"):
        _waterfall(wb.create_sheet(WF), cre, r)
    notes = wb.create_sheet(NOTES)
    notes.column_dimensions["A"].width = 120
    for i, line in enumerate(_NOTES, start=1):
        _put(notes, i, 1, line, Font(name=_F, size=13, bold=True) if i == 1 else BODY)
        notes.cell(row=i, column=1).alignment = Alignment(wrap_text=True, vertical="top")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
