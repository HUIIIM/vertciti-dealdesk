"""DealDesk API: FastAPI 后端 + 静态前端."""

from __future__ import annotations

import math
import os
import re
from datetime import date
import io

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, ValidationError

from . import db, image_intake, pdf_intake, pdf_report, pdf_uw, report, research_pipeline, scoring_commercial, scoring_residential, sensitivity, uw_commercial, workbench
from . import commercial_plus, condition_adjust, confidence as conf_mod, excel_uw, verdict as verdict_mod
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

def _check_upload_size(request: Request, limit: int, label: str) -> None:
    """上传前 Content-Length 预检：超限直接 413，避免全量读入内存 OOM。

    Content-Length 缺失/不可信时跳过预检（后由实际读取长度兜底）。
    """
    try:
        cl = request.headers.get("content-length")
        if cl and int(cl) > limit:
            # 用 400 而非 413：与下游 save_* 的"超限"错误码保持一致，前端错误处理不用改
            raise HTTPException(400, f"{label}超过大小上限（{limit // 1024 // 1024}MB），已拒绝接收")
    except HTTPException:
        raise
    except Exception:
        pass


def _validate(model, data, label: str = "输入"):
    """手动 model_validate 的统一包装：ValidationError → 422 中文（不 500）。"""
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(422, f"{label}校验失败：" + _zh_error_message(exc))


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


@app.post("/api/tax/estimate")
def tax_estimate(payload: dict | None = None):
    """地址 → 州 → 州平均税率 → 年房产税估算.

    body: {"address": "...", "price": 18500000}
    返回: {"state": "NY", "rate": 0.013, "annual_tax": 240500, ...}
    查不到州或税率时返回 {"state": None, ...}，前端不填数、不报错。
    口径：州平均税率估算，待独立验证（county 实际税率可差 ±50%）。
    """
    from . import geocode as _geocode
    from .data import state_tax_rates as _tax
    payload = payload or {}
    raw_addr = payload.get("address") or ""
    if not isinstance(raw_addr, str):
        raise HTTPException(422, "address 必须是字符串")
    address = raw_addr.strip()
    if len(address) > 200:
        raise HTTPException(422, "地址过长（最多 200 字符）")
    try:
        price = float(payload.get("price") or 0)
    except (TypeError, ValueError):
        price = 0
    if not math.isfinite(price) or price < 0:
        raise HTTPException(422, "price 必须是非负有限数字")
    try:
        g = _geocode.geocode_state(address)
    except Exception as e:  # noqa: BLE001
        # geocode 异常不 500：按"查不到"降级
        g = {"state": None, "matched_address": None}
    rate = _tax.get_rate(g["state"]) if g.get("state") else None
    annual = round(price * rate) if (rate and price > 0) else None
    return {
        "state": g["state"],
        "rate": rate,
        "annual_tax": annual,
        "matched_address": g["matched_address"],
        "source": _tax.SOURCE,
        "source_url": _tax.SOURCE_URL,
        "confidence": _tax.CALIBRATION_NOTE,
    }


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
def run_sensitivity(payload: dict):
    """档位参数化：payload 可带 tiers{rate_bps, vacancy_pp, rent_pct, combo}；
    不带 tiers 时保持 legacy 五档（旧链路零改动）。"""
    track = payload.get("track")
    data = payload.get("input", payload)
    return sensitivity.run(track, data, payload.get("tiers"))


# ---------------- Phase 3 新引擎：verdict / confidence / condition ----------------

class _VerdictReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    track: str = "residential"
    score: dict = {}
    confidence: int = 0
    evidence: dict = {}


@app.post("/api/verdict")
def api_verdict(req: _VerdictReq):
    """verdict 三档引擎：住宅 值得买/再看看/别碰；商业 BUY/HOLD/PASS."""
    try:
        return verdict_mod.verdict(req.track, req.score, req.confidence, req.evidence)
    except ValueError as e:
        raise HTTPException(400, str(e))


class _ConfidenceReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    track: str = "residential"
    comps: list = []
    evidence: dict = {}


@app.post("/api/confidence")
def api_confidence(req: _ConfidenceReq):
    """Confidence Score 0-100（证据质量分，非推荐强度），公式公开."""
    try:
        return conf_mod.compute(req.track, req.comps, req.evidence)
    except ValueError as e:
        raise HTTPException(400, str(e))


class _ConditionReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    subject_tier: str = "Average"
    comp_tier: str = "Average"
    comp_price: float = 0
    basis: str = ""
    rate: float | None = None


@app.post("/api/condition/adjust")
def api_condition_adjust(req: _ConditionReq):
    """Condition Adjustment 五档规则：无依据不做调整."""
    try:
        return condition_adjust.adjust(req.subject_tier, req.comp_tier,
                                       req.comp_price, req.basis, req.rate)
    except ValueError as e:
        raise HTTPException(422, str(e))


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
    try:
        return uw_commercial.compute_all(data)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"计算失败：{str(e)[:200]}")


@app.post("/api/uw/report")
def uw_report(payload: dict):
    """商业核保报告导出：当前（未保存也行）输入 -> 经典版/增强版 PDF。
    variant: classic（Manny Khoshbin 模板版式）| enhanced（DealDesk 增强版：
    DSCR/IRR/盈亏平衡/持有退出）。"""
    variant = str(payload.get("variant", "classic") or "classic").lower()
    if variant not in ("classic", "enhanced"):
        raise HTTPException(400, f"unknown variant: {variant!r}")
    data = payload.get("input", payload)
    try:
        r = uw_commercial.compute_all(data)
        pdf_bytes = pdf_uw.build_uw_pdf(r, variant)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"报告生成失败：{str(e)[:200]}")
    name = (r.get("property", {}) or {}).get("name") or "deal"
    slug = "".join(c if c.isalnum() else "-" for c in name)[:30] or "deal"
    safe_ascii = f"DealDesk-uw-{variant}-{slug}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={safe_ascii}"},
    )


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


class _WbCompsPullReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    address: str = ""


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
    prop = _validate(WbProperty, payload.get("property", payload), "房产")
    return {"property": prop.model_dump(), "metrics": workbench.property_metrics(prop)}


@app.post("/api/wb/valuate")
def wb_valuate(req: _WbValuateReq):
    prop = _validate(WbProperty, req.property, "房产")
    metrics = workbench.property_metrics(prop)
    comps = [_validate(WbComp, c, "可比") for c in req.comps]
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
    scenarios = [_validate(WbScenario, s, "情景") for s in req.scenarios] or [
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


@app.post("/api/wb/comps/pull")
def wb_comps_pull(req: _WbCompsPullReq):
    """按地址从 TopHap CMA 一键拉取可比成交（recorded sales 口径）。"""
    if not (req.address or "").strip():
        raise HTTPException(422, "地址不能为空")
    r = workbench.pull_comps(req.address)
    if not r.get("ok"):
        raise HTTPException(502, f"拉取失败：{r.get('error')}")
    return r


@app.post("/api/wb/score")
def wb_score(req: _WbScoreReq):
    """工作台一键打分：字段映射到现有核保模型，走现有打分引擎（逻辑零改动）."""
    if req.track not in ("residential", "commercial"):
        raise HTTPException(400, f"unknown track: {req.track}")
    prop = _validate(WbProperty, req.property, "房产")
    mapped = workbench.to_scoring_input(prop, req.track)
    return {"score": score_input(req.track, mapped), "mapped_input": mapped,
            "note": "打分口径：住宅 buyer-box v2.3 / 商业 buyer-box-commercial v1.3（现有引擎）"}


@app.post("/api/wb/research")
def wb_research(req: _WbResearchReq):
    r = _validate(WbResearch, req.research, "研究")
    return workbench.research_payload(r, req.valuation, req.forecast)


@app.post("/api/wb/research/report", response_class=HTMLResponse)
def wb_research_report(req: _WbResearchReq):
    r = _validate(WbResearch, req.research, "研究")
    return workbench.render_research_report(workbench.research_payload(r, req.valuation, req.forecast))


# ---------------- 智能搜集 intake：地址 / 房源链接 / PDF ----------------

class _WbIntakeReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    mode: str = "address"  # address | url
    text: str = ""


@app.get("/api/wb/photos")
def wb_photos(address: str = ""):
    """轻量取图：商业页 A 栏"外观"小图用。先查 24h 地址缓存，未命中做轻量 og:image 抓取。"""
    try:
        return research_pipeline.run_photos_pipeline(address)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"取图失败：{str(e)[:200]}")


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
async def wb_intake_pdf(request: Request, file: UploadFile = File(...)):
    """PDF intake：上传房源 flyer/OM/卖方材料 → 文本提取 → 结构化字段.

    全部字段标"卖方材料口径、待独立验证"。
    """
    name = file.filename or "upload.pdf"
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "只接受 PDF 文件")
    _check_upload_size(request, 20 * 1024 * 1024, "PDF")
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(400, "PDF 超过 20MB 上限")
    if len(data) < 100:
        raise HTTPException(400, "文件过小或为空")
    if not data[:5] == b"%PDF-":
        raise HTTPException(400, "文件不是有效的 PDF（缺少 PDF 魔数），请检查文件")
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
async def uw_commercial_intake_pdf(request: Request, file: UploadFile = File(...)):
    """商业 PDF intake：上传 OM/flyer/卖方材料 → 提取商业核保字段.

    返回 fields[]（key 直接对应 uw-commercial.html 的 data-in 路径）
    与 tenants[]（租约表行），全部标"卖方材料口径、待独立验证"。
    """
    name = file.filename or "upload.pdf"
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "只接受 PDF 文件")
    _check_upload_size(request, 20 * 1024 * 1024, "PDF")
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(400, "PDF 超过 20MB 上限")
    if len(data) < 100:
        raise HTTPException(400, "文件过小或为空")
    if not data[:5] == b"%PDF-":
        raise HTTPException(400, "文件不是有效的 PDF（缺少 PDF 魔数），请检查文件")
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
async def wb_intake_image(request: Request, file: UploadFile = File(...)):
    """截图 intake：上传房源页截图（png/jpg/webp）→ 存入 pending 队列.

    视觉提取由定时 watcher 完成（约10分钟内），结果经
    GET /api/wb/intake/pending 查询、GET /api/wb/intake/extracted/{task_id} 取回。
    全部字段标"截图提取、待验证"。
    """
    name = file.filename or "screenshot.png"
    _check_upload_size(request, 15 * 1024 * 1024, "截图")
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


# ---------------- 商业核保增补（接 compute_all，零逻辑改动） ----------------

@app.post("/api/uw/compute-plus")
def uw_compute_plus(payload: dict):
    """compute_all() ＋ 增补：Debt Yield / DSCR 双轨 / NOI 银行调整桥 /
    LTV 双算 / 压力测试 / rent roll 摘要 / P0 缺口."""
    data = payload.get("input", payload)
    try:
        return commercial_plus.compute_plus(
            data,
            loan_amount=payload.get("loan_amount"),
            valuation_range=payload.get("valuation_range"),
            market_vacancy_pct=payload.get("market_vacancy_pct"),
            with_stress=bool(payload.get("with_stress", True)),
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"计算失败：{str(e)[:200]}")


def _deal_slug(text: str) -> str:
    """文件名 slug：中文地址用拼音；纯符号时回退短 hash."""
    import hashlib
    from pypinyin import lazy_pinyin
    t = (text or "").strip()
    parts = []
    for ch in t:
        if ch.isascii() and ch.isalnum():
            parts.append(ch.lower())
        elif "\u4e00" <= ch <= "\u9fff":
            parts.extend(lazy_pinyin(ch))
        elif ch in (" ", "-", "_"):
            parts.append("-")
    slug = re.sub(r"-+", "-", "".join(parts)).strip("-")[:40]
    if not slug:
        slug = hashlib.md5(t.encode()).hexdigest()[:8]
    return slug


@app.post("/api/uw/report/xlsx")
def uw_report_xlsx(payload: dict):
    """商业核保明细 Excel：总览/现金流/comps/假设；DSCR/IRR 用原生公式."""
    data = payload.get("input", payload)
    comps = payload.get("comps") or []
    try:
        r = uw_commercial.compute_all(data)
        xbytes = excel_uw.build_uw_xlsx(r, data, comps=comps)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"报告生成失败：{str(e)[:200]}")
    prop = r.get("property") or {}
    slug = _deal_slug(prop.get("address") or prop.get("name") or "deal")
    stamp = date.today().strftime("%Y%m%d")
    fname = f"dealdesk_{slug}_{stamp}.xlsx"
    from urllib.parse import quote
    return Response(
        content=xbytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f"attachment; filename={fname}; filename*=UTF-8''{quote(fname)}"},
    )


@app.get("/api/uw/rentroll/template.xlsx")
def rentroll_template():
    """rent roll 导入模板（Excel）：逐租户行，用户填完上传."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "rent_roll"
    headers = ["单元", "租户", "面积SF", "月租金$", "租约开始(YYYY-MM-DD)",
               "租约结束(YYYY-MM-DD)", "年递增%", "费用结构(NNN/Gross/ModGross)"]
    ws.append(headers)
    ws.append(["101", "示例租户", 1200, 3500, "2024-01-01", "2027-12-31", 3, "NNN"])
    for i, w in enumerate([10, 20, 12, 12, 22, 22, 10, 26], start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    import io
    buf = io.BytesIO()
    wb.save(buf)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=dealdesk_rentroll_template.xlsx"},
    )


@app.post("/api/uw/rentroll/parse")
async def rentroll_parse(request: Request, file: UploadFile | None = File(None)):
    """rent roll 导入：上传 Excel 模板 或 body 粘贴 {"rows": [...]}.

    返回 uw 租户行格式（suite/tenant/sf/monthly_rent/lease_start/lease_end/
    escalation/expense_structure），可直接塞进 compute input.tenants。
    无 rent roll 时商业 verdict 最高 HOLD（由 verdict 引擎执行）。
    """
    rows: list[dict] = []
    if file is not None:
        _check_upload_size(request, 5 * 1024 * 1024, "rent roll")
        data = await file.read()
        if len(data) > 5 * 1024 * 1024:
            raise HTTPException(400, "文件超过 5MB 上限")
        try:
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(data), data_only=True)
            ws = wb.active
            vals = list(ws.iter_rows(values_only=True))
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"Excel 解析失败：{str(e)[:120]}")
        if len(vals) < 2:
            raise HTTPException(400, "模板为空（至少需要表头＋1 行）")
        header = [str(h or "").strip() for h in vals[0]]
        def col(*names):
            for n in names:
                if n in header:
                    return header.index(n)
            return None
        c_suite = col("单元", "suite"); c_tenant = col("租户", "tenant")
        c_sf = col("面积SF", "sf"); c_rent = col("月租金$", "月租金", "monthly_rent")
        c_start = col("租约开始(YYYY-MM-DD)", "租约开始", "lease_start")
        c_end = col("租约结束(YYYY-MM-DD)", "租约结束", "lease_end")
        c_esc = col("年递增%", "escalation"); c_exp = col("费用结构(NNN/Gross/ModGross)", "费用结构")
        for line in vals[1:]:
            if not any(line):
                continue
            get = lambda c: line[c] if c is not None and c < len(line) else ""
            rows.append({
                "suite": str(get(c_suite) or ""), "tenant": str(get(c_tenant) or ""),
                "sf": get(c_sf) or 0, "monthly_rent": get(c_rent) or 0,
                "lease_start": str(get(c_start) or "")[:10],
                "lease_end": str(get(c_end) or "")[:10],
                "escalation": str(get(c_esc) or ""),
                "expense_structure": str(get(c_exp) or ""),
            })
    else:
        body = await request.json()
        for r0 in (body.get("rows") or []):
            if isinstance(r0, dict):
                rows.append(r0)
    tenants = []
    for r0 in rows:
        try:
            tenants.append({
                "suite": str(r0.get("suite", "")),
                "tenant": str(r0.get("tenant", "")),
                "sf": float(r0.get("sf") or 0),
                "monthly_rent": float(r0.get("monthly_rent") or 0),
                "lease_start": str(r0.get("lease_start", ""))[:10],
                "lease_end": str(r0.get("lease_end", ""))[:10],
                "escalation": str(r0.get("escalation", "")),
                "expense_structure": str(r0.get("expense_structure", "")),
            })
        except (TypeError, ValueError):
            continue
    return {
        "tenants": tenants,
        "count": len(tenants),
        "total_monthly": round(sum(t["monthly_rent"] for t in tenants), 2),
        "note": "租约明细待补充" if not tenants else "已导入，可进 compute_all().tenants",
    }


# ---------------- 统一 dashboard 路由 ----------------
@app.get("/d", response_class=HTMLResponse)
def dashboard_page():
    """统一 dashboard（spec §2）：/d?addr=…&type=res|com."""
    path = os.path.join(STATIC_DIR, "d.html")
    if not os.path.exists(path):
        raise HTTPException(404, "dashboard 未构建")
    return HTMLResponse(open(path, encoding="utf-8").read())


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
