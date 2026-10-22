"""交易、承销版本、可复现运行。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.context import current_actor
from app.core.i18n import T
from app.domain.v2 import kill_criteria, reproducible
from app.domain.v2.lifecycle import ORDER, STAGE_LABEL
from app.domain.v2.model import PRICE_PATH, TRACKS, ModelInputError, run_model
from app.domain.v2.paths import get_path
from app.services.persistence import audit
from app.services.persistence.engine import session_scope
from app.services.persistence.schema import Deal, DealEvent, DealVersion, Run
from app.services.v2.errors import InvalidInputError, NotFoundError
from app.services.v2.serialize import row

JSON = dict[str, Any]
RUN_KIND = "underwrite"


def _event(s: Session, deal_id: int, kind: str, payload: JSON | None = None) -> None:
    s.add(DealEvent(deal_id=deal_id, kind=kind, payload=payload or {}, created_by=current_actor().username))


def deal_or_404(s: Session, deal_id: int) -> Deal:
    d = s.get(Deal, deal_id)
    if d is None or d.archived:
        raise NotFoundError(T("交易 {0} 不存在", deal_id))
    return d


def _deal_dict(d: Deal) -> JSON:
    out = row(d)
    out["stage_label"] = STAGE_LABEL.get(d.stage, d.stage)
    return out


def create_deal(name: str, track: str, *, address: str = "", asking_price: float | None = None,
                kill: list[JSON] | None = None, tags: list[str] | None = None) -> JSON:
    if track not in TRACKS:
        raise InvalidInputError(T("赛道只能是 residential 或 commercial"))
    if not name.strip():
        raise InvalidInputError(T("交易名称不能为空"))
    try:
        crit = kill_criteria.validate(kill or [])
    except ValueError as e:
        raise InvalidInputError(str(e)) from e
    with session_scope() as s:
        d = Deal(name=name.strip(), track=track, address=address.strip(), asking_price=asking_price,
                 kill_criteria=crit, tags=list(tags or []), created_by=current_actor().username)
        s.add(d)
        s.flush()
        _event(s, d.id, "created", {"kill_criteria": crit})
        audit.record(s, "deal", d.id, "create", None, _deal_dict(d))
        return _deal_dict(d)


def update_deal(deal_id: int, changes: JSON) -> JSON:
    allowed = {"name", "address", "asking_price", "tags", "kill_criteria"}
    bad = set(changes) - allowed
    if bad:
        raise InvalidInputError(T("不能修改的字段：{0}", ", ".join(sorted(bad))))
    with session_scope() as s:
        d = deal_or_404(s, deal_id)
        before = _deal_dict(d)
        if "kill_criteria" in changes:
            try:
                changes["kill_criteria"] = kill_criteria.validate(changes["kill_criteria"])
            except ValueError as e:
                raise InvalidInputError(str(e)) from e
        for k, v in changes.items():
            setattr(d, k, v)
        s.flush()
        after = _deal_dict(d)
        audit.record(s, "deal", d.id, "update", before, after)
        if "kill_criteria" in changes:
            _event(s, d.id, "kill_criteria_changed", {"before": before["kill_criteria"],
                                                       "after": changes["kill_criteria"]})
        return after


def archive_deal(deal_id: int) -> None:
    with session_scope() as s:
        d = deal_or_404(s, deal_id)
        d.archived = True
        audit.record(s, "deal", d.id, "delete", _deal_dict(d), None)


def _store_run(s: Session, kind: str, inputs: JSON, outputs: JSON) -> Run:
    rid = reproducible.run_id(kind, inputs)
    existing = s.get(Run, rid)
    if existing is not None:
        return existing
    r = Run(run_id=rid, engine_version=reproducible.engine_version(), kind=kind, inputs=inputs, outputs=outputs,
            output_sha256=reproducible.sha256_hex(reproducible.canonical_json(outputs)),
            created_by=current_actor().username)
    s.add(r)
    return r


def save_version(deal_id: int, inputs: JSON, label: str = "") -> JSON:
    """保存一版承销：跑模型 → 记可复现运行 → 生成版本 → 设为当前版。坏输入 → InvalidInputError。"""
    with session_scope() as s:
        d = deal_or_404(s, deal_id)
        try:
            outputs = run_model(d.track, inputs)
        except ModelInputError as e:
            raise InvalidInputError(str(e)) from e
        run = _store_run(s, RUN_KIND + ":" + d.track, inputs, outputs)
        n = (s.scalar(select(func.max(DealVersion.version_no)).where(DealVersion.deal_id == d.id)) or 0) + 1
        v = DealVersion(deal_id=d.id, version_no=n, label=label or T("第 {0} 版", n), inputs=inputs, outputs=outputs,
                        run_id=run.run_id, created_by=current_actor().username)
        s.add(v)
        s.flush()
        d.current_version_id = v.id
        price = get_path(inputs, PRICE_PATH[d.track])  # type: ignore[index]
        if isinstance(price, (int, float)) and price > 0 and d.asking_price is None:
            d.asking_price = float(price)
        _event(s, d.id, "version_saved", {"version_id": v.id, "version_no": n, "run_id": run.run_id})
        audit.record(s, "deal_version", v.id, "create", None, {"run_id": run.run_id, "version_no": n})
        return version_dict(v)


def version_dict(v: DealVersion, *, with_detail: bool = False) -> JSON:
    out = row(v)
    if not with_detail:
        out["outputs"] = {"track": v.outputs.get("track"), "metrics": v.outputs.get("metrics", {})}
    return out


def list_versions(deal_id: int) -> list[JSON]:
    with session_scope() as s:
        deal_or_404(s, deal_id)
        vs = s.scalars(select(DealVersion).where(DealVersion.deal_id == deal_id)
                       .order_by(DealVersion.version_no.desc())).all()
        return [version_dict(v) for v in vs]


def get_version(deal_id: int, version_id: int, *, with_detail: bool = True) -> JSON:
    with session_scope() as s:
        v = s.get(DealVersion, version_id)
        if v is None or v.deal_id != deal_id:
            raise NotFoundError(T("版本 {0} 不存在", version_id))
        return version_dict(v, with_detail=with_detail)


def current_version(s: Session, d: Deal) -> DealVersion | None:
    return s.get(DealVersion, d.current_version_id) if d.current_version_id else None


def get_run(rid: str) -> JSON:
    with session_scope() as s:
        r = s.get(Run, rid)
        if r is None:
            raise NotFoundError(T("运行编号 {0} 不存在", rid))
        return row(r)


def verify_run(rid: str) -> JSON:
    """用当前引擎重算该运行：结果哈希一致 = 分毫不差。引擎升级过会明确标出。"""
    stored = get_run(rid)
    track = stored["kind"].split(":", 1)[1]
    outputs = run_model(track, stored["inputs"])
    now_hash = reproducible.sha256_hex(reproducible.canonical_json(outputs))
    same_engine = stored["engine_version"] == reproducible.engine_version()
    return {"run_id": rid, "stored_engine": stored["engine_version"], "current_engine": reproducible.engine_version(),
            "same_engine": same_engine, "identical": now_hash == stored["output_sha256"],
            "stored_sha256": stored["output_sha256"], "recomputed_sha256": now_hash,
            "checked_at": datetime.now(timezone.utc).isoformat()}


def list_deals(stage: str | None = None, track: str | None = None, q: str | None = None) -> list[JSON]:
    with session_scope() as s:
        stmt = select(Deal).where(Deal.archived.is_(False))
        if stage:
            stmt = stmt.where(Deal.stage == stage)
        if track:
            stmt = stmt.where(Deal.track == track)
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where((Deal.name.ilike(like)) | (Deal.address.ilike(like)))
        deals = s.scalars(stmt.order_by(Deal.updated_at.desc())).all()
        out = []
        for d in deals:
            item = _deal_dict(d)
            v = current_version(s, d)
            metrics = v.outputs.get("metrics", {}) if v else {}
            item["metrics"] = metrics
            item["kill"] = kill_criteria.evaluate(d.kill_criteria, metrics) if v else None
            item["stage_index"] = ORDER.index(d.stage) if d.stage in ORDER else len(ORDER)
            out.append(item)
        return out


def events(deal_id: int, limit: int = 200) -> list[JSON]:
    with session_scope() as s:
        deal_or_404(s, deal_id)
        rows = s.scalars(select(DealEvent).where(DealEvent.deal_id == deal_id)
                         .order_by(DealEvent.id.desc()).limit(limit)).all()
        return [row(e) for e in rows]
