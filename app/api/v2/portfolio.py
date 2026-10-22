"""持有期与组合：录入实际数、实际 vs 承销偏差、事后归因；持有中交易的组合汇总。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.v2.deps import need
from app.api.v2.schemas import ActualIn, ActualOut, HoldingOut, PortfolioOut
from app.services.v2 import deals, holding

router = APIRouter(prefix="/api/v2", tags=["v2 · portfolio"])


@router.put("/deals/{deal_id}/actuals", response_model=ActualOut, dependencies=[need("holding.write")])
def upsert_actual(deal_id: int, body: ActualIn) -> dict[str, Any]:
    b = body.model_dump(exclude_unset=True)
    return holding.upsert_actual(deal_id, b.pop("period"), b)


@router.get("/deals/{deal_id}/holding", response_model=HoldingOut, dependencies=[need("deal.read")])
def holding_report(deal_id: int) -> dict[str, Any]:
    """偏差表 + 事后归因（对照 BUY 决策时冻结的那一版：当时错在哪条假设）。"""
    return holding.report(deal_id)


@router.get("/portfolio", response_model=PortfolioOut, dependencies=[need("deal.read")])
def portfolio() -> dict[str, Any]:
    """持有中交易汇总：笔数、合计收购价、加权现金回报。"""
    held = deals.list_deals(stage="holding")
    prices = [d["metrics"].get("price") or 0 for d in held]
    total = sum(prices)
    coc = [(d["metrics"].get("coc_pct"), d["metrics"].get("price") or 0) for d in held]
    known = [(c, p) for c, p in coc if c is not None and p]
    return {"count": len(held), "total_price": total,
            "weighted_coc_pct": (sum(c * p for c, p in known) / sum(p for _, p in known)) if known else None,
            "deals": held}
