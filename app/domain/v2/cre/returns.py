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


def _grid(lo: float, hi: float) -> list[float]:
    """扫根用的利率网格：0 附近密、两头疏（覆盖 −99.99% 到 1000%）。"""
    near = [x / 100 for x in range(-99, 101)]                 # −99% … 100%，步长 1%
    far = [1.0 + 0.25 * k for k in range(1, int((hi - 1.0) / 0.25) + 1)]
    return sorted({lo, *near, *far, hi})


def _bisect(flows: Sequence[float], lo: float, hi: float, tol: float) -> float:
    f_lo = npv(lo, flows)
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


def irr(flows: Sequence[float], lo: float = -0.9999, hi: float = 10.0, tol: float = 1e-10) -> float | None:
    """每期收益率（与 flows 的期长一致）。没有正负号变化或区间内无根 → None。

    现金流多次变号（如分配后又追加出资）时可能有多个根：扫网格找出所有变号区间，取离 10% 最近的那个根
    （与 Excel IRR 的默认猜测一致），而不是在两端同号时直接放弃。
    """
    if not any(f < 0 for f in flows) or not any(f > 0 for f in flows):
        return None
    pts = _grid(lo, hi)
    vals = [npv(r, flows) for r in pts]
    brackets = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1) if vals[i] == 0 or vals[i] * vals[i + 1] < 0]
    if not brackets:
        return None
    a, b = min(brackets, key=lambda ab: abs((ab[0] + ab[1]) / 2 - 0.10))
    return a if npv(a, flows) == 0 else _bisect(flows, a, b, tol)


def equity_multiple(flows: Sequence[float]) -> float | None:
    out = -sum(f for f in flows if f < 0)
    return sum(f for f in flows if f > 0) / out if out > 0 else None
