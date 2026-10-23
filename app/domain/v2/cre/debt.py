"""按月债务。

只付息期 → 按剩余摊还月数计等额本息；浮动利率 = min(SOFR, 上限) + 利差，按分析年取曲线值，
利率变化时用当期余额与剩余摊还月数重算月供。贷款在分析起点一次放款，退出时按余额偿清。
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.v2.cre.inputs import Debt


@dataclass(frozen=True)
class DebtSchedule:
    amount: float
    orig_fee: float
    interest: list[float]
    principal: list[float]
    balance_end: list[float]   # 每月月末余额
    rate_pct: list[float]      # 每月执行年利率（百分比数）

    def payoff(self, month: int) -> float:
        """第 month 月月末（含当月还款后）的未偿余额；month < 0 = 放款额。"""
        return self.amount if month < 0 else self.balance_end[month]


def annual_rate_pct(d: Debt, m: int) -> float:
    if d.rate_type == "fixed":
        return d.rate_pct
    curve = d.sofr_curve_pct
    sofr = curve[min(m // 12, len(curve) - 1)]
    if d.cap_strike_pct is not None:
        sofr = min(sofr, d.cap_strike_pct)
    return sofr + d.spread_bps / 100


def loan_amount(d: Debt, price: float) -> float:
    if d.amount is not None:
        return d.amount
    return price * (d.ltv_pct or 0) / 100


def schedule(d: Debt | None, price: float, months: int) -> DebtSchedule:
    if d is None:
        z = [0.0] * months
        return DebtSchedule(0.0, 0.0, z, z[:], z[:], z[:])
    amount = loan_amount(d, price)
    bal, interest, principal, ends, rates = amount, [], [], [], []
    amort_n = d.amort_years * 12
    pmt, last_rate = 0.0, None
    for m in range(months):
        rate = annual_rate_pct(d, m)
        r = rate / 100 / 12
        i = bal * r
        if m < d.io_months:
            p = 0.0
        else:
            left = max(amort_n - (m - d.io_months), 1)
            if rate != last_rate or m == d.io_months:  # 利率变化或摊还开始：按剩余期限重算月供
                pmt = bal * (r / (1 - (1 + r) ** -left)) if r > 0 else bal / left
            p = min(bal, pmt - i)
        bal -= p
        last_rate = rate
        interest.append(i)
        principal.append(p)
        ends.append(bal)
        rates.append(rate)
    return DebtSchedule(amount, amount * d.orig_fee_pct / 100, interest, principal, ends, rates)
