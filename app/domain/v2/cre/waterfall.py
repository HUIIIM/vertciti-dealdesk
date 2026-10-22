"""GP / LP 分配瀑布（按 LP IRR 门槛，美式逐期分配），可选按月、GP catch-up 与回拨（clawback）。

每个门槛 h 维护一个“LP 要拿到多少才达到 IRR=h”的账户：每期先按 h 复利、加上本期 LP 出资；本期可分配现金依次填：
第 0 档（优先回报以内）按出资比例分（LP 拿 lp_equity_pct）→ [GP catch-up] → 第 1 档按该档 LP 份额分，
直到 LP 达到下一门槛 → … → 最后一档之上按 final_lp_share_pct 分。
分完后各账户扣掉 LP 本期所得（不低于 0：已达标就不再回头）。
负现金流（追加出资）按出资比例由 LP / GP 承担。GP 所得含其跟投部分；promote = GP 所得 − GP 按出资比例本应得的部分。

- 按月（frequency = monthly）：门槛是年化 IRR，按 (1 + h)^(1/12) − 1 折成月利率复利；报出的 IRR 按月现金流年化。
- GP catch-up（catch_up_target_pct = t、catch_up_rate_pct = c，c > t）：LP 达到优先回报后，
  本期现金先按 c 给 GP、1 − c 给 LP，直到 GP 累计利润（累计所得 − 累计出资）= t × 双方累计利润合计；之后再进第 1 档。
- 回拨（clawback）：期末若 LP 的 IRR 仍低于优先回报而 GP 拿过 promote，GP 在最后一期退回 promote，
  最多退到 LP 恰好达到优先回报为止（缺口 = 按优先回报复利到期末的 LP 净出资）。
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.domain.v2.cre.inputs import Waterfall
from app.domain.v2.cre.returns import equity_multiple, irr

JSON = dict[str, Any]


def _annualize(r: float | None, periods: int) -> float | None:
    return None if r is None else (1 + r) ** periods - 1


class _Allocator:
    """逐期分配：记 LP / GP 每期所得，以及算 catch-up 要用的累计出资与累计所得。"""

    def __init__(self, w: Waterfall, periods_per_year: int) -> None:
        self.w = w
        self.lp_pct = w.lp_equity_pct / 100
        annual_hurdles = (w.pref_pct, *(t.irr_pct for t in w.tiers))
        self.hurdles = [(1 + h / 100) ** (1 / periods_per_year) - 1 for h in annual_hurdles]
        self.shares = [self.lp_pct, *(t.lp_share_pct / 100 for t in w.tiers)]  # 第 i 档：门槛 i-1 到门槛 i 之间
        self.c_rate = w.catch_up_rate_pct / 100
        self.target = None if w.catch_up_target_pct is None else w.catch_up_target_pct / 100
        self.accounts = [0.0] * len(self.hurdles)
        self.lp: list[float] = []
        self.gp: list[float] = []
        self.lp_in = self.gp_in = self.lp_out = self.gp_out = 0.0
        # 当期状态
        self.left = self.lp_got = self.lp_t = self.gp_t = 0.0

    def _pay(self, x: float, lp_share: float) -> None:
        lp_x, gp_x = lp_share * x, (1 - lp_share) * x
        self.lp_got += lp_x
        self.lp_t += lp_x
        self.gp_t += gp_x
        self.lp_out += lp_x
        self.gp_out += gp_x
        self.left -= x

    def _catch_up(self) -> None:
        """GP 累计利润补到双方累计利润的 target 为止（按累计口径逐期判断，已达标则不付）。"""
        if self.target is None or self.left <= 0:
            return
        lp_p, gp_p = self.lp_out - self.lp_in, self.gp_out - self.gp_in
        need = (self.target * (lp_p + gp_p) - gp_p) / (self.c_rate - self.target)
        if need > 0:
            self._pay(min(self.left, need), 1 - self.c_rate)

    def period(self, t: int, cash: float) -> None:
        contrib = -cash if cash < 0 else 0.0
        lp_c = contrib * self.lp_pct
        self.lp_in += lp_c
        self.gp_in += contrib - lp_c
        balances = [a * (1 + h) + lp_c if t > 0 else a + lp_c for a, h in zip(self.accounts, self.hurdles, strict=True)]
        self.lp_t, self.gp_t = -lp_c, -(contrib - lp_c)
        self.left, self.lp_got = max(cash, 0.0), 0.0
        for i, share in enumerate(self.shares):
            if i == 1:  # 优先回报已满足：先 GP catch-up，再进第 1 档
                self._catch_up()
            if self.left <= 0:
                break
            self._pay(min(self.left, max(0.0, balances[i] - self.lp_got) / share), share)
        if len(self.shares) == 1:  # 没有中间档：catch-up 直接接在优先回报之后
            self._catch_up()
        if self.left > 0:
            self._pay(self.left, self.w.final_lp_share_pct / 100)
        self.accounts = [max(0.0, b - self.lp_got) for b in balances]
        self.lp.append(self.lp_t)
        self.gp.append(self.gp_t)


def distribute(w: Waterfall, flows: Sequence[float], periods_per_year: int = 1) -> JSON:
    """flows：有杠杆股权现金流（第 0 期为出资，之后各期分配；负数 = 追加出资）。

    periods_per_year：1 = 按年，12 = 按月。
    """
    book = _Allocator(w, periods_per_year)
    for t, cash in enumerate(flows):
        book.period(t, cash)
    lp, gp = book.lp, book.gp
    gp_pro_rata = sum(f for f in flows if f > 0) * (1 - book.lp_pct)
    promote = max(0.0, sum(g for g in gp if g > 0) - gp_pro_rata)
    clawback = 0.0
    if w.clawback and promote > 0 and lp:
        h0, last = book.hurdles[0], len(lp) - 1
        shortfall = -sum(x * (1 + h0) ** (last - k) for k, x in enumerate(lp))  # LP 离优先回报还差多少（期末口径）
        clawback = min(promote, max(0.0, shortfall))
        lp[last] += clawback
        gp[last] -= clawback
        promote -= clawback
    lp_irr = _annualize(irr(lp), periods_per_year)
    gp_irr = _annualize(irr(gp), periods_per_year)
    return {
        "lp": lp, "gp": gp, "periods_per_year": periods_per_year,
        "lp_irr_pct": None if lp_irr is None else lp_irr * 100,
        "gp_irr_pct": None if gp_irr is None else gp_irr * 100,
        "lp_multiple": equity_multiple(lp), "gp_multiple": equity_multiple(gp),
        "gp_promote": promote, "clawback": clawback,
    }


def describe(w: JSON) -> str:
    """瀑布条款的一句话说明（Excel、备忘录共用）。w 为已校验的 Waterfall dict。"""
    parts = [f"LP 出资 {w['lp_equity_pct']:g}%", f"优先回报 {w['pref_pct']:g}%（按出资比例）"]
    if w.get("catch_up_target_pct") is not None:
        parts.append(f"GP catch-up {w['catch_up_rate_pct']:g}% 至利润的 {w['catch_up_target_pct']:g}%")
    parts += [f"LP IRR 至 {t['irr_pct']:g}%：LP 分 {t['lp_share_pct']:g}%" for t in w.get("tiers", [])]
    parts.append(f"之上：LP 分 {w['final_lp_share_pct']:g}%")
    freq = "按月分配（门槛按月复利）" if w.get("frequency") == "monthly" else "按年度分配"
    claw = "期末 LP 未达优先回报时 GP 回拨 promote" if w.get("clawback") else "无回拨"
    return "；".join(parts) + f"。{freq}，{claw}。"


def annual(series: Sequence[float], periods_per_year: int) -> list[float]:
    """按月分配序列 → 年度（第 0 期单列，之后每 12 期一年），与年度现金流对齐展示。"""
    if periods_per_year == 1:
        return list(series)
    head, rest = series[0], series[1:]
    return [head, *(sum(rest[i:i + periods_per_year]) for i in range(0, len(rest), periods_per_year))]
