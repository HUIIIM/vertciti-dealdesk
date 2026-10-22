"""持有期：实际 vs 承销偏差；以及 vertciti 独有的“事后归因复盘”。

事后归因：把实际值逐项代回当时那次运行的输入，依次替换，每一步主回报指标（IRR）的变化
就是该项偏差的贡献；各项之和 = 总偏差（顺序替换法，顺序固定、可复现）：
  1. 出租率：预测空置率 ← 100 − 实际平均出租率
  2. 其他经营差异：把测算 NOI 校准到第 1 年实际 NOI（残差，含租金、费用等出租率以外的差异）
  3. NOI 增长：← 实际 NOI 的年复合增长
退出 cap 在实际出售前沿用承销值。v1 引擎的退出 IRR 由现金流测算出的 proforma NOI 驱动，
NOI 校准通过调整 proforma.other_income 实现（NOI 对其线性，割线法两步即精确）。
目前对商业赛道（IRR）做归因；住宅给偏差表。
"""
from __future__ import annotations

from typing import Any

from app.domain.v2.model import primary_value, run_model
from app.domain.v2.paths import get_path, set_path

JSON = dict[str, Any]


def _pro_noi(outputs: JSON) -> float | None:
    v = (((outputs.get("detail") or {}).get("compute") or {}).get("proforma") or {}).get("noi")
    return None if v is None else float(v)


def underwritten_series(track: str, outputs: JSON) -> dict[int, JSON]:
    """承销时的逐年预测（第 1..N 年）：NOI、现金流（与退出 IRR 用的是同一条现金流）。"""
    m = outputs.get("metrics", {})
    if track == "commercial":
        a = ((outputs.get("detail") or {}).get("compute") or {}).get("analysis", {})
        ex = a.get("exit", {}) or {}
        cfs = ex.get("cash_flows") or []
        g = ex.get("noi_growth") or 0.0
        noi1 = _pro_noi(outputs)
        out: dict[int, JSON] = {}
        for y in range(1, len(cfs)):
            out[y] = {"noi": None if noi1 is None else noi1 * (1 + g) ** (y - 1),
                      "cash_flow": cfs[y] if y < len(cfs) - 1 else None}
        return out
    return {1: {"noi": m.get("noi"), "cash_flow": m.get("annual_cash_flow")}}


def variance(track: str, outputs: JSON, actuals: list[JSON]) -> list[JSON]:
    """actuals: [{"period": "2027", "noi": ..., "cash_flow": ..., "occupancy_pct": ...}]，按年对齐第 1、2… 年。"""
    uw = underwritten_series(track, outputs)
    rows = []
    for i, a in enumerate(sorted(actuals, key=lambda r: r["period"]), start=1):
        u = uw.get(i, {})
        row: JSON = {"period": a["period"], "year": i}
        for k in ("noi", "cash_flow"):
            av, uv = a.get(k), u.get(k)
            row[k] = {"actual": av, "underwritten": uv,
                      "variance": None if av is None or uv is None else av - uv,
                      "variance_pct": None if av is None or not uv else (av - uv) / abs(uv) * 100}
        row["occupancy_pct"] = a.get("occupancy_pct")
        rows.append(row)
    return rows


def _calibrate_noi(track: str, inputs: JSON, target: float) -> JSON:
    """调整 proforma.other_income，使测算 NOI 恰为 target（线性：割线法）。"""
    path = "proforma.other_income"
    base = get_path(inputs, path) or 0.0
    n0 = _pro_noi(run_model(track, inputs))
    probe = set_path(inputs, path, base + 1_000_000.0)
    n1 = _pro_noi(run_model(track, probe))
    if n0 is None or n1 is None or n1 == n0:
        return inputs
    k = (n1 - n0) / 1_000_000.0
    return set_path(inputs, path, base + (target - n0) / k)


def attribution(track: str, inputs: JSON, actuals: list[JSON]) -> JSON:
    if track != "commercial":
        return {"available": False, "reason": "事后归因目前支持商业赛道（IRR）；住宅请看偏差表"}
    acts = sorted([a for a in actuals if a.get("noi") is not None], key=lambda r: r["period"])
    if not acts:
        return {"available": False, "reason": "还没有录入实际 NOI"}
    base = primary_value(track, run_model(track, inputs))
    cur, prev, rows = inputs, base, []

    def step(key: str, label: str, underwritten: Any, actual: Any, nxt: JSON) -> None:
        nonlocal cur, prev
        cur = nxt
        now = primary_value(track, run_model(track, cur))
        rows.append({"key": key, "label": label, "underwritten": underwritten, "actual": actual,
                     "contribution_pct_points": None if now is None or prev is None else now - prev})
        prev = now

    occ = [a["occupancy_pct"] for a in acts if a.get("occupancy_pct") is not None]
    if occ:
        vac = 100 - sum(occ) / len(occ)
        step("vacancy", "出租率（实际平均）", get_path(cur, "proforma.vacancy_pct"), vac,
             set_path(cur, "proforma.vacancy_pct", vac))
    uw_noi = _pro_noi(run_model(track, inputs))
    step("noi_level", "其他经营差异（第 1 年 NOI 校准到实际）", uw_noi, acts[0]["noi"],
         _calibrate_noi(track, cur, float(acts[0]["noi"])))
    if len(acts) >= 2 and acts[0]["noi"] > 0:
        cagr = ((acts[-1]["noi"] / acts[0]["noi"]) ** (1 / (len(acts) - 1)) - 1) * 100
        step("noi_growth", "NOI 年增长（实际年复合）", get_path(cur, "analysis.noi_growth"), cagr,
             set_path(cur, "analysis.noi_growth", cagr))
    return {"available": True, "metric": "irr_pct", "underwritten": base, "actual_implied": prev,
            "total_pct_points": None if prev is None or base is None else prev - base, "steps": rows,
            "note": "顺序替换法：出租率 → 其他经营差异 → NOI 增长；退出 cap 未发生前沿用承销值。"}
