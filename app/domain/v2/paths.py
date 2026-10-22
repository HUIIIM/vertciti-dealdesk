"""点路径读写：'analysis.exit_cap_rate'、'tenants.0.monthly_rent'、'tenants.*.monthly_rent'（* = 每一项）。"""
from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

JSON = dict[str, Any]


def _step(node: Any, key: str) -> Any:
    if isinstance(node, list):
        return node[int(key)]
    if isinstance(node, dict):
        return node.get(key)
    return None


def get_path(data: Any, path: str) -> Any:
    """读值；路径不存在返回 None。含 * 时返回各项值的列表。"""
    parts = path.split(".")
    for i, k in enumerate(parts):
        if k == "*":
            if not isinstance(data, list):
                return None
            rest = ".".join(parts[i + 1:])
            return [get_path(x, rest) if rest else x for x in data]
        try:
            data = _step(data, k)
        except (IndexError, ValueError):
            return None
        if data is None:
            return None
    return data


def update_path(data: JSON, path: str, fn: Callable[[Any], Any]) -> JSON:
    """返回深拷贝后的新对象，path 处的值替换为 fn(旧值)；* 对每一项生效；中间缺失的 dict 自动补。"""
    out = copy.deepcopy(data)
    _apply(out, path.split("."), fn)
    return out


def set_path(data: JSON, path: str, value: Any) -> JSON:
    return update_path(data, path, lambda _old: value)


def _apply(node: Any, parts: list[str], fn: Callable[[Any], Any]) -> None:
    k, rest = parts[0], parts[1:]
    if k == "*":
        if isinstance(node, list):
            for i in range(len(node)):
                if rest:
                    _apply(node[i], rest, fn)
                else:
                    node[i] = fn(node[i])
        return
    if isinstance(node, list):
        idx = int(k)
        if rest:
            _apply(node[idx], rest, fn)
        else:
            node[idx] = fn(node[idx])
        return
    if not isinstance(node, dict):
        return
    if rest:
        if not isinstance(node.get(k), (dict, list)):
            node[k] = {}
        _apply(node[k], rest, fn)
    else:
        node[k] = fn(node.get(k))


def scale_numeric(value: Any, factor: float) -> Any:
    """数值乘以 factor；非数值（None / 文本）原样返回。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    return value * factor
