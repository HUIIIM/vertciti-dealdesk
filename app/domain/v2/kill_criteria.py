"""淘汰条件（先写后算）：建交易时就写好“什么情况下放弃”，模型一碰线就红标。

条件形如 {"metric": "dscr", "op": "<", "threshold": 1.25}，含义是“DSCR 低于 1.25 就放弃”。
指标没算出来（None）时状态为 unknown——未知不等于安全，进投委会关卡会把它当作未通过。
"""
from __future__ import annotations

import operator
from collections.abc import Callable
from typing import Any

from app.core.i18n import T, label
from app.domain.v2.model import METRICS

OPS: dict[str, Callable[[float, float], bool]] = {
    "<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge,
}
OP_TEXT = {"<": "低于", "<=": "不高于", ">": "高于", ">=": "不低于"}

# 默认模板（设置页可改）：蓝图示例 DSCR < 1.25、IRR < 12%
DEFAULT_COMMERCIAL = [
    {"metric": "dscr", "op": "<", "threshold": 1.25},
    {"metric": "irr_pct", "op": "<", "threshold": 12.0},
]
DEFAULT_RESIDENTIAL = [
    {"metric": "dscr", "op": "<", "threshold": 1.2},
    {"metric": "annual_cash_flow", "op": "<", "threshold": 0.0},
]


def validate(criteria: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """规范化并校验；不合法抛 ValueError（中文）。"""
    out: list[dict[str, Any]] = []
    for i, c in enumerate(criteria or []):
        m, op, th = c.get("metric"), c.get("op"), c.get("threshold")
        if m not in METRICS:
            raise ValueError(T("第 {0} 条淘汰条件：未知指标 {1!r}", i + 1, m))
        if op not in OPS:
            raise ValueError(T("第 {0} 条淘汰条件：比较符只能是 < <= > >=", i + 1))
        if isinstance(th, bool) or not isinstance(th, (int, float)):
            # 输入校验错误（用户填错），统一 ValueError → 422，而非编程错误的 TypeError
            raise ValueError(T("第 {0} 条淘汰条件：阈值必须是数字", i + 1))  # noqa: TRY004
        out.append({"metric": m, "op": op, "threshold": float(th)})
    return out


def describe(c: dict[str, Any]) -> str:
    met = METRICS[c["metric"]]
    unit = "%" if met.unit == "pct" else ("×" if met.unit == "x" else "")
    th = f"${c['threshold']:,.0f}" if met.unit == "usd" else f"{c['threshold']:g}{unit}"
    return T("{0}{1} {2} 即放弃", label(met.label), label(OP_TEXT[c["op"]]), th)


def evaluate(criteria: list[dict[str, Any]], metrics: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for c in validate(criteria):
        v = metrics.get(c["metric"])
        if v is None:
            state = "unknown"  # 未知保持未知：缺数不算通过也不算触发
        elif OPS[c["op"]](float(v), c["threshold"]):
            state = "triggered"
        else:
            state = "ok"
        rows.append({**c, "value": v, "state": state, "text": describe(c)})
    return {
        "items": rows,
        "triggered": [r for r in rows if r["state"] == "triggered"],
        "unknown": [r for r in rows if r["state"] == "unknown"],
        "defined": bool(rows),
        "clear": bool(rows) and all(r["state"] == "ok" for r in rows),
    }
