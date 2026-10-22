"""市场与可比：税费估算、工作台估值/预测/可比、市场调查、产权穿透、卖方动机。"""

from __future__ import annotations

import math

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict

from app.api.common import _validate, score_input
from app.data import hpi
from app.services import ownership, research_pipeline, sell_readiness, workbench
from app.services.workbench import WbComp, WbProperty, WbResearch, WbScenario

router = APIRouter(tags=["market"])


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


@router.post("/api/tax/estimate")
def tax_estimate(payload: dict | None = None):
    """地址 → 州 → 州平均税率 → 年房产税估算.

    body: {"address": "...", "price": 18500000}
    返回: {"state": "NY", "rate": 0.013, "annual_tax": 240500, ...}
    查不到州或税率时返回 {"state": None, ...}，前端不填数、不报错。
    口径：州平均税率估算，待独立验证（county 实际税率可差 ±50%）。
    """
    from app.data import state_tax_rates as _tax
    from app.services import geocode as _geocode
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
    except Exception:  # noqa: BLE001
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


@router.get("/api/wb/markets")
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


@router.post("/api/wb/metrics")
def wb_metrics(payload: dict):
    prop = _validate(WbProperty, payload.get("property", payload), "房产")
    return {"property": prop.model_dump(), "metrics": workbench.property_metrics(prop)}


@router.post("/api/wb/valuate")
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


@router.post("/api/wb/forecast")
def wb_forecast(req: _WbForecastReq):
    scenarios = [_validate(WbScenario, s, "情景") for s in req.scenarios] or [
        WbScenario(name="conservative", label="保守", annual_rate_pct=1.0),
        WbScenario(name="base", label="基准", annual_rate_pct=3.0),
        WbScenario(name="optimistic", label="乐观", annual_rate_pct=5.0),
    ]
    return workbench.forecast(req.base_value, scenarios, years=max(1, min(req.years, 10)))


@router.post("/api/wb/series")
def wb_series(req: _WbSeriesReq):
    return workbench.series_stats(req.points)


@router.post("/api/wb/comps/parse")
def wb_comps_parse(req: _WbCsvReq):
    return workbench.parse_comps_csv(req.csv)


@router.post("/api/wb/comps/pull")
def wb_comps_pull(req: _WbCompsPullReq):
    """按地址从 TopHap CMA 一键拉取可比成交（recorded sales 口径）。"""
    if not (req.address or "").strip():
        raise HTTPException(422, "地址不能为空")
    r = workbench.pull_comps(req.address)
    if not r.get("ok"):
        raise HTTPException(502, f"拉取失败：{r.get('error')}")
    return r


@router.post("/api/wb/score")
def wb_score(req: _WbScoreReq):
    """工作台一键打分：字段映射到现有核保模型，走现有打分引擎（逻辑零改动）."""
    if req.track not in ("residential", "commercial"):
        raise HTTPException(400, f"unknown track: {req.track}")
    prop = _validate(WbProperty, req.property, "房产")
    mapped = workbench.to_scoring_input(prop, req.track)
    return {"score": score_input(req.track, mapped), "mapped_input": mapped,
            "note": "打分口径：住宅 buyer-box v2.3 / 商业 buyer-box-commercial v1.3（现有引擎）"}


@router.post("/api/wb/research")
def wb_research(req: _WbResearchReq):
    r = _validate(WbResearch, req.research, "研究")
    return workbench.research_payload(r, req.valuation, req.forecast)


@router.post("/api/wb/research/report", response_class=HTMLResponse)
def wb_research_report(req: _WbResearchReq):
    r = _validate(WbResearch, req.research, "研究")
    return workbench.render_research_report(workbench.research_payload(r, req.valuation, req.forecast))


@router.get("/api/wb/photos")
def wb_photos(address: str = ""):
    """轻量取图：商业页 A 栏"外观"小图用。先查 24h 地址缓存，未命中做轻量 og:image 抓取。"""
    try:
        return research_pipeline.run_photos_pipeline(address)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"取图失败：{str(e)[:200]}")


@router.post("/api/wb/ownership/tree")
def wb_ownership_tree(payload: dict):
    """产权穿透树（台账 2026-10-08 第 1 项，学自 Reonomy Top4）。

    body: {"address": "...", "owner_name": "可选/手动指定",
           "owner_source": "可选/持有人来源说明"}。
    owner_name 未给时走 TopHap 解析持有人（token 过期则降级为部分树）；
    NY 物业自动查 NY DOS 公开备案穿透到注册代理人/负责人。
    任一推断节点带[待验证]；联系方式只收 verified 公开记录地址。
    """
    try:
        return ownership.tree_for_address(
            (payload or {}).get("address", ""),
            owner_name=(payload or {}).get("owner_name") or None,
            owner_source=(payload or {}).get("owner_source") or "")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"穿透树生成失败：{str(e)[:200]}")


@router.post("/api/wb/sell-readiness/score")
def wb_sell_readiness_score(payload: dict):
    """卖方动机分（台账 2026-10-09 第 3 项，学自 Reonomy Top5）。

    body: {"address": "..."}。0-100 规则分（持有>10年+25 / 贷款到期<24mo+30 /
    再融资+15 / 留置权·违规+20 / 区域热度+10），每项附来源；
    无数据源的信号记 unavailable 不计分、不虚构。
    TopHap 不可用时对应信号 unavailable；DOB 查询仅 NYC、best-effort。
    """
    try:
        return sell_readiness.score_for_address(
            (payload or {}).get("address", ""))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"卖方动机分计算失败：{str(e)[:200]}")


# ---------------- 全面分析工作台 ----------------
# 纯分析接口：测算 / 估值(估算) / 预测(情景) / 市场调查。
# 打分仍走现有 /api/score 引擎，本工作台只做字段映射，不改核保逻辑。
