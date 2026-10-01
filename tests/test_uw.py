"""商业核保引擎测试：锁定模板数字 + 验证全链路联动。"""
import math

import pytest

from app.uw_commercial import (
    amort_payment,
    compute_all,
    default_inputs,
    example_39_main,
    remaining_balance,
)


def approx(a, b, tol=0.01):
    return abs(a - b) <= tol


# ---------- 模板示例：39-09 Main St（Excel 里的手算值） ----------
def test_template_example_matches_excel():
    r = compute_all(example_39_main())
    rr, h, p, an = r["rent_roll"], r["historical"], r["proforma"], r["analysis"]
    # Rent Roll: 83333.34 x 12 = 1,000,000.08；包租 2,000,000
    assert approx(rr["total_annual_lease"], 1000000.08)
    assert approx(rr["total_annual_uw"], 2000000.0)
    # Cash Flow: NOI（模板 F13=1,000,000 / F15=2,000,000）
    assert approx(h["noi"], 1000000.08)
    assert approx(p["noi"], 2000000.0)
    # 模板硬编码的 Cash Flow 行：NOI + 其他收入
    assert approx(p["cash_flow_gross"], 2299048.0)
    assert approx(h["cash_flow_gross"], 1299048.08)
    # 贷款：29.4M，IO 年还 1.764M
    assert approx(an["loan_bal"], 29400000.0)
    assert approx(an["annual_debt_service"], 1764000.0)
    # 自有资金：43.284M - 29.4M = 13.884M
    assert approx(an["net_liquidity"], 13884000.0)
    # 在手 cap = 1M/42M
    assert approx(an["inplace_cap"], 1000000.08 / 42000000.0, 1e-6)
    # 转售 50M，净收益 4.716M，ROI 33.97%
    assert approx(an["projected_resale"], 50000000.0)
    assert approx(an["net_gains"], 4716000.0)
    assert approx(an["roi"], 0.3397, 1e-4)
    # 净现金流 / Cash-on-Cash（模板 F27/F28, I27/I28）
    assert approx(an["projected"]["net_cash_flow"], 236000.0)
    assert approx(an["projected"]["cash_on_cash"], 0.017, 1e-4)
    assert approx(an["inplace"]["net_cash_flow"], -763999.92)
    assert approx(an["inplace"]["cash_on_cash"], -0.055, 1e-3)


# ---------- 联动：改租户月租，全链跟着动 ----------
def test_rent_change_cascades():
    d = example_39_main()
    r0 = compute_all(d)
    d["tenants"][0]["monthly_rent"] = 100000.0  # 83333.34 -> 100000
    r1 = compute_all(d)
    # 年租 +199,999.92 → 历史基础租金、NOI、cap、净现金流、CoC 全变
    delta = (100000.0 - 83333.34) * 12
    assert approx(r1["rent_roll"]["total_annual_lease"] - r0["rent_roll"]["total_annual_lease"], delta)
    assert approx(r1["historical"]["noi"] - r0["historical"]["noi"], delta)
    assert r1["historical"]["cap_rate"] > r0["historical"]["cap_rate"]
    assert approx(r1["analysis"]["inplace"]["net_cash_flow"] - r0["analysis"]["inplace"]["net_cash_flow"], delta)
    # 预测口径不受影响（包租没变）
    assert approx(r1["proforma"]["noi"], r0["proforma"]["noi"])


def test_underwritten_change_cascades_to_proforma():
    d = example_39_main()
    d["tenants"][0]["underwritten_annual"] = 2400000.0
    r = compute_all(d)
    # 预测基础租金 ← 包租合计（模板断链已修复）
    assert approx(r["proforma"]["base_rents"], 2400000.0)
    assert approx(r["proforma"]["noi"], 2400000.0)
    assert approx(r["analysis"]["projected_noi"], 2400000.0)
    assert approx(r["analysis"]["projected_resale"], 2400000.0 / 0.04)
    # 历史口径不受影响
    assert approx(r["historical"]["noi"], 1000000.08)


def test_purchase_price_change_cascades():
    d = example_39_main()
    d["analysis"]["purchase_price"] = 40000000.0
    r = compute_all(d)
    an = r["analysis"]
    assert approx(an["loan_bal"], 28000000.0)
    assert approx(an["annual_debt_service"], 1680000.0)
    assert approx(an["inplace_cap"], 1000000.08 / 40000000.0, 1e-6)
    assert r["historical"]["cap_rate"] == an["inplace_cap"]


def test_expense_change_reduces_noi():
    d = example_39_main()
    d["proforma"]["management_fee"] = 100000.0
    r = compute_all(d)
    assert approx(r["proforma"]["noi"], 1900000.0)
    assert approx(r["proforma"]["total_expenses"], 399048.0)


# ---------- 新增字段 ----------
def test_vacancy_pct_new():
    d = example_39_main()
    d["proforma"]["vacancy_pct"] = 0.05
    r = compute_all(d)
    p = r["proforma"]
    assert approx(p["vacancy_loss"], 2299048.0 * 0.05)
    assert approx(p["egi"], 2299048.0 * 0.95)
    assert approx(p["noi"], 2299048.0 * 0.95 - 299048.0)


def test_amortizing_loan_new():
    pmt = amort_payment(29400000, 0.06, 30)
    # 等额本息年还应大于只还利息
    assert pmt > 29400000 * 0.06
    assert approx(pmt, 29400000 * 0.06 / (1 - 1.06 ** -30))
    d = example_39_main()
    d["analysis"]["amort_type"] = "AMORTIZING"
    d["analysis"]["amort_years"] = 30
    r = compute_all(d)
    assert approx(r["analysis"]["annual_debt_service"], pmt)
    # 5 年后剩余本金小于原贷款
    rem = remaining_balance(29400000, 0.06, 30, pmt, 5)
    assert 0 < rem < 29400000
    assert approx(r["analysis"]["exit"]["remaining_loan"], rem)


def test_dscr_and_breakeven_new():
    r = compute_all(example_39_main())
    an = r["analysis"]
    assert approx(an["projected"]["dscr"], 2000000.0 / 1764000.0, 1e-6)
    assert approx(an["inplace"]["dscr"], 1000000.08 / 1764000.0, 1e-6)
    # 盈亏平衡 = (费用 + 还贷) / 总潜在收入
    assert approx(an["breakeven_occupancy"], (299048.0 + 1764000.0) / 2299048.0, 1e-6)


def test_exit_irr_sanity():
    d = example_39_main()
    r = compute_all(d)
    ex = r["analysis"]["exit"]
    assert ex["hold_years"] == 5
    assert ex["sale_price"] > 0
    assert ex["sale_proceeds"] > 0
    assert -0.5 < ex["irr"] < 2.0
    assert ex["equity_multiple"] > 0
    # 简单校验：IRR 应使 NPV≈0
    flows = [-13884000.0]
    for y in range(1, 6):
        flows.append(2000000.0 * 1.02 ** (y - 1) - 1764000.0)
    noi_exit = 2000000.0 * 1.02 ** 5
    sale = noi_exit / 0.05
    flows[-1] += sale - 29400000.0 - sale * 0.04
    npv = sum(cf / (1 + ex["irr"]) ** i for i, cf in enumerate(flows))
    assert abs(npv) < 100.0


# ---------- 边界 ----------
def test_empty_project_no_crash():
    r = compute_all(default_inputs())
    assert r["rent_roll"]["total_annual_lease"] == 0
    assert r["historical"]["noi"] == 0
    assert r["analysis"]["net_liquidity"] == 0
    assert r["analysis"]["exit"]["irr"] == 0


def test_zero_sf_no_div0():
    d = default_inputs()
    d["tenants"] = [{"suite": "1", "tenant": "T", "sf": 0, "monthly_rent": 5000,
                     "underwritten_annual": 60000}]
    r = compute_all(d)
    assert r["rent_roll"]["tenants"][0]["monthly_per_sf"] == 0
    assert r["rent_roll"]["occupancy"] == 0


# ---------- API ----------
def _client():
    import os
    from fastapi.testclient import TestClient
    from app import db
    from app.main import app
    p = os.environ["DEALDESK_DB"]
    if os.path.exists(p):
        os.remove(p)
    db.init_db()
    return TestClient(app)


def test_uw_api_crud_and_compute():
    client = _client()
    # compute
    r = client.post("/api/uw/compute", json={"input": example_39_main()})
    assert r.status_code == 200
    body = r.json()
    assert abs(body["analysis"]["net_gains"] - 4716000.0) < 0.01
    # create
    r = client.post("/api/uw/projects", json={"name": "UW测试", "input": example_39_main()})
    assert r.status_code == 200
    pid = r.json()["id"]
    # list / get
    assert any(p["id"] == pid for p in client.get("/api/uw/projects").json())
    g = client.get(f"/api/uw/projects/{pid}")
    assert g.status_code == 200 and g.json()["input"]["property"]["name"] == "39-09 Main St"
    # update
    inp = example_39_main()
    inp["analysis"]["purchase_price"] = 40000000
    u = client.put(f"/api/uw/projects/{pid}", json={"name": "UW测试2", "input": inp})
    assert u.status_code == 200 and u.json()["name"] == "UW测试2"
    # delete
    assert client.delete(f"/api/uw/projects/{pid}").status_code == 200
    assert client.get(f"/api/uw/projects/{pid}").status_code == 404


def test_uw_template_endpoint():
    client = _client()
    r = client.get("/api/uw/template")
    assert r.status_code == 200
    body = r.json()
    assert body["blank"]["analysis"]["down_pct"] == 0.3
    assert body["example_39_main"]["property"]["zip"] == "11354"


def test_new_property_fields_and_parking_per_1000sf():
    d = default_inputs()
    p = d["property"]
    # 新增字段存在于 blank 模板
    for k in ("county", "year_renovated", "buildings", "floors", "occupancy_as_of"):
        assert k in p, k
    # 模板公式 =F6/(F4/1000)：0 车位 / 17042 SF = 0
    r = compute_all(example_39_main())
    assert r["property"]["parking_per_1000sf"] == 0
    # 设 50 个车位验证公式：50 / (17042/1000) ≈ 2.9339
    d2 = example_39_main()
    d2["property"]["parking_spaces"] = 50
    r2 = compute_all(d2)
    assert approx(r2["property"]["parking_per_1000sf"], 50 / (17042 / 1000), 1e-4)
    # market_cap_rate 可输入并驱动转售价：NOI / cap
    d3 = example_39_main()
    d3["analysis"]["market_cap_rate"] = 0.05
    r3 = compute_all(d3)
    assert approx(r3["analysis"]["projected_resale"], 2000000.0 / 0.05)


def test_manual_noi_override_f2_pattern():
    # F2 血缘：Analysis F13/F15 手工输入可与 Cash Flow 脱钩
    d = example_39_main()
    d["analysis"]["underwritten_noi"] = 516000   # F13 手工
    d["analysis"]["projected_noi"] = 616000      # F15 手工
    d["analysis"]["inplace_noi_cf"] = 423000    # I24 手工
    r = compute_all(d)
    an = r["analysis"]
    # 在手 Cap 用 F13：516000/42M
    assert approx(an["inplace_cap"], 516000 / 42000000, 1e-6)
    # 转售用 F15：616000/4%
    assert approx(an["projected_resale"], 616000 / 0.04)
    # 现金流块用 I24：423000 - 1764000 = 负
    assert approx(an["inplace"]["net_cash_flow"], 423000 - 1764000)
    assert an["noi_sources"]["underwritten_noi"] == "manual"
    # 空=自动回退现金流
    r2 = compute_all(example_39_main())
    assert r2["analysis"]["noi_sources"]["projected_noi"] == "cashflow"
    assert approx(r2["analysis"]["projected_noi"], 2000000.0)
