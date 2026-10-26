"""API 层共用：输入校验（中文错误）、上传大小预检、打分入口、质量门。"""

from __future__ import annotations

import re

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, ValidationError

from app.domain import (
    scoring_commercial,
    scoring_residential,
    validators,
)
from app.domain.models import CommercialInput, ResidentialInput
from app.paths import STATIC_DIR as _STATIC

STATIC_DIR = str(_STATIC)


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


def score_input(track: str, data: dict, lang: str = "zh") -> dict:
    validated = validate_input(track, data)
    if track == "residential":
        return scoring_residential.score(validated, lang=lang)
    return scoring_commercial.score(validated, lang=lang)


def _with_fresh_score(p: dict) -> dict:
    """每次读取都用最新引擎重算，保证口径一致；并挂载一级字段 cash_to_close。"""
    try:
        p["score"] = score_input(p["track"], p["input"])
    except HTTPException:
        pass  # 保留入库时的旧打分
    p["cash_to_close"] = (p.get("score") or {}).get("metrics", {}).get("cash_to_close")
    return p


# ---------------- 商业核保工作台 (UW) ----------------
class UwProjectIn(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str = ""
    input: dict = {}


def _enforce_quality_gate(data: dict, action: str):
    """fail 清零才能进 underwriting：blocked → 422 硬拦。"""
    g = validators.gate_verdict_for_state(data)
    if g["blocked"]:
        raise HTTPException(422, {
            "error": f"数据质量门拦截（{action}）：{g['fails_n']} 项自相矛盾，修正后重试",
            "quality_gate": g,
        })
    return g


# ---------------- 智能搜集 intake：地址 / 房源链接 / PDF ----------------

class _WbIntakeReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    mode: str = "address"  # address | url
    text: str = ""


def _enforce_gate_fields(gate_fields: dict | None, deal_type: str, action: str):
    """导出前过门：前端显式送来的 gate_fields 跑门，
    blocked → 422 硬拦（与商业 /api/uw/report 同口径）。
    未送 gate_fields 时不拦（向后兼容旧调用方）。"""
    if not gate_fields:
        return None
    dt = deal_type if deal_type in ("commercial", "residential") else "residential"
    g = validators.run_quality_gate(dt, gate_fields, strict_unknown=False)
    if g["blocked"]:
        raise HTTPException(422, {
            "error": f"数据质量门拦截（{action}）：{g['fails_n']} 项自相矛盾，修正后重试",
            "quality_gate": g,
        })
    return g


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


def _parse_rr_date(v) -> str:
    """rent roll 日期鲁棒解析（P0-13＋Phase 5 第二轮 item 14）：datetime/date 对象、
    YYYY-MM-DD 文本、YYYY/MM/DD、"Jan 1, 2025" / "January 1, 2025" 英文文本均接受；
    解析失败返回 ""（调用方计数，不静默吞掉整行）。"""
    if v is None or v == "":
        return ""
    try:
        from datetime import date as _date
        from datetime import datetime as _dt
        if isinstance(v, _dt):
            return v.date().isoformat()
        if isinstance(v, _date):
            return v.isoformat()
    except Exception:
        pass
    s = str(v).strip()[:10].replace("/", "-")
    try:
        from datetime import date as _date
        return _date.fromisoformat(s).isoformat()
    except Exception:
        pass
    # 英文文本日期："Jan 1, 2025" / "January 1, 2025"（模板手填常见）
    try:
        from datetime import datetime as _dt
        txt = str(v).strip()
        for _fmt in ("%b %d, %Y", "%B %d, %Y"):
            try:
                return _dt.strptime(txt, _fmt).date().isoformat()
            except ValueError:
                continue
    except Exception:
        pass
    return ""


# ---------------- 统一 dashboard 导出：备忘录 PDF / 住宅 Excel ----------------

class _MemoReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    track: str = "residential"
    name: str = ""
    address: str = ""
    input: dict = {}
    variant: str = "classic"
    # P0-8：当前 deal 真实数据（前端传入）
    verdict: dict | None = None
    score: dict | None = None
    comps: list = []
    assumptions: dict = {}
    # Phase 5 第四轮 B2：前端实际生效的假设清单（含默认值，标 is_default）
    effective_assumptions: list = []
    uw_input: dict | None = None  # 商业：compute-plus 同款富输入（含租户/假设）
    # Phase 5 第四轮 A1：verdict 显示词（否决态为独立第 4 状态：住宅"否决"/商业"VETO"，
    # 与网页 Zone 1 同源）、否决数、银行口径 trailing DSCR（与网页 KPI 卡同数）
    verdict_word: str = ""
    veto_count: int = 0
    dscr_trailing: float | None = None
    # Phase 5 第三轮 A2：有无 rent roll（前端 compute-plus has_rent_roll 门）
    has_rent_roll: bool = False
    # Phase 5 第五轮 C9：网页 Zone 1 的估值结论（前端 valuationDisplay() 同源文案），
    # 备忘录 PDF 必须带上（放贷人必看）
    valuation_display: str = ""
    # 导出前过门——前端送来的 intake 门字段
    # （住宅 asking_price/building_sf/... 或商业扁平字段）；blocked → 422
    gate_fields: dict | None = None
    gate_deal_type: str = ""


class _ResXlsxReq(BaseModel):
    model_config = ConfigDict(extra="ignore")
    score: dict = {}
    input: dict = {}
    address: str = ""
    verdict: dict | None = None
    confidence: dict | None = None
    comps: list = []
    # 导出前过门（同 _MemoReq）
    gate_fields: dict | None = None
    gate_deal_type: str = ""
