"""反推最高出价：给目标（IRR / DSCR / 现金回报 / 淘汰条件），反算还能出到的最高价。

vertciti 独有：同时算每条约束各自允许的最高价，取最低者为可出价，并写明是哪条约束卡住了价格。
方法：对价格二分查找（指标随价格单调递减；端点先验证），精确到 100 美元，结果向下取整。
住宅赛道改价时按原 LTV 等比调整首付与贷款额；商业赛道贷款按首付比例自动随价变化。
"""
from __future__ import annotations

from typing import Any

from app.core.i18n import T
from app.domain.v2 import kill_criteria
from app.domain.v2.model import METRICS, PRICE_PATH, ModelInputError, run_model
from app.domain.v2.paths import get_path, set_path

JSON = dict[str, Any]
STEP = 100.0


def with_price(track: str, inputs: JSON, price: float) -> JSON:
    old = get_path(inputs, PRICE_PATH[track])  # type: ignore[index]
    out = set_path(inputs, PRICE_PATH[track], price)  # type: ignore[index]
    if track == "residential" and isinstance(old, (int, float)) and old > 0:
        f = price / old
        for k in ("down_payment", "loan_balance"):
            v = out.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[k] = v * f
    return out


def _ok(track: str, inputs: JSON, price: float, metric: str, op: str, target: float) -> bool | None:
    try:
        v = run_model(track, with_price(track, inputs, price))["metrics"].get(metric)
    except ModelInputError:
        return None
    if v is None:
        return None
    return bool(kill_criteria.OPS[op](float(v), target))


def solve_one(track: str, inputs: JSON, *, metric: str, op: str, target: float, hi: float, asking: float) -> JSON:
    """满足 metric op target 的最高价格（op 为 >= 或 >）。

    先在 [搜索上限, 要价, 要价×0.9 … ×0.05] 网格上自上而下找第一个满足点，再在它与上一个
    不满足点之间二分。极端低价下指标可能算不出（如 IRR 不收敛），不拿它当端点。
    """
    ok_hi = _ok(track, inputs, hi, metric, op, target)
    if ok_hi:
        return {"price": hi, "status": "above_range", "reason": T("到 ${0:,.0f}（搜索上限）仍满足", hi)}
    grid = [asking * f for f in (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.05) if asking * f < hi]
    upper, lo, saw_unknown = hi, None, ok_hi is None
    for g in grid:
        r = _ok(track, inputs, g, metric, op, target)
        if r:
            lo = g
            break
        saw_unknown = saw_unknown or r is None
        upper = g
    if lo is None:
        if saw_unknown:
            return {"price": None, "status": "unknown", "reason": T("{0}在搜索区间内无法计算", METRICS[metric].label)}
        return {"price": None, "status": "infeasible", "reason": T("降到要价的 5% 仍达不到目标")}
    hi_b = upper
    while hi_b - lo > STEP:
        mid = (lo + hi_b) / 2
        if _ok(track, inputs, mid, metric, op, target):
            lo = mid
        else:
            hi_b = mid
    return {"price": float(int(lo // STEP) * STEP), "status": "ok", "reason": ""}


def run(track: str, inputs: JSON, targets: list[JSON], *, kill: list[JSON] | None = None,
        search_multiple: float = 3.0) -> JSON:
    """targets: [{"metric": "irr_pct", "min": 12}, {"metric": "dscr", "min": 1.25}]。"""
    asking = get_path(inputs, PRICE_PATH[track])  # type: ignore[index]
    if not isinstance(asking, (int, float)) or asking <= 0:
        raise ValueError(T("先填要价（收购价）才能反推最高出价"))
    hi = float(asking) * search_multiple
    cons: list[JSON] = []
    for t in targets:
        if t.get("metric") not in METRICS or not isinstance(t.get("min"), (int, float)):
            raise ValueError(T("目标格式应为 {{metric, min}}：{0!r}", t))
        r = solve_one(track, inputs, metric=t["metric"], op=">=", target=float(t["min"]), hi=hi, asking=float(asking))
        cons.append({"source": "target", "metric": t["metric"], "label": f"{METRICS[t['metric']].label} ≥ {t['min']:g}",
                     **r})
    # 淘汰条件 “metric < X 即放弃” 等价于约束 metric >= X（只取下限型条件）
    for c in kill_criteria.validate(kill or []):
        if c["op"] in ("<", "<="):
            op = ">=" if c["op"] == "<" else ">"
            r = solve_one(track, inputs, metric=c["metric"], op=op, target=c["threshold"], hi=hi, asking=float(asking))
            cons.append({"source": "kill_criteria", "metric": c["metric"], "label": kill_criteria.describe(c), **r})
    priced = [c for c in cons if c["status"] in ("ok", "above_range") and c["price"] is not None]
    blocked = [c for c in cons if c["status"] in ("infeasible", "unknown")]
    if blocked or not priced:
        best = None
        binding = blocked[0] if blocked else None
    else:
        binding = min(priced, key=lambda c: c["price"])
        best = binding["price"]
    return {"asking": float(asking), "max_bid": best, "binding": binding, "constraints": cons,
            "headroom_pct": None if best is None else (best / float(asking) - 1) * 100,
            "note": T("可出价 = 各约束允许最高价中的最低者；任一约束无法满足或无法计算则不给数。")}


def price_check(track: str, inputs: JSON, price: float, *, kill: list[JSON] | None = None) -> JSON:
    """试算出价：按给定价格（住宅同比例调整首付与贷款）重跑模型，返回各指标与淘汰条件逐条结果。

    与 run() 同一套改价规则，前端拖动“出价空间”时调用；不保存任何东西。
    """
    if price <= 0:
        raise ValueError(T("试算价格必须大于 0"))
    asking = get_path(inputs, PRICE_PATH[track])  # type: ignore[index]
    try:
        metrics = run_model(track, with_price(track, inputs, price))["metrics"]
    except ModelInputError as e:
        raise ValueError(str(e)) from e
    ask = float(asking) if isinstance(asking, (int, float)) and asking > 0 else None
    return {"price": float(price), "asking": ask, "vs_asking_pct": None if ask is None else (price / ask - 1) * 100,
            "metrics": metrics, "kill": kill_criteria.evaluate(kill or [], metrics)}
