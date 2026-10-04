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
        x = excel_uw.build_uw_xlsx(r, data, comps=[])
        wb = load_workbook(io.BytesIO(x))
        assert wb.sheetnames == ["总览", "现金流", "comps", "假设"]

    def test_native_formulas_present(self):
        r = _result()
        x = excel_uw.build_uw_xlsx(r, {}, comps=[])
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
        x = excel_uw.build_uw_xlsx(r, {}, comps=[])
        wb = load_workbook(io.BytesIO(x), data_only=False)
        ws = wb["总览"]
        dscr_cell = None
        for row in ws.iter_rows():
            if row[0].value and "DSCR（trailing 主）" in str(row[0].value):
                dscr_cell = row[1]
                break
        assert dscr_cell is not None
        assert dscr_cell.value.startswith("=")
        # 公式引用的两个单元格都存在且为数字
        import re
        refs = re.findall(r"B(\d+)", dscr_cell.value)
        assert len(refs) == 2
        for rr in refs:
            v = ws.cell(row=int(rr), column=2).value
            assert isinstance(v, (int, float)) or (isinstance(v, str) and v.startswith("="))

    def test_comps_empty_honest(self):
        r = _result()
        x = excel_uw.build_uw_xlsx(r, {}, comps=[])
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
        assert wb.sheetnames == ["总览", "现金流", "comps", "假设"]
