"""DealDesk API: FastAPI 后端 + 静态前端."""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from . import db, report, scoring_commercial, scoring_residential, sensitivity
from .models import CommercialInput, ProjectCreate, ResidentialInput

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "..", "static")

# API 传输层剥离的展示字段（不进核保模型）
_STRIP_KEYS = ("name", "address")

_ZH_ERROR_TYPES = {
    "missing": "缺少必填字段",
    "extra_forbidden": "不支持的字段（请检查字段名拼写）",
    "greater_than": "必须大于 {gt}",
    "greater_than_equal": "必须 ≥ {ge}",
    "less_than": "必须小于 {lt}",
    "less_than_equal": "必须 ≤ {le}",
    "literal_error": "取值不在允许范围内",
    "int_parsing": "必须是整数",
    "float_parsing": "必须是数字",
    "bool_parsing": "必须是 true/false",
    "string_type": "必须是文本",
    "model_type": "必须是对象",
    "list_type": "必须是列表",
    "too_short": "长度不够（至少需要 {min_length} 项）",
}


def _zh_error_message(exc: ValidationError) -> str:
    parts = []
    for e in exc.errors():
        loc = ".".join(str(x) for x in e.get("loc", ())) or "input"
        template = _ZH_ERROR_TYPES.get(e.get("type", ""), e.get("msg", "输入无效"))
        ctx = e.get("ctx", {}) or {}
        try:
            template = template.format(**{k: v for k, v in ctx.items()})
        except Exception:
            pass
        parts.append(f"[{loc}] {template}")
    return "；".join(parts)


def validate_input(track: str, data: dict) -> dict:
    """Pydantic 严格校验（extra="forbid"），非法字段返回中文错误信息。"""
    if track not in ("residential", "commercial"):
        raise HTTPException(400, f"unknown track: {track}")
    clean = {k: v for k, v in (data or {}).items() if k not in _STRIP_KEYS}
    model = ResidentialInput if track == "residential" else CommercialInput
    try:
        return model.model_validate(clean).model_dump()
    except ValidationError as exc:
        raise HTTPException(422, "输入校验失败：" + _zh_error_message(exc))

app = FastAPI(title="DealDesk", description="vertciti 房地产交易核保台")


@app.on_event("startup")
def _startup():
    db.init_db()


def score_input(track: str, data: dict) -> dict:
    validated = validate_input(track, data)
    if track == "residential":
        return scoring_residential.score(validated)
    return scoring_commercial.score(validated)


def _with_fresh_score(p: dict) -> dict:
    """每次读取都用最新引擎重算，保证口径一致；并挂载一级字段 cash_to_close。"""
    try:
        p["score"] = score_input(p["track"], p["input"])
    except HTTPException:
        pass  # 保留入库时的旧打分
    p["cash_to_close"] = (p.get("score") or {}).get("metrics", {}).get("cash_to_close")
    return p


@app.get("/api/health")
def health():
    return {"ok": True, "service": "dealdesk"}


@app.get("/api/projects")
def list_projects(track: str | None = None, sort: str | None = None):
    """sort=cash_to_close 时按全口径现金需求升序（Miao 硬约束：资金有限，先看便宜的）。"""
    items = [_with_fresh_score(p) for p in db.list_projects(track)]
    if sort == "cash_to_close":
        items.sort(key=lambda p: (p["cash_to_close"] is None, p["cash_to_close"] or 0))
    return items


@app.post("/api/projects")
def create_project(payload: ProjectCreate):
    validated = validate_input(payload.track, payload.input)
    score = score_input(payload.track, validated)
    return db.create_project(payload.track, payload.name, payload.address,
                             validated, score)


@app.get("/api/projects/{pid}")
def get_project(pid: int):
    p = db.get_project(pid)
    if not p:
        raise HTTPException(404, "project not found")
    return _with_fresh_score(p)


@app.put("/api/projects/{pid}")
def update_project(pid: int, payload: ProjectCreate):
    p = db.get_project(pid)
    if not p:
        raise HTTPException(404, "project not found")
    validated = validate_input(payload.track, payload.input)
    score = score_input(payload.track, validated)
    return db.update_project(pid, payload.name, payload.address, validated, score)


@app.delete("/api/projects/{pid}")
def delete_project(pid: int):
    if not db.delete_project(pid):
        raise HTTPException(404, "project not found")
    return {"deleted": pid}


@app.post("/api/score")
def score_only(payload: ProjectCreate):
    """一键打分（不入库，用于录入时实时预览）。"""
    return score_input(payload.track, payload.input)


@app.post("/api/sensitivity")
def run_sensitivity(payload: ProjectCreate):
    return sensitivity.run(payload.track, payload.input)


@app.get("/api/compare")
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


@app.get("/api/projects/{pid}/report", response_class=HTMLResponse)
def project_report(pid: int):
    p = db.get_project(pid)
    if not p:
        raise HTTPException(404, "project not found")
    p = _with_fresh_score(p)
    return report.render(p)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
