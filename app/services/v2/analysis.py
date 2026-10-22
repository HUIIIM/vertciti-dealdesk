"""决策支持：红队面板、情景加权、反推最高出价、版本对比、交易并排、核对进度、关卡预检。"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.context import current_actor
from app.domain.v2 import diffing, kill_criteria, lifecycle, max_bid, provenance, redteam, scenarios
from app.domain.v2.committee import tally
from app.domain.v2.model import METRICS, ModelInputError
from app.services.persistence.engine import session_scope
from app.services.persistence.schema import (
    Approval,
    CommitteeVote,
    Deal,
    DealEvent,
    DealVersion,
    Decision,
    Task,
    User,
)
from app.services.v2 import evidence
from app.services.v2.deals import _deal_dict, _event, current_version, deal_or_404, version_dict
from app.services.v2.errors import ConflictError, InvalidInputError, NotFoundError

JSON = dict[str, Any]


def _require_version(s: Session, d: Deal) -> DealVersion:
    v = current_version(s, d)
    if v is None:
        raise ConflictError("这笔交易还没有承销版本：先在模型页保存一版")
    return v


def redteam_for(deal_id: int) -> JSON:
    with session_scope() as s:
        d = deal_or_404(s, deal_id)
        v = _require_version(s, d)
        r = redteam.run(d.track, v.inputs)
        read = s.scalar(select(DealEvent.id).where(DealEvent.deal_id == d.id, DealEvent.kind == "redteam_read",
                                                   DealEvent.payload["version_id"].as_integer() == v.id))
        return {**r, "version_id": v.id, "read": read is not None}


def mark_redteam_read(deal_id: int) -> JSON:
    with session_scope() as s:
        d = deal_or_404(s, deal_id)
        v = _require_version(s, d)
        _event(s, d.id, "redteam_read", {"version_id": v.id, "reader": current_actor().username})
        return {"version_id": v.id, "read": True}


def scenarios_for(deal_id: int, custom: list[JSON] | None = None) -> JSON:
    with session_scope() as s:
        d = deal_or_404(s, deal_id)
        v = _require_version(s, d)
        try:
            return scenarios.run(d.track, v.inputs, custom)
        except (ValueError, KeyError, ModelInputError) as e:
            raise InvalidInputError(str(e)) from e


def max_bid_for(deal_id: int, targets: list[JSON], *, include_kill: bool = True) -> JSON:
    with session_scope() as s:
        d = deal_or_404(s, deal_id)
        v = _require_version(s, d)
        try:
            return max_bid.run(d.track, v.inputs, targets, kill=d.kill_criteria if include_kill else [])
        except ValueError as e:
            raise InvalidInputError(str(e)) from e


def price_check_for(deal_id: int, price: float) -> JSON:
    with session_scope() as s:
        d = deal_or_404(s, deal_id)
        v = _require_version(s, d)
        try:
            return max_bid.price_check(d.track, v.inputs, price, kill=d.kill_criteria)
        except ValueError as e:
            raise InvalidInputError(str(e)) from e


def diff_versions(deal_id: int, a: int, b: int) -> JSON:
    with session_scope() as s:
        va, vb = s.get(DealVersion, a), s.get(DealVersion, b)
        if va is None or vb is None or va.deal_id != deal_id or vb.deal_id != deal_id:
            raise NotFoundError("版本不存在")
        out = diffing.compare_versions(version_dict(va, with_detail=True), version_dict(vb, with_detail=True))
        return {"a": {"id": va.id, "version_no": va.version_no, "label": va.label, "run_id": va.run_id},
                "b": {"id": vb.id, "version_no": vb.version_no, "label": vb.label, "run_id": vb.run_id}, **out}


def _context(s: Session, d: Deal) -> JSON:
    """关卡与核对进度所需的全部事实（一次查齐）。"""
    v = current_version(s, d)
    metrics = v.outputs.get("metrics", {}) if v else {}
    ev = evidence.counts(s, d.id)
    key_fields: list[str] = []
    rt_read = False
    if v is not None:
        try:
            key_fields = redteam.run(d.track, v.inputs)["key_fields"]
        except ModelInputError:
            key_fields = []
        rt_read = s.scalar(select(DealEvent.id).where(
            DealEvent.deal_id == d.id, DealEvent.kind == "redteam_read",
            DealEvent.payload["version_id"].as_integer() == v.id)) is not None
    kn = provenance.key_number_status(key_fields, ev["passports"])
    votes = s.scalars(select(CommitteeVote).where(CommitteeVote.deal_id == d.id,
                                                  CommitteeVote.version_id == (v.id if v else None))).all()
    roles = {u.username: u.role for u in s.scalars(select(User)).all()} | {"local": "chairman"}
    last = s.scalars(select(Decision).where(Decision.deal_id == d.id).order_by(Decision.id.desc()).limit(1)).first()
    tasks = s.scalars(select(Task).where(Task.deal_id == d.id, Task.status != "done")).all()
    open_tasks: dict[str, int] = {}
    for t in tasks:
        open_tasks[t.stage] = open_tasks.get(t.stage, 0) + 1
    pays = s.scalars(select(Approval).where(Approval.deal_id == d.id, Approval.kind == "payment")).all()
    return {
        "has_basics": bool(d.name and d.track and d.address), "asking_price": d.asking_price,
        "kill": kill_criteria.evaluate(d.kill_criteria, metrics), "versions": 1 if v else 0,
        "key_numbers": kn, "open_conflicts": ev["open_conflicts"], "stale_evidence": ev["stale_evidence"],
        "review_due": ev["review_due"], "redteam_read": rt_read,
        "committee": tally([{"voter": x.voter, "vote": x.vote} for x in votes], roles),
        "last_verdict": last.verdict if last else None, "open_tasks": open_tasks,
        "payments": {"approved": sum(1 for p in pays if p.status == "approved"),
                     "pending": sum(1 for p in pays if p.status == "pending")},
        "metrics": metrics, "version": version_dict(v) if v else None,
    }


def overview(deal_id: int) -> JSON:
    """交易页顶部结论卡 + 核对进度条 + 下一阶段关卡预检。"""
    with session_scope() as s:
        d = deal_or_404(s, deal_id)
        ctx = _context(s, d)
        nxt = lifecycle.next_stage(d.stage)
        gate = lifecycle.evaluate(d.stage, nxt, ctx) if nxt else None
        kn = ctx["key_numbers"]
        return {
            "deal": _deal_dict(d), "version": ctx["version"], "metrics": ctx["metrics"],
            "metric_catalog": {k: {"label": m.label, "label_en": m.label_en, "unit": m.unit, "better": m.better}
                               for k, m in METRICS.items()},
            "kill": ctx["kill"],
            "verification": {"key_reviewed": kn["done"], "key_total": kn["total"], "key_items": kn["items"],
                             "open_conflicts": ctx["open_conflicts"], "stale_evidence": ctx["stale_evidence"],
                             "review_due": ctx["review_due"], "redteam_read": ctx["redteam_read"]},
            "committee": ctx["committee"], "last_verdict": ctx["last_verdict"],
            "next_stage": nxt, "next_gate": gate, "stages": [{"key": k, "label": lbl} for k, lbl in lifecycle.STAGES],
        }


def gate_check(deal_id: int, target: str) -> JSON:
    with session_scope() as s:
        d = deal_or_404(s, deal_id)
        try:
            return lifecycle.evaluate(d.stage, target, _context(s, d))
        except ValueError as e:
            raise InvalidInputError(str(e)) from e


def compare_deals(ids: list[int]) -> JSON:
    if not 2 <= len(ids) <= 4:
        raise InvalidInputError("比较页支持 2–4 笔交易")
    with session_scope() as s:
        out: list[JSON] = []
        for i in ids:
            d = deal_or_404(s, i)
            v = current_version(s, d)
            m = v.outputs.get("metrics", {}) if v else {}
            out.append({"deal": _deal_dict(d), "metrics": m, "version": version_dict(v) if v else None,
                        "kill": kill_criteria.evaluate(d.kill_criteria, m) if v else None})
        best: JSON = {}
        for k, meta in METRICS.items():
            vals: list[tuple[int, float]] = []
            for x in out:
                v_ = (x["metrics"] or {}).get(k)
                if isinstance(v_, (int, float)):
                    vals.append((int(x["deal"]["id"]), float(v_)))
            if len(vals) >= 2:
                pick = max(vals, key=lambda t: t[1]) if meta.better == "higher" else min(vals, key=lambda t: t[1])
                best[k] = pick[0]
        return {"deals": out, "best": best}
