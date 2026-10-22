"""示例输入：10 万 SF 郊区办公楼。

3 份租约 + 一块空置（含一份基年租约、一份即将到期的租约），浮动利率贷款带利率上限，LP / GP 两档瀑布。
用于接口示例与回归测试；数字为演示用，不是真实交易。
"""
from __future__ import annotations

from typing import Any


def suburban_office() -> dict[str, Any]:
    return {
        "analysis_start": "2026-01", "hold_years": 7, "area_sf": 100_000,
        "purchase_price": 24_000_000, "closing_costs_pct": 1.5,
        "leases": [
            {"tenant": "Northwind Legal", "suite": "100", "sf": 32_000, "start": "2021-04", "end": "2031-03",
             "rent_psf_yr": 31.5, "escalation_pct": 2.5, "recovery": "base_year", "base_year_opex_psf": 11.0},
            {"tenant": "Contoso Health", "suite": "200", "sf": 28_000, "start": "2023-01", "end": "2027-06",
             "rent_psf_yr": 33.0, "escalation_pct": 3, "recovery": "nnn"},
            {"tenant": "Fabrikam Labs", "suite": "300", "sf": 22_000, "start": "2025-07", "end": "2035-06",
             "rent_psf_yr": 34.0, "escalation_pct": 3, "free_rent_months": 2, "recovery": "nnn"},
        ],
        "market": {"rent_psf_yr": 34.0, "rent_growth_pct": 3, "renewal_prob_pct": 65, "downtime_months": 9,
                   "free_rent_new_months": 6, "free_rent_renew_months": 2, "ti_new_psf": 55, "ti_renew_psf": 20,
                   "lc_new_pct": 6, "lc_renew_pct": 3, "lease_term_years": 7, "escalation_pct": 3},
        "opex": {"recoverable_psf_yr": 12.0, "non_recoverable_psf_yr": 1.5, "growth_pct": 3,
                 "mgmt_fee_pct_egr": 3, "reserves_psf_yr": 0.3},
        "general_vacancy_pct": 5, "credit_loss_pct": 1,
        "debt": {"ltv_pct": 60, "rate_type": "floating", "sofr_curve_pct": [4.1, 3.7, 3.5, 3.5, 3.6],
                 "spread_bps": 275, "cap_strike_pct": 4.5, "io_months": 36, "amort_years": 30, "orig_fee_pct": 1},
        "exit_cap_pct": 7.75, "selling_costs_pct": 2, "discount_rate_pct": 9,
        "waterfall": {"lp_equity_pct": 90, "pref_pct": 8, "tiers": [{"irr_pct": 12, "lp_share_pct": 80},
                                                                   {"irr_pct": 16, "lp_share_pct": 70}],
                      "final_lp_share_pct": 60},
    }
