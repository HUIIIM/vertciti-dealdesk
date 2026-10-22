"""文件与证据：交易文件上传下载、数字护照（来源 / 页码 / 方式 / 可信度 / 复核 / 新鲜度 / 历史）、矛盾登记。"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import Response

from app.api.common import _check_upload_size
from app.api.v2.deps import LocalizedRoute, need
from app.api.v2.schemas import (
    ConflictOut,
    ConflictResolve,
    DocOut,
    EvidenceIn,
    EvidenceOut,
    PassportDetail,
    PassportOut,
    ReviewIn,
)
from app.core.i18n import T
from app.services.v2 import evidence, workflow

router = APIRouter(prefix="/api/v2", tags=["v2 · documents"], route_class=LocalizedRoute)


@router.get("/deals/{deal_id}/documents", response_model=list[DocOut], dependencies=[need("deal.read")])
def list_documents(deal_id: int) -> list[dict[str, Any]]:
    return workflow.list_documents(deal_id)


@router.post("/deals/{deal_id}/documents", response_model=DocOut, status_code=201,
             dependencies=[need("document.write")])
async def upload_document(deal_id: int, request: Request, file: UploadFile = File(...),
                          category: str = Form("other")) -> dict[str, Any]:
    """上传 OM / 租金表 / T12 / 尽调文件（≤ 20MB，存 SHA-256 便于核对原件）。"""
    _check_upload_size(request, workflow.MAX_DOC_BYTES, T("文件"))
    data = await file.read(workflow.MAX_DOC_BYTES + 1)
    return workflow.upload_document(deal_id, file.filename or "file", file.content_type or "", data, category)


@router.get("/deals/{deal_id}/documents/{doc_id}", dependencies=[need("deal.read")],
            responses={200: {"content": {"application/octet-stream": {}}}})
def download_document(deal_id: int, doc_id: int) -> Response:
    meta, data = workflow.get_document(deal_id, doc_id)
    fn = meta["filename"]
    return Response(content=data, media_type=meta["content_type"],
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(fn)}",
                             "X-Content-SHA256": meta["sha256"]})


@router.get("/deals/{deal_id}/passports", response_model=list[PassportOut], dependencies=[need("deal.read")])
def passports(deal_id: int) -> list[dict[str, Any]]:
    """全部字段的当前数字护照（每字段最新一条）。"""
    return evidence.list_passports(deal_id)


@router.get("/deals/{deal_id}/passport", response_model=PassportDetail, dependencies=[need("deal.read")])
def passport(deal_id: int, field: str) -> dict[str, Any]:
    """点开任一数字：来源文件第几页、抽取方式、可信度、复核、新鲜度、谁在何时改过、相关矛盾。"""
    return evidence.passport(deal_id, field)


@router.post("/deals/{deal_id}/evidence", response_model=EvidenceOut, status_code=201,
             dependencies=[need("deal.write")])
def add_evidence(deal_id: int, body: EvidenceIn) -> dict[str, Any]:
    """登记一个数字的来源；与其他来源数值不一致时自动开一条矛盾。"""
    return evidence.add_evidence(deal_id, evidence.Evidence(**body.model_dump()))


@router.post("/deals/{deal_id}/review", response_model=PassportOut, dependencies=[need("deal.write")])
def review(deal_id: int, body: ReviewIn) -> dict[str, Any]:
    """把字段当前来源标为已复核（记复核人、时间）。"""
    return evidence.review(deal_id, body.field, body.note)


@router.get("/deals/{deal_id}/conflicts", response_model=list[ConflictOut], dependencies=[need("deal.read")])
def conflicts(deal_id: int, status: str | None = None) -> list[dict[str, Any]]:
    return evidence.list_conflicts(deal_id, status)


@router.post("/deals/{deal_id}/conflicts/{conflict_id}/resolve", response_model=ConflictOut,
             dependencies=[need("deal.write")])
def resolve(deal_id: int, conflict_id: int, body: ConflictResolve) -> dict[str, Any]:
    """裁决矛盾：采用哪个值、为什么（必填）。"""
    return evidence.resolve_conflict(deal_id, conflict_id, body.value, body.note)
