"""版本对比：任意两版承销并排，逐路径列出假设与结果的变化（像代码对比一样看）。"""
from __future__ import annotations

from typing import Any


def _diff_dict(a: dict[Any, Any], b: dict[Any, Any], path: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for k in sorted(set(a) | set(b), key=str):
        p = f"{path}.{k}" if path else str(k)
        if k not in a:
            out.append({"path": p, "kind": "added", "before": None, "after": b[k]})
        elif k not in b:
            out.append({"path": p, "kind": "removed", "before": a[k], "after": None})
        else:
            out.extend(deep_diff(a[k], b[k], p))
    return out


def _diff_list(a: list[Any], b: list[Any], path: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i in range(max(len(a), len(b))):
        p = f"{path}.{i}"
        if i >= len(a):
            out.append({"path": p, "kind": "added", "before": None, "after": b[i]})
        elif i >= len(b):
            out.append({"path": p, "kind": "removed", "before": a[i], "after": None})
        else:
            out.extend(deep_diff(a[i], b[i], p))
    return out


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def deep_diff(a: Any, b: Any, path: str = "") -> list[dict[str, Any]]:
    """逐路径列出差异：dict 按键、list 按下标递归；数值变化附带差额与变化率。"""
    if isinstance(a, dict) and isinstance(b, dict):
        return _diff_dict(a, b, path)
    if isinstance(a, list) and isinstance(b, list):
        return _diff_list(a, b, path)
    if a == b:
        return []
    row: dict[str, Any] = {"path": path, "kind": "changed", "before": a, "after": b}
    if _is_num(a) and _is_num(b):
        row["delta"] = b - a
        row["delta_pct"] = None if a == 0 else (b - a) / abs(a) * 100
    return [row]


def compare_versions(v1: dict[str, Any], v2: dict[str, Any]) -> dict[str, Any]:
    """V = {"inputs", "outputs": {"metrics": ...}}。结果变化只比标准指标（详细输出太多，噪声大）。"""
    inp = deep_diff(v1.get("inputs", {}), v2.get("inputs", {}))
    met = deep_diff((v1.get("outputs") or {}).get("metrics", {}), (v2.get("outputs") or {}).get("metrics", {}))
    return {"inputs": inp, "metrics": met, "changed_inputs": len(inp), "changed_metrics": len(met)}
