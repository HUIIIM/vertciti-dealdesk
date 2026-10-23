"""资本结构：优先贷款 + 夹层 + 再融资，合成逐月还本付息、再融资净所得与任一月末的未偿余额。

- 优先贷款：debt.schedule（固定 / 浮动、只付息再摊还）。
- 夹层：交割时放款、只付息（固定利率），退出时偿清；再融资且 repay_mezz 时在再融资月一并偿清。
- 再融资（第 r 月）：价值 = 第 r … r+11 月 NOI 合计 ÷ 估值资本化率；新贷款 = min(LTV × 价值,
  NOI ÷ (最低 DSCR × 年还款常数), NOI ÷ 最低债务收益率)；年还款常数在只付息 ≥ 12 个月时取利率，否则取等额本息常数。
  第 r 月先照旧还旧贷款，月末用新贷款偿清旧贷款余额（及夹层），扣再融资费用，净额进股权现金流；新贷款从第 r+1 月起计息。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.v2.cre import debt
from app.domain.v2.cre.inputs import CreInputs, Debt, Refinance

JSON = dict[str, Any]


@dataclass
class Stack:
    months: int
    senior_at_close: float = 0.0
    mezz_at_close: float = 0.0
    fees_at_close: float = 0.0
    debt_service: list[float] = field(default_factory=list)
    mezz_service: list[float] = field(default_factory=list)
    refi_net: list[float] = field(default_factory=list)
    rate_pct: list[float] = field(default_factory=list)
    balance_end: list[float] = field(default_factory=list)   # 月末未偿余额合计（优先 / 新贷款 + 夹层）
    refi: JSON | None = None

    def payoff(self, month: int) -> float:
        return self.balance_end[month]


def annual_constant(rate_pct: float, amort_years: int, io_months: int) -> float:
    """每 1 美元贷款一年的还款额：只付息 ≥ 12 个月 = 利率；否则 = 等额本息月供 × 12。"""
    r = rate_pct / 100 / 12
    if io_months >= 12:
        return rate_pct / 100
    n = amort_years * 12
    return 12 * (r / (1 - (1 + r) ** -n) if r > 0 else 1 / n)


def size_refi(rf: Refinance, noi_12m: float) -> JSON:
    value = noi_12m / (rf.value_cap_pct / 100)
    limits = {"ltv": rf.ltv_pct / 100 * value}
    if rf.min_dscr is not None:
        limits["dscr"] = noi_12m / (rf.min_dscr * annual_constant(rf.rate_pct, rf.amort_years, rf.io_months))
    if rf.min_debt_yield_pct is not None:
        limits["debt_yield"] = noi_12m / (rf.min_debt_yield_pct / 100)
    sized_by = min(limits, key=lambda k: limits[k])
    return {"value": value, "noi_12m": noi_12m, "limits": limits, "sized_by": sized_by,
            "amount": max(0.0, limits[sized_by])}


def build(cre: CreInputs, noi: list[float], months: int) -> Stack:
    st = Stack(months)
    senior = debt.schedule(cre.debt, cre.purchase_price, months)
    st.senior_at_close, st.fees_at_close = senior.amount, senior.orig_fee
    mz = cre.mezz
    if mz is None:
        mezz_amt = 0.0
    else:
        mezz_amt = mz.amount if mz.amount is not None else cre.purchase_price * (mz.ltv_pct or 0) / 100
    st.mezz_at_close = mezz_amt
    st.fees_at_close += mezz_amt * (mz.orig_fee_pct / 100 if mz else 0)
    mezz_int = mezz_amt * (mz.rate_pct / 100 / 12) if mz else 0.0
    rf = cre.refinance
    r = rf.month if rf else months
    mezz_end = r if (rf and rf.repay_mezz) else months  # 夹层存续到第 mezz_end 月（含）
    for m in range(months):
        mezz_alive = mezz_amt > 0 and m <= mezz_end
        st.mezz_service.append(mezz_int if mezz_alive else 0.0)
        if m <= r:
            st.debt_service.append(senior.interest[m] + senior.principal[m] + st.mezz_service[m])
            st.rate_pct.append(senior.rate_pct[m])
            st.balance_end.append(senior.balance_end[m] + (mezz_amt if mezz_alive else 0.0))
        st.refi_net.append(0.0)
    if rf is not None:
        sized = size_refi(rf, sum(noi[r:r + 12]))
        new_loan = sized["amount"]
        repaid = senior.balance_end[r] + (mezz_amt if rf.repay_mezz else 0.0)
        costs = new_loan * rf.costs_pct / 100
        st.refi_net[r] = new_loan - repaid - costs
        new = debt.schedule(Debt(amount=new_loan, rate_type="fixed", rate_pct=rf.rate_pct, io_months=rf.io_months,
                                 amort_years=rf.amort_years, orig_fee_pct=0), cre.purchase_price, months - r - 1)
        st.balance_end[r] = new_loan + (0.0 if rf.repay_mezz else mezz_amt)
        for k in range(months - r - 1):
            m = r + 1 + k
            mezz_alive = mezz_amt > 0 and m <= mezz_end
            st.debt_service.append(new.interest[k] + new.principal[k] + (mezz_int if mezz_alive else 0.0))
            st.rate_pct.append(rf.rate_pct)
            st.balance_end.append(new.balance_end[k] + (mezz_amt if mezz_alive else 0.0))
        st.refi = {**sized, "month": r, "repaid": repaid, "costs": costs, "net": st.refi_net[r],
                   "rate_pct": rf.rate_pct}
    return st
