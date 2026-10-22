"""可复现运行：运行编号 = 引擎版本 + 运行类型 + 规范化输入 的哈希。

引擎版本取 app/domain 全部源码的哈希：计算代码一改，版本号就变；同一份代码、同一份输入，
任何时间、任何机器算出的编号与结果都一样（半年后输入编号即可原样取回并核验）。
"""
from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

APP_VERSION = "2.0.0"
_DOMAIN_DIR = Path(__file__).resolve().parents[1]


def _clean(obj: Any) -> Any:
    if isinstance(obj, float):
        if math.isnan(obj):
            return "NaN"
        if math.isinf(obj):
            return "Inf" if obj > 0 else "-Inf"
        return obj
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return obj


def canonical_json(obj: Any) -> str:
    """键排序、无多余空白、浮点按 repr：同内容同字符串。"""
    return json.dumps(_clean(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str | bytes) -> str:
    return hashlib.sha256(text.encode("utf-8") if isinstance(text, str) else text).hexdigest()


@lru_cache(maxsize=1)
def engine_version() -> str:
    h = hashlib.sha256()
    for p in sorted(_DOMAIN_DIR.rglob("*.py")):
        h.update(p.relative_to(_DOMAIN_DIR).as_posix().encode())
        h.update(p.read_bytes())
    return f"{APP_VERSION}+{h.hexdigest()[:12]}"


def run_id(kind: str, inputs: Any, version: str | None = None) -> str:
    v = version or engine_version()
    return "R" + sha256_hex(f"{v}|{kind}|{canonical_json(inputs)}")[:20]
