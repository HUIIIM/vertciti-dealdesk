"""概率加权结果：基准 / 乐观 / 悲观三情景加概率，给出期望回报与亏损概率，而不只是一个点估计。

情景写法：{"name": "悲观", "probability": 25, "changes": [{"assumption": "rent_level", "pct": -10},
          {"path": "analysis.exit_cap_rate", "add": 0.75}]}  （概率用百分比数，合计须为 100）
change 支持 pct（相对变动 %）、add（加减绝对值，百分比类字段即加减百分点）、set（直接设值）。
亏损判定：商业 = 权益倍数 < 1；住宅 = 年净现金流 < 0。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.i18n import T, label
from app.domain.v2.assumptions import find
from app.domain.v2.model import METRICS, PRIMARY_METRIC, run_model
from app.domain.v2.paths import get_path, set_path, update_path

JSON = dict[str, Any]


def default_scenarios(track: str) -> list[JSON]:
    if track == "commercial":
        return [
            {"name": T("基准"), "probability": 50, "changes": []},
            {"name": T("乐观"), "probability": 25, "changes": [{"assumption": "rent_level", "pct": 5},
                                                          {"assumption": "exit_cap", "add": -0.25}]},
            {"name": T("悲观"), "probability": 25, "changes": [{"assumption": "rent_level", "pct": -10},
                                                          {"assumption": "vacancy", "add": 5},
                                                          {"assumption": "exit_cap", "add": 0.75}]},
        ]
    return [
        {"name": T("基准"), "probability": 50, "changes": []},
        {"name": T("乐观"), "probability": 25, "changes": [{"assumption": "rent_level", "pct": 5}]},
        {"name": T("悲观"), "probability": 25, "changes": [{"assumption": "rent_level", "pct": -10},
                                                      {"assumption": "vacancy", "add": 5}]},
    ]


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _has_number(v: Any) -> bool:
    return any(_is_num(x) for x in v) if isinstance(v, list) else _is_num(v)


def _adder(d: float) -> Callable[[Any], Any]:
    """加减绝对值（百分比类字段即加减百分点）。原值为空不在这里处理：_apply_change 会先判为“缺数”。"""
    return lambda v: v + d if _is_num(v) else v


class MissingInputError(ValueError):
    """情景要调整的假设没有输入值：这个情景算不出（未知保持未知），绝不拿变动量当原值。"""


def _scaler(f: float) -> Callable[[Any], Any]:
    return lambda v: v * f if _is_num(v) else v


def _apply_change(track: str, inputs: JSON, ch: JSON) -> JSON:
    paths = list(find(track, ch["assumption"]).paths) if ch.get("assumption") else [ch["path"]]
    out = inputs
    for p in paths:
        if not any(k in ch for k in ("set", "add", "pct")):
            raise ValueError(T("情景变动须含 pct / add / set 之一"))
        try:
            if ("add" in ch or "pct" in ch) and not _has_number(get_path(out, p)):
                if not ch.get("assumption"):  # 直接写的路径不存在 / 没有值：是输入错误
                    raise ValueError(T("路径不存在：{0}", p))
                raise MissingInputError(T("「{0}」没有输入值，无法按情景调整", ch["assumption"]))
            if "set" in ch:
                out = set_path(out, p, ch["set"])
            elif "add" in ch:
                out = update_path(out, p, _adder(float(ch["add"])))
            else:
                out = update_path(out, p, _scaler(1 + float(ch["pct"]) / 100))
        except (IndexError, KeyError, TypeError) as e:  # 路径不存在（如 tenants.999）：是输入错误，不是服务器故障
            raise ValueError(T("路径不存在：{0}", p)) from e
    return out


def _is_loss(track: str, m: JSON) -> bool | None:
    if track == "commercial":
        em = m.get("equity_multiple")
        return None if em is None else em < 1
    cf = m.get("annual_cash_flow")
    return None if cf is None else cf < 0


def run(track: str, inputs: JSON, scenarios: list[JSON] | None = None) -> JSON:
    sc = scenarios or default_scenarios(track)
    total_p = sum(float(s.get("probability", 0)) for s in sc)
    if abs(total_p - 100.0) > 1e-6:
        raise ValueError(T("情景概率合计须为 100（当前 {0:g}）", total_p))
    metric = PRIMARY_METRIC[track]  # type: ignore[index]
    rows: list[JSON] = []
    for s in sc:
        x = inputs
        try:
            for ch in s.get("changes", []):
                x = _apply_change(track, x, ch)
        except MissingInputError as e:  # 这个情景算不出：显示未知，期望值随之未知
            rows.append({"name": s["name"], "probability": float(s["probability"]), "changes": s.get("changes", []),
                         "metrics": {}, "primary": None, "loss": None, "note": str(e)})
            continue
        m = run_model(track, x)["metrics"]
        rows.append({"name": s["name"], "probability": float(s["probability"]), "changes": s.get("changes", []),
                     "metrics": m, "primary": m.get(metric), "loss": _is_loss(track, m), "note": ""})
    known = [r for r in rows if r["primary"] is not None]
    expected = (sum(r["primary"] * r["probability"] for r in known) / sum(r["probability"] for r in known)
                if known and len(known) == len(rows) else None)
    loss_known = [r for r in rows if r["loss"] is not None]
    loss_p = sum(r["probability"] for r in loss_known if r["loss"]) if len(loss_known) == len(rows) else None
    return {"metric": metric, "metric_label": label(METRICS[metric].label), "scenarios": rows,
            "expected": expected, "loss_probability_pct": loss_p,
            "note": T("期望值 = Σ 概率 × 情景值；任一情景算不出则期望值显示为未知，不拿部分情景凑数。")}
