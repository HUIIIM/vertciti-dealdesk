"""商业核保明细 Excel（openpyxl）.

多 sheet：总览 / 现金流 / comps / 假设。
DSCR / IRR / Equity Multiple 用 Excel 原生公式（改假设可重算），
明细数字为 compute_all() 测算值并标注来源。

调用：POST /api/uw/report/xlsx  ← 只接线，不改 uw_commercial 计算逻辑。
"""

from __future__ import annotations

import io
from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HDR_FILL = PatternFill("solid", fgColor="0F2B26")
HDR_FONT = Font(bold=True, color="E9EFF9", name="Microsoft YaHei", size=11)
SUB_FILL = PatternFill("solid", fgColor="13202B")
SUB_FONT = Font(bold=True, color="2DD4BF", name="Microsoft YaHei", size=11)
BODY_FONT = Font(name="Microsoft YaHei", size=11)
MONEY = '#,##0'
MONEY2 = '$#,##0'
PCT = '0.00%'
THIN = Side(style="thin", color="1D2A45")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _hdr(ws, row, cols):
    for c, text in enumerate(cols, start=1):
        cell = ws.cell(row=row, column=c, value=text)
        cell.font = HDR_FONT
        cell.fill = HDR_FILL
        cell.border = BORDER


def _row(ws, row, a, b=None, c=None, fmt_b=None, bold_a=False, fill=None):
    ca = ws.cell(row=row, column=1, value=a)
    ca.font = Font(name="Microsoft YaHei", size=11, bold=bold_a)
    if fill:
        ca.fill = fill
    for col, val, fmt in ((2, b, fmt_b), (3, c, fmt_b)):
        cell = ws.cell(row=row, column=col, value=val)
        cell.font = BODY_FONT
        if fmt:
            cell.number_format = fmt
        cell.border = BORDER


def _section(ws, row, title):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
    cell = ws.cell(row=row, column=1, value=title)
    cell.font = SUB_FONT
    cell.fill = SUB_FILL
    return row + 1


def _f(x, default=0.0) -> float:
    try:
        v = float(x)
        if v != v or v in (float("inf"), float("-inf")):
            return default
        return v
    except (TypeError, ValueError):
        return default


def build_uw_xlsx(result: dict, inputs: dict, comps: list | None = None,
                  meta: dict | None = None) -> bytes:
    """result=uw_commercial.compute_all() 输出；inputs=原始输入；返回 xlsx bytes."""
    meta = meta or {}
    prop = (result.get("property") or {})
    ana = (result.get("analysis") or {})
    hist = (result.get("historical") or {})
    pro = (result.get("proforma") or {})
    proj = ana.get("projected") or {}
    inpl = ana.get("inplace") or {}
    ex = ana.get("exit") or {}
    wb = Workbook()

    rows_cf = [
        ("租金总收入", "base_rents", MONEY2),
        ("CAM 回收", "cam_recovery", MONEY2),
        ("停车收入", "parking_income", MONEY2),
        ("其他收入", "other_income", MONEY2),
        ("总潜在收入", "total_potential", MONEY2),
        ("空置损失", "vacancy_loss", MONEY2),
        ("有效总收入 EGI", "egi", MONEY2),
        ("总营业费用", "total_expenses", MONEY2),
        ("NOI", "noi", MONEY2),
        ("TI 摊销", "tenant_improvements", MONEY2),
        ("CapEx", "capex", MONEY2),
        ("租赁佣金", "leasing_commissions", MONEY2),
        ("可分配现金流", "cash_flow_avail", MONEY2),
        ("cap rate", "cap_rate", PCT),
    ]
    noi_row_cf = 2 + [k for _, k, _ in rows_cf].index("noi")  # 现金流 sheet 的 NOI 行

    # ---------------- 总览 ----------------
    ws = wb.active
    ws.title = "总览"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    _hdr(ws, 1, ["项目", "数值", "说明"])
    r = 2
    r = _section(ws, r, "物业")
    for label, val in (("名称", prop.get("name", "")),
                       ("地址", prop.get("address", "")),
                       ("物业类型", prop.get("property_type", "")),
                       ("可租面积 SF", _f(prop.get("net_rentable_sf")),),
                       ("建成年份", prop.get("year_built", "")),
                       ("报告日期", date.today().isoformat()),
                       ("口径", "投资筛选用，非 USPAP 合规评估报告")):
        fmt = MONEY if isinstance(val, float) else None
        _row(ws, r, label, val, None, fmt_b=fmt); r += 1
    r = _section(ws, r, "关键指标（可改黄色格重算）")
    loan_bal = _f(ana.get("loan_bal"))
    debt_svc = _f(ana.get("annual_debt_service"))
    eq_row = r
    _row(ws, r, "收购价 $", _f(ana.get("purchase_price")), None, MONEY2); r += 1
    noi_cell_row = r
    _row(ws, r, "NOI（历史/银行口径前）$",
         _f(hist.get("noi")), "=现金流!B{0}".format(noi_row_cf), MONEY2); r += 1
    ds_cell_row = r
    _row(ws, r, "年还本付息 $", debt_svc, None, MONEY2); r += 1
    dscr_row = r
    _row(ws, r, "DSCR（trailing 主）",
         f"=B{noi_cell_row}/B{ds_cell_row}", "NOI ÷ 年还本付息", PCT, bold_a=True); r += 1
    _row(ws, r, "DSCR（pro forma 辅）",
         _f(proj.get("dscr")), "预测口径 NOI ÷ 年还本付息", PCT); r += 1
    _row(ws, r, "Debt Yield（NOI ÷ 拟贷款额）",
         f"=B{noi_cell_row}/{loan_bal or 1}",
         "银行 sizing 硬约束；≥8-10% 舒适", PCT); r += 1
    _row(ws, r, "拟贷款额 $", loan_bal, None, MONEY2); r += 1
    _row(ws, r, "全口径现金投入 $", _f(ana.get("net_liquidity")),
         "首付＋交割费＋储备金", MONEY2); r += 1
    be_row = r
    _row(ws, r, "盈亏平衡出租率", _f(ana.get("breakeven_occupancy")),
         "(费用＋还本付息＋储备金) ÷ 满租 EGI", PCT); r += 1
    r = _section(ws, r, "退出与回报（原生公式）")
    hold = int(ex.get("hold_years") or 5)
    flows = list(ex.get("cash_flows") or [])
    eq_invest = abs(_f(flows[0])) if flows else _f(ana.get("net_liquidity"))
    _row(ws, r, "持有期（年）", hold, None); r += 1
    _row(ws, r, "初始股权投入 $", eq_invest, None, MONEY2)
    y0_row = r; r += 1
    sched_start = r
    _row(ws, r, f"现金流 Y0", f"=-B{y0_row}", "=-初始投入", MONEY2); r += 1
    annuals = flows[1:] if len(flows) > 1 else []
    for i in range(1, hold + 1):
        v = annuals[i - 1] if i - 1 < len(annuals) else 0.0
        _row(ws, r, f"现金流 Y{i}", v, "Y{0} 含出售所得".format(hold) if i == hold else None, MONEY2)
        r += 1
    sched_end = r - 1
    rng = f"B{sched_start}:B{sched_end}"
    _row(ws, r, "IRR（原生公式）", f"=IRR({rng})",
         "需同时披露退出假设（见假设表）", PCT, bold_a=True); r += 1
    _row(ws, r, "Equity Multiple（原生公式）",
         f"=SUM({rng})/B{y0_row}", "总回收 ÷ 股权投入", "0.00"); r += 1
    _row(ws, r, "退出 cap", _f(ex.get("exit_cap_rate")), None, PCT); r += 1
    _row(ws, r, "预计出售价 $", _f(ex.get("sale_price")), None, MONEY2); r += 1
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 40

    # ---------------- 现金流 ----------------
    cf = wb.create_sheet("现金流")
    _hdr(cf, 1, ["项目", "历史 trailing", "预测 pro forma"])
    r = 2
    for label, key, fmt in rows_cf:
        bold = label in ("有效总收入 EGI", "NOI", "可分配现金流")
        _row(cf, r, label, _f(hist.get(key)), _f(pro.get(key)), fmt_b=fmt, bold_a=bold)
        r += 1
    cf.column_dimensions["A"].width = 24
    cf.column_dimensions["B"].width = 20
    cf.column_dimensions["C"].width = 20

    # ---------------- comps ----------------
    cp = wb.create_sheet("comps")
    _hdr(cp, 1, ["地址", "成交日", "成交价 $", "面积 SF", "$/SF", "调整后单价", "来源"])
    comps = comps or []
    r = 2
    if not comps:
        cp.merge_cells("A2:G2")
        cp["A2"] = "暂无 comps：用 POST /api/wb/comps/pull 拉取 TopHap CMA 后填入本表（只认 recorded sales）"
        cp["A2"].font = BODY_FONT
    for c in comps:
        cp.cell(row=r, column=1, value=c.get("address", "")).font = BODY_FONT
        cp.cell(row=r, column=2, value=str(c.get("sale_date", ""))).font = BODY_FONT
        for col, key, fmt in ((3, "price", MONEY2), (4, "sf", MONEY),
                              (5, "price_per_sf", MONEY2)):
            cell = cp.cell(row=r, column=col, value=_f(c.get(key)))
            cell.number_format = fmt
            cell.font = BODY_FONT
        adj = c.get("adjusted_price_per_sf")
        cell = cp.cell(row=r, column=6, value=_f(adj) if adj else None)
        cell.number_format = MONEY2
        cell.font = BODY_FONT
        cp.cell(row=r, column=7, value=c.get("source", "")).font = BODY_FONT
        r += 1
    for i, w in enumerate([36, 12, 14, 12, 12, 14, 24], start=1):
        cp.column_dimensions[get_column_letter(i)].width = w

    # ---------------- 假设 ----------------
    ax = wb.create_sheet("假设")
    _hdr(ax, 1, ["假设项", "值", "来源/备注"])
    flat = []
    for k, v in (inputs or {}).items():
        if isinstance(v, (dict, list)):
            continue
        flat.append((k, v))
    r = 2
    if not flat:
        ax.merge_cells("A2:C2")
        ax["A2"] = "无假设输入（直接用模板/示例跑的 compute）"
        ax["A2"].font = BODY_FONT
    for k, v in flat:
        ax.cell(row=r, column=1, value=str(k)).font = BODY_FONT
        cell = ax.cell(row=r, column=2, value=v if isinstance(v, (int, float)) else str(v))
        cell.font = BODY_FONT
        ax.cell(row=r, column=3, value="用户输入" if v not in (None, "", 0) else "默认值").font = BODY_FONT
        r += 1
    ax.cell(row=r + 1, column=1, value="exit cap").font = BODY_FONT
    ax.cell(row=r + 1, column=2, value=_f(ex.get("exit_cap_rate"))).number_format = PCT
    ax.cell(row=r + 1, column=2).font = BODY_FONT
    ax.cell(row=r + 1, column=3, value="IRR 退出假设，必须披露").font = BODY_FONT
    for i, w in enumerate([30, 24, 30], start=1):
        ax.column_dimensions[get_column_letter(i)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_res_xlsx(score: dict, inputs: dict, address: str,
                   verdict: dict | None = None, confidence: dict | None = None,
                   comps: list | None = None) -> bytes:
    """住宅核保明细 Excel：总览 / 现金流 / comps / 假设."""
    m = (score or {}).get("metrics") or {}
    wb = Workbook()
    ws = wb.active
    ws.title = "总览"
    _hdr(ws, 1, ["项目", "数值", "说明"])
    r = 2
    r = _section(ws, r, "物业")
    for label, val in (("地址", address or ""), ("收购价 $", _f((inputs or {}).get("price"))),
                       ("报告日期", date.today().isoformat()),
                       ("口径", "筛选辅助工具，不构成投资建议")):
        _row(ws, r, label, val, None, MONEY2 if isinstance(val, float) else None); r += 1
    r = _section(ws, r, "结论")
    if verdict:
        _row(ws, r, "verdict", verdict.get("verdict", ""), verdict.get("one_liner", "")); r += 1
    if confidence:
        _row(ws, r, "Confidence", confidence.get("score", ""),
             "证据质量分，非推荐强度", None); r += 1
    r = _section(ws, r, "关键指标")
    for label, key, fmt, note in (
            ("月现金流 $", "cash_flow_monthly", MONEY2, ""),
            ("现金回报率 CoC", "cash_on_cash", PCT, "年净现金流 ÷ 全口径现金投入"),
            ("月供 PITI $", "piti", MONEY2, ""),
            ("DSCR", "dscr", "0.00", ""),
            ("全口径现金需求 $", "cash_to_close", MONEY2, "首付＋交割＋储备金"),
            ("空置假设", None, None, f"{_f((inputs or {}).get('vacancy_pct'))}%")):
        v = _f(m.get(key)) if key else None
        _row(ws, r, label, v, note, fmt); r += 1
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 44

    cf = wb.create_sheet("现金流")
    _hdr(cf, 1, ["项目", "月 $", "年 $"])
    rent_m = _f((inputs or {}).get("monthly_rent"))
    egi_m = _f(m.get("egi"))
    rows = [("租金总收入", rent_m), ("有效总收入 EGI", egi_m),
            ("营业费用", _f(m.get("opex"))), ("月供 PITI", _f(m.get("piti"))),
            ("净现金流", _f(m.get("cash_flow_monthly")))]
    rr = 2
    for label, mv in rows:
        _row(cf, rr, label, mv, mv * 12, fmt_b=MONEY2); rr += 1
    cf.column_dimensions["A"].width = 22
    cf.column_dimensions["B"].width = 16
    cf.column_dimensions["C"].width = 16

    cp = wb.create_sheet("comps")
    _hdr(cp, 1, ["地址", "成交日", "成交价 $", "面积 SF", "$/SF", "来源"])
    r = 2
    for c in (comps or []):
        cp.cell(row=r, column=1, value=c.get("address", "")).font = BODY_FONT
        cp.cell(row=r, column=2, value=str(c.get("sale_date", ""))).font = BODY_FONT
        for col, key in ((3, "price"), (4, "sf"), (5, "price_per_sf")):
            cell = cp.cell(row=r, column=col, value=_f(c.get(key)))
            cell.number_format = MONEY2; cell.font = BODY_FONT
        cp.cell(row=r, column=6, value=c.get("source", "")).font = BODY_FONT
        r += 1
    if r == 2:
        cp.merge_cells("A2:F2"); cp["A2"] = "暂无 comps"; cp["A2"].font = BODY_FONT

    ax = wb.create_sheet("假设")
    _hdr(ax, 1, ["假设项", "值", "备注"])
    r = 2
    for k, v in (inputs or {}).items():
        if isinstance(v, (dict, list)):
            continue
        ax.cell(row=r, column=1, value=str(k)).font = BODY_FONT
        cell = ax.cell(row=r, column=2, value=v if isinstance(v, (int, float)) else str(v))
        cell.font = BODY_FONT
        ax.cell(row=r, column=3, value="用户输入").font = BODY_FONT
        r += 1
    for i, w in enumerate([26, 22, 30], start=1):
        ax.column_dimensions[get_column_letter(i)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
