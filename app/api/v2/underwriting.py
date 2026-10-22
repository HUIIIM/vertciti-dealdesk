"""承销：模型试算、红队面板、概率加权情景、反推最高出价、淘汰条件、指标与假设目录。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.v2.deps import LocalizedRoute, need
from app.api.v2.schemas import (
    CatalogOut,
    DevilsMemoOut,
    MaxBidIn,
    MaxBidOut,
    ModelOut,
    PriceCheckIn,
    PriceCheckOut,
    RedTeamOut,
    RedTeamReadOut,
    ScenariosIn,
    ScenariosOut,
    Track,
    VerifyQueueOut,
)
from app.domain.v2 import kill_criteria, scenarios
from app.domain.v2.assumptions import BY_TRACK
from app.domain.v2.model import METRICS, PRIMARY_METRIC, ModelInputError, run_model
from app.services.v2 import analysis
from app.services.v2.errors import InvalidInputError

router = APIRouter(prefix="/api/v2", tags=["v2 · underwriting"], route_class=LocalizedRoute)


@router.post("/model/{track}", response_model=ModelOut, dependencies=[need("deal.read")])
def preview(track: Track, inputs: dict[str, Any]) -> dict[str, Any]:
    """不保存的试算（模型页左改假设、右侧实时更新）。"""
    try:
        r = run_model(track, inputs)
    except ModelInputError as e:
        raise InvalidInputError(str(e)) from e
    return r


@router.get("/catalog", response_model=CatalogOut, dependencies=[need("deal.read")])
def catalog() -> dict[str, Any]:
    """指标、假设、默认淘汰条件、默认情景目录（前端表单与说明文字的唯一来源）。"""
    return {
        "metrics": {k: {"label": m.label, "label_en": m.label_en, "unit": m.unit, "better": m.better}
                    for k, m in METRICS.items()},
        "primary_metric": PRIMARY_METRIC,
        "assumptions": {t: [{"key": a.key, "label": a.label, "paths": list(a.paths), "source_hint": a.source_hint}
                            for a in v] for t, v in BY_TRACK.items()},
        "kill_criteria_defaults": {"commercial": kill_criteria.DEFAULT_COMMERCIAL,
                                   "residential": kill_criteria.DEFAULT_RESIDENTIAL},
        "scenario_defaults": {t: scenarios.default_scenarios(t) for t in ("commercial", "residential")},
    }


@router.get("/deals/{deal_id}/redteam", response_model=RedTeamOut, dependencies=[need("deal.read")])
def redteam(deal_id: int) -> dict[str, Any]:
    """最可能出错的 5 个假设 + 每个 ±10% 对主回报的影响（龙卷风图）；同时给出客观定义的关键数字。"""
    return analysis.redteam_for(deal_id)


@router.post("/deals/{deal_id}/redteam/read", response_model=RedTeamReadOut, dependencies=[need("deal.write")])
def redteam_read(deal_id: int) -> dict[str, Any]:
    """标记当前版本的红队面板已读（进投委会关卡之一）。"""
    return analysis.mark_redteam_read(deal_id)


@router.post("/deals/{deal_id}/scenarios", response_model=ScenariosOut, dependencies=[need("deal.read")])
def run_scenarios(deal_id: int, body: ScenariosIn) -> dict[str, Any]:
    """基准 / 乐观 / 悲观加概率：期望回报与亏损概率。不传 scenarios 用默认三情景。"""
    custom = [s.model_dump(exclude_none=True) for s in body.scenarios] if body.scenarios else None
    return analysis.scenarios_for(deal_id, custom)


@router.get("/deals/{deal_id}/devils-memo", response_model=DevilsMemoOut, dependencies=[need("deal.read")])
def devils_memo(deal_id: int) -> dict[str, Any]:
    """反方备忘录：这笔交易最可能怎么失败（确定性规则，不经 AI）。"""
    return analysis.devils_memo(deal_id)


@router.get("/deals/{deal_id}/verify-queue", response_model=VerifyQueueOut, dependencies=[need("deal.read")])
def verify_queue(deal_id: int) -> dict[str, Any]:
    """先核哪个：每处待核（矛盾 / 未复核关键数字）按对主回报指标的摆动排序。"""
    return analysis.verification_queue(deal_id)


@router.post("/deals/{deal_id}/price-check", response_model=PriceCheckOut, dependencies=[need("deal.read")])
def price_check(deal_id: int, body: PriceCheckIn) -> dict[str, Any]:
    """试算出价：拖动“出价空间”时按该价重跑当前版本，返回指标与淘汰条件逐条结果（不保存）。"""
    return analysis.price_check_for(deal_id, body.price)


@router.post("/deals/{deal_id}/max-bid", response_model=MaxBidOut, dependencies=[need("deal.read")])
def max_bid(deal_id: int, body: MaxBidIn) -> dict[str, Any]:
    """输入目标 IRR / DSCR 等，反算最高出价；同时满足淘汰条件，写明卡住价格的约束。"""
    targets = [t.model_dump() for t in body.targets]
    return analysis.max_bid_for(deal_id, targets, include_kill=body.include_kill_criteria)
