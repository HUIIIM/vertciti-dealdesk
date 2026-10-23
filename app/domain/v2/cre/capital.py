"""资本结构：优先贷款 + 夹层 + 再融资，合成逐月还本付息、再融资净所得与任一月末的未偿余额。

- 优先贷款：debt.schedule（固定 / 浮动、只付息再摊还）。
- 夹层：交割时放款、只付息（固定利率），退出时偿清；再融资且 repay_mezz 时在再融资月一并偿清。
- 再融资（第 r 月）：价值 = 第 r … r+11 月 NOI 合计 ÷ 估值资本化率；新贷款 = min(LTV × 价值,
  NOI ÷ (最低 DSCR × 年还款常数), NOI ÷ 最低债务收益率)；年还款常数在只付息 ≥ 12 个月时取利率，否则取等额本息常数。
  第 r 月先照旧还旧贷款，月末用新贷款偿清旧贷款余额（及夹层），扣再融资费用，净额进股权现金流；新贷款从第 r+1 月起计息。
- 施工贷（开发项目）：按总成本的 LTC 承诺；股权先投，投满后按月提款（提款进股权现金流，抵开发成本）；
  施工期利息资本化，竣工后按月付息（计入还本付息）；再融资时偿清，否则出售时偿清。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.v2.cre import debt
from app.domain.v2.cre.development import total_cost
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
    draws: list[float] = field(default_factory=list)          # 施工贷每月提款（进股权现金流，正数）
    construction: JSON | None = None

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


@dataclass
class _Construction:
    draw_close: float
    fee: float
    draws: list[float]
    interest_paid: list[float]
    balance_end: list[float]
    summary: JSON


def _construction(cre: CreInputs, dev_costs: list[float], months: int, end: int) -> _Construction | None:
    """股权先投、投满后按月提款；施工期（第 0 … C-1 月）利息资本化，竣工后按月付息。

    第 end 月月末偿清（再融资），否则一直到出售。
    """
    cl, dev = cre.construction_loan, cre.development
    if cl is None or dev is None:
        return None
    total = total_cost(cre)
    commitment = cl.ltc_pct / 100 * total
    fee = commitment * cl.orig_fee_pct / 100
    equity_left = total - commitment          # 股权先投的额度（开办费另由股权付）
    r = cl.rate_pct / 100 / 12

    def fund(cost: float) -> float:
        nonlocal equity_left
        eq = min(cost, equity_left)
        equity_left -= eq
        return cost - eq

    draw_close = fund(cre.purchase_price * (1 + cre.closing_costs_pct / 100))
    bal, drawn, cap_int, peak = draw_close, draw_close, 0.0, draw_close
    draws, paid, ends = [], [], []
    for m in range(months):
        if m > end:
            draws.append(0.0)
            paid.append(0.0)
            ends.append(0.0)
            continue
        interest = bal * r
        if m < dev.construction_months:
            bal += interest
            cap_int += interest
            paid.append(0.0)
        else:
            paid.append(interest)
        d = min(fund(dev_costs[m]), max(0.0, commitment - drawn))
        drawn += d
        bal += d
        draws.append(d)
        ends.append(bal)
        peak = max(peak, bal)
    summary = {"total_cost": total, "commitment": commitment, "equity_required": total - commitment,
               "capitalized_interest": cap_int, "peak_balance": peak, "drawn": drawn, "rate_pct": cl.rate_pct}
    return _Construction(draw_close, fee, draws, paid, ends, summary)


def build(cre: CreInputs, noi: list[float], months: int, dev_costs: list[float] | None = None) -> Stack:
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
    cons = _construction(cre, dev_costs or [0.0] * months, months, r)
    if cons is not None:
        st.senior_at_close += cons.draw_close
        st.fees_at_close += cons.fee
        st.construction = cons.summary
    mezz_end = r if (rf and rf.repay_mezz) else months  # 夹层存续到第 mezz_end 月（含）
    for m in range(months):
        mezz_alive = mezz_amt > 0 and m <= mezz_end
        st.mezz_service.append(mezz_int if mezz_alive else 0.0)
        c_paid, c_bal = (cons.interest_paid[m], cons.balance_end[m]) if cons else (0.0, 0.0)
        st.draws.append(cons.draws[m] if cons else 0.0)
        if m <= r:
            st.debt_service.append(senior.interest[m] + senior.principal[m] + st.mezz_service[m] + c_paid)
            st.rate_pct.append(cons.summary["rate_pct"] if cons else senior.rate_pct[m])
            st.balance_end.append(senior.balance_end[m] + (mezz_amt if mezz_alive else 0.0) + c_bal)
        st.refi_net.append(0.0)
    if rf is not None:
        sized = size_refi(rf, sum(noi[r:r + 12]))
        new_loan = sized["amount"]
        repaid = senior.balance_end[r] + (mezz_amt if rf.repay_mezz else 0.0) + (cons.balance_end[r] if cons else 0.0)
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
