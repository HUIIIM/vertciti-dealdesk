"""概率加权结果：基准 / 乐观 / 悲观三情景加概率，给出期望回报与亏损概率，而不只是一个点估计。

情景写法：{"name": "悲观", "probability": 25, "changes": [{"assumption": "rent_level", "pct": -10},
          {"path": "analysis.exit_cap_rate", "add": 0.75}]}  （概率用百分比数，合计须为 100）
change 支持 pct（相对变动 %）、add（加减绝对值，百分比类字段即加减百分点）、set（直接设值）。
亏损判定：商业 = 权益倍数 < 1；住宅 = 年净现金流 < 0。
"""
from __future__ import annotations

from typing import Any

from app.domain.v2.assumptions import find
from app.domain.v2.model import PRIMARY_METRIC, METRICS, run_model
from app.domain.v2.paths import set_path, update_path

JSON = dict[str, Any]


def default_scenarios(track: str) -> list[JSON]:
    if track == "commercial":
        return [
            {"name": "基准", "probability": 50, "changes": []},
            {"name": "乐观", "probability": 25, "changes": [{"assumption": "rent_level", "pct": 5},
                                                          {"assumption": "exit_cap", "add": -0.25}]},
            {"name": "悲观", "probability": 25, "changes": [{"assumption": "rent_level", "pct": -10},
                                                          {"assumption": "vacancy", "add": 5},
                                                          {"assumption": "exit_cap", "add": 0.75}]},
        ]
    return [
        {"name": "基准", "probability": 50, "changes": []},
        {"name": "乐观", "probability": 25, "changes": [{"assumption": "rent_level", "pct": 5}]},
        {"name": "悲观", "probability": 25, "changes": [{"assumption": "rent_level", "pct": -10},
                                                      {"assumption": "vacancy", "add": 5}]},
    ]


def _apply_change(track: str, inputs: JSON, ch: JSON) -> JSON:
    paths = list(find(track, ch["assumption"]).paths) if ch.get("assumption") else [ch["path"]]
    out = inputs
    for p in paths:
        if "set" in ch:
            out = set_path(out, p, ch["set"])
        elif "add" in ch:
            out = update_path(out, p, lambda v, d=float(ch["add"]): (v + d) if isinstance(v, (int, float))
                              and not isinstance(v, bool) else (d if v is None else v))
        elif "pct" in ch:
            out = update_path(out, p, lambda v, f=1 + float(ch["pct"]) / 100: v * f if isinstance(v, (int, float))
                              and not isinstance(v, bool) else v)
        else:
            raise ValueError("情景变动须含 pct / add / set 之一")
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
        raise ValueError(f"情景概率合计须为 100（当前 {total_p:g}）")
    metric = PRIMARY_METRIC[track]  # type: ignore[index]
    rows: list[JSON] = []
    for s in sc:
        x = inputs
        for ch in s.get("changes", []):
            x = _apply_change(track, x, ch)
        m = run_model(track, x)["metrics"]
        rows.append({"name": s["name"], "probability": float(s["probability"]), "changes": s.get("changes", []),
                     "metrics": m, "primary": m.get(metric), "loss": _is_loss(track, m)})
    known = [r for r in rows if r["primary"] is not None]
    expected = (sum(r["primary"] * r["probability"] for r in known) / sum(r["probability"] for r in known)
                if known and len(known) == len(rows) else None)
    loss_known = [r for r in rows if r["loss"] is not None]
    loss_p = sum(r["probability"] for r in loss_known if r["loss"]) if len(loss_known) == len(rows) else None
    return {"metric": metric, "metric_label": METRICS[metric].label, "scenarios": rows,
            "expected": expected, "loss_probability_pct": loss_p,
            "note": "期望值 = Σ 概率 × 情景值；任一情景算不出则期望值显示为未知，不拿部分情景凑数。"}
