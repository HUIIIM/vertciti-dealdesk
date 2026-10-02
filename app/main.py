"""DealDesk API: FastAPI 后端 + 静态前端."""

from __future__ import annotations

import os

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, ValidationError

from . import db, image_intake, pdf_intake, pdf_report, report, research_pipeline, scoring_commercial, scoring_residential, sensitivity, uw_commercial, workbench
from .data import hpi
from .models import CommercialInput, ProjectCreate, ResidentialInput
from .workbench import WbComp, WbProperty, WbResearch, WbScenario

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


@app.get("/api/tophap/status")
def tophap_status():
    """TopHap 数据源状态：开关 / 授权 / 连通性 / tool 面（OAuth 授权后的校验入口）。"""
    from . import tophap  # 懒导入：未启用时不增加启动依赖
    return tophap.status()


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


# ---------------- 商业核保工作台 (UW) ----------------
class UwProjectIn(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str = ""
    input: dict = {}


@app.get("/api/uw/template")
def uw_template():
    """空白模板（与 Excel 模板同结构）＋模板自带示例。"""
    return {
        "blank": uw_commercial.default_inputs(),
        "example_39_main": uw_commercial.example_39_main(),
    }


@app.post("/api/uw/compute")
def uw_compute(payload: dict):
    """实时计算：输入 -> 全链路结果（Rent Roll -> Cash Flow -> Analysis）。"""
    data = payload.get("input", payload)
    return uw_commercial.compute_all(data)


@app.get("/api/uw/projects")
def uw_list_projects():
    return db.list_uw_projects()


@app.post("/api/uw/projects")
def uw_create_project(payload: UwProjectIn):
    return db.create_uw_project(payload.name, payload.input)


@app.get("/api/uw/projects/{pid}")
def uw_get_project(pid: int):
    p = db.get_uw_project(pid)
    if not p:
        raise HTTPException(404, "uw project not found")
    return p


@app.put("/api/uw/projects/{pid}")
def uw_update_project(pid: int, payload: UwProjectIn):
    p = db.update_uw_project(pid, payload.name, payload.input)
    if not p:
        raise HTTPException(404, "uw project not found")
    return p


@app.delete("/api/uw/projects/{pid}")
def uw_delete_project(pid: int):
    if not db.delete_uw_project(pid):
        raise HTTPException(404, "uw project not found")
    return {"deleted": pid}


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


@app.get("/api/projects/{pid}/pdf")
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


# ---------------- 全面分析工作台 ----------------
# 纯分析接口：测算 / 估值(估算) / 预测(情景) / 市场调查。
# 打分仍走现有 /api/score 引擎，本工作台只做字段映射，不改核保逻辑。

class _WbValuateReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    property: dict = {}
    comps: list = []
    income_noi_annual: float | None = None
    income_cap_rate_pct: float | None = None
    comp_weight: float = 0.5


class _WbForecastReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    base_value: float = 0
    years: int = 3
    scenarios: list = []


class _WbSeriesReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    points: list = []


class _WbCsvReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    csv: str = ""


class _WbScoreReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    track: str = "residential"
    property: dict = {}


class _WbResearchReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    research: dict = {}
    valuation: dict | None = None
    forecast: dict | None = None


@app.get("/api/wb/markets")
def wb_markets():
    """嵌入的公开房价指数数据：市场列表 + 口径说明 + 公开数据源链接."""
    return {
        "markets": hpi.market_list(),
        "series": {k: (v.get("series") or []) for k, v in hpi.MARKETS.items()},
        "methodology": hpi.METHODOLOGY,
        "public_sources": hpi.PUBLIC_SOURCES,
        "release": hpi.FHFA_RELEASE,
        "release_date": hpi.FHFA_RELEASE_DATE,
    }


@app.post("/api/wb/metrics")
def wb_metrics(payload: dict):
    prop = WbProperty.model_validate(payload.get("property", payload))
    return {"property": prop.model_dump(), "metrics": workbench.property_metrics(prop)}


@app.post("/api/wb/valuate")
def wb_valuate(req: _WbValuateReq):
    prop = WbProperty.model_validate(req.property)
    metrics = workbench.property_metrics(prop)
    comps = [WbComp.model_validate(c) for c in req.comps]
    comps_val = workbench.valuate_comps(comps)
    noi = req.income_noi_annual if req.income_noi_annual is not None else metrics["noi_annual"]
    income_val = workbench.valuate_income(noi, req.income_cap_rate_pct or 0)
    rec = workbench.reconcile(comps_val.get("estimate"), income_val.get("value"),
                              req.comp_weight)
    return {
        "metrics": metrics,
        "comps": comps_val,
        "income": income_val,
        "reconciled": rec,
        "tag": workbench.ESTIMATE_TAG,
    }


@app.post("/api/wb/forecast")
def wb_forecast(req: _WbForecastReq):
    scenarios = [WbScenario.model_validate(s) for s in req.scenarios] or [
        WbScenario(name="conservative", label="保守", annual_rate_pct=1.0),
        WbScenario(name="base", label="基准", annual_rate_pct=3.0),
        WbScenario(name="optimistic", label="乐观", annual_rate_pct=5.0),
    ]
    return workbench.forecast(req.base_value, scenarios, years=max(1, min(req.years, 10)))


@app.post("/api/wb/series")
def wb_series(req: _WbSeriesReq):
    return workbench.series_stats(req.points)


@app.post("/api/wb/comps/parse")
def wb_comps_parse(req: _WbCsvReq):
    return workbench.parse_comps_csv(req.csv)


@app.post("/api/wb/score")
def wb_score(req: _WbScoreReq):
    """工作台一键打分：字段映射到现有核保模型，走现有打分引擎（逻辑零改动）."""
    if req.track not in ("residential", "commercial"):
        raise HTTPException(400, f"unknown track: {req.track}")
    prop = WbProperty.model_validate(req.property)
    mapped = workbench.to_scoring_input(prop, req.track)
    return {"score": score_input(req.track, mapped), "mapped_input": mapped,
            "note": "打分口径：住宅 buyer-box v2.3 / 商业 buyer-box-commercial v1.3（现有引擎）"}


@app.post("/api/wb/research")
def wb_research(req: _WbResearchReq):
    r = WbResearch.model_validate(req.research)
    return workbench.research_payload(r, req.valuation, req.forecast)


@app.post("/api/wb/research/report", response_class=HTMLResponse)
def wb_research_report(req: _WbResearchReq):
    r = WbResearch.model_validate(req.research)
    return workbench.render_research_report(workbench.research_payload(r, req.valuation, req.forecast))


# ---------------- 智能搜集 intake：地址 / 房源链接 / PDF ----------------

class _WbIntakeReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    mode: str = "address"  # address | url
    text: str = ""


@app.post("/api/wb/intake/run")
def wb_intake_run(req: _WbIntakeReq):
    """智能搜集：纯地址或房源链接 → 全网公开信息自动搜集.

    慢接口（多次公网抓取，约 30-90 秒）。每个字段带来源/抓取时间/可信度；
    抓不到标"需手动补"；卖方口径标"卖方口径、待验证"。
    """
    if req.mode not in ("address", "url"):
        raise HTTPException(400, f"unknown mode: {req.mode}")
    try:
        return research_pipeline.run(req.mode, req.text)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"搜集失败：{str(e)[:200]}")


@app.post("/api/wb/intake/pdf")
async def wb_intake_pdf(file: UploadFile = File(...)):
    """PDF intake：上传房源 flyer/OM/卖方材料 → 文本提取 → 结构化字段.

    全部字段标"卖方材料口径、待独立验证"。
    """
    name = file.filename or "upload.pdf"
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "只接受 PDF 文件")
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(400, "PDF 超过 20MB 上限")
    if len(data) < 100:
        raise HTTPException(400, "文件过小或为空")
    path = pdf_intake.save_upload(data, name)
    try:
        return pdf_intake.run_pdf_upload(path, name)
    finally:
        try:
            import os
            os.remove(path)
        except Exception:
            pass


# ---------------- 商业核保 PDF intake：OM/flyer → 商业字段 → 自动填表 ----------------

@app.post("/api/uw-commercial/intake/pdf")
async def uw_commercial_intake_pdf(file: UploadFile = File(...)):
    """商业 PDF intake：上传 OM/flyer/卖方材料 → 提取商业核保字段.

    返回 fields[]（key 直接对应 uw-commercial.html 的 data-in 路径）
    与 tenants[]（租约表行），全部标"卖方材料口径、待独立验证"。
    """
    name = file.filename or "upload.pdf"
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "只接受 PDF 文件")
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(400, "PDF 超过 20MB 上限")
    if len(data) < 100:
        raise HTTPException(400, "文件过小或为空")
    path = pdf_intake.save_upload(data, name)
    try:
        return pdf_intake.run_commercial_pdf_upload(path, name)
    finally:
        try:
            import os
            os.remove(path)
        except Exception:
            pass


# ---------------- 截图 intake：房源页截图 → pending 队列 → cron 视觉提取 ----------------

@app.post("/api/wb/intake/image")
async def wb_intake_image(file: UploadFile = File(...)):
    """截图 intake：上传房源页截图（png/jpg/webp）→ 存入 pending 队列.

    视觉提取由定时 watcher 完成（约10分钟内），结果经
    GET /api/wb/intake/pending 查询、GET /api/wb/intake/extracted/{task_id} 取回。
    全部字段标"截图提取、待验证"。
    """
    name = file.filename or "screenshot.png"
    data = await file.read()
    try:
        return image_intake.save_screenshot(data, name)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/wb/intake/pending")
def wb_intake_pending():
    """列出截图提取任务（pending/done/failed）。"""
    return {"tasks": image_intake.list_tasks()}


@app.get("/api/wb/intake/extracted/{task_id}")
def wb_intake_extracted(task_id: str):
    """取回某截图任务的视觉提取结果（renderIntake 兼容格式）。"""
    try:
        return image_intake.get_extracted(task_id)
    except FileNotFoundError:
        raise HTTPException(404, "提取结果尚未生成，请稍后刷新")
    except ValueError as e:
        raise HTTPException(400, str(e))


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
