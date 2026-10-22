"""决策支持：红队面板、情景加权、反推最高出价、版本对比、交易并排、核对进度、关卡预检。"""
from __future__ import annotations

import copy
import threading
from collections import OrderedDict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import security
from app.core.context import current_actor
from app.core.i18n import T, current_lang, label
from app.domain.v2 import (
    devils_advocate,
    diffing,
    kill_criteria,
    lifecycle,
    max_bid,
    provenance,
    redteam,
    scenarios,
    verification_value,
)
from app.domain.v2.committee import tally
from app.domain.v2.model import METRICS, ModelInputError
from app.services.persistence import audit
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
from app.services.persistence.schema import (
    Conflict as ConflictRow,
)
from app.services.v2 import evidence
from app.services.v2.deals import _deal_dict, _event, current_version, deal_or_404, version_dict, version_label
from app.services.v2.errors import ConflictError, InvalidInputError, NotFoundError

JSON = dict[str, Any]


_RT_CACHE: OrderedDict[tuple[str, str], JSON] = OrderedDict()
_RT_LOCK = threading.Lock()
_RT_MAX = 256


def redteam_of(d: Deal, v: DealVersion) -> JSON:
    """红队面板（数十次模型运行），按 (运行编号, 语言) 缓存。

    运行编号 = 引擎版本 + 输入哈希，同编号结果必然相同。交易页每次打开都要用它定义关键数字，
    不缓存的话大输入会让任何只读用户拖慢服务。
    """
    key = (v.run_id, current_lang())
    with _RT_LOCK:
        hit = _RT_CACHE.get(key)
        if hit is not None:
            _RT_CACHE.move_to_end(key)
            return copy.deepcopy(hit)
    out = redteam.run(d.track, v.inputs)
    with _RT_LOCK:
        _RT_CACHE[key] = out
        while len(_RT_CACHE) > _RT_MAX:
            _RT_CACHE.popitem(last=False)
    return copy.deepcopy(out)


def _require_version(s: Session, d: Deal) -> DealVersion:
    v = current_version(s, d)
    if v is None:
        raise ConflictError(T("这笔交易还没有承销版本：先在模型页保存一版"))
    return v


def redteam_for(deal_id: int) -> JSON:
    with session_scope() as s:
        d = deal_or_404(s, deal_id)
        v = _require_version(s, d)
        r = redteam_of(d, v)
        read = s.scalar(select(DealEvent.id).where(DealEvent.deal_id == d.id, DealEvent.kind == "redteam_read",
                                                   DealEvent.payload["version_id"].as_integer() == v.id))
        return {**r, "version_id": v.id, "read": read is not None}


def mark_redteam_read(deal_id: int) -> JSON:
    with session_scope() as s:
        d = deal_or_404(s, deal_id)
        v = _require_version(s, d)
        _event(s, d.id, "redteam_read", {"version_id": v.id, "reader": current_actor().username})
        audit.record(s, "deal", d.id, "update", None, {"redteam_read": v.id})  # 进投委会关卡之一，必须留痕
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


def verification_queue(deal_id: int) -> JSON:
    """先核哪个：未裁决矛盾 + 未达标关键数字，按对主回报指标的摆动排序。"""
    with session_scope() as s:
        d = deal_or_404(s, deal_id)
        v = _require_version(s, d)
        try:
            rt = redteam_of(d, v)
        except ModelInputError as e:
            raise InvalidInputError(str(e)) from e
        ps = evidence.latest_passports(s, d.id)
        ks = provenance.key_number_status(rt["key_fields"], ps, four_eyes=security.auth_enabled())
        cons = [{"id": c.id, "field": c.field, "value_a": c.value_a, "source_a": c.source_a, "value_b": c.value_b,
                 "source_b": c.source_b} for c in s.scalars(select(ConflictRow).where(
                     ConflictRow.deal_id == d.id, ConflictRow.status == "open").order_by(ConflictRow.id)).all()]
        return {**verification_value.rank(d.track, v.inputs, rt, ks, cons), "version_id": v.id}


def kill_changes_after_model(s: Session, deal_id: int) -> int:
    """第一版承销保存之后，淘汰条件又被改过几次（看过模型再改门槛，是治理上要被看见的事）。"""
    first = s.scalar(select(DealEvent.id).where(DealEvent.deal_id == deal_id, DealEvent.kind == "version_saved")
                     .order_by(DealEvent.id).limit(1))
    if first is None:
        return 0
    return len(s.scalars(select(DealEvent.id).where(DealEvent.deal_id == deal_id, DealEvent.id > first,
                                                    DealEvent.kind == "kill_criteria_changed")).all())


def devils_memo(deal_id: int) -> JSON:
    """反方备忘录：确定性规则拼出“这笔交易最可能怎么失败”，不经 AI。"""
    queue = verification_queue(deal_id)
    with session_scope() as s:
        d = deal_or_404(s, deal_id)
        v = _require_version(s, d)
        ctx = _context(s, d)
        try:
            rt = redteam_of(d, v)
        except ModelInputError:
            rt = None
        try:
            sc = scenarios.run(d.track, v.inputs)
        except (ValueError, KeyError, ModelInputError):
            sc = None
        try:
            mb = max_bid.run(d.track, v.inputs, [], kill=d.kill_criteria)
        except ValueError:
            mb = None
        memo = devils_advocate.build(d.track, v.inputs, ctx["metrics"], {
            "kill": ctx["kill"], "redteam": rt, "scenarios": sc, "max_bid": mb, "key_numbers": ctx["key_numbers"],
            "queue": queue, "stale": ctx["stale_evidence"], "kill_changes": kill_changes_after_model(s, d.id)})
        return {**memo, "version_id": v.id, "run_id": v.run_id}


def diff_versions(deal_id: int, a: int, b: int) -> JSON:
    with session_scope() as s:
        deal_or_404(s, deal_id)
        va, vb = s.get(DealVersion, a), s.get(DealVersion, b)
        if va is None or vb is None or va.deal_id != deal_id or vb.deal_id != deal_id:
            raise NotFoundError(T("版本不存在"))
        out = diffing.compare_versions(version_dict(va, with_detail=True), version_dict(vb, with_detail=True))
        return {"a": {"id": va.id, "version_no": va.version_no, "label": version_label(va), "run_id": va.run_id},
                "b": {"id": vb.id, "version_no": vb.version_no, "label": version_label(vb), "run_id": vb.run_id}, **out}


def _context(s: Session, d: Deal) -> JSON:
    """关卡与核对进度所需的全部事实（一次查齐）。"""
    v = current_version(s, d)
    metrics = v.outputs.get("metrics", {}) if v else {}
    ev = evidence.counts(s, d.id)
    key_fields: list[str] = []
    rt_read = False
    if v is not None:
        try:
            key_fields = redteam_of(d, v)["key_fields"]
        except ModelInputError:
            key_fields = []
        rt_read = s.scalar(select(DealEvent.id).where(
            DealEvent.deal_id == d.id, DealEvent.kind == "redteam_read",
            DealEvent.payload["version_id"].as_integer() == v.id)) is not None
    kn = provenance.key_number_status(key_fields, ev["passports"], four_eyes=security.auth_enabled())
    votes = s.scalars(select(CommitteeVote).where(CommitteeVote.deal_id == d.id,
                                                  CommitteeVote.version_id == (v.id if v else None))).all()
    roles = {u.username: u.role for u in s.scalars(select(User)).all()} | security.builtin_roles()
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
            "metric_catalog": {k: {"label": label(m.label), "label_en": m.label_en, "unit": m.unit, "better": m.better}
                               for k, m in METRICS.items()},
            "kill": ctx["kill"],
            "verification": {"key_reviewed": kn["done"], "key_total": kn["total"], "key_items": kn["items"],
                             "open_conflicts": ctx["open_conflicts"], "stale_evidence": ctx["stale_evidence"],
                             "review_due": ctx["review_due"], "redteam_read": ctx["redteam_read"]},
            "committee": ctx["committee"], "last_verdict": ctx["last_verdict"],
            "next_stage": nxt, "next_gate": gate,
            "stages": [{"key": k, "label": label(lbl)} for k, lbl in lifecycle.STAGES],
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
        raise InvalidInputError(T("比较页支持 2–4 笔交易"))
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
