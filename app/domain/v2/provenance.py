"""数字护照规则：可信度、抽取方式、复核状态、假设来源、跨来源矛盾、关键数字判定。"""
from __future__ import annotations

from typing import Any

CONFIDENCE = ("low", "medium", "high")
CONFIDENCE_LABEL = {"low": "低", "medium": "中", "high": "高"}
METHODS = {"manual": "人工录入", "ocr": "OCR 识别", "api": "接口拉取", "pdf": "PDF 抽取", "calc": "系统计算",
           "import": "导入"}
REVIEW = {"pending": "待复核", "reviewed": "已复核", "overridden": "人工改写"}
ASSUMPTION_SOURCES = {"document": "文件抽取", "historical": "历史数据", "benchmark": "市场基准",
                      "comps": "可比交易", "analyst": "分析师判断"}
# 两个来源数值相对差超过此比例 → 记为矛盾（0.5%：四舍五入差异不算矛盾）
CONFLICT_TOLERANCE = 0.005


def confidence_at_least(c: str, floor: str) -> bool:
    return CONFIDENCE.index(c) >= CONFIDENCE.index(floor)


def values_conflict(a: Any, b: Any, tol: float = CONFLICT_TOLERANCE) -> bool:
    if isinstance(a, bool) or isinstance(b, bool) or not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return a != b
    if a == b:
        return False
    base = max(abs(a), abs(b))
    return base > 0 and abs(a - b) / base > tol


def diff_pct(a: Any, b: Any) -> float | None:
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)) or isinstance(a, bool):
        return None
    base = max(abs(a), abs(b))
    return None if base == 0 else abs(a - b) / base * 100.0


def key_number_status(key_fields: list[str], passports: dict[str, dict[str, Any]],
                      floor: str = "medium") -> dict[str, Any]:
    """关键数字（由红队面板的敏感性客观定义）是否都已复核且可信度 ≥ floor。"""
    rows = []
    for f in key_fields:
        p = passports.get(f)
        if p is None:
            rows.append({"field": f, "ok": False, "reason": "没有来源记录（数字护照为空）"})
            continue
        if not confidence_at_least(p.get("confidence", "low"), floor):
            rows.append({"field": f, "ok": False,
                         "reason": f"可信度{CONFIDENCE_LABEL.get(p.get('confidence', 'low'))}，低于{CONFIDENCE_LABEL[floor]}"})
            continue
        if p.get("review_status", "pending") == "pending":
            rows.append({"field": f, "ok": False, "reason": "尚未复核"})
            continue
        rows.append({"field": f, "ok": True, "reason": ""})
    done = sum(1 for r in rows if r["ok"])
    return {"items": rows, "done": done, "total": len(rows), "ok": done == len(rows)}
