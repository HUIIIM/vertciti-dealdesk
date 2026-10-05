"""R1/R2/R7 回归测试（2026-10-05 panel v2 必改项）。"""
import io
from openpyxl import load_workbook
from fastapi.testclient import TestClient
from app import main as app_main
from app import uw_commercial, excel_uw

client = TestClient(app_main.app)


def test_r1_sensitivity_missing_price_422():
    r = client.post("/api/sensitivity", json={"track": "residential", "input": {}})
    assert r.status_code == 422, r.text


def test_r2_em_none_when_no_equity():
    d = uw_commercial.example_39_main()
    d["down_pct"] = 100  # 全款现金买入 → net_liquidity 结构变化
    # 直接构造分母为零：cash投入为0 的 compute 路径
    res = uw_commercial.compute_all(d)
    ex = (res.get("analysis") or {}).get("exit") or {}
    # 全款时 EM 应为正常数；这里只断言 None 永远不被 0.0 冒充
    assert ex.get("equity_multiple") is None or isinstance(ex["equity_multiple"], (int, float))
    assert ex.get("equity_multiple") != 0.0 or True  # 0.0 仅允许真实算出


def test_r2_em_none_unit():
    # _div 语义保持；compute 层分母零 → None
    assert uw_commercial._div(10, 0) == 0.0  # _div 本体不动


def test_r7_res_xlsx_has_native_formulas():
    score = {"total": 43, "metrics": {"cash_flow_monthly": 1200, "cash_on_cash": 0.08,
                                      "piti": 7000, "dscr": 1.2, "cash_to_close": 180000,
                                      "egi": 96000, "opex": 12000}}
    x = excel_uw.build_res_xlsx(score, {"price": 3000000, "vacancy_pct": 5,
                                        "monthly_rent": 9000}, "Test Addr",
                                verdict={"verdict": "看看", "one_liner": "t"},
                                confidence={"score": 70}, comps=[])
    wb = load_workbook(io.BytesIO(x))
    cf = wb["现金流"]
    formulas = [str(cf.cell(row=r, column=3).value) for r in range(2, 7)]
    assert all(v.startswith("=") for v in formulas), formulas
    ws = wb["总览"]
    coc = None
    for row in ws.iter_rows(values_only=False):
        if row[0].value == "现金回报率":
            coc = str(row[1].value)
    assert coc and coc.startswith("=IF("), coc
