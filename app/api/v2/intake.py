"""取数与导出（老版功能搬进 v2）：导出备忘录 / Excel / 一页纸 / 核保报告、从文件提取字段、按地址搜集、导入老版项目。"""
from __future__ import annotations

from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import Response

from app.api.v2.deps import LocalizedRoute, need
from app.api.v2.schemas import ExtractOut, LegacyImportOut, LegacyProjectOut, ResearchIn, ResearchOut
from app.services.v2 import exports, intake

router = APIRouter(prefix="/api/v2", tags=["v2 · intake & exports"], route_class=LocalizedRoute)
ExportKind = Literal["memo", "model", "tearsheet", "report"]


@router.get("/deals/{deal_id}/export/{kind}", dependencies=[need("deal.read")],
            responses={200: {"content": {exports.PDF: {}, exports.XLSX: {}}}})
def export(deal_id: int, kind: ExportKind) -> Response:
    """按当前承销版本导出。

    memo 投资备忘录 PDF · model 核保明细 Excel · tearsheet 一页纸（商业）· report 经典核保报告（商业）。
    """
    fn, media, data = exports.export(deal_id, kind)
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": f"attachment; filename={fn}; filename*=UTF-8''{quote(fn)}"})


@router.post("/deals/{deal_id}/documents/{doc_id}/extract", response_model=ExtractOut,
             dependencies=[need("document.write")])
def extract(deal_id: int, doc_id: int) -> dict[str, Any]:
    """从已上传的 PDF（OM / flyer / 卖方材料）提取候选字段与租户行；不改承销，逐条采用后才写入。"""
    return intake.extract_document(deal_id, doc_id)


@router.post("/research", response_model=ResearchOut, dependencies=[need("deal.write")])
def research(body: ResearchIn) -> dict[str, Any]:
    """按地址或房源链接搜集公开信息（慢：多次公网抓取，约 30–90 秒）；每个字段带来源与可信度。"""
    return intake.research(body.track, body.mode, body.text)


@router.get("/legacy/projects", response_model=list[LegacyProjectOut], dependencies=[need("deal.read")])
def legacy_projects() -> list[dict[str, Any]]:
    """老版（v1）保存过的项目，标出已导入到哪笔交易。"""
    return intake.list_legacy()


@router.post("/legacy/projects/{kind}/{pid}/import", response_model=LegacyImportOut, status_code=201,
             dependencies=[need("deal.write")])
def legacy_import(kind: Literal["project", "uw"], pid: int) -> dict[str, Any]:
    """把一个老版项目导入为新交易，输入原样带成第一版承销；同一项目不重复导入。"""
    return intake.import_legacy(kind, pid)
