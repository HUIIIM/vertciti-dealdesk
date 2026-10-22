"""D3/D4（2026-10-10，D460 CEO 已定）：误导性数字口径。

- D3：`_div` 零分母 → None（N/A 链），禁止 0.0 冒充（0.00/0% 会被误读为真实算出的零）。
- D4：`_irr` 无解 → None（终裁⑤既有，本文件做显式回归）。
- 调用方算术链一律做 None 守卫；前端/报表 None → "—"，绝不渲染 0.00/0%。
"""

from app import commercial_plus
from app.uw_commercial import _div, _irr, compute_all, default_inputs


def test_div_zero_denom_returns_none():
    assert _div(10, 0) is None
    assert _div(10, None) is None
    assert _div(0, 0) is None
    assert _div(10, 2) == 5.0


def test_commercial_plus_div_zero_denom_returns_none():
    assert commercial_plus._div(10, 0) is None
    assert commercial_plus._div(3, 2) == 1.5


def test_irr_unsolvable_returns_none():
    # 全负现金流：无解 → None（禁 0.0 冒充"保本"）
    assert _irr([-100.0, -10.0, -10.0]) is None
    # NPV 恒为正（首期正、后续全零）：无解 → None
    assert _irr([100.0, 0.0, 0.0]) is None
    # 正常：收敛
    r = _irr([-100.0, 60.0, 60.0])
    assert r is not None and 0.0 < r < 1.0


def test_projected_resale_none_chain():
    # market_cap=0 → projected_resale=None → 退出费用/净收益/ROI 整条链断开
    d = default_inputs()
    d["analysis"]["purchase_price"] = 4_350_000
    d["analysis"]["market_cap_rate"] = 0
    r = compute_all(d)
    an = r["analysis"]
    assert an["projected_resale"] is None
    assert an["exit_fees"] is None
    assert an["net_gains"] is None
    assert an["roi"] is None


def test_dscr_none_when_no_debt():
    # 全款（down_pct=100 → annual_debt=0）→ dscr/cash_on_cash 为 None 而非 0.0
    d = default_inputs()
    d["analysis"]["purchase_price"] = 4_350_000
    d["analysis"]["down_pct"] = 100
    r = compute_all(d)
    an = r["analysis"]
    assert an["projected"]["dscr"] is None
    assert an["inplace"]["dscr"] is None
    # 0.0 仅允许真实算出：这里必须严格是 None
    assert an["projected"]["dscr"] != 0.0


def test_breakeven_none_when_no_potential():
    # 满租有效总收入=0（无 rent roll 且无收入）→ breakeven_occupancy None
    d = default_inputs()
    r = compute_all(d)
    assert r["analysis"]["breakeven_occupancy"] is None


def test_compute_plus_debt_yield_none_when_no_loan():
    d = default_inputs()
    d["analysis"]["purchase_price"] = 4_350_000
    d["analysis"]["down_pct"] = 100  # 全款 → loan=0
    out = commercial_plus.compute_plus(d)
    assert out["plus"]["debt_yield"] is None
    # breaks 未知不判破线
    for row in out["plus"]["stress"]["rows"]:
        assert row["breaks"]["debt_yield"] is False
        assert row["debt_yield"] is None
        assert row["dscr_trailing"] is None
        assert row["dscr_proforma"] is None


def test_dscr_dual_labels_na_when_dscr_none():
    # 全款时双口径 DSCR label 渲染"—"而非"0.00×"
    d = default_inputs()
    d["analysis"]["purchase_price"] = 4_350_000
    d["analysis"]["down_pct"] = 100
    r = compute_all(d)
    dual = commercial_plus.dscr_dual(r)
    assert dual["trailing"]["dscr"] is None
    assert "—" in dual["trailing"]["label"]
    assert dual["proforma"]["dscr"] is None
    assert "—" in dual["proforma"]["label"]


def test_compute_all_no_crash_on_degenerate():
    # 退化输入（全零项目）整套 compute_all 不崩，关键比率全 None
    r = compute_all(default_inputs())
    an = r["analysis"]
    assert an["inplace_cap"] is None
    assert an["exit"]["irr"] is None
    assert an["exit"]["equity_multiple"] is None
    assert an["roi"] is None
