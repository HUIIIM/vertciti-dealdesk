"""持有期：录入实际数（按期），实际 vs 承销偏差，事后归因复盘（对照当时的运行编号）。"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.core.context import current_actor
from app.domain.v2 import holding as hd
from app.services.persistence import audit
from app.services.persistence.engine import session_scope
from app.services.persistence.schema import DealVersion, Decision, HoldingActual
from app.services.v2.analysis import _require_version
from app.services.v2.deals import deal_or_404
from app.services.v2.errors import InvalidInputError
from app.services.v2.serialize import row

JSON = dict[str, Any]
FIELDS = ("noi", "occupancy_pct", "capex", "debt_service", "cash_flow")


def upsert_actual(deal_id: int, period: str, values: JSON) -> JSON:
    if not (len(period) in (4, 7) and period[:4].isdigit()):
        raise InvalidInputError("期间格式为 YYYY 或 YYYY-MM")
    bad = set(values) - set(FIELDS)
    if bad:
        raise InvalidInputError(f"未知字段：{', '.join(sorted(bad))}")
    occ = values.get("occupancy_pct")
    if occ is not None and not 0 <= occ <= 100:
        raise InvalidInputError("出租率用百分比数（0–100）")
    with session_scope() as s:
        deal_or_404(s, deal_id)
        rec = s.scalar(select(HoldingActual).where(HoldingActual.deal_id == deal_id, HoldingActual.period == period))
        before = row(rec) if rec else None
        if rec is None:
            rec = HoldingActual(deal_id=deal_id, period=period, created_by=current_actor().username)
            s.add(rec)
        for k, v in values.items():
            setattr(rec, k, v)
        s.flush()
        audit.record(s, "holding_actual", rec.id, "update" if before else "create", before, row(rec))
        return row(rec)


def report(deal_id: int) -> JSON:
    """偏差表 + 归因。对照基准优先用 BUY 决策时冻结的那一版（复盘看当时原样），否则用当前版。"""
    with session_scope() as s:
        d = deal_or_404(s, deal_id)
        acts = [row(a) for a in s.scalars(select(HoldingActual).where(HoldingActual.deal_id == deal_id)
                                          .order_by(HoldingActual.period)).all()]
        buy = s.scalars(select(Decision).where(Decision.deal_id == deal_id, Decision.verdict == "BUY")
                        .order_by(Decision.id.desc()).limit(1)).first()
        base_v = None
        if buy and buy.snapshot.get("version_id"):
            base_v = s.get(DealVersion, buy.snapshot["version_id"])
        base_v = base_v or _require_version(s, d)
        return {"basis": {"version_id": base_v.id, "version_no": base_v.version_no, "run_id": base_v.run_id,
                          "from_buy_decision": bool(buy)},
                "actuals": acts, "variance": hd.variance(d.track, base_v.outputs, acts),
                "attribution": hd.attribution(d.track, base_v.inputs, acts)}
