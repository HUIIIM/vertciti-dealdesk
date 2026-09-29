"""输入数据模型（Pydantic v2, frozen 风格校验）.

百分制约定：所有 `*_pct` 字段输入百分制数字（8 表示 8%），内部统一 /100。
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ResidentialInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    structure: Literal["subject_to", "seller_financing", "loan_assumption",
                       "lease_option", "novation", "wholesale"] = "subject_to"
    price: float = Field(gt=0, description="收购价/成交价")
    down_payment: float = Field(default=0, ge=0, description="首付金额 $")
    loan_balance: float = Field(default=0, ge=0, description="承接贷款余额 $")
    rate: float = Field(default=0, ge=0, description="贷款年利率（百分制）")
    rate_type: Literal["fixed", "floating"] = "fixed"
    term_years_remaining: float = Field(default=30, gt=0, description="剩余年限")
    balloon_years: Optional[float] = Field(default=None, description="balloon 年限（无则空）")
    is_assumption: bool = Field(default=False, description="是否银行正式承接")
    monthly_rent: float = Field(default=0, ge=0)
    other_income_monthly: float = Field(default=0, ge=0)
    units: int = Field(default=1, ge=1)
    rent_source: Literal["comps_verified", "estimated", "proforma"] = "estimated"
    taxes_annual: float = Field(default=0, ge=0)
    insurance_annual: float = Field(default=0, ge=0)
    hoa_monthly: float = Field(default=0, ge=0)
    utilities_owner_monthly: float = Field(default=0, ge=0)
    vacancy_pct: float = Field(default=8, ge=0, le=100)
    maint_pct: float = Field(default=8, ge=0, le=100)
    capex_pct: float = Field(default=8, ge=0, le=100)
    mgmt_pct: float = Field(default=10, ge=0, le=100)
    closing_costs: float = Field(default=0, ge=0)
    initial_repairs: float = Field(default=0, ge=0)
    other_liens: float = Field(default=0, ge=0, description="其他留置/欠费 $")
    seller_delinquent_days: int = Field(default=0, ge=0)
    has_discount_hedge: bool = False
    insurance_available: bool = True
    seller_signed_auth_release: bool = False
    hoa_arrears_severe: bool = False
    title_defect: bool = False
    fraud_flag: bool = False
    exit_primary: str = ""
    exit_backup: str = ""
    due_on_sale_plan: str = ""
    reserves_months_piti: float = Field(default=0, ge=0)
    risk_flags: list[str] = Field(default_factory=list)
    market_pop: int = Field(default=0, ge=0, le=4, description="人口流入 0-4")
    market_employment: int = Field(default=0, ge=0, le=4, description="就业增长 0-4")
    market_inventory: int = Field(default=0, ge=0, le=4, description="库存/DOM 0-4")
    market_appreciation: int = Field(default=0, ge=0, le=3, description="历史增值 0-3")


class LoanTranche(BaseModel):
    model_config = ConfigDict(extra="forbid")

    balance: float = Field(ge=0)
    rate: float = Field(ge=0, description="年利率（百分制）")
    rate_type: Literal["fixed", "floating"] = "fixed"
    term_years: float = Field(gt=0)
    balloon_years: Optional[float] = None


class CommercialInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_class: Literal["small_bay_industrial", "retail_strip", "mixed_use",
                         "small_multifamily_5plus", "office", "hotel",
                         "other"] = "retail_strip"
    structure: Literal["seller_financing", "master_lease", "subject_to",
                       "loan_assumption", "seller_carryback_2nd"] = "seller_financing"
    price: float = Field(gt=0)
    closing_costs: float = Field(default=0, ge=0)
    capex_y1: float = Field(default=0, ge=0, description="首年必须投的 capex")
    down_payment: float = Field(default=0, ge=0)
    tranches: list[LoanTranche] = Field(default_factory=list)
    annual_base_rent: float = Field(default=0, ge=0)
    other_income_annual: float = Field(default=0, ge=0)
    other_income_verified: bool = False
    vacancy_pct: float = Field(default=8, ge=0, le=100)
    tax_annual: float = Field(default=0, ge=0)
    insurance_annual: float = Field(default=0, ge=0)
    mgmt_pct: float = Field(default=8, ge=0, le=100)
    maint_pct: float = Field(default=5, ge=0, le=100)
    property_age_years: float = Field(default=0, ge=0)
    utilities_cam_gap_annual: float = Field(default=0, ge=0)
    building_sf: float = Field(default=0, ge=0)
    units: int = Field(default=0, ge=0)
    ti_lc_annual_amort: float = Field(default=0, ge=0)
    market_cap_rate_pct: float = Field(default=0, ge=0, description="市场 cap（百分制）")
    market_cap_source: str = ""
    walt_years: float = Field(default=0, ge=0)
    all_nnn: bool = False
    concentration_12mo_pct: float = Field(default=0, ge=0, le=100)
    tenant_quality_ok: bool = False
    escalations_ok: bool = False
    as_is_appraisal: float = Field(default=0, ge=0, description="交割时 as-is 评估值")
    phase1_clear: bool = True
    zoning_ok: bool = True
    ti_lc_unfunded_over_12mo: bool = False
    noi_evidence: Literal["rent_roll", "proforma"] = "rent_roll"
    seller_signed_auth_release: bool = False
    fraud_flag: bool = False
    exit_primary: str = ""
    exit_backup: str = ""
    buyer_pool_evidence: str = ""
    reserves_months_ds: float = Field(default=0, ge=0)
    is_value_add_vacant: bool = False
    # --- v1.1: office 专项（buyer-box-commercial.md v1.1 专项核保口径）---
    occupancy_pct: float = Field(default=0, ge=0, le=100, description="在租率 %（office 要求 ≥80）")
    ti_lc_itemized: bool = Field(default=False, description="office TI/LC 已逐项核算")
    # --- v1.1: hotel 专项 ---
    hotel_revenue_annual: float = Field(default=0, ge=0, description="酒店年总营收 $（按保守 RevPAR 口径）")
    hotel_opex_annual: float = Field(default=0, ge=0, description="酒店年部门/固定费用 $（按经营 P&L 填，不含管理费/FF&E）")
    revpar_source: Literal["verified_conservative", "proforma"] = "verified_conservative"
    hotel_mgmt_pct: float = Field(default=5, ge=0, le=100, description="酒店管理费 %（≥5% revenue）")
    hotel_ff_e_pct: float = Field(default=4, ge=0, le=100, description="FF&E reserve %（≥4% revenue）")
    has_operating_history: bool = Field(default=True, description="有稳定经营记录")
    pip_capex: float = Field(default=0, ge=0, description="品牌 PIP capex $（全额计入收购成本）")
    franchise_term_ok: bool = Field(default=True, description="特许经营协议 ≥10 年或有续期权")
    low_season_covers_ds: bool = Field(default=False, description="淡季月份现金流覆盖当月 debt service")
    # --- v1.1: 通用新增 ---
    pre_lease_pct: float = Field(default=0, ge=0, le=100, description="预租率 %（value-add 进 A 级要求 ≥70）")
    exit_flip_dependent_only: bool = Field(default=False, description="退出含高价抛售成分（v1.3 起不再单独否决，挂风险旗；仅当 refi/持有皆不成立时否决）")
    refi_cashout_viable: bool = Field(default=False, description="refi 路径能独立算通、refi 后能拿出钱（v1.3 高价抛售软化条件）")
    risk_flags: list[str] = Field(default_factory=list)
    market_pop_employment: int = Field(default=0, ge=0, le=3)
    market_vacancy_trend: int = Field(default=0, ge=0, le=3)
    market_rent_trend: int = Field(default=0, ge=0, le=2)
    market_landlord_friendly: int = Field(default=0, ge=0, le=2)


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    track: Literal["residential", "commercial"]
    name: str = ""
    address: str = ""
    input: dict
