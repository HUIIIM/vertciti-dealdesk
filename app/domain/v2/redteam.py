"""红队面板：自动找出这笔交易最可能出错的 5 个假设，以及每个错 10% 对主回报指标的影响（龙卷风图）。

vertciti 独有：用同一结果客观定义“关键数字”——凡是 ±10% 会让主回报指标移动 ≥ 100 个基点
（1 个百分点）的假设，都是关键数字；进投委会前必须全部复核、可信度 ≥ 中。
"""
from __future__ import annotations

from functools import partial
from typing import Any

from app.core.i18n import T, label
from app.domain.v2.assumptions import BY_TRACK, Assumption
from app.domain.v2.model import METRICS, PRIMARY_METRIC, ModelInputError, primary_value, run_model
from app.domain.v2.paths import get_path, scale_numeric, update_path

SHOCK = 0.10
MATERIAL_BPS = 100.0
TOP_N = 5
JSON = dict[str, Any]


def _has_value(inputs: JSON, a: Assumption) -> bool:
    for p in a.paths:
        v = get_path(inputs, p)
        vals = v if isinstance(v, list) else [v]
        if any(isinstance(x, (int, float)) and not isinstance(x, bool) and x != 0 for x in vals):
            return True
    return False


def shock(inputs: JSON, a: Assumption, factor: float) -> JSON:
    out = inputs
    for p in a.paths:
        out = update_path(out, p, partial(scale_numeric, factor=factor))
    return out


def _safe_primary(track: str, inputs: JSON) -> float | None:
    try:
        return primary_value(track, run_model(track, inputs))
    except ModelInputError:
        return None


def run(track: str, inputs: JSON, shock_pct: float = SHOCK * 100) -> JSON:
    factor = shock_pct / 100.0
    base = primary_value(track, run_model(track, inputs))
    metric = PRIMARY_METRIC[track]  # type: ignore[index]
    rows: list[JSON] = []
    skipped: list[JSON] = []
    for a in BY_TRACK[track]:
        if not _has_value(inputs, a):
            skipped.append({"key": a.key, "label": label(a.label), "reason": T("当前输入为空或 0，无法扰动")})
            continue
        low = _safe_primary(track, shock(inputs, a, 1 - factor))
        high = _safe_primary(track, shock(inputs, a, 1 + factor))
        if base is None or low is None or high is None:
            skipped.append({"key": a.key, "label": label(a.label), "reason": T(
                "{0}无法计算（数据不足）",
                label(METRICS[metric].label))})
            continue
        d_low, d_high = low - base, high - base
        swing_bps = max(abs(d_low), abs(d_high)) * 100.0
        rows.append({
            "key": a.key, "label": label(a.label), "paths": list(a.paths), "source_hint": label(a.source_hint),
            "minus": {"value": low, "delta_pct_points": d_low},
            "plus": {"value": high, "delta_pct_points": d_high},
            "swing_bps": swing_bps, "material": swing_bps >= MATERIAL_BPS,
        })
    rows.sort(key=lambda r: r["swing_bps"], reverse=True)
    return {
        "metric": metric, "metric_label": label(METRICS[metric].label), "base": base, "shock_pct": shock_pct,
        "material_bps": MATERIAL_BPS, "top": rows[:TOP_N], "all": rows, "skipped": skipped,
        "key_assumptions": [r["key"] for r in rows if r["material"]],
        "key_fields": sorted({p for r in rows if r["material"] for p in r["paths"]}),
        "note": T("每个假设单独上下浮动 {0:g}%，其余不变；主指标为{1}。"
                  "波动 ≥ {2:g} 个基点的假设定为关键数字。", shock_pct, label(METRICS[metric].label), MATERIAL_BPS),
    }
