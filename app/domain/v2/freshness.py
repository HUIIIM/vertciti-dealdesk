"""证据新鲜度（沿用官网机制）：市场数据超过 14 天标黄“待复核”，超过 30 天停用并提示重拉。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.i18n import label

REVIEW_AFTER_DAYS = 14
STALE_AFTER_DAYS = 30
LABEL = {"fresh": "已验证", "review": "待复核", "stale": "已停用·需重拉", "unknown": "时间未知"}


def classify(evidence_at: datetime | None, now: datetime | None = None, *, market_data: bool = True) -> dict[str, Any]:
    if evidence_at is None:
        return {"state": "unknown", "age_days": None, "label": label(LABEL["unknown"])}
    now = now or datetime.now(timezone.utc)
    if evidence_at.tzinfo is None:
        evidence_at = evidence_at.replace(tzinfo=timezone.utc)
    age = (now - evidence_at).total_seconds() / 86400.0
    if not market_data or age <= REVIEW_AFTER_DAYS:
        state = "fresh"
    elif age <= STALE_AFTER_DAYS:
        state = "review"
    else:
        state = "stale"
    return {"state": state, "age_days": round(age, 1), "label": label(LABEL[state])}
