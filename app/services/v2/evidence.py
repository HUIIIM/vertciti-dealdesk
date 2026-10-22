"""数字护照：每个数字的来源、页码、抽取方式、可信度、复核、新鲜度与修改历史；跨来源矛盾登记。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.context import current_actor
from app.domain.v2 import freshness, provenance
from app.services.persistence import audit
from app.services.persistence.engine import session_scope
from app.services.persistence.schema import Conflict, FieldProvenance
from app.services.v2.deals import _event, deal_or_404
from app.services.v2.errors import Invalid, NotFound
from app.services.v2.serialize import row

JSON = dict[str, Any]


def _parse_dt(v: Any) -> datetime | None:
    if v is None or isinstance(v, datetime):
        return v
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError as e:
        raise Invalid(f"时间格式不对（应为 ISO 8601）：{v!r}") from e
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _passport_dict(p: FieldProvenance, now: datetime | None = None) -> JSON:
    out = row(p)
    out["method_label"] = provenance.METHODS.get(p.method, p.method)
    out["confidence_label"] = provenance.CONFIDENCE_LABEL.get(p.confidence, p.confidence)
    out["review_label"] = provenance.REVIEW.get(p.review_status, p.review_status)
    out["assumption_source_label"] = provenance.ASSUMPTION_SOURCES.get(p.assumption_source, p.assumption_source)
    out["freshness"] = freshness.classify(p.evidence_at, now, market_data=p.market_data)
    return out


def add_evidence(deal_id: int, field: str, value: Any, *, source: str, method: str, confidence: str,
                 page: int | None = None, document_id: int | None = None, evidence_at: Any = None,
                 market_data: bool = False, assumption_source: str = "document", note: str = "") -> JSON:
    if method not in provenance.METHODS:
        raise Invalid(f"抽取方式只能是：{', '.join(provenance.METHODS)}")
    if confidence not in provenance.CONFIDENCE:
        raise Invalid("可信度只能是 high / medium / low")
    if assumption_source not in provenance.ASSUMPTION_SOURCES:
        raise Invalid(f"假设来源只能是：{', '.join(provenance.ASSUMPTION_SOURCES)}")
    if not field.strip() or not source.strip():
        raise Invalid("字段与来源不能为空")
    with session_scope() as s:
        deal_or_404(s, deal_id)
        prior = s.scalars(select(FieldProvenance).where(FieldProvenance.deal_id == deal_id,
                                                        FieldProvenance.field == field)
                          .order_by(FieldProvenance.id.desc())).all()
        p = FieldProvenance(deal_id=deal_id, field=field, value=value, source=source.strip(), page=page,
                            document_id=document_id, method=method, confidence=confidence,
                            evidence_at=_parse_dt(evidence_at), market_data=market_data,
                            assumption_source=assumption_source, note=note, created_by=current_actor().username,
                            review_status="overridden" if method == "manual" and prior else "pending")
        s.add(p)
        s.flush()
        conflict = None
        other = next((x for x in prior if x.source != p.source), None)
        if other is not None and provenance.values_conflict(other.value, value):
            c = Conflict(deal_id=deal_id, field=field, value_a=other.value, source_a=other.source, value_b=value,
                         source_b=p.source, diff_pct=provenance.diff_pct(other.value, value),
                         created_by=current_actor().username)
            s.add(c)
            s.flush()
            conflict = row(c)
            _event(s, deal_id, "conflict_opened", {"field": field, "conflict_id": c.id})
        audit.record(s, "field_provenance", p.id, "create", None, {"field": field, "value": value, "source": source})
        return {"passport": _passport_dict(p), "conflict": conflict}


def review(deal_id: int, field: str, note: str = "") -> JSON:
    """把该字段当前（最新）来源标为已复核。"""
    with session_scope() as s:
        deal_or_404(s, deal_id)
        p = s.scalars(select(FieldProvenance).where(FieldProvenance.deal_id == deal_id, FieldProvenance.field == field)
                      .order_by(FieldProvenance.id.desc()).limit(1)).first()
        if p is None:
            raise NotFound(f"字段 {field} 没有来源记录")
        before = p.review_status
        if p.review_status != "overridden":
            p.review_status = "reviewed"
        p.reviewed_by, p.reviewed_at = current_actor().username, datetime.now(timezone.utc)
        if note:
            p.note = (p.note + "\n" if p.note else "") + f"复核：{note}"
        audit.record(s, "field_provenance", p.id, "update", {"review_status": before},
                     {"review_status": p.review_status, "reviewed_by": p.reviewed_by})
        return _passport_dict(p)


def passport(deal_id: int, field: str) -> JSON:
    """单个数字的护照：当前值 + 全部历史（谁在何时改过）+ 相关矛盾。"""
    with session_scope() as s:
        deal_or_404(s, deal_id)
        hist = s.scalars(select(FieldProvenance).where(FieldProvenance.deal_id == deal_id,
                                                       FieldProvenance.field == field)
                         .order_by(FieldProvenance.id.desc())).all()
        if not hist:
            raise NotFound(f"字段 {field} 没有来源记录（未知保持未知）")
        cons = s.scalars(select(Conflict).where(Conflict.deal_id == deal_id, Conflict.field == field)
                         .order_by(Conflict.id.desc())).all()
        now = datetime.now(timezone.utc)
        return {"field": field, "current": _passport_dict(hist[0], now),
                "history": [_passport_dict(h, now) for h in hist], "conflicts": [row(c) for c in cons]}


def latest_passports(s: Session, deal_id: int) -> dict[str, JSON]:
    rows = s.scalars(select(FieldProvenance).where(FieldProvenance.deal_id == deal_id)
                     .order_by(FieldProvenance.id.desc())).all()
    now = datetime.now(timezone.utc)
    out: dict[str, JSON] = {}
    for r in rows:
        if r.field not in out:
            out[r.field] = _passport_dict(r, now)
    return out


def list_passports(deal_id: int) -> list[JSON]:
    with session_scope() as s:
        deal_or_404(s, deal_id)
        return sorted(latest_passports(s, deal_id).values(), key=lambda p: p["field"])


def list_conflicts(deal_id: int, status: str | None = None) -> list[JSON]:
    with session_scope() as s:
        deal_or_404(s, deal_id)
        q = select(Conflict).where(Conflict.deal_id == deal_id)
        if status:
            q = q.where(Conflict.status == status)
        return [row(c) for c in s.scalars(q.order_by(Conflict.id.desc())).all()]


def resolve_conflict(deal_id: int, conflict_id: int, value: Any, note: str) -> JSON:
    if not note.strip():
        raise Invalid("裁决须写理由（为什么采用这个值）")
    with session_scope() as s:
        c = s.get(Conflict, conflict_id)
        if c is None or c.deal_id != deal_id:
            raise NotFound(f"矛盾 {conflict_id} 不存在")
        before = row(c)
        c.status, c.resolved_value, c.resolution_note = "resolved", value, note.strip()
        c.resolved_by, c.resolved_at = current_actor().username, datetime.now(timezone.utc)
        _event(s, deal_id, "conflict_resolved", {"conflict_id": c.id, "field": c.field, "value": value})
        audit.record(s, "conflict", c.id, "decide", before, row(c))
        return row(c)


def counts(s: Session, deal_id: int) -> JSON:
    open_c = len(s.scalars(select(Conflict.id).where(Conflict.deal_id == deal_id, Conflict.status == "open")).all())
    ps = latest_passports(s, deal_id)
    stale = sum(1 for p in ps.values() if p["freshness"]["state"] == "stale")
    review_due = sum(1 for p in ps.values() if p["freshness"]["state"] == "review")
    return {"open_conflicts": open_c, "stale_evidence": stale, "review_due": review_due, "passports": ps}
