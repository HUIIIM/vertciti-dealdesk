"""可扰动的假设清单（红队面板、情景、事后归因共用）。一条假设可对应多个输入路径（如“租金水平”）。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Assumption:
    key: str
    label: str
    paths: tuple[str, ...]
    source_hint: str = "analyst"  # 默认假设来源类型（provenance.ASSUMPTION_SOURCES）


COMMERCIAL: tuple[Assumption, ...] = (
    Assumption("rent_level", "租金水平", ("tenants.*.monthly_rent", "tenants.*.underwritten_annual"), "document"),
    Assumption("vacancy", "空置率（预测）", ("proforma.vacancy_pct",)),
    Assumption("other_income", "其他收入", ("proforma.other_income",), "document"),
    Assumption("exit_cap", "退出 Cap Rate", ("analysis.exit_cap_rate",), "benchmark"),
    Assumption("noi_growth", "NOI 年增长", ("analysis.noi_growth",)),
    Assumption("rate", "贷款利率", ("analysis.rate",), "benchmark"),
    Assumption("property_tax", "房产税", ("proforma.property_tax",), "historical"),
    Assumption("insurance", "保险", ("proforma.insurance",), "historical"),
    Assumption("repairs", "维修保养", ("proforma.repairs_maintenance",), "historical"),
    Assumption("management_fee", "管理费", ("proforma.management_fee",), "historical"),
    Assumption("building_repairs", "交割即修", ("analysis.building_repairs",)),
    Assumption("closing_costs", "交割费用", ("analysis.closing_costs",)),
)

RESIDENTIAL: tuple[Assumption, ...] = (
    Assumption("rent_level", "月租金", ("monthly_rent",), "comps"),
    Assumption("vacancy", "空置率", ("vacancy_pct",), "benchmark"),
    Assumption("rate", "贷款利率", ("rate",), "document"),
    Assumption("taxes", "房产税", ("taxes_annual",), "historical"),
    Assumption("insurance", "保险", ("insurance_annual",), "historical"),
    Assumption("maintenance", "维修比例", ("maint_pct",)),
    Assumption("capex", "资本支出比例", ("capex_pct",)),
    Assumption("management", "管理费比例", ("mgmt_pct",)),
    Assumption("other_income", "其他收入", ("other_income_monthly",)),
    Assumption("hoa", "HOA", ("hoa_monthly",), "document"),
    Assumption("closing_costs", "交割费用", ("closing_costs",)),
    Assumption("initial_repairs", "初始维修", ("initial_repairs",)),
)

INSTITUTIONAL: tuple[Assumption, ...] = (  # 按租约与多户公寓两种物业的路径并列；某笔交易没有的路径自动跳过
    Assumption("rent_level", "租金水平", ("leases.*.rent_psf_yr", "market.rent_psf_yr", "unit_mix.*.in_place_rent",
                                       "unit_mix.*.market_rent"), "document"),
    Assumption("market_rent_growth", "市场租金增长", ("market.rent_growth_pct", "multifamily.rent_growth_pct"),
               "benchmark"),
    Assumption("renewal", "续租概率", ("market.renewal_prob_pct",), "benchmark"),
    Assumption("downtime", "新租空置月数", ("market.downtime_months",), "benchmark"),
    Assumption("ti_new", "新租 TI", ("market.ti_new_psf",), "benchmark"),
    Assumption("reno_premium", "翻新溢价", ("unit_mix.*.reno_premium",), "benchmark"),
    Assumption("reno_cost", "翻新成本", ("unit_mix.*.reno_cost_per_unit",), "analyst"),
    Assumption("other_income", "其他收入", ("multifamily.other_income_per_unit",), "historical"),
    Assumption("vacancy", "一般空置率", ("general_vacancy_pct",), "benchmark"),
    Assumption("exit_cap", "退出 Cap Rate", ("exit_cap_pct",), "benchmark"),
    Assumption("opex", "运营费用", ("opex.recoverable_psf_yr", "opex.non_recoverable_psf_yr",
                                  "multifamily.opex_per_unit_yr", "multifamily.taxes_yr", "multifamily.insurance_yr"),
               "historical"),
    Assumption("opex_growth", "费用增长", ("opex.growth_pct",), "historical"),
    Assumption("rate", "贷款利率", ("debt.rate_pct", "debt.spread_bps"), "benchmark"),
    Assumption("closing_costs", "交割费用", ("closing_costs_pct",)),
)

BY_TRACK = {"commercial": COMMERCIAL, "residential": RESIDENTIAL, "institutional": INSTITUTIONAL}


def find(track: str, key: str) -> Assumption:
    for a in BY_TRACK[track]:
        if a.key == key:
            return a
    raise KeyError(key)
