"""统一模型入口：两条赛道一个出口，输出同一套标准指标。

- residential：v1 住宅打分引擎（ResidentialInput 严格校验 → scoring_residential.score）
- commercial：v1 商业核保全链路（uw_commercial.compute_all：租金表 → 现金流 → 分析 → 退出 IRR）

单位口径（AGENTS.md）：百分比一律“百分比数”（6.5 表示 6.5%），键名以 _pct 结尾；倍数以 x 计。
未知保持未知：引擎没算出来的指标为 None，绝不填 0。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError

from app.core.i18n import T
from app.domain import scoring_residential, uw_commercial
from app.domain.models import ResidentialInput
from app.domain.v2.cre import engine as cre_engine

Track = Literal["residential", "commercial", "institutional"]
JSON = dict[str, Any]
TRACKS: tuple[Track, ...] = ("residential", "commercial", "institutional")


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    label_en: str
    unit: Literal["usd", "pct", "x", "usd_month", "pts"]
    better: Literal["higher", "lower"]


METRICS: dict[str, Metric] = {m.key: m for m in (
    Metric("price", "收购价", "Purchase price", "usd", "lower"),
    Metric("noi", "NOI（年）", "NOI (annual)", "usd", "higher"),
    Metric("cap_rate_pct", "Cap Rate", "Cap rate", "pct", "higher"),
    Metric("dscr", "DSCR", "DSCR", "x", "higher"),
    Metric("irr_pct", "IRR", "IRR", "pct", "higher"),
    Metric("coc_pct", "现金回报", "Cash-on-cash", "pct", "higher"),
    Metric("equity_multiple", "权益倍数", "Equity multiple", "x", "higher"),
    Metric("annual_cash_flow", "年净现金流", "Annual cash flow", "usd", "higher"),
    Metric("cash_to_close", "全口径现金需求", "Cash to close", "usd", "lower"),
    Metric("ltv_pct", "LTV", "LTV", "pct", "lower"),
    Metric("breakeven_occupancy_pct", "盈亏平衡出租率", "Breakeven occupancy", "pct", "lower"),
    Metric("score", "deal 评分", "Deal score", "pts", "higher"),
    Metric("unlevered_irr_pct", "无杠杆 IRR", "Unlevered IRR", "pct", "higher"),
    Metric("debt_yield_pct", "债务收益率", "Debt yield", "pct", "higher"),
    Metric("avg_occupancy_pct", "平均出租率", "Average occupancy", "pct", "higher"),
)}

# 每条赛道的“主回报指标”：红队面板、情景加权、事后归因都围绕它
PRIMARY_METRIC: dict[Track, str] = {"commercial": "irr_pct", "residential": "coc_pct", "institutional": "irr_pct"}
# 价格所在路径（反推最高出价时改这里）
PRICE_PATH: dict[Track, str] = {"commercial": "analysis.purchase_price", "residential": "price",
                                "institutional": "purchase_price"}
_STRIP = ("name", "address")


class ModelInputError(ValueError):
    """输入不合法（中文说明可直接给用户看）。"""


def _pct(v: Any) -> float | None:
    return None if v is None else float(v) * 100.0


def _num(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _residential(inputs: JSON) -> tuple[JSON, JSON]:
    clean = {k: v for k, v in (inputs or {}).items() if k not in _STRIP}
    try:
        validated = ResidentialInput.model_validate(clean).model_dump()
    except ValidationError as e:
        parts = [f"[{'.'.join(str(x) for x in err.get('loc', ()))}] {err.get('msg', '')}" for err in e.errors()]
        raise ModelInputError(T("住宅输入校验失败：") + T("；").join(parts)) from e
    s = scoring_residential.score(validated)
    m = s.get("metrics", {})
    price = _num(validated.get("price"))
    loan = _num(validated.get("loan_balance"))
    cf_m, noi_m = _num(m.get("cash_flow_monthly")), _num(m.get("noi_monthly"))
    metrics: JSON = {
        "price": price,
        "noi": None if noi_m is None else noi_m * 12,
        "cap_rate_pct": _pct(m.get("cap_rate")),
        "dscr": _num(m.get("dscr")),
        "irr_pct": None,
        "coc_pct": _pct(m.get("cash_on_cash")),
        "equity_multiple": None,
        "annual_cash_flow": None if cf_m is None else cf_m * 12,
        "cash_to_close": _num(m.get("cash_to_close")),
        "ltv_pct": (loan / price * 100.0) if (price and loan is not None) else None,
        "breakeven_occupancy_pct": None,
        "score": _num(s.get("total")),
    }
    return metrics, {"score": s, "validated_input": validated}


def _commercial(inputs: JSON) -> tuple[JSON, JSON]:
    clean = {k: v for k, v in (inputs or {}).items() if k not in _STRIP}
    try:
        r = uw_commercial.compute_all(clean)
    except Exception as e:
        raise ModelInputError(T("商业核保计算失败：{0}", str(e)[:200])) from e
    a = r.get("analysis", {}) or {}
    proj = a.get("projected", {}) or {}
    ex = a.get("exit", {}) or {}
    price = _num(a.get("purchase_price"))
    loan = _num(a.get("loan_bal"))
    metrics: JSON = {
        "price": price,
        "noi": _num(a.get("projected_noi")),
        "cap_rate_pct": _pct((r.get("proforma") or {}).get("cap_rate")),
        "dscr": _num(proj.get("dscr")),
        "irr_pct": _pct(ex.get("irr")),
        "coc_pct": _pct(proj.get("cash_on_cash")),
        "equity_multiple": _num(ex.get("equity_multiple")),
        "annual_cash_flow": _num(proj.get("net_cash_flow")),
        "cash_to_close": _num(a.get("net_liquidity")),
        "ltv_pct": (loan / price * 100.0) if (price and loan is not None) else None,
        "breakeven_occupancy_pct": _pct(a.get("breakeven_occupancy")),
        "score": None,
    }
    return metrics, {"compute": r}


def _institutional(inputs: JSON) -> tuple[JSON, JSON]:
    """机构级引擎（逐租约按月）：主指标取有杠杆 IRR；DSCR 取持有期最小值（贷款条款看最差年）。"""
    clean = {k: v for k, v in (inputs or {}).items() if k not in _STRIP}
    try:
        r = cre_engine.run(clean)
    except cre_engine.CreInputError as e:
        raise ModelInputError(T("机构级承销输入校验失败：{0}", str(e))) from e
    m, a = r["metrics"], r["annual"]
    metrics: JSON = {
        "price": float(clean["purchase_price"]), "noi": a["noi"][0], "cap_rate_pct": m["going_in_cap_pct"],
        "dscr": m["dscr_min"], "irr_pct": m["levered_irr_pct"], "coc_pct": m["cash_on_cash_year1_pct"],
        "equity_multiple": m["levered_multiple"], "annual_cash_flow": a["cf_after_debt"][0],
        "cash_to_close": m["equity"], "ltv_pct": m["ltv_pct"], "breakeven_occupancy_pct": None, "score": None,
        "unlevered_irr_pct": m["unlevered_irr_pct"], "debt_yield_pct": m["debt_yield_pct"],
        "avg_occupancy_pct": m["avg_occupancy_pct"],
    }
    return metrics, {"cre": r}


def run_model(track: str, inputs: JSON) -> JSON:
    """跑一次模型 → {"track", "metrics", "detail"}。坏输入抛 ModelInputError。"""
    if track == "residential":
        metrics, detail = _residential(inputs)
    elif track == "commercial":
        metrics, detail = _commercial(inputs)
    elif track == "institutional":
        metrics, detail = _institutional(inputs)
    else:
        raise ModelInputError(T("未知赛道：{0!r}（只支持 residential / commercial / institutional）", track))
    return {"track": track, "metrics": metrics, "detail": detail}


def primary_value(track: str, result: JSON) -> float | None:
    v = result["metrics"].get(PRIMARY_METRIC[track])  # type: ignore[index]
    return None if v is None else float(v)
