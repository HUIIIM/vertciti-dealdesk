"""版本对比：任意两版承销并排，逐路径列出假设与结果的变化（像代码对比一样看）。"""
from __future__ import annotations

from typing import Any


def deep_diff(a: Any, b: Any, path: str = "") -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            p = f"{path}.{k}" if path else str(k)
            if k not in a:
                out.append({"path": p, "kind": "added", "before": None, "after": b[k]})
            elif k not in b:
                out.append({"path": p, "kind": "removed", "before": a[k], "after": None})
            else:
                out.extend(deep_diff(a[k], b[k], p))
        return out
    if isinstance(a, list) and isinstance(b, list):
        for i in range(max(len(a), len(b))):
            p = f"{path}.{i}"
            if i >= len(a):
                out.append({"path": p, "kind": "added", "before": None, "after": b[i]})
            elif i >= len(b):
                out.append({"path": p, "kind": "removed", "before": a[i], "after": None})
            else:
                out.extend(deep_diff(a[i], b[i], p))
        return out
    if a != b:
        row: dict[str, Any] = {"path": path, "kind": "changed", "before": a, "after": b}
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
            row["delta"] = b - a
            row["delta_pct"] = None if a == 0 else (b - a) / abs(a) * 100
        out.append(row)
    return out


def compare_versions(v1: dict[str, Any], v2: dict[str, Any]) -> dict[str, Any]:
    """v = {"inputs", "outputs": {"metrics": ...}}。结果变化只比标准指标（详细输出太多，噪声大）。"""
    inp = deep_diff(v1.get("inputs", {}), v2.get("inputs", {}))
    met = deep_diff((v1.get("outputs") or {}).get("metrics", {}), (v2.get("outputs") or {}).get("metrics", {}))
    return {"inputs": inp, "metrics": met, "changed_inputs": len(inp), "changed_metrics": len(met)}
