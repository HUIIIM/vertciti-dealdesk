"""收益指标：IRR（二分法，不依赖第三方库；无符号变化时返回 None——未知保持未知）、NPV、权益倍数。"""
from __future__ import annotations

import math
from collections.abc import Sequence


def _discount(f: float, rate: float, t: int) -> float:
    # 用对数算贴现因子：长期限（如 360 个月）× 接近 -100% 的利率时，(1+r)^t 会下溢成 0、直接除会报错
    try:
        return f * math.exp(-t * math.log1p(rate))
    except OverflowError:
        return math.copysign(math.inf, f)


def npv(rate: float, flows: Sequence[float]) -> float:
    return sum(_discount(f, rate, t) for t, f in enumerate(flows))


def irr(flows: Sequence[float], lo: float = -0.9999, hi: float = 10.0, tol: float = 1e-10) -> float | None:
    """每期收益率（与 flows 的期长一致）。没有正负号变化或区间内无根 → None。"""
    if not any(f < 0 for f in flows) or not any(f > 0 for f in flows):
        return None
    f_lo, f_hi = npv(lo, flows), npv(hi, flows)
    if f_lo * f_hi > 0:
        return None
    for _ in range(300):
        mid = (lo + hi) / 2
        f_mid = npv(mid, flows)
        if abs(f_mid) < tol or hi - lo < tol:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def equity_multiple(flows: Sequence[float]) -> float | None:
    out = -sum(f for f in flows if f < 0)
    return sum(f for f in flows if f > 0) / out if out > 0 else None
