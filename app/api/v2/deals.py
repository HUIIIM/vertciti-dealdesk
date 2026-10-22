"""交易：流水线、单笔交易（概览 / 版本 / 运行 / 阶段推进 / 日志）、比较。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.api.v2.deps import need
from app.api.v2.schemas import (
    CompareOut,
    DealCreate,
    DealListItem,
    DealOut,
    DealPatch,
    DiffOut,
    EventOut,
    GateOut,
    OverviewOut,
    RunOut,
    RunVerifyOut,
    Stage,
    StageAdvance,
    StageResultOut,
    Track,
    VersionCreate,
    VersionOut,
)
from app.services.v2 import analysis, deals, workflow

router = APIRouter(prefix="/api/v2", tags=["v2 · deals"])


@router.get("/deals", response_model=list[DealListItem], dependencies=[need("deal.read")])
def list_deals(
    stage: Stage | None = None, track: Track | None = None, q: str | None = Query(None, max_length=100),
) -> list[dict[str, Any]]:
    """流水线：全部交易（含当前版本标准指标与淘汰条件状态），看板与表格两种视图共用。"""
    return deals.list_deals(stage, track, q)


@router.post("/deals", response_model=DealOut, status_code=201, dependencies=[need("deal.write")])
def create_deal(body: DealCreate) -> dict[str, Any]:
    return deals.create_deal(body.name, body.track, address=body.address, asking_price=body.asking_price,
                             kill=[c.model_dump() for c in body.kill_criteria], tags=body.tags)


@router.get("/deals/{deal_id}", response_model=OverviewOut, dependencies=[need("deal.read")])
def overview(deal_id: int) -> dict[str, Any]:
    """交易页顶部：结论卡指标、淘汰条件、核对进度、投委会状态、下一阶段关卡预检。"""
    return analysis.overview(deal_id)


@router.patch("/deals/{deal_id}", response_model=DealOut, dependencies=[need("deal.write")])
def patch_deal(deal_id: int, body: DealPatch) -> dict[str, Any]:
    ch: dict[str, Any] = body.model_dump(exclude_unset=True)
    if "kill_criteria" in ch and ch["kill_criteria"] is not None:
        ch["kill_criteria"] = [dict(c) for c in ch["kill_criteria"]]
    return deals.update_deal(deal_id, ch)


@router.delete("/deals/{deal_id}", status_code=204, dependencies=[need("deal.archive")])
def archive_deal(deal_id: int) -> None:
    deals.archive_deal(deal_id)


@router.get("/deals/{deal_id}/gate", response_model=GateOut, dependencies=[need("deal.read")])
def gate(deal_id: int, target: Stage) -> dict[str, Any]:
    return analysis.gate_check(deal_id, target)


@router.post("/deals/{deal_id}/stage", response_model=StageResultOut, dependencies=[need("deal.advance")])
def advance(deal_id: int, body: StageAdvance) -> dict[str, Any]:
    """推进 / 回退阶段。关卡未过 → 409，响应 gate 字段列出逐项检查。"""
    return workflow.advance(deal_id, body.target, body.reason)


@router.get("/deals/{deal_id}/versions", response_model=list[VersionOut], dependencies=[need("deal.read")])
def versions(deal_id: int) -> list[dict[str, Any]]:
    return deals.list_versions(deal_id)


@router.post("/deals/{deal_id}/versions", response_model=VersionOut, status_code=201,
             dependencies=[need("deal.write")])
def save_version(deal_id: int, body: VersionCreate) -> dict[str, Any]:
    """保存一版承销：跑模型、生成可复现运行编号、设为当前版。"""
    return deals.save_version(deal_id, body.inputs, body.label)


@router.get("/deals/{deal_id}/versions/{version_id}", response_model=VersionOut, dependencies=[need("deal.read")])
def get_version(deal_id: int, version_id: int) -> dict[str, Any]:
    return deals.get_version(deal_id, version_id)


@router.get("/deals/{deal_id}/diff", response_model=DiffOut, dependencies=[need("deal.read")])
def diff(deal_id: int, a: int, b: int) -> dict[str, Any]:
    """任意两版并排：假设与结果的逐项差异。"""
    return analysis.diff_versions(deal_id, a, b)


@router.get("/deals/{deal_id}/events", response_model=list[EventOut], dependencies=[need("deal.read")])
def events(deal_id: int, limit: int = Query(200, ge=1, le=1000)) -> list[dict[str, Any]]:
    """日志标签页：阶段推进、版本、证据、矛盾、投票、决策、文件……按时间倒序。"""
    return deals.events(deal_id, limit)


@router.get("/runs/{run_id}", response_model=RunOut, dependencies=[need("deal.read")])
def get_run(run_id: str) -> dict[str, Any]:
    """按运行编号取回当时的输入与输出原样（半年后也一样）。"""
    return deals.get_run(run_id)


@router.post("/runs/{run_id}/verify", response_model=RunVerifyOut, dependencies=[need("deal.read")])
def verify_run(run_id: str) -> dict[str, Any]:
    """用当前引擎重算并比对结果哈希：identical=true 即分毫不差。"""
    return deals.verify_run(run_id)


@router.get("/compare", response_model=CompareOut, dependencies=[need("deal.read")])
def compare(ids: str = Query(..., description="2–4 个交易 id，逗号分隔")) -> dict[str, Any]:
    try:
        id_list = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        id_list = []
    return analysis.compare_deals(id_list)
