"""敏感性分析：租金 ±10%、利率 ±2% 对关键指标的影响（what-if 表）.

思路借鉴 R1 的 4 张 what-if 表；计算全部复用 scoring 引擎，保证口径一致。
"""

from __future__ import annotations

import copy

from . import scoring_commercial as com
from . import scoring_residential as res


def _fmt_pct(x, digits=1):
    return None if x is None else round(x * 100, digits)


def residential_sensitivity(d: dict) -> dict:
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


def commercial_sensitivity(d: dict) -> dict:
    base = copy.deepcopy(d)
    # v1.1: 酒店按保守 RevPAR 口径的年总营收做租金情景
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


def run(track: str, d: dict) -> dict:
    if track == "residential":
        return residential_sensitivity(d)
    if track == "commercial":
        return commercial_sensitivity(d)
    raise ValueError(f"unknown track: {track}")
