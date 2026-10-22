"""流程：阶段推进（关卡）、任务、审批（付款仅董事长）、文件、决策日志（决策时刻冻结）。"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.core import security
from app.core.context import current_actor
from app.core.i18n import T
from app.domain.v2 import lifecycle, reproducible
from app.services.persistence import audit
from app.services.persistence.engine import session_scope
from app.services.persistence.schema import Approval, Decision, Document, Task
from app.services.v2.analysis import _context
from app.services.v2.deals import _deal_dict, _event, current_version, deal_or_404
from app.services.v2.errors import ConflictError, InvalidInputError, NotFoundError
from app.services.v2.serialize import row

JSON = dict[str, Any]
MAX_DOC_BYTES = 20 * 1024 * 1024
VERDICTS = ("BUY", "HOLD", "PASS")


# ---------------------------------------------------------------- 阶段
def advance(deal_id: int, target: str, reason: str = "") -> JSON:
    with session_scope() as s:
        d = deal_or_404(s, deal_id)
        try:
            res = lifecycle.evaluate(d.stage, target, _context(s, d))
        except ValueError as e:
            raise InvalidInputError(str(e)) from e
        if not res["allowed"]:
            raise ConflictError(res["reason"], res)
        if res.get("direction") == "back" and not reason.strip():
            raise InvalidInputError(T("回退阶段须写原因"))
        before = d.stage
        d.stage = target
        _event(s, d.id, "stage_changed", {"from": before, "to": target, "reason": reason,
                                          "checks": res.get("checks", [])})
        audit.record(s, "deal", d.id, "update", {"stage": before}, {"stage": target})
        return {"deal": _deal_dict(d), "gate": res}


# ---------------------------------------------------------------- 任务
def add_task(deal_id: int, title: str, stage: str = "", assignee: str = "", due: str = "") -> JSON:
    if not title.strip():
        raise InvalidInputError(T("任务标题不能为空"))
    if stage and stage not in lifecycle.ORDER:
        raise InvalidInputError(T("未知阶段：{0}", stage))
    with session_scope() as s:
        d = deal_or_404(s, deal_id)
        t = Task(deal_id=d.id, title=title.strip(), stage=stage or d.stage, assignee=assignee, due=due,
                 created_by=current_actor().username)
        s.add(t)
        s.flush()
        return row(t)


def update_task(deal_id: int, task_id: int, changes: JSON) -> JSON:
    allowed = {"title", "status", "assignee", "due"}
    if set(changes) - allowed:
        raise InvalidInputError(T("只能修改 title / status / assignee / due"))
    if "status" in changes and changes["status"] not in ("open", "done"):
        raise InvalidInputError(T("任务状态只能是 open / done"))
    with session_scope() as s:
        t = s.get(Task, task_id)
        if t is None or t.deal_id != deal_id:
            raise NotFoundError(T("任务 {0} 不存在", task_id))
        before = row(t)
        for k, v in changes.items():
            setattr(t, k, v)
        s.flush()
        if changes.get("status") == "done":
            _event(s, deal_id, "task_done", {"task_id": t.id, "title": t.title})
        audit.record(s, "task", t.id, "update", before, row(t))
        return row(t)


def list_tasks(deal_id: int) -> list[JSON]:
    with session_scope() as s:
        deal_or_404(s, deal_id)
        return [row(t) for t in s.scalars(select(Task).where(Task.deal_id == deal_id).order_by(Task.id)).all()]


# ---------------------------------------------------------------- 审批
def request_approval(deal_id: int, kind: str, title: str, amount: float | None = None, note: str = "") -> JSON:
    if kind not in ("payment", "general", "stage_override"):
        raise InvalidInputError(T("审批类型只能是 payment / general / stage_override"))
    if kind == "payment" and (amount is None or amount <= 0):
        raise InvalidInputError(T("付款审批须填金额"))
    with session_scope() as s:
        deal_or_404(s, deal_id)
        a = Approval(deal_id=deal_id, kind=kind, title=title.strip() or kind, amount=amount, note=note,
                     created_by=current_actor().username)
        s.add(a)
        s.flush()
        _event(s, deal_id, "approval_requested", {"approval_id": a.id, "kind": kind, "amount": amount})
        audit.record(s, "approval", a.id, "create", None, row(a))
        return row(a)


def decide_approval(deal_id: int, approval_id: int, *, approve: bool, note: str = "") -> JSON:
    """付款类只能董事长批准；任何人不能批自己发起的申请（分权）。"""
    actor = current_actor()
    with session_scope() as s:
        a = s.get(Approval, approval_id)
        if a is None or a.deal_id != deal_id:
            raise NotFoundError(T("审批 {0} 不存在", approval_id))
        if a.status != "pending":
            raise ConflictError(T("该审批已{0}，不能重复决定", T("批准") if a.status == "approved" else T("驳回")))
        security.require("payment.approve" if a.kind == "payment" else "approval.decide")
        if a.created_by == actor.username and actor.username not in ("local", "system"):
            raise ConflictError(T("不能审批自己发起的申请（分权）"))
        before = row(a)
        a.status = "approved" if approve else "rejected"
        a.decided_by, a.decided_at = actor.username, datetime.now(timezone.utc)
        if note:
            a.note = (a.note + "\n" if a.note else "") + T("决定：{0}", note)
        _event(s, deal_id, "approval_decided", {"approval_id": a.id, "status": a.status})
        audit.record(s, "approval", a.id, "decide", before, row(a))
        return row(a)


def list_approvals(deal_id: int) -> list[JSON]:
    with session_scope() as s:
        deal_or_404(s, deal_id)
        return [row(a) for a in s.scalars(select(Approval).where(Approval.deal_id == deal_id)
                                          .order_by(Approval.id.desc())).all()]


# ---------------------------------------------------------------- 文件
def upload_document(deal_id: int, filename: str, content_type: str, data: bytes, category: str = "other") -> JSON:
    if not data:
        raise InvalidInputError(T("文件为空"))
    if len(data) > MAX_DOC_BYTES:
        raise InvalidInputError(T("文件超过 {0}MB 上限", MAX_DOC_BYTES // 1024 // 1024))
    with session_scope() as s:
        deal_or_404(s, deal_id)
        doc = Document(deal_id=deal_id, filename=filename[:300] or "file", content_type=content_type or
                       "application/octet-stream", size=len(data), sha256=hashlib.sha256(data).hexdigest(),
                       category=category, content=data, created_by=current_actor().username)
        s.add(doc)
        s.flush()
        _event(s, deal_id, "document_uploaded", {"document_id": doc.id, "filename": doc.filename})
        return row(doc, exclude=("content",))


def list_documents(deal_id: int) -> list[JSON]:
    with session_scope() as s:
        deal_or_404(s, deal_id)
        return [row(d, exclude=("content",)) for d in
                s.scalars(select(Document).where(Document.deal_id == deal_id).order_by(Document.id.desc())).all()]


def get_document(deal_id: int, doc_id: int) -> tuple[JSON, bytes]:
    with session_scope() as s:
        doc = s.get(Document, doc_id)
        if doc is None or doc.deal_id != deal_id:
            raise NotFoundError(T("文件 {0} 不存在", doc_id))
        return row(doc, exclude=("content",)), bytes(doc.content)


# ---------------------------------------------------------------- 决策日志
def log_decision(deal_id: int, verdict: str, rationale: str) -> JSON:
    """记 BUY / HOLD / PASS：冻结当时的数字快照、运行编号与输入哈希（复盘看的是当时原样）。"""
    if verdict not in VERDICTS:
        raise InvalidInputError(T("结论只能是 BUY / HOLD / PASS"))
    if len(rationale.strip()) < 10:
        raise InvalidInputError(T("理由至少写 10 个字（复盘时要看得懂当时为什么）"))
    with session_scope() as s:
        d = deal_or_404(s, deal_id)
        v = current_version(s, d)
        ctx = _context(s, d)
        snap = {"metrics": ctx["metrics"], "kill": ctx["kill"], "stage": d.stage,
                "version_id": v.id if v else None, "version_no": v.version_no if v else None,
                "inputs_sha256": reproducible.sha256_hex(reproducible.canonical_json(v.inputs)) if v else None,
                "verification": {"key_numbers": ctx["key_numbers"], "open_conflicts": ctx["open_conflicts"],
                                 "stale_evidence": ctx["stale_evidence"]},
                "committee": ctx["committee"]}
        dec = Decision(deal_id=d.id, verdict=verdict, rationale=rationale.strip(), snapshot=snap,
                       run_id=v.run_id if v else None, stage=d.stage, created_by=current_actor().username)
        s.add(dec)
        s.flush()
        _event(s, d.id, "decision", {"decision_id": dec.id, "verdict": verdict})
        audit.record(s, "decision", dec.id, "create", None, {"verdict": verdict, "run_id": dec.run_id})
        return row(dec)


def list_decisions(deal_id: int) -> list[JSON]:
    with session_scope() as s:
        deal_or_404(s, deal_id)
        return [row(x) for x in s.scalars(select(Decision).where(Decision.deal_id == deal_id)
                                          .order_by(Decision.id.desc())).all()]
