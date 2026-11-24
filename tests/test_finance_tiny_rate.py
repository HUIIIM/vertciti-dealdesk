"""第 67 项回归：极小利率下 (1+r)^n - 1 的相消误差.

Hypothesis 反例（tests/test_v2_properties.py）：
p=1000.0, r=2.7689395298966817e-12, n=1 年 —— 旧实现算出月供 86.5986，
而利率 +0.5 后月供反降为 83.5592，违反单调性。根因是直接计算
(1+r)**n - 1 时的灾难性相消；修复走 expm1(n * log1p(r)) 精确求值。
本文件以 Decimal 高精度值为参照钉死该口径。
"""

from decimal import Decimal, getcontext

from app.domain import finance

getcontext().prec = 50


def _ref_payment(principal: float, annual_rate_pct: float, years: float) -> float:
    """Decimal 高精度等额本息月供（参照值，非生产口径）."""
    p = Decimal(str(principal))
    r = Decimal(str(annual_rate_pct)) / 100 / 12
    n = int(round(years * 12))
    if r == 0:
        return float(p / n)
    f = (1 + r) ** n
    return float(p * r * f / (f - 1))


def test_hypothesis_counterexample_is_monotonic():
    p, r = 1000.0, 2.7689395298966817e-12
    lo = finance.monthly_payment(p, r, 1.0)
    hi = finance.monthly_payment(p, r + 0.5, 1.0)
    assert hi >= lo
    # 极小利率月供应贴近零利率摊还 1000/12 = 83.333…，而非旧值的 86.5986
    assert abs(lo - _ref_payment(p, r, 1.0)) < 1e-6


def test_tiny_rates_match_high_precision_reference():
    for rate in (0.0, 1e-12, 1e-9, 1e-6, 1e-4, 0.01, 0.5, 6.5, 30.0):
        got = finance.monthly_payment(250_000.0, rate, 30.0)
        ref = _ref_payment(250_000.0, rate, 30.0)
        assert abs(got - ref) <= max(1e-6, abs(ref) * 1e-9), rate


def test_payment_monotonic_across_tiny_rate_sweep():
    rates = [0.0, 1e-12, 1e-10, 1e-8, 1e-6, 1e-4, 1e-2, 0.1, 0.5, 1.0]
    pmts = [finance.monthly_payment(1000.0, r, 1.0) for r in rates]
    assert all(b >= a for a, b in zip(pmts, pmts[1:]))


def test_remaining_balance_tiny_rate_amortizes_linearly():
    # 极小利率下剩余本金应近似线性递减（与零利率口径差 < 1%）
    p = 1200.0
    bal = finance.remaining_balance(p, 1e-9, 1.0, 0.5)
    assert abs(bal - 600.0) < 6.0
    end = finance.remaining_balance(p, 1e-9, 1.0, 1.0)
    assert end == 0.0
