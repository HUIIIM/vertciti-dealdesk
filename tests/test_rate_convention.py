"""利率口径统一回归测试.

埋雷复盘：app.finance.monthly_payment / finance.remaining_balance 用百分制
（如 6.5 表示 6.5%），而 app.uw_commercial.amort_payment / remaining_balance
曾用小数制（如 0.065），同名函数不同口径 → 传错即静默错数（100 倍偏差）。

2026-10-11 起四函数统一为百分制 [PCT]；本文件钉死该约定：
  - 同百分制输入 → amort_payment == monthly_payment * 12
  - 同百分制输入 → uw remaining_balance == finance remaining_balance
  - broker 实证值不变（$2.24M/6.5%/25年 年供 $181,495.68）
"""

import pytest

from app.finance import monthly_payment
from app.finance import remaining_balance as fin_remaining_balance
from app.uw_commercial import amort_payment
from app.uw_commercial import remaining_balance as uw_remaining_balance


def test_amort_payment_matches_monthly_payment_same_pct():
    # 同百分制输入：年供必须恒等于月供 × 12（口径一致的机械判据）
    assert amort_payment(2_240_000, 6.5, 25) == pytest.approx(
        monthly_payment(2_240_000, 6.5, 25) * 12, rel=1e-9
    )
    assert amort_payment(1_000_000, 6.0, 30) == pytest.approx(
        monthly_payment(1_000_000, 6.0, 30) * 12, rel=1e-9
    )


def test_remaining_balance_matches_finance_same_pct():
    # 同百分制输入：两 remaining_balance 必须一致
    pmt = amort_payment(29_400_000, 6.0, 30)
    assert uw_remaining_balance(29_400_000, 6.0, 30, pmt, 5) == pytest.approx(
        fin_remaining_balance(29_400_000, 6.0, 30, 5), rel=1e-9
    )


def test_known_broker_value_unchanged():
    # 2026-10-04 broker 实证：$2.24M/6.5%/25年 按月摊还年供 $181,495.68
    assert amort_payment(2_240_000, 6.5, 25) == pytest.approx(181495.68, abs=1.0)


def test_zero_rate_pct():
    # 0% → 本金均摊，无除零
    assert amort_payment(1_000_000, 0.0, 30) == pytest.approx(1_000_000 / 30)
