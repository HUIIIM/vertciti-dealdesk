"""承销计算：敏感性、verdict、置信度、条件调整、商业核保全链路。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app.domain import (
    commercial_plus,
    condition_adjust,
    sensitivity,
    uw_commercial,
)
from app.domain import confidence as conf_mod
from app.domain import verdict as verdict_mod

router = APIRouter(tags=["underwriting"])


class _VerdictReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    track: str = "residential"
    score: dict = {}
    confidence: float = 0
    evidence: dict = {}
    lang: str = "zh"

class _ConfidenceReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    track: str = "residential"
    comps: list = []
    evidence: dict = {}
    lang: str = "zh"

class _ConditionReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    subject_tier: str = "Average"
    comp_tier: str = "Average"
    comp_price: float = 0
    basis: str = ""
    rate: float | None = None


@router.post("/api/sensitivity")
def run_sensitivity(payload: dict):
    """档位参数化：payload 可带 tiers{rate_bps, vacancy_pp, rent_pct, combo}；
    不带 tiers 时保持 legacy 五档（旧链路零改动）。
    P0-2 (2026-10-05): tiers 非法（标量/错类型）→ 422 中文，不再 500 透出。"""
    track = payload.get("track")
    data = payload.get("input", payload)
    try:
        return sensitivity.run(track, data, payload.get("tiers"))
    except ValueError as e:
        raise HTTPException(422, f"敏感性分析参数错误：{e}")
    except KeyError as e:
        # R1 (2026-10-05)：缺必填字段（如 price）→ 422 中文，不再 500 透出
        raise HTTPException(422, f"敏感性分析缺少必填字段：{e}")


@router.post("/api/verdict")
def api_verdict(req: _VerdictReq):
    """verdict 三档引擎：住宅 值得买/再看看/别碰；商业 BUY/HOLD/PASS."""
    try:
        return verdict_mod.verdict(req.track, req.score, req.confidence, req.evidence,
                                   lang=req.lang)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/confidence")
def api_confidence(req: _ConfidenceReq):
    """Confidence Score 0-100（证据质量分，非推荐强度），公式公开."""
    try:
        return conf_mod.compute(req.track, req.comps, req.evidence, lang=req.lang)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/condition/adjust")
def api_condition_adjust(req: _ConditionReq):
    """Condition Adjustment 五档规则：无依据不做调整."""
    try:
        return condition_adjust.adjust(req.subject_tier, req.comp_tier,
                                       req.comp_price, req.basis, req.rate)
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.get("/api/uw/template")
def uw_template():
    """空白模板（与 Excel 模板同结构）＋模板自带示例。"""
    return {
        "blank": uw_commercial.default_inputs(),
        "example_39_main": uw_commercial.example_39_main(),
    }


@router.post("/api/uw/compute")
def uw_compute(payload: dict):
    """实时计算：输入 -> 全链路结果（Rent Roll -> Cash Flow -> Analysis）。"""
    data = payload.get("input", payload)
    try:
        return uw_commercial.compute_all(data)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"计算失败：{str(e)[:200]}")


@router.post("/api/com/sensitivity")
def com_sensitivity(payload: dict):
    """商业二维敏感性矩阵（P0-5，对标 ARGUS）。

    横轴=退出 cap rate（±100bps，步长 50bps），纵轴=租金增长率
    （±100bps，步长 50bps），格子=IRR / Equity Multiple。
    25 格全部复用 uw_commercial.compute_all()（与页面/Excel 同源），
    基准格（中心）= 当前输入的实际退出 cap 与增长率。
    """
    import copy

    def _f(x, default=0.0) -> float:
        try:
            v = float(x)
        except (TypeError, ValueError):
            return default
        if v != v or v in (float("inf"), float("-inf")):
            return default
        return v

    data = payload.get("input", payload)
    if not isinstance(data, dict):
        raise HTTPException(400, "input 必须是对象")
    try:
        base = uw_commercial.compute_all(data)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"计算失败：{str(e)[:200]}")
    base_exit = (base.get("analysis") or {}).get("exit") or {}
    # 标准 v1.0 §1.1：输入层 [PCT]，输出回显 [DEC] —— 扫描在百分制输入上加减，
    # 轴标签/响应回显保持小数（前端 fmtPct 按小数消费）
    exit_cap_base = _f(base_exit.get("exit_cap_rate")) or 0.05
    _g_in = (data.get("analysis") or {}).get("noi_growth")
    growth_base = _f(_g_in if _g_in not in (None, "") else 2.0)  # [PCT]
    offsets_dec = [-0.01, -0.005, 0.0, 0.005, 0.01]   # 轴步长（小数）
    offsets_pct = [-1.0, -0.5, 0.0, 0.5, 1.0]          # 输入步长（百分点）
    cells = []
    for gi, go in enumerate(offsets_pct):
        row = []
        for ci, co in enumerate(offsets_dec):
            d2 = copy.deepcopy(data)
            an = d2.get("analysis")
            if not isinstance(an, dict):
                an = d2["analysis"] = {}
            # 显式写入百分制输入：compute_exit 按"用户输入"口径采用，保证 25 格口径一致
            an["exit_cap_rate"] = max((exit_cap_base + co) * 100, 0.1)
            an["noi_growth"] = max(growth_base + go, -99.0)
            try:
                r2 = uw_commercial.compute_all(d2)
            except Exception as e:  # noqa: BLE001
                raise HTTPException(500, f"扫描计算失败：{str(e)[:200]}")
            ex2 = (r2.get("analysis") or {}).get("exit") or {}
            # LINT-04：IRR 不收敛 → None（前端渲染"—"），不许 round(0.0) 冒充
            _irr_v = ex2.get("irr")
            row.append({
                "irr": None if _irr_v is None else round(_f(_irr_v), 4),
                # R2：EM 与 IRR 同口径，None 透传不许 round(0.0) 冒充
                "equity_multiple": None if ex2.get("equity_multiple") is None
                else round(_f(ex2.get("equity_multiple")), 4),
            })
        cells.append(row)
    return {
        "exit_cap_base": round(exit_cap_base, 4),
        "growth_base": round(growth_base, 4),
        "exit_cap_source": base_exit.get("exit_cap_source"),
        "exit_cap_offsets_bps": [-100, -50, 0, 50, 100],
        "growth_offsets_bps": [-100, -50, 0, 50, 100],
        "exit_caps": [round(exit_cap_base + o, 4) for o in offsets_dec],
        "growths": [round(growth_base / 100 + o, 4) for o in offsets_dec],
        "cells": cells,
    }


# ---------------- 商业核保增补（接 compute_all，零逻辑改动） ----------------

@router.post("/api/uw/compute-plus")
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
            lang=payload.get("lang") or "zh",
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"计算失败：{str(e)[:200]}")


# ---------------- Phase 3 新引擎：verdict / confidence / condition ----------------
