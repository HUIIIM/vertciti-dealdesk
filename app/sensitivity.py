"""敏感性分析：what-if 表（档位可参数化）.

默认档位（专家规范 §2.12）：
  利率 +100/+200/+300bps（+200 必答）/ 空置 +2/+5/+10pp /
  租金 -5%/-10%/-20% / 组合压力（利率+200bps & 空置+5pp）。
计算全部复用 scoring 引擎，保证口径一致。
"""

from __future__ import annotations

import copy

from . import scoring_commercial as com
from . import scoring_residential as res


DEFAULT_TIERS = {
    "rate_bps": [100, 200, 300],      # 利率上行 bps（只做上行压力）
    "vacancy_pp": [0, 2, 5, 10],      # 空置上行百分点（含基准 0）
    "rent_pct": [-20, -10, -5, 0],    # 租金下行（只做下行压力）
    "combo": True,                    # 组合：利率+200bps & 空置+5pp
}


def _fmt_pct(x, digits=1):
    return None if x is None else round(x * 100, digits)


def residential_sensitivity(d: dict, tiers: dict | None = None) -> dict:
    # tiers=None → legacy 五档（±对称，供 charts/pdf_report 旧链路，零改动）
    if tiers is None:
        return _residential_legacy(d)
    base = copy.deepcopy(d)
    tiers = {**DEFAULT_TIERS, **tiers}
    rent_steps, rate_steps, vacancy_steps = [], [], []

    for pct in tiers["rent_pct"]:
        dd = copy.deepcopy(base)
        dd["monthly_rent"] = base.get("monthly_rent", 0) * (1 + pct / 100)
        dd["other_income_monthly"] = base.get("other_income_monthly", 0) * (1 + pct / 100)
        m = res.compute_metrics(dd)
        rent_steps.append({
            "label": f"{pct:+d}%",
            "cash_flow_monthly": m["cash_flow_monthly"],
            "cash_flow_per_door": m["cash_flow_per_door"],
            "cash_on_cash_pct": _fmt_pct(m["cash_on_cash"]),
            "dscr": m["dscr"],
        })

    for bps in tiers["rate_bps"]:
        delta = bps / 100
        dd = copy.deepcopy(base)
        dd["rate"] = max(base.get("rate", 0) + delta, 0)
        m = res.compute_metrics(dd)
        rate_steps.append({
            "label": f"+{bps}bps",
            "cash_flow_monthly": m["cash_flow_monthly"],
            "cash_on_cash_pct": _fmt_pct(m["cash_on_cash"]),
            "dscr": m["dscr"],
        })

    for pp in tiers["vacancy_pp"]:
        dd = copy.deepcopy(base)
        dd["vacancy_pct"] = base.get("vacancy_pct", 8) + pp
        m = res.compute_metrics(dd)
        vacancy_steps.append({
            "label": f"+{pp}pp",
            "cash_flow_monthly": m["cash_flow_monthly"],
            "cash_on_cash_pct": _fmt_pct(m["cash_on_cash"]),
            "dscr": m["dscr"],
        })

    combo = None
    if tiers.get("combo"):
        dd = copy.deepcopy(base)
        dd["rate"] = max(base.get("rate", 0) + 2, 0)
        dd["vacancy_pct"] = base.get("vacancy_pct", 8) + 5
        m = res.compute_metrics(dd)
        combo = {"label": "组合：利率+200bps & 空置+5pp",
                 "cash_flow_monthly": m["cash_flow_monthly"],
                 "cash_on_cash_pct": _fmt_pct(m["cash_on_cash"]),
                 "dscr": m["dscr"]}

    return {"rent_table": rent_steps, "rate_table": rate_steps,
            "vacancy_table": vacancy_steps, "combo": combo,
            "base": {"cash_flow_monthly": res.compute_metrics(base)["cash_flow_monthly"]}}


def commercial_sensitivity(d: dict, tiers: dict | None = None) -> dict:
    # tiers=None → legacy 五档（±对称，供 charts/pdf_report 旧链路，零改动）
    if tiers is None:
        return _commercial_legacy(d)
    base = copy.deepcopy(d)
    tiers = {**DEFAULT_TIERS, **tiers}
    # v1.1: 酒店按保守 RevPAR 口径的年总营收做租金情景
    is_hotel = base.get("asset_class") == "hotel"
    rent_key = "hotel_revenue_annual" if is_hotel else "annual_base_rent"
    rent_steps, rate_steps, vacancy_steps = [], [], []

    for pct in tiers["rent_pct"]:
        dd = copy.deepcopy(base)
        dd[rent_key] = base.get(rent_key, 0) * (1 + pct / 100)
        if not is_hotel:
            dd["other_income_annual"] = base.get("other_income_annual", 0) * (1 + pct / 100)
        m = com.compute_metrics(dd)
        rent_steps.append({
            "label": f"{pct:+d}%",
            "net_cf_monthly": m["net_cf_monthly"],
            "cash_on_cash_pct": _fmt_pct(m["cash_on_cash"]),
            "dscr": m["dscr"],
            "entry_cap_pct": _fmt_pct(m["entry_cap"], 2),
        })

    for bps in tiers["rate_bps"]:
        delta = bps / 100
        dd = copy.deepcopy(base)
        dd["tranches"] = [
            {**t, "rate": max(t.get("rate", 0) + delta, 0)}
            for t in base.get("tranches", [])
        ]
        m = com.compute_metrics(dd)
        rate_steps.append({
            "label": f"+{bps}bps",
            "net_cf_monthly": m["net_cf_monthly"],
            "cash_on_cash_pct": _fmt_pct(m["cash_on_cash"]),
            "dscr": m["dscr"],
        })

    for pp in tiers["vacancy_pp"]:
        dd = copy.deepcopy(base)
        dd["vacancy_pct"] = base.get("vacancy_pct", 8) + pp
        m = com.compute_metrics(dd)
        vacancy_steps.append({
            "label": f"+{pp}pp",
            "net_cf_monthly": m["net_cf_monthly"],
            "cash_on_cash_pct": _fmt_pct(m["cash_on_cash"]),
            "dscr": m["dscr"],
        })

    combo = None
    if tiers.get("combo"):
        dd = copy.deepcopy(base)
        dd["tranches"] = [
            {**t, "rate": max(t.get("rate", 0) + 2, 0)}
            for t in base.get("tranches", [])
        ]
        dd["vacancy_pct"] = base.get("vacancy_pct", 8) + 5
        m = com.compute_metrics(dd)
        combo = {"label": "组合：利率+200bps & 空置+5pp",
                 "net_cf_monthly": m["net_cf_monthly"],
                 "cash_on_cash_pct": _fmt_pct(m["cash_on_cash"]),
                 "dscr": m["dscr"]}

    return {"rent_table": rent_steps, "rate_table": rate_steps,
            "vacancy_table": vacancy_steps, "combo": combo}


def _validate_tiers(tiers: dict | None) -> dict | None:
    """P0-2 (2026-10-05): tiers 参数校验，fail-closed。

    tiers 为 None → 走 legacy 五档（合法）。
    非 None 时必须为 dict；rate_bps/vacancy_pp/rent_pct 必须为数字数组
    （标量如 200 会直接 422，不再 500 透出）；combo 必须为布尔值。
    非法时抛 ValueError（中文），由 API 层转 422。
    """
    if tiers is None:
        return None
    if not isinstance(tiers, dict):
        raise ValueError(f"tiers 应为对象，如 {{\"rate_bps\": [100,200,300]}}；收到 {type(tiers).__name__}")
    for key in ("rate_bps", "vacancy_pp", "rent_pct"):
        if key not in tiers:
            continue
        v = tiers[key]
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            raise ValueError(
                f"tiers.{key} 应为数组（如 [{int(v)}])，收到标量 {v}；"
                f"文档口径：rate_bps/vacancy_pp/rent_pct 均为数组")
        if not isinstance(v, (list, tuple)) or not all(
                isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
            raise ValueError(f"tiers.{key} 应为数字数组，收到 {v!r}")
    if "combo" in tiers and not isinstance(tiers["combo"], bool):
        raise ValueError(f"tiers.combo 应为 true/false，收到 {tiers['combo']!r}")
    return tiers


def run(track: str, d: dict, tiers: dict | None = None) -> dict:
    _validate_tiers(tiers)
    if track == "residential":
        return residential_sensitivity(d, tiers)
    if track == "commercial":
        return commercial_sensitivity(d, tiers)
    raise ValueError(f"unknown track: {track}")


# ---------------------------------------------------------------- legacy 五档
# 旧链路（charts.prep_sensitivity / pdf_report / report）逐字保留，不许改。

def _residential_legacy(d: dict) -> dict:
    base = copy.deepcopy(d)
    rent_steps, rate_steps = [], []
    for pct in (-10, -5, 0, 5, 10):
        dd = copy.deepcopy(base)
        dd["monthly_rent"] = base.get("monthly_rent", 0) * (1 + pct / 100)
        dd["other_income_monthly"] = base.get("other_income_monthly", 0) * (1 + pct / 100)
        m = res.compute_metrics(dd)
        rent_steps.append({
            "label": f"{pct:+d}%",
            "cash_flow_monthly": m["cash_flow_monthly"],
            "cash_flow_per_door": m["cash_flow_per_door"],
            "cash_on_cash_pct": _fmt_pct(m["cash_on_cash"]),
            "dscr": m["dscr"],
        })
    for delta in (-2, -1, 0, 1, 2):
        dd = copy.deepcopy(base)
        dd["rate"] = max(base.get("rate", 0) + delta, 0)
        m = res.compute_metrics(dd)
        rate_steps.append({
            "label": f"{delta:+d}%",
            "cash_flow_monthly": m["cash_flow_monthly"],
            "cash_on_cash_pct": _fmt_pct(m["cash_on_cash"]),
            "dscr": m["dscr"],
        })
    return {"rent_table": rent_steps, "rate_table": rate_steps,
            "base": {"cash_flow_monthly": res.compute_metrics(base)["cash_flow_monthly"]}}


def _commercial_legacy(d: dict) -> dict:
    base = copy.deepcopy(d)
    is_hotel = base.get("asset_class") == "hotel"
    rent_key = "hotel_revenue_annual" if is_hotel else "annual_base_rent"
    rent_steps, rate_steps = [], []
    for pct in (-10, -5, 0, 5, 10):
        dd = copy.deepcopy(base)
        dd[rent_key] = base.get(rent_key, 0) * (1 + pct / 100)
        if not is_hotel:
            dd["other_income_annual"] = base.get("other_income_annual", 0) * (1 + pct / 100)
        m = com.compute_metrics(dd)
        rent_steps.append({
            "label": f"{pct:+d}%",
            "net_cf_monthly": m["net_cf_monthly"],
            "cash_on_cash_pct": _fmt_pct(m["cash_on_cash"]),
            "dscr": m["dscr"],
            "entry_cap_pct": _fmt_pct(m["entry_cap"], 2),
        })
    for delta in (-2, -1, 0, 1, 2):
        dd = copy.deepcopy(base)
        dd["tranches"] = [
            {**t, "rate": max(t.get("rate", 0) + delta, 0)}
            for t in base.get("tranches", [])
        ]
        m = com.compute_metrics(dd)
        rate_steps.append({
            "label": f"{delta:+d}%",
            "net_cf_monthly": m["net_cf_monthly"],
            "cash_on_cash_pct": _fmt_pct(m["cash_on_cash"]),
            "dscr": m["dscr"],
        })
    return {"rent_table": rent_steps, "rate_table": rate_steps}
