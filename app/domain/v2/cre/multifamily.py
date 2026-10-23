"""多户公寓按户型逐月测算，产出与按租约物业同一套科目（cashflow.LINES），债务 / 退出 / 收益 / 瀑布全部复用。

收入：
- 潜在租金 GPR = 全部户数 × 当月市场月租（市场租金按分析年阶梯增长）。
- 在租租约按租期（lease_term_months）均匀到期：第 c 批（c = 0..T-1）在第 c 月月末到期，之后每 T 个月续一次，
  续约时调到当月市场租金；首次到期前按交割时在租租金收。GPR 与在租租金之差 = loss-to-lease（为负即 gain-to-lease）。
- 翻新：从 reno_start_month 起按户型顺序每月开工 reno_units_per_month 户，每户停用 reno_downtime_months 个月
  （停用损失计入周转空置），复工后按当月市场租金 + 溢价（溢价随市场租金增长）出租；翻新成本在开工当月计入资本支出。
  翻新后的户不再计 loss-to-lease 滞后（按当月租金计），这是简化。
- 不产生租金的户数按各户型户数占比摊。
- 基本租金 = 在线、产生租金户的在租租金；优惠 = 优惠率 × 基本租金；空置 = 空置率 × 基本租金；
  其他收入 = 每户其他收入 × 在线产生租金户数 × (1 − 空置率)；坏账 = 坏账率 × (基本租金 − 优惠 − 空置 + 其他收入)。

费用：房产税与保险（全年金额，按费用增长率阶梯增长）记在“税与保险”；每户运营费用与翻房成本
（年换租率 × 在线户数 × 每次成本 ÷ 12）记在“运营费用”；管理费 = 管理费率 × 有效总收入。资本储备按户计。
TI / LC 为 0。科目键沿用按租约物业：recoveries = 其他收入，opex_recoverable = 税与保险，
opex_non_recoverable = 运营费用，turnover_vacancy = 翻新停用损失，capex = 翻新成本。
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.v2.cre.cashflow import Monthly
from app.domain.v2.cre.inputs import CreInputs, Multifamily, UnitType
from app.domain.v2.cre.leases import year_step


@dataclass(frozen=True)
class RenoBatch:
    unit_type: int   # unit_mix 下标
    start: int       # 开工月
    units: int


def reno_schedule(mix: list[UnitType], mf: Multifamily, months: int) -> list[RenoBatch]:
    """按户型顺序、每月 reno_units_per_month 户排开工计划；超出分析期的不排。"""
    out: list[RenoBatch] = []
    m, room = mf.reno_start_month, mf.reno_units_per_month
    for t, u in enumerate(mix):
        left = u.renovate_units
        while left > 0 and m < months:
            n = min(left, room)
            out.append(RenoBatch(t, m, n))
            left -= n
            room -= n
            if room == 0:
                m, room = m + 1, mf.reno_units_per_month
    return out


def in_place_rent(u: UnitType, mf: Multifamily, m: int) -> float:
    """未翻新户第 m 月的平均在租月租：T 批租约，第 c 批在第 c、c+T、… 月月末到期，次月起按到期次月的市场租金续。"""
    t = mf.lease_term_months
    total = 0.0
    for c in range(t):
        if m <= c:
            total += u.in_place_rent
        else:
            last_roll = c + 1 + ((m - c - 1) // t) * t
            total += u.market_rent * year_step(mf.rent_growth_pct, last_roll)
    return total / t


def project(cre: CreInputs, months: int) -> Monthly:
    mf = cre.mfa()
    mix = cre.unit_mix
    out = Monthly(months)
    total_units = sum(u.units for u in mix)
    nr_share = mf.non_revenue_units / total_units
    batches = reno_schedule(mix, mf, months)
    vac, conc, bad = cre.general_vacancy_pct / 100, mf.concessions_pct / 100, cre.credit_loss_pct / 100
    rs = 1 - nr_share  # 产生租金的户数占比
    for m in range(months):
        g_rent = year_step(mf.rent_growth_pct, m)
        g_opex = year_step(cre.opex.growth_pct, m)
        gpr = base = ltl = premium = offline_loss = online_units = 0.0
        for t, u in enumerate(mix):
            mkt = u.market_rent * g_rent
            mine = [b for b in batches if b.unit_type == t]
            started = sum(b.units for b in mine if b.start <= m)
            offline = sum(b.units for b in mine if b.start <= m < b.start + mf.reno_downtime_months)
            done = started - offline
            old = u.units - started
            gpr += u.units * mkt
            ltl -= rs * old * (mkt - in_place_rent(u, mf, m))
            premium += rs * done * u.reno_premium * g_rent
            offline_loss += rs * offline * mkt
            online_units += rs * (u.units - offline)
            out.add("capex", m, -sum(b.units for b in mine if b.start == m) * u.reno_cost_per_unit)
        non_revenue = nr_share * gpr
        base = gpr + ltl + premium - offline_loss - non_revenue
        free = -conc * base
        vac_m = max(vac, _unleased(cre, m, rs * total_units))  # 去化期：未租出的户也计空置
        gv = -vac_m * base
        other = mf.other_income_per_unit * year_step(mf.other_income_growth_pct, m) * online_units * (1 - vac_m)
        credit = -bad * (base + free + gv + other)
        egr = base + free + other + gv + credit
        taxes_ins = (mf.taxes_yr + mf.insurance_yr) / 12 * g_opex
        operating = (mf.opex_per_unit_yr * total_units / 12
                     + mf.turnover_pct / 100 * online_units * mf.make_ready_per_turn / 12) * g_opex
        mgmt = cre.opex.mgmt_fee_pct_egr / 100 * egr
        reserves = mf.reserves_per_unit_yr * total_units / 12 * g_opex
        noi = egr - taxes_ins - operating - mgmt
        for key, v in (("potential_rent", gpr), ("loss_to_lease", ltl), ("premium", premium),
                       ("turnover_vacancy", -offline_loss), ("non_revenue", -non_revenue), ("base_rent", base),
                       ("free_rent", free), ("recoveries", other), ("general_vacancy", gv), ("credit_loss", credit),
                       ("egr", egr), ("opex_recoverable", -taxes_ins), ("opex_non_recoverable", -operating),
                       ("mgmt_fee", -mgmt), ("opex", -(taxes_ins + operating + mgmt)), ("noi", noi),
                       ("reserves", -reserves)):
            out.add(key, m, v)
        out.add("cf_before_debt", m, noi - reserves + out.lines["capex"][m])
        out.add("occupancy_pct", m, online_units * (1 - vac_m) / total_units * 100)
    return out


def _unleased(cre: CreInputs, m: int, revenue_units: float) -> float:
    """开发项目竣工后的去化：第 C 月起每月租出 absorption 户，未租出的比例（计为空置）；不是开发项目或已满租时为 0。"""
    dev = cre.development
    if dev is None or dev.absorption_units_per_month is None or revenue_units <= 0:
        return 0.0
    leased = dev.absorption_units_per_month * (m - dev.construction_months + 1)
    return max(0.0, 1 - leased / revenue_units)

