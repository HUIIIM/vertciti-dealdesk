"""开发 / 重度改造：施工期成本曲线、施工期不出租不运营、总成本与开发收益率。

- 成本：交割当月付软成本的 soft_upfront_pct；其余软成本与硬成本（含不可预见费）在施工期第 0 … C-1 月按曲线支出：
  straight = 平均；s_curve = 权重 sin(π(k + 0.5) / C)（两头少、中间多）。
- 施工期（第 0 … C-1 月）所有收入、费用、储备清零，只留开发成本；竣工（第 C 月）起按租约 / 户型正常测算。
- 总成本 = 收购价 + 交割成本 + 硬成本 × (1 + 不可预见费) + 软成本。施工贷利息资本化不计入总成本（单列）。
"""
from __future__ import annotations

import math

from app.domain.v2.cre.cashflow import LINES, Monthly
from app.domain.v2.cre.inputs import CreInputs, Development


def weights(n: int, curve: str) -> list[float]:
    raw = [math.sin(math.pi * (k + 0.5) / n) for k in range(n)] if curve == "s_curve" else [1.0] * n
    total = sum(raw)
    return [w / total for w in raw]


def hard_total(dev: Development) -> float:
    return dev.hard_costs * (1 + dev.contingency_pct / 100)


def total_cost(cre: CreInputs) -> float:
    dev = cre.development
    acq = cre.purchase_price * (1 + cre.closing_costs_pct / 100)
    return acq if dev is None else acq + hard_total(dev) + dev.soft_costs


def cost_schedule(dev: Development, months: int) -> list[float]:
    """每月开发成本（正数）。"""
    out = [0.0] * months
    upfront = dev.soft_costs * dev.soft_upfront_pct / 100
    spread = hard_total(dev) + dev.soft_costs - upfront
    out[0] += upfront
    for k, w in enumerate(weights(dev.construction_months, dev.draw_curve)):
        out[k] += spread * w
    return out


def apply(cre: CreInputs, cf: Monthly) -> list[float]:
    """把施工期清零、记入开发成本（科目 dev_costs，负数，计入债前现金流）。返回每月开发成本（正数）。"""
    dev = cre.development
    if dev is None:
        return [0.0] * cf.n
    costs = cost_schedule(dev, cf.n)
    for m in range(dev.construction_months):
        for k in LINES:
            cf.lines[k][m] = 0.0
    for m, c in enumerate(costs):
        cf.lines["dev_costs"][m] = -c
        cf.lines["cf_before_debt"][m] -= c
    return costs


def stabilization_month(dev: Development) -> int:
    return dev.stabilization_month if dev.stabilization_month is not None else dev.construction_months + 12
