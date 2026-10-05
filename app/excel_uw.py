"""商业核保明细 Excel（openpyxl）.

多 sheet：总览 / 现金流 / comps / 假设。
DSCR / IRR / Equity Multiple 用 Excel 原生公式（改假设可重算），
明细数字为 compute_all() 测算值并标注来源。

调用：POST /api/uw/report/xlsx  ← 只接线，不改 uw_commercial 计算逻辑。
"""

from __future__ import annotations

import io
from datetime import date, datetime
from zoneinfo import ZoneInfo

# Phase 5 第七轮 #6/#9（xiaobai/R8）：报告日期按用户时区 America/New_York——
# 服务器在 UTC，date.today() 在美东深夜会印出"明天"的日期。
_ET = ZoneInfo("America/New_York")


def _today_et() -> str:
    return datetime.now(_ET).date().isoformat()

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .pdf_uw import _ASSUMP_LABELS, _ASSUMP_VALUE_LABELS  # 假设中文标签/值标签（item 12，与 PDF 同源）
from .pdf_uw import _comp_dup_key, _comp_dup_set  # Phase 5 第七轮 R10：重复 comps 检测（与 PDF 同源）

HDR_FILL = PatternFill("solid", fgColor="0F2B26")
HDR_FONT = Font(bold=True, color="E9EFF9", name="Microsoft YaHei", size=11)
SUB_FILL = PatternFill("solid", fgColor="13202B")
SUB_FONT = Font(bold=True, color="2DD4BF", name="Microsoft YaHei", size=11)
BODY_FONT = Font(name="Microsoft YaHei", size=11)
# P0-5（2026-10-05）：敏感性矩阵 sheet 的可改输入格（黄色）
INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")
INPUT_FONT = Font(name="Microsoft YaHei", size=11, bold=True)
BASE_FILL = PatternFill("solid", fgColor="D9EAD3")  # 基准格高亮
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


def _assump_val(k, v):
    """假设值中文化：英文内部值→中文（与 PDF 同源；数值原样返回）.

    Phase 5 第三轮 D10：Excel 假设 sheet 曾泄露英文 raw 值（structure="standard"、
    property_type="commercial"），与 PDF 不一致。
    """
    if isinstance(v, (int, float)):
        return v
    return _ASSUMP_VALUE_LABELS.get(str(k), {}).get(str(v), v)


def build_uw_xlsx(result: dict, inputs: dict, comps: list | None = None,
                  meta: dict | None = None) -> bytes:
    """result=uw_commercial.compute_all() 输出；inputs=原始输入；返回 xlsx bytes."""
    meta = meta or {}
    # Phase 5 第三轮 A3：无 rent roll 时 RR 依赖指标一律"待 rent roll"，
    # 不许公式得 0（沿用 bank_noi 的 has_rent_roll 门做法）
    has_rr = bool(meta.get("has_rent_roll"))
    rr_wait = "待 rent roll"
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
        ("有效总收入", "egi", MONEY2),
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
                       ("报告日期", _today_et()),
                       ("口径", "投资筛选用，非 USPAP 合规评估报告")):
        fmt = MONEY if isinstance(val, float) else None
        _row(ws, r, label, val, None, fmt_b=fmt); r += 1
    r = _section(ws, r, "关键指标（可改黄色格重算）")
    loan_bal = _f(ana.get("loan_bal"))
    rate = _f(ana.get("rate"))
    amort_years = _f(ana.get("amort_years")) or 30
    eq_row = r
    _row(ws, r, "收购价 $", _f(ana.get("purchase_price")), None, MONEY2); r += 1
    # Phase 5 第二轮 item 6：三端统一用银行口径 NOI——Excel 的 DSCR 分子必须与
    # 网页 KPI 卡 / PDF（银行口径）同数；meta.bank_noi 由 compute-plus 传入
    noi_cell_row = r
    bank_noi = meta.get("bank_noi")
    if bank_noi is not None:
        _row(ws, r, "NOI（银行口径）$", round(_f(bank_noi), 2),
             "与网页 KPI 卡 / PDF 同口径（银行调整桥）", MONEY2); r += 1
    else:
        _row(ws, r, "NOI（历史/银行口径前）$",
             _f(hist.get("noi")), "=现金流!B{0}".format(noi_row_cf), MONEY2); r += 1
    loan_row = r
    _row(ws, r, "拟贷款额 $", round(loan_bal, 2), None, MONEY2); r += 1
    rate_row = r
    _row(ws, r, "年利率", rate, "可改（改后 DSCR 联动重算）", PCT); r += 1
    yrs_row = r
    _row(ws, r, "摊销年数", amort_years, "可改（改后 DSCR 联动重算）"); r += 1
    ds_cell_row = r
    # Phase 5 第二轮 item 5＋broker 保留②：年还本付息改用原生 PMT 公式（按月摊还，
    # 银行标准），不再是硬编码值；改利率/年限/贷款额自动重算
    _row(ws, r, "年还本付息 $",
         f"=PMT(B{rate_row}/12,B{yrs_row}*12,-B{loan_row})*12",
         "按月摊还（银行标准）", MONEY2); r += 1
    dscr_row = r
    _row(ws, r, "偿债覆盖率（DSCR，历史主）",
         f"=IF(B{ds_cell_row}=0,0,B{noi_cell_row}/B{ds_cell_row})" if has_rr else rr_wait,
         "银行口径 NOI ÷ 年还本付息（按月摊还）" if has_rr else "无 rent roll，DSCR 无法核保",
         PCT if has_rr else None, bold_a=True); r += 1
    _row(ws, r, "偿债覆盖率（DSCR，预测辅）",
         _f(proj.get("dscr")) if has_rr else rr_wait,
         "预测口径 NOI ÷ 年还本付息" if has_rr else "无 rent roll，DSCR 无法核保",
         PCT if has_rr else None); r += 1
    _row(ws, r, "Debt Yield（NOI ÷ 拟贷款额）",
         f"=IF(B{loan_row}=0,0,B{noi_cell_row}/B{loan_row})" if has_rr else rr_wait,
         "银行 sizing 硬约束；≥8-10% 舒适" if has_rr else "无 rent roll，待接数据",
         PCT if has_rr else None); r += 1
    _row(ws, r, "全口径现金投入 $", _f(ana.get("net_liquidity")),
         "首付＋交割费＋储备金", MONEY2); r += 1
    be_row = r
    _row(ws, r, "盈亏平衡出租率",
         _f(ana.get("breakeven_occupancy")) if has_rr else rr_wait,
         "(费用＋还本付息＋储备金) ÷ 满租有效总收入" if has_rr else "无 rent roll，待接数据",
         PCT if has_rr else None); r += 1
    r = _section(ws, r, "退出与回报（原生公式）")
    hold = int(ex.get("hold_years") or 5)
    flows = list(ex.get("cash_flows") or [])
    eq_invest = abs(_f(flows[0])) if flows else _f(ana.get("net_liquidity"))
    # Phase 5 第六轮微修复 #2（remote N1）：Y5 备注与 PDF 口径对齐——
    # 无退出（退出假设缺失）时 Y5 = 年还贷＋偿还剩余贷款，不含出售所得；
    # 只有 projected_resale > 0（PDF resale_ok 同口径）才写"含退出净所得"。
    _resale_ok = _f(ana.get("projected_resale")) > 0
    _row(ws, r, "持有期（年）", hold, None); r += 1
    _row(ws, r, "初始股权投入 $", eq_invest, None, MONEY2)
    y0_row = r; r += 1
    sched_start = r
    _row(ws, r, f"现金流 Y0", f"=-B{y0_row}", "=-初始投入", MONEY2); r += 1
    annuals = flows[1:] if len(flows) > 1 else []
    for i in range(1, hold + 1):
        v = annuals[i - 1] if i - 1 < len(annuals) else 0.0
        _y5_note = None
        if i == hold:
            _y5_note = (f"Y{hold} 含退出净所得" if _resale_ok
                        else f"Y{hold} = 剩余贷款＋年还贷（不含退出，退出假设缺失）")
        _row(ws, r, f"现金流 Y{i}", v, _y5_note, MONEY2)
        r += 1
    sched_end = r - 1
    rng = f"B{sched_start}:B{sched_end}"
    _row(ws, r, "IRR（原生公式）", f"=IRR({rng})",
         "需同时披露退出假设（见假设表）", PCT, bold_a=True); r += 1
    _row(ws, r, "Equity Multiple（原生公式）",
         f"=SUM({rng})/B{y0_row}", "总回收 ÷ 股权投入", "0.00"); r += 1
    _row(ws, r, "退出 cap", _f(ex.get("exit_cap_rate")), None, PCT); r += 1
    _row(ws, r, "预计出售价 $", _f(ex.get("sale_price")), None, MONEY2); r += 1
    # Phase 5 第三轮 A3（remote R6）：总览加 verdict 行——导出的表要有"买还是不买"。
    # 放在总览末尾，不前移 DSCR 行（B17/B18/B21 行号保持稳定）。
    # Phase 5 第四轮 D8：英文 label 中文化
    r = _section(ws, r, "结论")
    _vd = meta.get("verdict") or {}
    _vword = str(meta.get("verdict_word") or _vd.get("verdict") or "")
    _veto_n = int(meta.get("veto_count") or 0)
    if _vword:
        # Phase 5 第四轮 A1：否决态为独立第 4 状态（_vword 已为"否决"/"VETO"），徽标只保留"一票否决 ×N"
        _vline = _vword + (f" · 一票否决 ×{_veto_n}" if _veto_n else "")
        _row(ws, r, "结论", _vline, str(_vd.get("one_liner") or ""),
             bold_a=True); r += 1
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 40

    # ---------------- 现金流 ----------------
    cf = wb.create_sheet("现金流")
    _hdr(cf, 1, ["项目", "历史 trailing", "预测 pro forma", "备注"])
    r = 2
    for label, key, fmt in rows_cf:
        bold = label in ("有效总收入", "NOI", "可分配现金流")
        hv, pv = _f(hist.get(key)), _f(pro.get(key))
        _row(cf, r, label, hv, pv, fmt_b=fmt, bold_a=bold)
        # Phase 5 第五轮 A2（remote R2）：裸 0 不许直接转发——双列皆 0 时备注
        # "待接/未填"，标准与 PDF（"$0（待接/未填）"）看齐
        if hv == 0 and pv == 0:
            cell = cf.cell(row=r, column=4, value="待接/未填")
            cell.font = BODY_FONT
            cell.border = BORDER
        r += 1
    cf.column_dimensions["A"].width = 24
    cf.column_dimensions["B"].width = 20
    cf.column_dimensions["C"].width = 20
    cf.column_dimensions["D"].width = 14

    # ---------------- comps ----------------
    cp = wb.create_sheet("comps")
    _hdr(cp, 1, ["地址", "成交日", "成交价 $", "面积 SF", "$/SF", "调整后单价", "来源"])
    comps = comps or []
    r = 2
    # Phase 5 第七轮 R10（remote）：重复 comps 标注（检测键与 PDF 同源）
    _dup_addrs = _comp_dup_set(comps)
    if not comps:
        cp.merge_cells("A2:G2")
        cp["A2"] = "暂无 comps：用 POST /api/wb/comps/pull 拉取 TopHap CMA 后填入本表（只认 recorded sales）"
        cp["A2"].font = BODY_FONT
    for c in comps:
        # Phase 5 第七轮 R10（remote）：重复抓取的 comps 标注"（重复）"（与页/PDF 同口径）
        _addr = c.get("address", "")
        if _comp_dup_key(c) in _dup_addrs:
            _addr = str(_addr) + "（重复）"
        cp.cell(row=r, column=1, value=_addr).font = BODY_FONT
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
    # Phase 5 第二轮 item 12：英文内部字段名一律换中文；嵌套输入展平为有效字段
    _ax_labels = dict(_ASSUMP_LABELS)
    _ax_labels.update({
        "purchase_price": "收购价 $", "building_repairs": "建筑维修 $",
        "capital_reserve": "资本储备 $", "lender_fees": "贷款费用 $",
        "closing_costs": "交割费 $", "amort_type": "摊还类型",
        "hold_years": "持有年数", "exit_cap_rate": "退出 cap",
        "noi_growth": "NOI 年增长率", "net_rentable_sf": "可租面积 SF",
        "property_type": "物业类型", "name": "物业名称", "address": "地址",
        "tenant_count": "租户数",
        "down_pct": "首付比例", "rate": "年利率", "amort_years": "摊销年数",
        "vacancy_pct": "空置率", "market_cap_rate": "市场 cap",
    })
    flat = []
    _inp = inputs or {}
    _seen_keys = set()  # Phase 5 第三轮 A3：historical/proforma 都有 vacancy_pct，
    # 去重只保留第一行（此前"空置率"重复两行）
    for _sec, _keys in (("property", ("name", "address", "property_type",
                                      "net_rentable_sf")),
                        ("analysis", ("purchase_price", "down_pct", "rate",
                                      "amort_years", "amort_type", "market_cap_rate",
                                      "hold_years", "exit_cap_rate", "noi_growth",
                                      "building_repairs", "capital_reserve",
                                      "lender_fees", "closing_costs")),
                        ("historical", ("vacancy_pct",)),
                        ("proforma", ("vacancy_pct",))):
        _d = _inp.get(_sec) or {}
        for _k in _keys:
            if _k in _d and _d[_k] not in (None, "") and _k not in _seen_keys:
                _seen_keys.add(_k)
                flat.append((_k, _d[_k]))
    _tenants = _inp.get("tenants") or []
    if _tenants:
        flat.append(("tenant_count", len(_tenants)))
    for k, v in (_inp or {}).items():
        if isinstance(v, (dict, list)):
            continue
        flat.append((k, v))
    r = 2
    if not flat:
        ax.merge_cells("A2:C2")
        ax["A2"] = "无假设输入（直接用模板/示例跑的 compute）"
        ax["A2"].font = BODY_FONT
    for k, v in flat:
        ax.cell(row=r, column=1, value=_ax_labels.get(str(k), str(k))).font = BODY_FONT
        disp = _assump_val(k, v)  # Phase 5 第三轮 D10/A3：英文内部值→中文
        cell = ax.cell(row=r, column=2,
                       value=disp if isinstance(disp, (int, float)) else str(disp))
        cell.font = BODY_FONT
        ax.cell(row=r, column=3, value="用户输入" if v not in (None, "", 0) else "默认值").font = BODY_FONT
        r += 1
    ax.cell(row=r + 1, column=1, value="退出 cap").font = BODY_FONT
    ax.cell(row=r + 1, column=2, value=_f(ex.get("exit_cap_rate"))).number_format = PCT
    ax.cell(row=r + 1, column=2).font = BODY_FONT
    ax.cell(row=r + 1, column=3, value="IRR 退出假设，必须披露").font = BODY_FONT
    for i, w in enumerate([30, 24, 30], start=1):
        ax.column_dimensions[get_column_letter(i)].width = w

    # ---------------- 敏感性矩阵（P0-5） ----------------
    _build_sensitivity_sheet(wb, result, inputs)

    wb.calculation.fullCalcOnLoad = True  # P0-5：含公式的敏感性矩阵打开即重算
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _build_sensitivity_sheet(wb, result: dict, inputs: dict) -> None:
    """P0-5 商业二维敏感性矩阵（对标 ARGUS）：退出 cap × 租金增长率 → IRR / EM。

    自包含 sheet：顶部黄色格为可改输入（基准退出 cap / 基准增长率 /
    持有年数 / 初始股权投入 / 基准年 NOI / 年还本付息 / 年减免 /
    退出时剩余贷款 / 退出费用率），25 格全部为 Excel 原生公式，
    改黄色格即重算。现金流定义与后端 compute_exit 同口径：
      年现金流 Y1..YH = NOI0×(1+g)^(y-1) − 减免 − 还本付息；
      退出所得 = NOI0×(1+g)^H ÷ 退出cap − 剩余贷款 − 出售价×退出费用率；
      IRR = IRR({−股权投入; Y1; …; YH＋退出所得})；
      EM = 仅正向回收 ÷ 股权投入（与后端总览 EM 同口径）。
    注意：改持有年数后现金流排布需重跑导出（公式按导出时年数生成）；
    改退出 cap / 增长率 / 投入 / NOI / 还本付息可直接重算。
    """
    from openpyxl.utils import get_column_letter as _gcl

    ana = (result.get("analysis") or {})
    pro = (result.get("proforma") or {})
    ex = (ana.get("exit") or {})
    an_in = (inputs or {}).get("analysis") or {}

    hold = int(ex.get("hold_years") or 5)
    hold = max(1, min(hold, 50))
    noi0 = _f(pro.get("noi"))
    equity = _f(ana.get("net_liquidity"))
    debt = _f(ana.get("annual_debt_service"))
    abate = _f(an_in.get("abatements"))
    rem_loan = _f(ex.get("remaining_loan"))
    exit_fee = 0.04  # 模板锁定（2026-10-01 Miao 决定），与 compute_exit 同值
    cap_base = _f(ex.get("exit_cap_rate")) or 0.05
    g_base = _f(ex.get("noi_growth"), 0.02)

    ws = wb.create_sheet("敏感性矩阵")
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.merge_cells("A1:F1")
    ws["A1"] = "敏感性矩阵：退出 cap rate × 租金增长率 → IRR / Equity Multiple"
    ws["A1"].font = HDR_FONT
    ws["A1"].fill = HDR_FILL
    ws["A1"].alignment = Alignment(horizontal="center")

    def _inrow(r, label, val, fmt, note):
        ws.cell(row=r, column=1, value=label).font = BODY_FONT
        c = ws.cell(row=r, column=2, value=val)
        c.font = INPUT_FONT
        c.fill = INPUT_FILL
        c.border = BORDER
        if fmt:
            c.number_format = fmt
        ws.cell(row=r, column=1).border = BORDER
        n = ws.cell(row=r, column=3, value=note)
        n.font = BODY_FONT
        n.border = BORDER

    _inrow(2, "基准退出 cap", cap_base, PCT, "退出假设，必须披露（改后全表重算）")
    _inrow(3, "基准租金增长率", g_base, PCT, "NOI 年增长率（改后全表重算）")
    _inrow(4, "持有年数", hold, None, "改后需重跑导出（现金流排布按导出时年数生成）")
    _inrow(5, "初始股权投入 $", round(equity, 2), MONEY2, "首付＋交割费＋储备金")
    _inrow(6, "基准年 NOI $", round(noi0, 2), MONEY2, "预测口径 NOI（Y1 起点）")
    _inrow(7, "年还本付息 $", round(debt, 2), MONEY2, "按月摊还（银行标准）")
    _inrow(8, "年减免 $", round(abate, 2), MONEY2, "abatements")
    _inrow(9, "退出时剩余贷款 $", round(rem_loan, 2), MONEY2,
           "按摊还表；改持有年数后需重跑导出")
    _inrow(10, "退出费用率", exit_fee, PCT, "模板锁定 4%")
    ws.cell(row=11, column=1,
            value="黄色格可改；中心格（+0bps / +0bps）为当前基准假设").font = BODY_FONT

    offs = [-0.01, -0.005, 0.0, 0.005, 0.01]
    # ---- IRR 网格 ----
    r0 = 12
    ws.cell(row=r0, column=1, value="IRR：租金增长 ＼ 退出cap").font = SUB_FONT
    ws.cell(row=r0, column=1).fill = SUB_FILL
    for j, o in enumerate(offs):
        c = ws.cell(row=r0, column=2 + j,
                    value=f"=$B$2{'+' if o >= 0 else ''}{o}")
        c.number_format = PCT
        c.font = HDR_FONT
        c.fill = HDR_FILL
        c.border = BORDER
        if o == 0:
            c.fill = BASE_FILL
            c.font = Font(bold=True, color="0F2B26", name="Microsoft YaHei", size=11)
    # 每格现金流数组（Excel 原生公式；行分隔符 ; 为 en-US 规范，Excel 按区域自动转义）
    terms = []   # Y1..YH（不含退出所得）
    for y in range(1, hold + 1):
        terms.append(f"$B$6*(1+$A{{gr}})^{y - 1}-$B$8-$B$7")
    sale = ("$B$6*(1+$A{gr})^$B$4/{cc}-$B$9"
            "-($B$6*(1+$A{gr})^$B$4/{cc})*$B$10")
    for i, o in enumerate(offs):
        gr = r0 + 1 + i
        c = ws.cell(row=gr, column=1, value=f"=$B$3{'+' if o >= 0 else ''}{o}")
        c.number_format = PCT
        c.font = HDR_FONT
        c.fill = HDR_FILL
        c.border = BORDER
        if o == 0:
            c.fill = BASE_FILL
            c.font = Font(bold=True, color="0F2B26", name="Microsoft YaHei", size=11)
        for j in range(5):
            cc = f"{_gcl(2 + j)}${r0}"
            arr_terms = [t.format(gr=gr) for t in terms]
            arr_terms[-1] = arr_terms[-1] + "+(" + sale.format(gr=gr, cc=cc) + ")"
            arr = ";".join(arr_terms)
            cell = ws.cell(row=gr, column=2 + j,
                           value=f"=IRR({{-$B$5;{arr}}})")
            cell.number_format = PCT
            cell.font = BODY_FONT
            cell.border = BORDER
            if i == 2 and j == 2:
                cell.fill = BASE_FILL
    # ---- EM 网格 ----
    r1 = r0 + 7
    ws.cell(row=r1, column=1, value="Equity Multiple：租金增长 ＼ 退出cap").font = SUB_FONT
    ws.cell(row=r1, column=1).fill = SUB_FILL
    for j in range(5):
        c = ws.cell(row=r1, column=2 + j, value=f"={_gcl(2 + j)}${r0}")
        c.number_format = PCT
        c.font = HDR_FONT
        c.fill = HDR_FILL
        c.border = BORDER
    for i, o in enumerate(offs):
        gr = r1 + 1 + i
        c = ws.cell(row=gr, column=1, value=f"=A{r0 + 1 + i}")
        c.number_format = PCT
        c.font = HDR_FONT
        c.fill = HDR_FILL
        c.border = BORDER
        for j in range(5):
            cc = f"{_gcl(2 + j)}${r0}"
            arr_terms = [t.format(gr=gr) for t in terms]
            arr_terms[-1] = arr_terms[-1] + "+(" + sale.format(gr=gr, cc=cc) + ")"
            arr = ";".join(arr_terms)
            # 与后端同口径：只计正向回收 ÷ 股权投入
            cell = ws.cell(row=gr, column=2 + j,
                           value=f"=SUMPRODUCT(({{{arr}}}>0)*{{{arr}}})/$B$5")
            cell.number_format = "0.00"
            cell.font = BODY_FONT
            cell.border = BORDER
            if i == 2 and j == 2:
                cell.fill = BASE_FILL
    ws.cell(row=r1 + 7, column=1,
            value="口径注：IRR/EM 现金流定义与后端 compute_exit 一致；"
                  "EM 只计正向回收（与总览表同口径）；IRR 不收敛时显示 #NUM!").font = BODY_FONT
    for col, w in ((1, 34), (2, 16), (3, 16), (4, 16), (5, 16), (6, 16)):
        ws.column_dimensions[_gcl(col)].width = w


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
                       ("报告日期", _today_et()),
                       ("口径", "筛选辅助工具，不构成投资建议")):
        _row(ws, r, label, val, None, MONEY2 if isinstance(val, float) else None); r += 1
    r = _section(ws, r, "结论")
    if verdict:
        _row(ws, r, "结论", verdict.get("verdict", ""), verdict.get("one_liner", "")); r += 1
    if confidence:
        _row(ws, r, "置信度", confidence.get("score", ""),
             "证据质量分，非推荐强度", None); r += 1
    r = _section(ws, r, "关键指标")
    _krow = {}
    for label, key, fmt, note in (
            ("月现金流 $", "cash_flow_monthly", MONEY2, ""),
            ("现金回报率", "cash_on_cash", PCT, "年净现金流 ÷ 全口径现金投入"),
            ("月供 $", "piti", MONEY2, ""),
            ("偿债覆盖率（DSCR）", "dscr", "0.00", ""),
            ("全口径现金需求 $", "cash_to_close", MONEY2, "首付＋交割＋储备金"),
            ("空置假设", None, None, f"{_f((inputs or {}).get('vacancy_pct'))}%")):
        v = _f(m.get(key)) if key else None
        _row(ws, r, label, v, note, fmt)
        if key:
            _krow[key] = r
        r += 1
    # R7 (2026-10-05)：现金回报率改原生公式，可复算。
    # 现金流 sheet 行固定：净现金流在第 6 行（表头 1 ＋ 5 行），C6 = 年净现金流。
    if "cash_on_cash" in _krow and "cash_to_close" in _krow:
        _rr, _cr = _krow["cash_on_cash"], _krow["cash_to_close"]
        ws.cell(row=_rr, column=2,
                value=f"=IF(B{_cr}=0,\"—\",'现金流'!C6/B{_cr})")
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 44

    cf = wb.create_sheet("现金流")
    _hdr(cf, 1, ["项目", "月 $", "年 $", "备注"])
    rent_m = _f((inputs or {}).get("monthly_rent"))
    egi_m = _f(m.get("egi"))
    rows = [("租金总收入", rent_m), ("有效总收入", egi_m),
            ("营业费用", _f(m.get("opex"))), ("月供", _f(m.get("piti"))),
            ("净现金流", _f(m.get("cash_flow_monthly")))]
    rr = 2
    for label, mv in rows:
        # R7 (2026-10-05)：年 $ 列改原生公式 =B{rr}*12，可复算
        _row(cf, rr, label, mv, f"=B{rr}*12", fmt_b=MONEY2)
        # Phase 5 第五轮 A2：裸 0 加"待接/未填"备注（与商业 sheet 同标准）
        if mv == 0:
            cell = cf.cell(row=rr, column=4, value="待接/未填")
            cell.font = BODY_FONT
            cell.border = BORDER
        rr += 1
    cf.column_dimensions["A"].width = 22
    cf.column_dimensions["B"].width = 16
    cf.column_dimensions["C"].width = 16
    cf.column_dimensions["D"].width = 14

    cp = wb.create_sheet("comps")
    _hdr(cp, 1, ["地址", "成交日", "成交价 $", "面积 SF", "$/SF", "来源"])
    r = 2
    # Phase 5 第七轮 R10（remote）：重复 comps 标注（检测键与 PDF/商业版同源）
    _dup_addrs = _comp_dup_set(comps)
    for c in (comps or []):
        _addr = c.get("address", "")
        if _comp_dup_key(c) in _dup_addrs:
            _addr = str(_addr) + "（重复）"
        cp.cell(row=r, column=1, value=_addr).font = BODY_FONT
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
    # Phase 5 第二轮 item 12：英文内部字段名一律换中文
    # Phase 5 第三轮 D10：英文内部值一律换中文（structure="standard"→"普通购买"）
    for k, v in (inputs or {}).items():
        if isinstance(v, (dict, list)):
            continue
        ax.cell(row=r, column=1, value=_ASSUMP_LABELS.get(str(k), str(k))).font = BODY_FONT
        disp = _assump_val(k, v)
        cell = ax.cell(row=r, column=2,
                       value=disp if isinstance(disp, (int, float)) else str(disp))
        cell.font = BODY_FONT
        ax.cell(row=r, column=3, value="用户输入").font = BODY_FONT
        r += 1
    for i, w in enumerate([26, 22, 30], start=1):
        ax.column_dimensions[get_column_letter(i)].width = w

    # B1-07：敏感性 sheet（5×5：利率 × 空置率 → 月现金流），与 /d 矩阵同源
    from app import scoring_residential as _sres
    sx = wb.create_sheet("敏感性")
    _hdr(sx, 1, ["空置 ＼ 利率"] + [f"{b:+d}bps" for b in (-200, -100, 0, 100, 200)])
    _base_rate = _f((inputs or {}).get("rate"))
    _base_vac = _f((inputs or {}).get("vacancy_pct"))
    _sr = 2
    for _y in (-4, -2, 0, 2, 4):
        c0 = sx.cell(row=_sr, column=1, value=f"{_y:+d}pp")
        c0.font = BODY_FONT; c0.border = BORDER
        for _j, _x in enumerate((-200, -100, 0, 100, 200)):
            _dd = dict(inputs or {})
            _dd["rate"] = max(_base_rate + _x / 100, 0)
            _dd["vacancy_pct"] = max(_base_vac + _y, 0)
            try:
                _mv = _f(_sres.compute_metrics(_dd).get("cash_flow_monthly"))
            except Exception:
                _mv = None
            _cc = sx.cell(row=_sr, column=2 + _j, value=_mv)
            _cc.number_format = MONEY2; _cc.font = BODY_FONT; _cc.border = BORDER
        _sr += 1
    sx.column_dimensions["A"].width = 16
    for _j in range(2, 7):
        sx.column_dimensions[get_column_letter(_j)].width = 14

    wb.calculation.fullCalcOnLoad = True  # R7：含原生公式，打开即重算
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
