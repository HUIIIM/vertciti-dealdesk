"""app/excel_uw.py + POST /api/uw/report/xlsx 测试."""

import io

from openpyxl import load_workbook

from app import excel_uw, uw_commercial


def _result():
    return uw_commercial.compute_all(uw_commercial.example_39_main())


class TestExcelUw:
    def test_builds_four_sheets(self):
        data = _result().get("analysis") and uw_commercial.example_39_main()
        r = _result()
        x = excel_uw.build_uw_xlsx(r, data, comps=[], meta={"has_rent_roll": True})
        wb = load_workbook(io.BytesIO(x))
        assert wb.sheetnames == ["总览", "现金流", "comps", "假设", "敏感性矩阵"]  # P0-5 敏感性矩阵

    def test_native_formulas_present(self):
        r = _result()
        x = excel_uw.build_uw_xlsx(r, {}, comps=[], meta={"has_rent_roll": True})
        wb = load_workbook(io.BytesIO(x))
        ws = wb["总览"]
        formulas = [c.value for row in ws.iter_rows() for c in row
                    if isinstance(c.value, str) and c.value.startswith("=")]
        assert any("IRR(" in f for f in formulas), "IRR 必须用原生公式"
        assert any("/B" in f and "DSCR" in str(ws.cell(row=f_row, column=1).value)
                   for f_row in range(1, 40)
                   for f in [ws.cell(row=f_row, column=2).value]
                   if isinstance(f, str) and f.startswith("=")), "DSCR 必须用原生公式"

    def test_dscr_formula_recalc(self):
        # 改 NOI 单元格 → DSCR 公式引用正确（验证引用链不断）
        r = _result()
        x = excel_uw.build_uw_xlsx(r, {}, comps=[], meta={"has_rent_roll": True})
        wb = load_workbook(io.BytesIO(x), data_only=False)
        ws = wb["总览"]
        dscr_cell = None
        for row in ws.iter_rows():
            if row[0].value and "偿债覆盖率（DSCR，历史主）" in str(row[0].value):
                dscr_cell = row[1]
                break
        assert dscr_cell is not None
        assert dscr_cell.value.startswith("=")
        # 公式引用的单元格都存在且为数字或公式（IF 防除零会重复引用同一格）
        import re
        refs = re.findall(r"B(\d+)", dscr_cell.value)
        assert len(refs) >= 2
        for rr in set(refs):
            v = ws.cell(row=int(rr), column=2).value
            assert isinstance(v, (int, float)) or (isinstance(v, str) and v.startswith("="))

    def test_comps_empty_honest(self):
        r = _result()
        x = excel_uw.build_uw_xlsx(r, {}, comps=[], meta={"has_rent_roll": True})
        wb = load_workbook(io.BytesIO(x))
        ws = wb["comps"]
        assert "暂无 comps" in str(ws["A2"].value)

    def test_comps_rows(self):
        r = _result()
        x = excel_uw.build_uw_xlsx(r, {}, comps=[
            {"address": "1 Main St", "sale_date": "2026-01-15",
             "price": 500000, "sf": 1000, "price_per_sf": 500,
             "source": "TopHap CMA"}])
        wb = load_workbook(io.BytesIO(x))
        ws = wb["comps"]
        assert ws["A2"].value == "1 Main St"
        assert ws["C2"].value == 500000

    def test_xlsx_endpoint(self):
        from fastapi.testclient import TestClient
        from app.main import app
        c = TestClient(app)
        r = c.post("/api/uw/report/xlsx",
                   json={"input": uw_commercial.example_39_main(), "comps": []})
        assert r.status_code == 200
        assert "spreadsheetml" in r.headers["content-type"]
        cd = r.headers["content-disposition"]
        assert "dealdesk_" in cd and cd.rstrip('"').endswith(".xlsx")
        wb = load_workbook(io.BytesIO(r.content))
        assert wb.sheetnames == ["总览", "现金流", "comps", "假设", "敏感性矩阵"]  # P0-5 敏感性矩阵


class TestPhase5Round3NoRentRoll:
    """第三轮 A3：无 rent roll 时 Excel RR 依赖格一律"待 rent roll"，不许公式得 0."""

    def _wb_norr(self):
        r = _result()
        x = excel_uw.build_uw_xlsx(r, {}, comps=[], meta={"has_rent_roll": False})
        return load_workbook(io.BytesIO(x))["总览"]

    def _val(self, ws, label):
        for row in ws.iter_rows():
            if row[0].value and label in str(row[0].value):
                return row[1].value
        return None

    def test_b17_b18_b21_wait_rent_roll(self):
        ws = self._wb_norr()
        assert self._val(ws, "偿债覆盖率（DSCR，历史主）") == "待 rent roll"
        assert self._val(ws, "偿债覆盖率（DSCR，预测辅）") == "待 rent roll"
        assert self._val(ws, "盈亏平衡出租率") == "待 rent roll"

    def test_no_zero_dscr_in_norr(self):
        ws = self._wb_norr()
        for row in ws.iter_rows():
            v = row[1].value
            if isinstance(v, (int, float)) and row[0].value and "DSCR" in str(row[0].value):
                raise AssertionError(f"DSCR 行出现硬数字 0: {row[0].value}={v}")

    def test_verdict_row_present(self):
        r = _result()
        x = excel_uw.build_uw_xlsx(
            r, {}, comps=[],
            meta={"has_rent_roll": True,
                  "verdict": {"verdict": "HOLD", "one_liner": "测试"},
                  "verdict_word": "HOLD", "veto_count": 0})
        ws = load_workbook(io.BytesIO(x))["总览"]
        labels = [ws.cell(row=i, column=1).value for i in range(1, 60)]
        assert "结论" in labels
        # D8：section 头与数据行同名"结论"，取 B 列有值的那一行
        vi = next(i + 1 for i in range(60)
                  if labels[i] == "结论" and ws.cell(row=i + 1, column=2).value)
        assert ws.cell(row=vi, column=2).value == "HOLD"

    def test_vacancy_not_duplicated(self):
        r = _result()
        data = {"historical": {"vacancy_pct": 8}, "proforma": {"vacancy_pct": 8},
                "analysis": {"purchase_price": 1000000}}
        x = excel_uw.build_uw_xlsx(r, data, comps=[], meta={"has_rent_roll": True})
        ax = load_workbook(io.BytesIO(x))["假设"]
        labels = [ax.cell(row=i, column=1).value for i in range(2, 40)]
        assert labels.count("空置率") == 1

    def test_assump_values_chinese(self):
        # D10：英文内部值一律中文化
        r = _result()
        data = {"property": {"property_type": "commercial"},
                "analysis": {"purchase_price": 1000000}}
        data["structure"] = "standard"
        x = excel_uw.build_uw_xlsx(r, data, comps=[], meta={"has_rent_roll": True})
        ax = load_workbook(io.BytesIO(x))["假设"]
        vals = [ax.cell(row=i, column=2).value for i in range(2, 40)]
        assert "商业" in vals
        assert "普通购买" in vals
        assert "standard" not in vals and "commercial" not in vals
