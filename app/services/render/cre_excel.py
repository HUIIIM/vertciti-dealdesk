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
from app.domain.v2.cre.waterfall import describe as describe_waterfall


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


def _commercial_info(cre: JSON) -> list[tuple[str, Any, str | None]]:
    mk, ox = cre["market"], cre["opex"]
    return [
        ("市场租金 $/SF/年", mk["rent_psf_yr"], "0.00"), ("市场租金增长", mk["rent_growth_pct"] / 100, PCT),
        ("续租概率", mk["renewal_prob_pct"] / 100, PCT), ("新租空置月数", mk["downtime_months"], "0.0"),
        ("新租 / 续租免租月", f"{mk['free_rent_new_months']:g} / {mk['free_rent_renew_months']:g}", None),
        ("新租 / 续租 TI $/SF", f"{mk['ti_new_psf']:g} / {mk['ti_renew_psf']:g}", None),
        ("新租 / 续租 LC", f"{mk['lc_new_pct']:g}% / {mk['lc_renew_pct']:g}%", None),
        ("新租期（年）", mk["lease_term_years"], None), ("新租递增", mk["escalation_pct"] / 100, PCT),
        ("可回收费用 $/SF/年", ox["recoverable_psf_yr"], "0.00"),
        ("不可回收费用 $/SF/年", ox["non_recoverable_psf_yr"], "0.00"),
        ("费用增长", ox["growth_pct"] / 100, PCT), ("管理费（占有效总收入）", ox["mgmt_fee_pct_egr"] / 100, PCT),
        ("资本储备 $/SF/年", ox["reserves_psf_yr"], "0.00"),
    ]


def _mf_info(cre: JSON) -> list[tuple[str, Any, str | None]]:
    mf, ox = cre["multifamily"], cre["opex"]
    return [
        ("物业类型", "多户公寓（按户型）", None), ("总户数", sum(u["units"] for u in cre["unit_mix"]), "0"),
        ("市场租金增长", mf["rent_growth_pct"] / 100, PCT), ("租期（月，在租租约均匀到期）", mf["lease_term_months"], "0"),
        ("租金优惠（占在租租金）", mf["concessions_pct"] / 100, PCT), ("不产生租金的户数", mf["non_revenue_units"], "0"),
        ("其他收入（每户每月）", mf["other_income_per_unit"], MONEY),
        ("其他收入增长", mf["other_income_growth_pct"] / 100, PCT),
        ("年换租率 / 每次翻房成本", f"{mf['turnover_pct']:g}% / ${mf['make_ready_per_turn']:,.0f}", None),
        ("运营费用（每户每年）", mf["opex_per_unit_yr"], MONEY), ("房产税（全年）", mf["taxes_yr"], MONEY),
        ("保险（全年）", mf["insurance_yr"], MONEY), ("费用增长", ox["growth_pct"] / 100, PCT),
        ("管理费（占有效总收入）", ox["mgmt_fee_pct_egr"] / 100, PCT),
        ("资本储备（每户每年）", mf["reserves_per_unit_yr"], MONEY),
        ("翻新：开工月 / 每月户数 / 停用月", f"第 {mf['reno_start_month']} 月 / {mf['reno_units_per_month']} 户 / "
                                     f"{mf['reno_downtime_months']} 个月", None),
    ]


_SIZED = {"ltv": "LTV", "dscr": "最低 DSCR", "debt_yield": "最低债务收益率"}


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
    fee = m["equity"] - cre["purchase_price"] * (1 + cre["closing_costs_pct"] / 100) + m["loan_amount"] + m["mezz_amount"]
    _put(ws, 11, 1, "交割时贷款（优先 + 夹层）")
    _put(ws, 11, 2, m["loan_amount"] + m["mezz_amount"], ENGINE, MONEY)
    _put(ws, 12, 1, "开办费（优先 + 夹层）")
    _put(ws, 12, 2, fee, ENGINE, MONEY)
    _put(ws, 13, 1, "退出时贷款余额（含再融资后的新贷款、夹层）")
    _put(ws, 13, 2, r["exit"]["loan_payoff"], ENGINE, MONEY)
    d = cre.get("debt")
    debt_rows: list[tuple[str, Any]] = []
    if d:
        rate = (f"固定 {d.get('rate_pct', 6.5):g}%" if d.get("rate_type", "fixed") == "fixed" else
                f"浮动：SOFR {', '.join(f'{x:g}%' for x in d['sofr_curve_pct'])} + {d.get('spread_bps', 250):g}bp"
                + (f"，上限 {d['cap_strike_pct']:g}%" if d.get("cap_strike_pct") is not None else ""))
        debt_rows = [("利率", rate), ("只付息月数", d.get("io_months", 0)), ("摊还年限", d.get("amort_years", 30))]
    else:
        debt_rows = [("优先贷款", "无")]
    if cre.get("mezz"):
        mz = cre["mezz"]
        debt_rows.append(("夹层", f"${m['mezz_amount']:,.0f}，固定 {mz['rate_pct']:g}%，只付息"))
    cons = r.get("construction")
    if cons:
        cl, dv = cre["construction_loan"], cre["development"]
        debt_rows += [("开发", f"施工 {dv['construction_months']} 个月；总成本 ${cons['total_cost']:,.0f}"),
                      ("施工贷", f"LTC {cl['ltc_pct']:g}%（承诺 ${cons['commitment']:,.0f}），{cl['rate_pct']:g}%，"
                                 f"资本化利息 ${cons['capitalized_interest']:,.0f}，峰值 ${cons['peak_balance']:,.0f}")]
    elif cre.get("development"):
        debt_rows.append(("开发", f"施工 {cre['development']['construction_months']} 个月，全股权"))
    refi = r.get("refinance")
    if refi:
        debt_rows += [("再融资", f"第 {refi['month']} 月：新贷款 ${refi['amount']:,.0f}（按{_SIZED[refi['sized_by']]}限额），"
                                f"利率 {refi['rate_pct']:g}%"),
                      ("再融资净所得", f"${refi['net']:,.0f}（偿还 ${refi['repaid']:,.0f}、费用 ${refi['costs']:,.0f}）")]
    row = 14
    for label, v in debt_rows:
        _put(ws, row, 1, label)
        _put(ws, row, 2, v, ENGINE)
        row += 1
    row += 1
    _section(ws, row, "物业与市场假设（引擎输入，供核对）", 3)
    common: list[tuple[str, Any, str | None]] = [
        ("分析起点（交割月）", cre["analysis_start"], None), ("持有年限", cre["hold_years"], None),
        ("退出 NOI 口径", "稳定化（加回周转空置与免租）" if cre["exit_noi_basis"] == "stabilized" else "第 N+1 年 NOI 原值", None),
        ("可租面积 SF", cre["area_sf"], MONEY), ("一般空置率", cre["general_vacancy_pct"] / 100, PCT),
        ("信用损失率", cre["credit_loss_pct"] / 100, PCT),
    ]
    info = common + (_mf_info(cre) if cre["property_type"] == "multifamily" else _commercial_info(cre))
    for label, v, info_fmt in info:
        row += 1
        _put(ws, row, 1, label)
        _put(ws, row, 2, v, ENGINE, info_fmt)


# 现金流页的行：(科目键, 标签, 取值)。取值 "v" = 引擎值；元组 = 这些科目相加的 Excel 公式；"after" / "dscr" 为专用公式。
Formula = str | tuple[str, ...]
_DEBT_ROWS: list[tuple[str, str, Formula]] = [
    ("debt_service", "还本付息（优先 + 夹层）", "v"),
    ("refi_proceeds", "再融资净所得", "v"),
    ("construction_draws", "施工贷提款", "v"),
    ("cf_after_debt", "债后现金流（有杠杆）", "after"),
    ("dscr", "DSCR", "dscr"),
    ("occupancy_pct", "平均出租率", "v"),
]
_COMMERCIAL_ROWS: list[tuple[str, str, Formula]] = [
    ("potential_rent", "潜在租金（含空置面积按市场应收）", "v"),
    ("turnover_vacancy", "周转空置", "v"),
    ("base_rent", "基本租金", "v"),
    ("free_rent", "免租", "v"),
    ("recoveries", "费用回收", "v"),
    ("general_vacancy", "一般空置（已扣周转空置）", "v"),
    ("credit_loss", "信用损失", "v"),
    ("egr", "有效总收入 EGR", ("base_rent", "free_rent", "recoveries", "general_vacancy", "credit_loss")),
    ("opex_recoverable", "可回收费用", "v"),
    ("opex_non_recoverable", "不可回收费用", "v"),
    ("mgmt_fee", "管理费", "v"),
    ("opex", "运营费用合计", ("opex_recoverable", "opex_non_recoverable", "mgmt_fee")),
    ("noi", "净营业收入 NOI", ("egr", "opex")),
    ("ti", "租户改造 TI", "v"),
    ("lc", "租赁佣金 LC", "v"),
    ("reserves", "资本储备", "v"),
    ("dev_costs", "开发成本（施工期）", "v"),
    ("cf_before_debt", "债前现金流（无杠杆）", ("noi", "ti", "lc", "reserves", "dev_costs")),
    *_DEBT_ROWS,
]
_MULTIFAMILY_ROWS: list[tuple[str, str, Formula]] = [
    ("potential_rent", "潜在租金 GPR（全部户按市场租金）", "v"),
    ("loss_to_lease", "Loss-to-lease（在租低于市场）", "v"),
    ("premium", "翻新溢价", "v"),
    ("turnover_vacancy", "翻新停用", "v"),
    ("non_revenue", "不产生租金的户", "v"),
    ("base_rent", "在租租金", ("potential_rent", "loss_to_lease", "premium", "turnover_vacancy", "non_revenue")),
    ("free_rent", "租金优惠", "v"),
    ("general_vacancy", "空置", "v"),
    ("credit_loss", "坏账", "v"),
    ("recoveries", "其他收入（停车、RUBS、杂费）", "v"),
    ("egr", "有效总收入 EGR", ("base_rent", "free_rent", "general_vacancy", "credit_loss", "recoveries")),
    ("opex_recoverable", "房产税与保险", "v"),
    ("opex_non_recoverable", "运营费用（人工、维修、公用事业、翻房等）", "v"),
    ("mgmt_fee", "管理费", "v"),
    ("opex", "运营费用合计", ("opex_recoverable", "opex_non_recoverable", "mgmt_fee")),
    ("noi", "净营业收入 NOI", ("egr", "opex")),
    ("capex", "翻新资本支出", "v"),
    ("reserves", "资本储备", "v"),
    ("dev_costs", "开发成本（施工期）", "v"),
    ("cf_before_debt", "债前现金流（无杠杆）", ("noi", "capex", "reserves", "dev_costs")),
    *_DEBT_ROWS,
]


def cf_rows(property_type: str) -> list[tuple[str, str, Formula]]:
    return _MULTIFAMILY_ROWS if property_type == "multifamily" else _COMMERCIAL_ROWS


def row_index(property_type: str) -> dict[str, int]:
    """现金流页每个科目所在行（第 1、2 行是表头）。"""
    return {key: i for i, (key, _, _) in enumerate(cf_rows(property_type), start=3)}


ROW = row_index("commercial")


def _formula(kind: Formula, row: dict[str, int], c: str) -> str:
    if kind == "after":
        return (f"={c}{row['cf_before_debt']}-{c}{row['debt_service']}+{c}{row['refi_proceeds']}"
                f"+{c}{row['construction_draws']}")
    if kind == "dscr":
        return f'=IF({c}{row["debt_service"]}=0,"",{c}{row["noi"]}/{c}{row["debt_service"]})'
    rows = [row[k] for k in kind]
    if len(rows) > 2 and rows == list(range(rows[0], rows[0] + len(rows))):
        return f"=SUM({c}{rows[0]}:{c}{rows[-1]})"
    return "=" + "+".join(f"{c}{x}" for x in rows)


def _cashflow(ws: Worksheet, cre: JSON, r: JSON) -> None:
    n = cre["hold_years"]
    ann = r["annual"]
    row = row_index(cre["property_type"])
    _hdr(ws, 1, ["科目（美元）", *[f"第{y}年" for y in range(1, n + 1)], f"第{n + 1}年（退出用）"])
    _put(ws, 2, 1, "灰字 = 引擎测算（按月汇总）；黑字 = Excel 公式", NOTE)
    for i in range(1, n + 2):
        _put(ws, 2, i + 1, month_label(cre["analysis_start"], (i - 1) * 12), NOTE)
        ws.cell(row=2, column=i + 1).alignment = Alignment(horizontal="center")
    ws.column_dimensions["A"].width = 40
    bold_rows = {"egr", "noi", "cf_before_debt", "cf_after_debt"}
    for key, label, kind in cf_rows(cre["property_type"]):
        r_i = row[key]
        _put(ws, r_i, 1, label, BOLD if key in bold_rows else BODY)
        for y in range(n + 1):
            col = y + 2
            if kind == "v":
                v = ann[key][y]
                fmt = PCT if key == "occupancy_pct" else MONEY
                _put(ws, r_i, col, v / 100 if key == "occupancy_pct" else v, ENGINE, fmt)
            else:
                _put(ws, r_i, col, _formula(kind, row, _col(col)), BOLD if key in bold_rows else BODY,
                     X if key == "dscr" else MONEY)
        if key in ("debt_service", "refi_proceeds", "construction_draws", "cf_after_debt", "dscr"):  # 第 N+1 年只用于退出 NOI，不计债务
            ws.cell(row=r_i, column=n + 2).value = None
    for col in range(2, n + 3):
        ws.column_dimensions[_col(col)].width = 14
    ws.freeze_panes = "B3"


def _returns(ws: Worksheet, cre: JSON, r: JSON) -> None:
    ROW = row_index(cre["property_type"])  # noqa: N806 — 与模块级 ROW 同义，按物业类型取
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
    dv = cre.get("development")
    first = _col(int(m["dscr_from_year"]) + 1)   # 开发项目：DSCR 从长期贷款的第一个整年起算（与引擎同口径）
    dscr_rng = _ref(CF, f"{first}{ROW['dscr']}:{hold_col}{ROW['dscr']}")

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
        ("进入资本化率", "" if dv else f"={noi1}/{p}", pct(m["going_in_cap_pct"]), PCT),
        ("成本收益率", "" if dv else f"={noi1}/({acq})", pct(m["yield_on_cost_pct"]), PCT),
        ("债务收益率（开发：稳定 NOI ÷ 长期贷款，引擎）" if dv else "债务收益率（优先贷款）",
         "" if dv else f'=IF({m["loan_amount"]}=0,"",{noi1}/{m["loan_amount"]})', pct(m["debt_yield_pct"]), PCT),
        ("首年 DSCR", "" if dv else f"={_ref(CF, 'B' + str(ROW['dscr']))}", m["dscr_year1"], X),
        ("持有期最小 DSCR", f'=IF(COUNT({dscr_rng})=0,"",MIN({dscr_rng}))', m["dscr_min"], X),
        ("首年现金回报", "" if dv else f"={ds1}/-B13", pct(m["cash_on_cash_year1_pct"]), PCT),
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


def _unit_mix(ws: Worksheet, r: JSON) -> None:
    _hdr(ws, 1, ["户型", "户数", "户均面积 SF", "在租月租", "市场月租", "Loss-to-lease", "翻新户数", "每户翻新成本",
                 "翻新溢价 / 月"])
    rows = r["unit_mix"]
    for i, u in enumerate(rows, start=2):
        vals = [u["name"], u["units"], u["avg_sf"], u["in_place_rent"], u["market_rent"], u["loss_to_lease_pct"] / 100,
                u["renovate_units"], u["reno_cost_per_unit"], u["reno_premium"]]
        for c, (v, fmt) in enumerate(zip(vals, (None, "0", MONEY, MONEY, MONEY, PCT, "0", MONEY, MONEY), strict=True), 1):
            _put(ws, i, c, v, BODY, fmt)
    total = len(rows) + 2
    _put(ws, total, 1, "合计 / 按户数加权", BOLD)
    _put(ws, total, 2, f"=SUM(B2:B{total - 1})", BOLD, "0")
    for col in ("C", "D", "E"):
        _put(ws, total, "CDE".index(col) + 3, f"=SUMPRODUCT($B2:$B{total - 1},{col}2:{col}{total - 1})/B{total}", BOLD, MONEY)
    _put(ws, total, 6, f"=(E{total}-D{total})/E{total}", BOLD, PCT)
    _put(ws, total, 7, f"=SUM(G2:G{total - 1})", BOLD, "0")
    for letter, w in zip("ABCDEFGHI", (14, 8, 12, 11, 11, 13, 10, 13, 13), strict=True):
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
    monthly = w["frequency"] == "monthly"
    _put(ws, 1, 1, "GP / LP 分配瀑布（按 LP IRR 门槛）", Font(name=_F, size=13, bold=True))
    _put(ws, 2, 1, describe_waterfall(w) + ("各年 LP / GP 为按月分配的年度合计。" if monthly else ""), NOTE)
    _hdr(ws, 4, ["年", "有杠杆现金流", "LP", "GP", "核对 LP+GP−现金流"])
    lev = r["flows"]["levered"]
    for t in range(len(lev)):
        row = t + 5
        _put(ws, row, 1, f"第{t}年")
        _put(ws, row, 2, f"='{RET}'!{_col(t + 2)}13", BODY, MONEY)
        _put(ws, row, 3, wf["lp_annual"][t], ENGINE, MONEY)
        _put(ws, row, 4, wf["gp_annual"][t], ENGINE, MONEY)
        _put(ws, row, 5, f"=C{row}+D{row}-B{row}", BODY, MONEY)
    end = len(lev) + 4
    row = end + 2

    def pct(x: float | None) -> float | None:
        return None if x is None else x / 100

    for label, f, v, fmt in [
        ("LP IRR" + ("（Excel 按年度合计；引擎按月年化）" if monthly else ""), f"=IRR(C5:C{end})", pct(wf["lp_irr_pct"]), PCT),
        ("GP IRR" + ("（同上）" if monthly else ""), f"=IRR(D5:D{end})", pct(wf["gp_irr_pct"]), PCT),
        ("LP 权益倍数", f'=SUMIF(C5:C{end},">0")/-SUMIF(C5:C{end},"<0")', wf["lp_multiple"], X),
        ("GP 权益倍数", f'=SUMIF(D5:D{end},">0")/-SUMIF(D5:D{end},"<0")', wf["gp_multiple"], X),
        ("GP promote（超出出资比例部分，已扣回拨）", "", wf["gp_promote"], MONEY),
        ("回拨（clawback）", "", wf["clawback"], MONEY),
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
    "本版不建模：CPI 递增、百分比租金、费用上限 / gross-up、施工贷、开发期、欧式（整只基金）瀑布。",
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
    if cre["property_type"] == "multifamily":
        _unit_mix(wb.create_sheet("户型表"), r)
    else:
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
