"""核对价值排序（vertciti 独有）：先核哪个数？

别人只告诉你“有 n 处待核”；这里把每一处待核按“它能让主回报指标摆动多少个基点”排序：
- 未裁决的跨来源矛盾：分别代入两个来源的值重跑当前版本，主指标差多少；
- 未达标的关键数字（没来源 / 可信度不够 / 未复核）：取红队面板里它 ±10% 的摆动；
同一假设（可能覆盖多个字段）只列一次；既有矛盾又未复核时取矛盾的实测摆动。结果从大到小，第一条就是“先去追这份文件”。
"""
from __future__ import annotations

from typing import Any

from app.core.i18n import T, label
from app.domain.v2.assumptions import BY_TRACK
from app.domain.v2.model import METRICS, PRIMARY_METRIC, ModelInputError, primary_value, run_model
from app.domain.v2.paths import set_path

JSON = dict[str, Any]


def _assumption_for(track: str, field: str) -> tuple[str, str]:
    """字段所属假设（键，名称）；不属于任何假设时用字段本身。一个假设常覆盖多个字段路径（如各租户租金）。"""
    for a in BY_TRACK[track]:
        if any(_matches(p, field) for p in a.paths):
            return a.key, label(a.label)
    return field, field


def _matches(pattern: str, field: str) -> bool:
    """假设路径里的 * 匹配任一下标：tenants.*.monthly_rent 覆盖 tenants.0.monthly_rent。"""
    a, b = pattern.split("."), field.split(".")
    return len(a) == len(b) and all(x == y or (x == "*" and y.isdigit()) for x, y in zip(a, b, strict=True))


def _primary_at(track: str, inputs: JSON, field: str, value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        return primary_value(track, run_model(track, set_path(inputs, field, value)))
    except ModelInputError:
        return None


def rank(track: str, inputs: JSON, redteam: JSON, key_status: JSON, conflicts: list[JSON]) -> JSON:
    """redteam：redteam.run() 的结果；key_status：provenance.key_number_status()；conflicts：未裁决矛盾行。"""
    metric = PRIMARY_METRIC[track]  # type: ignore[index]
    items: list[JSON] = []
    seen: set[str] = set()  # 已列出的假设键：同一假设只列一次
    for c in conflicts:
        key, name = _assumption_for(track, c["field"])
        if key in seen:
            continue
        a = _primary_at(track, inputs, c["field"], c["value_a"])
        b = _primary_at(track, inputs, c["field"], c["value_b"])
        items.append({
            "kind": "conflict", "field": c["field"], "label": name, "conflict_id": c["id"],
            "swing_bps": None if a is None or b is None else abs(a - b) * 100.0,
            "detail": f"{c['source_a']} {c['value_a']} vs {c['source_b']} {c['value_b']}",
            "primary_a": a, "primary_b": b, "action": T("裁决矛盾"),
        })
        seen.add(key)
    swing_by_path = {p: r["swing_bps"] for r in redteam.get("all", []) for p in r["paths"]}
    pending: dict[str, JSON] = {}
    for k in key_status.get("items", []):
        key, name = _assumption_for(track, k["field"])
        if k["ok"] or key in seen:
            continue
        row = pending.setdefault(key, {"kind": "unverified", "field": k["field"], "label": name, "conflict_id": None,
                                       "swing_bps": swing_by_path.get(k["field"]), "primary_a": None, "primary_b": None,
                                       "reasons": set(), "n": 0, "no_source": False})
        row["reasons"].add(k["reason"])
        row["no_source"] = row["no_source"] or k.get("code") == "no_source"
        row["n"] += 1
    for row in pending.values():
        reasons, n = sorted(row.pop("reasons")), row.pop("n")
        row["detail"] = (T("{0} 个字段：", n) if n > 1 else "") + T("；").join(reasons)
        row["action"] = T("补来源") if row.pop("no_source") else T("复核")
        items.append(row)
    # 未知摆动（算不出）排最后，但不丢：未知保持未知
    items.sort(key=lambda x: -1.0 if x["swing_bps"] is None else x["swing_bps"], reverse=True)
    known = [x["swing_bps"] for x in items if x["swing_bps"] is not None]
    return {
        "metric": metric, "metric_label": label(METRICS[metric].label), "items": items,
        "top_share_pct": (known[0] / sum(known) * 100.0) if known and sum(known) > 0 else None,
        "note": T("按“这处待核能让主回报指标摆动多少基点”排序：矛盾按两个来源值实测，未复核关键数字按 ±10% 摆动。"),
    }
