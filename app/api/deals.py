"""交易（项目）：住宅/商业项目 CRUD、打分、对比、单项目报告。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response

from app.api.common import UwProjectIn, _with_fresh_score, score_input, validate_input
from app.domain.models import ProjectCreate
from app.services import db
from app.services.render import pdf_report, report

router = APIRouter(tags=["deals"])


@router.get("/api/projects")
def list_projects(track: str | None = None, sort: str | None = None):
    """sort=cash_to_close 时按全口径现金需求升序（Miao 硬约束：资金有限，先看便宜的）。"""
    items = [_with_fresh_score(p) for p in db.list_projects(track)]
    if sort == "cash_to_close":
        items.sort(key=lambda p: (p["cash_to_close"] is None, p["cash_to_close"] or 0))
    return items


@router.post("/api/projects")
def create_project(payload: ProjectCreate):
    validated = validate_input(payload.track, payload.input)
    score = score_input(payload.track, validated)
    return db.create_project(payload.track, payload.name, payload.address,
                             validated, score)


@router.get("/api/projects/{pid}")
def get_project(pid: int):
    p = db.get_project(pid)
    if not p:
        raise HTTPException(404, "project not found")
    return _with_fresh_score(p)


@router.put("/api/projects/{pid}")
def update_project(pid: int, payload: ProjectCreate):
    p = db.get_project(pid)
    if not p:
        raise HTTPException(404, "project not found")
    validated = validate_input(payload.track, payload.input)
    score = score_input(payload.track, validated)
    return db.update_project(pid, payload.name, payload.address, validated, score)


@router.delete("/api/projects/{pid}")
def delete_project(pid: int):
    if not db.delete_project(pid):
        raise HTTPException(404, "project not found")
    return {"deleted": pid}


@router.post("/api/score")
def score_only(payload: ProjectCreate):
    """一键打分（不入库，用于录入时实时预览）。"""
    return score_input(payload.track, payload.input, payload.lang)


@router.get("/api/uw/projects")
def uw_list_projects():
    return db.list_uw_projects()


@router.post("/api/uw/projects")
def uw_create_project(payload: UwProjectIn):
    return db.create_uw_project(payload.name, payload.input)


@router.get("/api/uw/projects/{pid}")
def uw_get_project(pid: int):
    p = db.get_uw_project(pid)
    if not p:
        raise HTTPException(404, "uw project not found")
    return p


@router.put("/api/uw/projects/{pid}")
def uw_update_project(pid: int, payload: UwProjectIn):
    p = db.update_uw_project(pid, payload.name, payload.input)
    if not p:
        raise HTTPException(404, "uw project not found")
    return p


@router.delete("/api/uw/projects/{pid}")
def uw_delete_project(pid: int):
    if not db.delete_uw_project(pid):
        raise HTTPException(404, "uw project not found")
    return {"deleted": pid}


@router.get("/api/compare")
def compare(ids: str):
    """项目对比：ids=1,2,3（最多 3 个）。"""
    out = []
    for raw in ids.split(",")[:3]:
        raw = raw.strip()
        if not raw.isdigit():
            continue
        p = db.get_project(int(raw))
        if p:
            out.append(_with_fresh_score(p))
    if not out:
        raise HTTPException(404, "no projects found")
    return out


@router.get("/api/projects/{pid}/report", response_class=HTMLResponse)
def project_report(pid: int):
    p = db.get_project(pid)
    if not p:
        raise HTTPException(404, "project not found")
    p = _with_fresh_score(p)
    return report.render(p)


@router.get("/api/projects/{pid}/pdf")
def project_pdf(pid: int):
    """一键生成投资筛选备忘录 PDF（服务端直出，无需浏览器打印）。"""
    p = db.get_project(pid)
    if not p:
        raise HTTPException(404, "project not found")
    p = _with_fresh_score(p)
    pdf_bytes = pdf_report.build_pdf(p)
    # Content-Disposition 文件名用 ASCII 安全（中文名放 filename* UTF-8）
    safe_ascii = f"DealDesk-memo-{pid}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={safe_ascii}"},
    )
