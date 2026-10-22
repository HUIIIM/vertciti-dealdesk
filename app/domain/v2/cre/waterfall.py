"""GP / LP 分配瀑布（按 LP IRR 门槛，美式逐期分配）。

每个门槛 h 维护一个“LP 要拿到多少才达到 IRR=h”的账户：每期先按 h 复利、加上本期 LP 出资；本期可分配现金依次填：
第 0 档（优先回报以内）按出资比例分（LP 拿 lp_equity_pct）→ 第 1 档按该档 LP 份额分，直到 LP 达到下一门槛 → …
→ 最后一档之上按 final_lp_share_pct 分。分完后各账户扣掉 LP 本期所得（不低于 0：已达标就不再回头）。
负现金流（追加出资）按出资比例由 LP / GP 承担。GP 所得含其跟投部分；promote = GP 所得 − GP 按出资比例本应得的部分。
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.domain.v2.cre.inputs import Waterfall
from app.domain.v2.cre.returns import equity_multiple, irr

JSON = dict[str, Any]


def distribute(w: Waterfall, flows: Sequence[float]) -> JSON:
    """flows：有杠杆股权现金流（第 0 期为负的出资，之后各期分配；负数 = 追加出资）。"""
    lp_pct = w.lp_equity_pct / 100
    hurdles = [w.pref_pct, *(t.irr_pct for t in w.tiers)]
    shares = [lp_pct, *(t.lp_share_pct / 100 for t in w.tiers)]  # 第 i 档：门槛 i-1 到门槛 i 之间
    accounts = [0.0] * len(hurdles)
    lp, gp = [], []
    for t, cash in enumerate(flows):
        contrib = -cash if cash < 0 else 0.0
        lp_c = contrib * lp_pct
        balances = [a * (1 + h / 100) + lp_c if t > 0 else a + lp_c for a, h in zip(accounts, hurdles, strict=True)]
        lp_t, gp_t = -lp_c, -(contrib - lp_c)
        left = cash if cash > 0 else 0.0
        lp_got = 0.0
        for i, share in enumerate(shares):
            if left <= 0:
                break
            need = max(0.0, balances[i] - lp_got) / share
            x = min(left, need)
            lp_got += share * x
            lp_t += share * x
            gp_t += (1 - share) * x
            left -= x
        if left > 0:
            s = w.final_lp_share_pct / 100
            lp_got += s * left
            lp_t += s * left
            gp_t += (1 - s) * left
        accounts = [max(0.0, b - lp_got) for b in balances]
        lp.append(lp_t)
        gp.append(gp_t)
    total_pos = sum(f for f in flows if f > 0)
    gp_pro_rata = total_pos * (1 - lp_pct)
    gp_pos = sum(g for g in gp if g > 0)
    lp_irr, gp_irr = irr(lp), irr(gp)
    return {
        "lp": lp, "gp": gp,
        "lp_irr_pct": None if lp_irr is None else lp_irr * 100,
        "gp_irr_pct": None if gp_irr is None else gp_irr * 100,
        "lp_multiple": equity_multiple(lp), "gp_multiple": equity_multiple(gp),
        "gp_promote": max(0.0, gp_pos - gp_pro_rata),
    }
