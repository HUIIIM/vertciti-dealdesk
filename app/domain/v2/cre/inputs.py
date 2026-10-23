"""引擎输入契约：严格校验（多余字段、负面积、错日期、百分比越界都直接拒绝），百分比一律按百分比数（6.5 = 6.5%）。"""
from __future__ import annotations

import itertools
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
Recovery = Literal["nnn", "gross", "base_year"]
Pct = float  # 百分比数：6.5 表示 6.5%


def month_offset(ym: str, origin: str) -> int:
    y, m = (int(x) for x in ym.split("-"))
    y0, m0 = (int(x) for x in origin.split("-"))
    return (y - y0) * 12 + (m - m0)


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _month(v: str) -> str:
    if not _MONTH.match(v):
        raise ValueError("日期格式应为 YYYY-MM")
    return v


class Lease(_In):
    tenant: str = Field(min_length=1, max_length=120)
    suite: str = Field(default="", max_length=40)
    sf: float = Field(gt=0)
    start: str = Field(description="租约起始月 YYYY-MM（可早于分析起点）")
    end: str = Field(description="租约到期月 YYYY-MM（含当月）；早于分析起点 = 分析开始即空置待租")
    rent_psf_yr: float = Field(ge=0, description="分析起点时的合同年租金 $/SF")
    escalation_pct: Pct = Field(default=0, ge=0, le=25, description="每个租约周年日的租金递增")
    free_rent_months: int = Field(default=0, ge=0, le=36, description="分析起点后仍剩余的免租月数")
    recovery: Recovery = "nnn"
    base_year_opex_psf: float | None = Field(default=None, ge=0,
                                             description="基年租约的基年可回收费用 $/SF；空 = 取分析首年")

    _v_start = field_validator("start")(classmethod(lambda _c, v: _month(v)))
    _v_end = field_validator("end")(classmethod(lambda _c, v: _month(v)))

    @model_validator(mode="after")
    def _order(self) -> Lease:
        if self.end < self.start:
            raise ValueError(f"{self.tenant}：到期月早于起始月")
        return self


class Market(_In):
    """市场租赁假设（MLA）：到期后续租与新租按续租概率加权成一条路径（Argus 默认口径）。"""

    rent_psf_yr: float = Field(gt=0, description="分析起点时的市场年租金 $/SF")
    rent_growth_pct: Pct = Field(default=3, ge=-20, le=20)
    renewal_prob_pct: Pct = Field(default=70, ge=0, le=100)
    downtime_months: float = Field(default=6, ge=0, le=36, description="新租（非续租）情形的空置月数（加权后四舍五入）")
    free_rent_new_months: float = Field(default=3, ge=0, le=36)
    free_rent_renew_months: float = Field(default=1, ge=0, le=36)
    ti_new_psf: float = Field(default=30, ge=0)
    ti_renew_psf: float = Field(default=10, ge=0)
    lc_new_pct: Pct = Field(default=6, ge=0, le=20, description="新租佣金：占新租期合同租金总额")
    lc_renew_pct: Pct = Field(default=3, ge=0, le=20)
    lease_term_years: int = Field(default=5, ge=1, le=30)
    escalation_pct: Pct = Field(default=3, ge=0, le=25)


class Opex(_In):
    recoverable_psf_yr: float = Field(default=0, ge=0, description="可回收费用（税、保险、CAM）$/SF/年")
    non_recoverable_psf_yr: float = Field(default=0, ge=0)
    growth_pct: Pct = Field(default=3, ge=-20, le=20)
    mgmt_fee_pct_egr: Pct = Field(default=3, ge=0, le=20, description="管理费占有效总收入（不回收）")
    reserves_psf_yr: float = Field(default=0.25, ge=0, description="资本储备 $/SF/年（NOI 之下）")


class Debt(_In):
    ltv_pct: Pct | None = Field(default=None, ge=0, le=95)
    amount: float | None = Field(default=None, ge=0, description="贷款额；与 ltv_pct 二选一")
    rate_type: Literal["fixed", "floating"] = "fixed"
    rate_pct: Pct = Field(default=6.5, ge=0, le=30, description="固定利率；浮动时忽略")
    sofr_curve_pct: list[Pct] = Field(default_factory=list, max_length=40,
                                      description="浮动：逐年 SOFR，最后一年向后沿用")
    spread_bps: float = Field(default=250, ge=0, le=2000)
    cap_strike_pct: Pct | None = Field(default=None, ge=0, le=30,
                                       description="利率上限：SOFR 超过即按上限计")
    io_months: int = Field(default=0, ge=0, le=360)
    amort_years: int = Field(default=30, ge=1, le=40)
    orig_fee_pct: Pct = Field(default=1, ge=0, le=10)

    @model_validator(mode="after")
    def _one_size(self) -> Debt:
        if self.ltv_pct is not None and self.amount is not None:
            raise ValueError("贷款额与 LTV 只能填一个")
        if self.rate_type == "floating" and not self.sofr_curve_pct:
            raise ValueError("浮动利率需要 SOFR 曲线（逐年）")
        return self


class Mezz(_In):
    """夹层贷款：交割时与优先贷款一起放款，只付息，退出（或再融资）时偿清。"""

    ltv_pct: Pct | None = Field(default=None, gt=0, le=40, description="夹层占收购价的比例（在优先贷款之上）")
    amount: float | None = Field(default=None, gt=0, description="夹层金额；与 ltv_pct 二选一")
    rate_pct: Pct = Field(default=11, ge=0, le=30)
    orig_fee_pct: Pct = Field(default=1, ge=0, le=10)

    @model_validator(mode="after")
    def _one_size(self) -> Mezz:
        if (self.ltv_pct is None) == (self.amount is None):
            raise ValueError("夹层：金额与 LTV 填且只填一个")
        return self


class Refinance(_In):
    """再融资：在第 month 月按届时的物业价值重新贷款，偿清原优先贷款（与夹层），净额分给股权（负数 = 需补钱）。

    新贷款额 = min(LTV × 价值, 按最低 DSCR 反推, 按最低债务收益率反推)；价值 = 再融资月起 12 个月 NOI ÷ 估值资本化率。
    """

    month: int = Field(ge=1, le=359, description="交割后第几个月再融资")
    value_cap_pct: Pct = Field(gt=0, le=25, description="估值资本化率")
    ltv_pct: Pct = Field(default=65, gt=0, le=90)
    min_dscr: float | None = Field(default=1.25, gt=0, le=5, description="按最低 DSCR 限额；空 = 不限")
    min_debt_yield_pct: Pct | None = Field(default=None, gt=0, le=30, description="按最低债务收益率限额；空 = 不限")
    rate_pct: Pct = Field(default=6.0, ge=0, le=30)
    io_months: int = Field(default=0, ge=0, le=360)
    amort_years: int = Field(default=30, ge=1, le=40)
    costs_pct: Pct = Field(default=1, ge=0, le=10, description="再融资费用：占新贷款")
    repay_mezz: bool = Field(default=True, description="再融资时一并偿清夹层")


class Development(_In):
    """开发 / 重度改造：交割后先施工（不出租、不计运营），竣工后起租。收购价 = 土地或旧楼价款，交割当月支付。

    硬成本（含不可预见费）与软成本按施工期逐月支出：straight = 平均；s_curve = 两头少中间多（正弦权重）。
    """

    construction_months: int = Field(ge=1, le=60)
    hard_costs: float = Field(ge=0, description="硬成本合计")
    soft_costs: float = Field(default=0, ge=0, description="软成本合计（设计、许可、开发商费等）")
    soft_upfront_pct: Pct = Field(default=20, ge=0, le=100, description="软成本在交割当月先付的比例")
    contingency_pct: Pct = Field(default=5, ge=0, le=30, description="不可预见费：占硬成本")
    draw_curve: Literal["straight", "s_curve"] = "s_curve"
    absorption_units_per_month: float | None = Field(default=None, gt=0,
                                                     description="多户公寓竣工后每月租出的户数；空 = 竣工即稳定")
    stabilization_month: int | None = Field(default=None, ge=1,
                                            description="稳定月（算开发收益率）；空 = 竣工后 12 个月")


class ConstructionLoan(_In):
    """施工贷：按总成本（土地 + 交割 + 硬 + 软 + 不可预见）的 LTC 承诺。

    股权先投，投满后贷款按月提款；施工期利息资本化（滚入本金），竣工后按月付息；再融资或出售时偿清。
    """

    ltc_pct: Pct = Field(default=60, gt=0, le=90, description="贷款占总成本比例")
    rate_pct: Pct = Field(default=8, ge=0, le=30)
    orig_fee_pct: Pct = Field(default=1, ge=0, le=10, description="开办费：占承诺额，交割时付")


class Tier(_In):
    irr_pct: Pct = Field(gt=0, le=100, description="LP 达到此 IRR 后进入下一档分配")
    lp_share_pct: Pct = Field(gt=0, le=100, description="本档（上一门槛到本门槛之间）LP 拿的现金比例")


class Waterfall(_In):
    """按 LP IRR 门槛的分配瀑布：门槛之下按出资比例；每过一档 LP 份额下降、GP 拿 promote。"""

    lp_equity_pct: Pct = Field(default=90, gt=0, lt=100)
    pref_pct: Pct = Field(default=8, gt=0, le=50, description="优先回报（复利、按 LP IRR 计）")
    tiers: list[Tier] = Field(default_factory=list, max_length=5, description="优先回报之上的各档，IRR 递增")
    final_lp_share_pct: Pct = Field(default=70, gt=0, le=100, description="最后一档之上 LP 的份额")
    frequency: Literal["annual", "monthly"] = Field(default="annual",
                                                    description="分配频率：按年或按月（门槛按年化 IRR）")
    catch_up_target_pct: Pct | None = Field(default=None, gt=0, lt=100,
                                            description="GP catch-up：LP 达到优先回报后 GP 补到累计利润的比例；空 = 无")
    catch_up_rate_pct: Pct = Field(default=100, gt=0, le=100, description="catch-up 期间 GP 拿的现金比例")
    clawback: bool = Field(default=False, description="期末 LP 未达优先回报时，GP 退回已拿的 promote")

    @model_validator(mode="after")
    def _ascending(self) -> Waterfall:
        hs = [self.pref_pct, *(t.irr_pct for t in self.tiers)]
        if any(b <= a for a, b in itertools.pairwise(hs)):
            raise ValueError("瀑布门槛必须逐档递增（优先回报 < 第一档 < 第二档 …）")
        if self.catch_up_target_pct is not None and self.catch_up_rate_pct <= self.catch_up_target_pct:
            raise ValueError("catch-up 期间 GP 的现金比例必须高于目标利润比例，否则永远补不到")
        return self


class UnitType(_In):
    """多户公寓的一个户型（如 1B1B）。租金一律按“每户每月”计。"""

    name: str = Field(min_length=1, max_length=60)
    units: int = Field(gt=0, le=10_000)
    avg_sf: float = Field(default=0, ge=0, description="户均面积 SF（只用于展示 $/SF）")
    in_place_rent: float = Field(ge=0, description="在租租约的平均月租（交割时）")
    market_rent: float = Field(gt=0, description="分析起点的市场月租")
    renovate_units: int = Field(default=0, ge=0, description="计划翻新的户数")
    reno_cost_per_unit: float = Field(default=0, ge=0, description="每户翻新成本")
    reno_premium: float = Field(default=0, ge=0, description="翻新后相对市场月租的溢价（分析起点口径，随市场租金增长）")

    @model_validator(mode="after")
    def _reno(self) -> UnitType:
        if self.renovate_units > self.units:
            raise ValueError(f"{self.name}：翻新户数 {self.renovate_units} 超过户数 {self.units}")
        return self


class Multifamily(_In):
    """多户公寓假设：在租租约按租期均匀到期、逐批调到市场租金（loss-to-lease 逐步消化）。

    空置率与坏账沿用 general_vacancy_pct / credit_loss_pct；费用增长与管理费沿用 opex.growth_pct / mgmt_fee_pct_egr。
    """

    rent_growth_pct: Pct = Field(default=3, ge=-20, le=20, description="市场租金年增长（按分析年阶梯）")
    lease_term_months: int = Field(default=12, ge=1, le=24, description="租期：在租租约在这么多个月里均匀到期")
    concessions_pct: Pct = Field(default=1, ge=0, le=20, description="租金优惠，占在租租金")
    non_revenue_units: int = Field(default=0, ge=0, description="不产生租金的户数（样板间、员工房）")
    other_income_per_unit: float = Field(default=0, ge=0, description="每户每月其他收入（停车、RUBS、杂费）")
    other_income_growth_pct: Pct = Field(default=3, ge=-20, le=20)
    turnover_pct: Pct = Field(default=50, ge=0, le=150, description="年换租率（用于翻房成本）")
    make_ready_per_turn: float = Field(default=0, ge=0, description="每次换租的翻房成本")
    opex_per_unit_yr: float = Field(default=0, ge=0, description="每户每年运营费用（人工、维修、公用事业、行政、营销）")
    taxes_yr: float = Field(default=0, ge=0, description="房产税（全年）")
    insurance_yr: float = Field(default=0, ge=0, description="保险（全年）")
    reserves_per_unit_yr: float = Field(default=250, ge=0, description="资本储备（每户每年，NOI 之下）")
    reno_start_month: int = Field(default=0, ge=0, le=360, description="翻新计划从交割后第几个月开始")
    reno_units_per_month: int = Field(default=4, ge=1, le=500, description="每月开工翻新的户数")
    reno_downtime_months: int = Field(default=1, ge=0, le=12, description="每户翻新停用月数")


class CreInputs(_In):
    analysis_start: str = Field(description="分析起点（收购交割）月 YYYY-MM")
    hold_years: int = Field(ge=1, le=30)
    area_sf: float = Field(gt=0, description="可租面积（NRA）")
    purchase_price: float = Field(gt=0)
    closing_costs_pct: Pct = Field(default=1.5, ge=0, le=10)
    property_type: Literal["commercial", "multifamily"] = Field(
        default="commercial", description="commercial = 按租约（写字楼 / 零售 / 工业）；multifamily = 按户型")
    leases: list[Lease] = Field(default_factory=list, max_length=2000)
    market: Market | None = Field(default=None, description="按租约物业的市场租赁假设（commercial 必填）")
    unit_mix: list[UnitType] = Field(default_factory=list, max_length=100)
    multifamily: Multifamily | None = None
    opex: Opex = Field(default_factory=Opex)
    general_vacancy_pct: Pct = Field(default=5, ge=0, le=50, description="一般空置：会扣除已建模的周转空置后再计")
    credit_loss_pct: Pct = Field(default=1, ge=0, le=20)
    debt: Debt | None = None
    mezz: Mezz | None = None
    refinance: Refinance | None = None
    development: Development | None = None
    construction_loan: ConstructionLoan | None = None
    exit_cap_pct: Pct = Field(gt=0, le=25)
    exit_noi_basis: Literal["forward", "stabilized"] = Field(
        default="forward",
        description="退出 NOI 口径：forward = 第 N+1 年 NOI 原值；"
                    "stabilized = 加回该年周转空置与免租、按满租潜在收入重算一般空置后的 NOI")
    selling_costs_pct: Pct = Field(default=2, ge=0, le=10)
    discount_rate_pct: Pct = Field(default=8, ge=0, le=50)
    waterfall: Waterfall | None = None

    _v_start = field_validator("analysis_start")(classmethod(lambda _c, v: _month(v)))

    def mla(self) -> Market:
        """按租约物业的市场租赁假设（校验器保证 commercial 必有）。"""
        if self.market is None:
            raise ValueError("按租约物业需要市场租赁假设（market）")
        return self.market

    def mfa(self) -> Multifamily:
        """多户公寓假设（校验器保证 multifamily 必有，缺省时补默认值）。"""
        if self.multifamily is None:
            raise ValueError("多户公寓需要户型假设（multifamily）")
        return self.multifamily

    @model_validator(mode="after")
    def _capital_and_development(self) -> CreInputs:
        dev = self.development
        if self.construction_loan is not None and dev is None:
            raise ValueError("施工贷需要开发计划（development）")
        if self.refinance is not None and self.refinance.month >= self.hold_years * 12:
            raise ValueError(f"再融资月（第 {self.refinance.month} 月）必须早于出售（第 {self.hold_years * 12} 月）")
        if dev is None:
            return self
        if dev.construction_months >= self.hold_years * 12:
            raise ValueError("施工期必须短于持有期")
        if self.debt is not None:
            raise ValueError("开发项目用施工贷（construction_loan），竣工后用再融资换成长期贷款；不填优先贷款")
        c = dev.construction_months
        late = [le.tenant for le in self.leases if month_offset(le.start, self.analysis_start) < c]
        if late:
            raise ValueError(f"开发项目的预租租约须在竣工后起租：{'、'.join(late)}")
        return self

    @model_validator(mode="after")
    def _space(self) -> CreInputs:
        if self.property_type == "multifamily":
            if not self.unit_mix:
                raise ValueError("多户公寓需要户型表（unit_mix）")
            if self.leases:
                raise ValueError("多户公寓按户型建模，不填逐份租约")
            if self.multifamily is None:
                self.multifamily = Multifamily()
            total = sum(u.units for u in self.unit_mix)
            if self.multifamily.non_revenue_units >= total:
                raise ValueError(f"不产生租金的户数 {self.multifamily.non_revenue_units} 不少于总户数 {total}")
            return self
        if self.market is None:
            raise ValueError("按租约物业需要市场租赁假设（market）")
        leased = sum(lease.sf for lease in self.leases)
        if leased > self.area_sf * 1.0001:
            raise ValueError(f"租约面积合计 {leased:,.0f} SF 超过可租面积 {self.area_sf:,.0f} SF")
        return self
