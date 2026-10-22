"""投委会：投票（每人每版一票，可改票留痕）、计票、一键生成投委会包、防篡改校验。"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import security
from app.core.context import current_actor
from app.core.i18n import T, label
from app.domain.v2 import (
    devils_advocate,
    diffing,
    max_bid,
    provenance,
    reproducible,
    scenarios,
    verification_value,
)
from app.domain.v2.committee import tally
from app.domain.v2.model import METRICS, ModelInputError
from app.services.persistence import audit
from app.services.persistence.engine import session_scope
from app.services.persistence.schema import CommitteePack, CommitteeVote, DealVersion, Decision, User
from app.services.persistence.schema import Conflict as ConflictRow
from app.services.render import committee_pack
from app.services.v2 import evidence
from app.services.v2.analysis import _context, _require_version, kill_changes_after_model, redteam_of
from app.services.v2.deals import _deal_dict, _event, deal_or_404, version_dict, version_label
from app.services.v2.errors import InvalidInputError
from app.services.v2.serialize import row

JSON = dict[str, Any]
CARD_KEYS = {"commercial": ["irr_pct", "cap_rate_pct", "dscr", "coc_pct", "equity_multiple", "cash_to_close"],
             "residential": ["coc_pct", "cap_rate_pct", "dscr", "annual_cash_flow", "cash_to_close", "score"]}


def _roles(s: Session) -> dict[str, str]:
    return {u.username: u.role for u in s.scalars(select(User)).all()} | security.builtin_roles()


def vote(deal_id: int, choice: str, comment: str = "") -> JSON:
    if choice not in ("approve", "reject", "abstain"):
        raise InvalidInputError(T("投票只能是 approve / reject / abstain"))
    security.require("committee.vote")
    actor = current_actor()
    with session_scope() as s:
        d = deal_or_404(s, deal_id)
        if d.stage != "committee":
            raise InvalidInputError(T("只有处于“投委会”阶段的交易才能投票"))
        v = _require_version(s, d)
        existing = s.scalar(select(CommitteeVote).where(CommitteeVote.deal_id == d.id,
                                                        CommitteeVote.version_id == v.id,
                                                        CommitteeVote.voter == actor.username))
        if existing:
            before = row(existing)
            existing.vote, existing.comment = choice, comment
            audit.record(s, "committee_vote", existing.id, "update", before, row(existing))
            rec = existing
        else:
            rec = CommitteeVote(deal_id=d.id, version_id=v.id, voter=actor.username, vote=choice, comment=comment,
                                created_by=actor.username)
            s.add(rec)
            s.flush()
            audit.record(s, "committee_vote", rec.id, "create", None, row(rec))
        _event(s, d.id, "vote", {"voter": actor.username, "vote": choice, "version_id": v.id})
        return status_in(s, d.id)


def status_in(s: Session, deal_id: int) -> JSON:
    d = deal_or_404(s, deal_id)
    v = _require_version(s, d)
    votes = s.scalars(select(CommitteeVote).where(CommitteeVote.deal_id == d.id, CommitteeVote.version_id == v.id)
                      .order_by(CommitteeVote.id)).all()
    roles = _roles(s)
    vs = [{**row(x), "role": roles.get(x.voter, ""), "role_label": security.ROLE_LABEL.get(roles.get(x.voter, ""), "")}
          for x in votes]
    return {"version_id": v.id, "votes": vs, "tally": tally([{"voter": x.voter, "vote": x.vote} for x in votes], roles),
            "rules": T("董事长一票否决；董事长赞成且赞成票不少于反对票即通过。")}


def status(deal_id: int) -> JSON:
    with session_scope() as s:
        return status_in(s, deal_id)


def pack_data(s: Session, deal_id: int) -> JSON:
    d = deal_or_404(s, deal_id)
    v = _require_version(s, d)
    ctx = _context(s, d)
    prev = s.scalars(select(DealVersion).where(DealVersion.deal_id == d.id, DealVersion.version_no < v.version_no)
                     .order_by(DealVersion.version_no.desc()).limit(1)).first()
    diff = None
    if prev is not None:
        diff = {"a": {"version_no": prev.version_no, "label": version_label(prev)}, "b": {"version_no": v.version_no},
                **diffing.compare_versions(version_dict(prev, with_detail=True), version_dict(v, with_detail=True))}
    try:
        rt = redteam_of(d, v)
    except ModelInputError:
        rt = {"top": [], "all": [], "metric_label": "", "note": T("数据不足"), "shock_pct": 10, "base": None}
    try:
        sc = scenarios.run(d.track, v.inputs)
    except (ModelInputError, ValueError):
        sc = None
    try:  # 与交易页同一口径：全部淘汰条件（下限型 + 上限型）都是约束
        mb = max_bid.run(d.track, v.inputs, [], kill=d.kill_criteria) if d.kill_criteria else None
    except ValueError:
        mb = None
    risks: list[str] = []
    risks += [T("淘汰条件触发：{0}（当前 {1}）", r["text"], r["value"]) for r in ctx["kill"]["triggered"]]
    risks += [T("淘汰条件无法判定（指标未算出）：{0}", r["text"]) for r in ctx["kill"]["unknown"]]
    risks += [T(
        "关键数字未达标：{0} — {1}",
        it["field"], it["reason"]) for it in ctx["key_numbers"]["items"] if not it["ok"]]
    if ctx["open_conflicts"]:
        risks.append(T("跨来源矛盾未裁决 {0} 条", ctx["open_conflicts"]))
    if ctx["stale_evidence"]:
        risks.append(T("过期证据（>30 天）{0} 条，需重拉", ctx["stale_evidence"]))
    for r in rt.get("top", []):
        if r.get("material"):
            risks.append(T("敏感假设：{0} ±{1:g}% → {2}波动 {3:.0f} bp",
                           r["label"], rt["shock_pct"], rt["metric_label"], r["swing_bps"]))
    unknown = [k for k, val in ctx["metrics"].items() if val is None and k in CARD_KEYS[d.track]]
    if unknown:
        risks.append(T("以下结论卡指标未能计算（未知保持未知）：") + T("、").join(unknown))
    # 反方意见（不经 AI）：与交易页同一套规则；附“先核哪个”提示
    cons = [{"id": c.id, "field": c.field, "value_a": c.value_a, "source_a": c.source_a, "value_b": c.value_b,
             "source_b": c.source_b} for c in s.scalars(select(ConflictRow).where(
                 ConflictRow.deal_id == d.id, ConflictRow.status == "open").order_by(ConflictRow.id)).all()]
    queue = verification_value.rank(d.track, v.inputs, rt, provenance.key_number_status(
        rt.get("key_fields", []), evidence.latest_passports(s, d.id), four_eyes=security.auth_enabled()),
        cons) if rt.get("all") else None
    devils = devils_advocate.build(d.track, v.inputs, ctx["metrics"], {
        "kill": ctx["kill"], "redteam": rt or None, "scenarios": sc, "max_bid": mb, "key_numbers": ctx["key_numbers"],
        "queue": queue, "stale": ctx["stale_evidence"], "kill_changes": kill_changes_after_model(s, d.id)})
    st = status_in(s, d.id)
    decisions = [row(x) for x in s.scalars(select(Decision).where(Decision.deal_id == d.id)
                                           .order_by(Decision.id.desc()).limit(10)).all()]
    data: JSON = {
        "deal": _deal_dict(d), "version": version_dict(v), "run_id": v.run_id,
        "engine_version": reproducible.engine_version(), "metrics": ctx["metrics"],
        "metric_catalog": {k: {"label": label(m.label), "unit": m.unit} for k, m in METRICS.items()},
        "card_keys": CARD_KEYS[d.track], "kill": ctx["kill"], "max_bid": mb, "redteam": rt, "scenarios": sc,
        "diff": diff, "risks": risks, "devils": devils, "committee": st["tally"], "votes": st["votes"],
        "decisions": decisions,
        "verification": {"key_reviewed": ctx["key_numbers"]["done"], "key_total": ctx["key_numbers"]["total"],
                         "open_conflicts": ctx["open_conflicts"], "stale_evidence": ctx["stale_evidence"]},
        "passports": sorted(evidence.latest_passports(s, d.id).values(), key=lambda p: p["field"]),
    }
    data["data_sha256"] = reproducible.sha256_hex(reproducible.canonical_json(
        {k: data[k] for k in ("run_id", "metrics", "kill", "risks", "devils", "committee", "votes")}))
    data["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return data


def generate_pack(deal_id: int, kind: str) -> tuple[bytes, JSON]:
    if kind not in ("pdf", "xlsx"):
        raise InvalidInputError(T("格式只能是 pdf / xlsx"))
    security.require("committee.package")
    with session_scope() as s:
        data = pack_data(s, deal_id)
        blob = committee_pack.build_pdf(data) if kind == "pdf" else committee_pack.build_xlsx(data)
        sha = hashlib.sha256(blob).hexdigest()
        # 同一内容的包（双击、两人同时生成）字节相同：复用已登记的那条，不重复登记、不报“冲突”
        if s.scalar(select(CommitteePack.id).where(CommitteePack.sha256 == sha)) is None:
            rec = CommitteePack(deal_id=deal_id, version_id=data["version"]["id"], run_id=data["run_id"], kind=kind,
                                sha256=sha, size=len(blob), created_by=current_actor().username)
            s.add(rec)
            s.flush()
            _event(s, deal_id, "committee_pack", {"kind": kind, "sha256": sha, "run_id": data["run_id"]})
            audit.record(s, "committee_pack", rec.id, "create", None, {"kind": kind, "sha256": sha,
                                                                        "run_id": data["run_id"]})
        meta = {"sha256": sha, "run_id": data["run_id"], "data_sha256": data["data_sha256"], "size": len(blob),
                "deal_name": data["deal"]["name"], "version_no": data["version"]["version_no"]}
        return blob, meta


def verify(blob: bytes) -> JSON:
    sha = hashlib.sha256(blob).hexdigest()
    with session_scope() as s:
        rec = s.scalar(select(CommitteePack).where(CommitteePack.sha256 == sha))
        if rec is None:
            return {"genuine": False, "sha256": sha,
                    "message": T("未登记：这份文件不是本系统生成的原件，或生成后被改动过")}
        return {"genuine": True, "sha256": sha, "deal_id": rec.deal_id, "version_id": rec.version_id,
                "run_id": rec.run_id, "kind": rec.kind, "generated_by": rec.created_by,
                "generated_at": rec.created_at.isoformat(), "message": T("原件：与登记哈希一致")}


def packs(deal_id: int) -> list[JSON]:
    with session_scope() as s:
        deal_or_404(s, deal_id)
        return [row(p) for p in s.scalars(select(CommitteePack).where(CommitteePack.deal_id == deal_id)
                                          .order_by(CommitteePack.id.desc())).all()]
