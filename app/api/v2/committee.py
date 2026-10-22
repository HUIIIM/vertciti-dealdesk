"""投委会：投票、计票状态、决策日志、投委会包（PDF / Excel）一键生成与防篡改校验；任务与审批。"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import Response

from app.api.common import _check_upload_size
from app.api.v2.deps import need
from app.api.v2.schemas import (
    ApprovalDecide,
    ApprovalIn,
    ApprovalOut,
    CommitteeStatusOut,
    DecisionIn,
    DecisionOut,
    PackOut,
    TaskIn,
    TaskOut,
    TaskPatch,
    VerifyOut,
    VoteIn,
)
from app.services.v2 import committee, workflow

router = APIRouter(prefix="/api/v2", tags=["v2 · committee"])
_MIME = {"pdf": "application/pdf", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


@router.get("/deals/{deal_id}/committee", response_model=CommitteeStatusOut, dependencies=[need("deal.read")])
def status(deal_id: int):
    return committee.status(deal_id)


@router.post("/deals/{deal_id}/committee/vote", response_model=CommitteeStatusOut, dependencies=[need("committee.vote")])
def vote(deal_id: int, body: VoteIn):
    """每人每版一票（可改票，留审计）；董事长一票否决。"""
    return committee.vote(deal_id, body.vote, body.comment)


@router.get("/deals/{deal_id}/committee/pack.{kind}", dependencies=[need("committee.package")],
            responses={200: {"content": {"application/pdf": {}, _MIME["xlsx"]: {}}}})
def pack(deal_id: int, kind: str):
    """投委会包：投资备忘录 + 关键图表 + 风险清单 + 投票记录。内容哈希登记在案，可校验原件。"""
    blob, meta = committee.generate_pack(deal_id, kind)
    fn = f"DealDesk-IC-{deal_id}-v{meta['version_no']}.{kind}"
    return Response(content=blob, media_type=_MIME.get(kind, "application/octet-stream"),
                    headers={"Content-Disposition": f"attachment; filename={fn}; filename*=UTF-8''{quote(fn)}",
                             "X-Content-SHA256": meta["sha256"], "X-Run-Id": meta["run_id"]})


@router.get("/deals/{deal_id}/committee/packs", response_model=list[PackOut], dependencies=[need("deal.read")])
def packs(deal_id: int):
    return committee.packs(deal_id)


@router.post("/committee/verify", response_model=VerifyOut, dependencies=[need("deal.read")])
async def verify(request: Request, file: UploadFile = File(...)):
    """上传一份投委会包 PDF / Excel：与登记哈希比对，判断是否原件未改动。"""
    _check_upload_size(request, 30 * 1024 * 1024, "文件")
    return committee.verify(await file.read())


@router.get("/deals/{deal_id}/decisions", response_model=list[DecisionOut], dependencies=[need("deal.read")])
def decisions(deal_id: int):
    return workflow.list_decisions(deal_id)


@router.post("/deals/{deal_id}/decisions", response_model=DecisionOut, status_code=201,
             dependencies=[need("decision.write")])
def decide(deal_id: int, body: DecisionIn):
    """记 BUY / HOLD / PASS：理由 + 当时的数字快照 + 运行编号（复盘看当时原样）。"""
    return workflow.log_decision(deal_id, body.verdict, body.rationale)


@router.get("/deals/{deal_id}/tasks", response_model=list[TaskOut], dependencies=[need("deal.read")])
def tasks(deal_id: int):
    return workflow.list_tasks(deal_id)


@router.post("/deals/{deal_id}/tasks", response_model=TaskOut, status_code=201, dependencies=[need("task.write")])
def add_task(deal_id: int, body: TaskIn):
    return workflow.add_task(deal_id, body.title, body.stage, body.assignee, body.due)


@router.patch("/deals/{deal_id}/tasks/{task_id}", response_model=TaskOut, dependencies=[need("task.write")])
def patch_task(deal_id: int, task_id: int, body: TaskPatch):
    return workflow.update_task(deal_id, task_id, body.model_dump(exclude_unset=True))


@router.get("/deals/{deal_id}/approvals", response_model=list[ApprovalOut], dependencies=[need("deal.read")])
def approvals(deal_id: int):
    return workflow.list_approvals(deal_id)


@router.post("/deals/{deal_id}/approvals", response_model=ApprovalOut, status_code=201,
             dependencies=[need("approval.request")])
def request_approval(deal_id: int, body: ApprovalIn):
    return workflow.request_approval(deal_id, body.kind, body.title, body.amount, body.note)


@router.post("/deals/{deal_id}/approvals/{approval_id}/decide", response_model=ApprovalOut,
             dependencies=[need("deal.read")])
def decide_approval(deal_id: int, approval_id: int, body: ApprovalDecide):
    """付款类只能董事长批准；不能审批自己发起的申请（权限在服务层按审批类型判定）。"""
    return workflow.decide_approval(deal_id, approval_id, body.approve, body.note)
