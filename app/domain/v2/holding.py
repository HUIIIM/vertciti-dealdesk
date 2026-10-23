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

from app.core.i18n import T
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
    if track == "institutional":  # 逐租约引擎本身就给逐年 NOI 与有杠杆现金流
        ann = ((outputs.get("detail") or {}).get("cre") or {}).get("annual") or {}
        noi, cf = ann.get("noi") or [], ann.get("cf_after_debt") or []
        hold = len(noi) - 1  # 引擎多算一年（退出用下一年 NOI）
        return {y: {"noi": noi[y - 1], "cash_flow": cf[y - 1] if y < hold else None} for y in range(1, hold + 1)}
    return {1: {"noi": m.get("noi"), "cash_flow": m.get("annual_cash_flow")}}


def annualize(actuals: list[JSON]) -> list[JSON]:
    """把实际数统一成年度。

    录了年度（YYYY）的直接用；只有月度（YYYY-MM）的按年合计——12 个月 NOI / 现金流都齐才算该年的数，
    不齐即未知（绝不拿半年当一年）；出租率取已录月份的平均。
    """
    yearly = {a["period"]: a for a in actuals if len(a["period"]) == 4}
    months: dict[str, list[JSON]] = {}
    for a in actuals:
        if len(a["period"]) == 7 and a["period"][:4] not in yearly:
            months.setdefault(a["period"][:4], []).append(a)
    out = [dict(a, months=12) for a in yearly.values()]
    for y, ms in months.items():
        def total(k: str, ms: list[JSON] = ms) -> float | None:
            vals = [m.get(k) for m in ms]
            nums = [float(v) for v in vals if v is not None]
            return sum(nums) if len(ms) == 12 and len(nums) == 12 else None
        occ = [m["occupancy_pct"] for m in ms if m.get("occupancy_pct") is not None]
        out.append({"period": y, "noi": total("noi"), "cash_flow": total("cash_flow"),
                    "occupancy_pct": sum(occ) / len(occ) if occ else None, "months": len(ms)})
    return sorted(out, key=lambda r: r["period"])


def variance(track: str, outputs: JSON, actuals: list[JSON]) -> list[JSON]:
    """actuals：年度或月度实际数；先 annualize()，再按年对齐承销的第 1、2… 年。"""
    uw = underwritten_series(track, outputs)
    rows = []
    for i, a in enumerate(annualize(actuals), start=1):
        u = uw.get(i, {})
        row: JSON = {"period": a["period"], "year": i}
        for k in ("noi", "cash_flow"):
            av, uv = a.get(k), u.get(k)
            row[k] = {"actual": av, "underwritten": uv,
                      "variance": None if av is None or uv is None else av - uv,
                      "variance_pct": None if av is None or not uv else (av - uv) / abs(uv) * 100}
        row["occupancy_pct"] = a.get("occupancy_pct")
        row["months"] = a.get("months", 12)
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
        return {"available": False,
                "reason": T("事后归因（逐条假设拆 IRR 偏差）目前只支持商业赛道；住宅与机构级请看上面的偏差表")}
    acts = [a for a in annualize(actuals) if a.get("noi") is not None]
    if not acts:
        return {"available": False, "reason": T("还没有录入实际 NOI")}
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
        step("vacancy", T("出租率（实际平均）"), get_path(cur, "proforma.vacancy_pct"), vac,
             set_path(cur, "proforma.vacancy_pct", vac))
    uw_noi = _pro_noi(run_model(track, inputs))
    step("noi_level", T("其他经营差异（第 1 年 NOI 校准到实际）"), uw_noi, acts[0]["noi"],
         _calibrate_noi(track, cur, float(acts[0]["noi"])))
    if len(acts) >= 2:
        first, last = acts[0]["noi"], acts[-1]["noi"]
        if first > 0 and last > 0:
            cagr = ((last / first) ** (1 / (len(acts) - 1)) - 1) * 100
            step("noi_growth", T("NOI 年增长（实际年复合）"), get_path(cur, "analysis.noi_growth"), cagr,
                 set_path(cur, "analysis.noi_growth", cagr))
        else:  # NOI 出现 ≤ 0：年复合增长率无定义（负数开方），这一步与整条归因的终点都是未知
            rows.append({"key": "noi_growth", "label": T("NOI 年增长（实际年复合）"),
                         "underwritten": get_path(cur, "analysis.noi_growth"), "actual": None,
                         "contribution_pct_points": None})
            prev = None
    return {"available": True, "metric": "irr_pct", "underwritten": base, "actual_implied": prev,
            "total_pct_points": None if prev is None or base is None else prev - base, "steps": rows,
            "note": T("顺序替换法：出租率 → 其他经营差异 → NOI 增长；退出 cap 未发生前沿用承销值。")}
