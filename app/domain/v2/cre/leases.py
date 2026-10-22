"""租约展开：每份租约（及未出租面积）在分析期内展开成一串“租期段”，到期后按市场租赁假设（MLA）滚动续上。

口径（与 Argus 默认一致）：
- 续租与新租按续租概率加权成一条路径：空置月 = (1-p)×新租空置月（四舍五入到整月）；免租月同样加权；
  TI、LC 按金额加权（不取整）。新段租金 = 起租当月的市场租金（市场租金按年阶梯增长）。
- 租金在每个租约周年日递增；已在执行中的租约，分析起点的租金即当前合同租金，之后逢周年日递增。
- 未出租面积视为“分析开始即到期、按新租招租”：先空置（新租空置月），再按市场条件起租并计 TI / LC。
月份用分析起点为 0 的整数下标；租期段 [start, end] 含两端。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from app.domain.v2.cre.inputs import CreInputs, Lease, Market, Recovery


def month_index(ym: str, origin: str) -> int:
    y, m = (int(x) for x in ym.split("-"))
    y0, m0 = (int(x) for x in origin.split("-"))
    return (y - y0) * 12 + (m - m0)


def year_step(rate_pct: float, m: int) -> float:
    """按分析年阶梯增长的系数：第 0–11 月为 1，第 12–23 月为 (1+g)，依此类推。"""
    return (1 + rate_pct / 100) ** (m // 12)


def _round_month(x: float) -> int:
    return math.floor(x + 0.5)


@dataclass(frozen=True)
class Segment:
    tenant: str
    suite: str
    sf: float
    start: int
    end: int
    rent_psf: float          # 本段参考租金（已在执行的租约 = 分析起点租金；新段 = 起租时市场租金）
    escalation_pct: float
    free_start: int          # 免租区间 [free_start, free_end)
    free_end: int
    recovery: Recovery
    base_psf: float          # 基年租约的基年可回收费用 $/SF/年
    speculative: bool        # True = 到期后按 MLA 假设续上的段（非签约事实）
    ti: float = 0.0          # 本段起租时一次性支出
    lc: float = 0.0
    downtime_before: int = 0

    def escalations(self, m: int) -> int:
        if self.start >= 0:
            return (m - self.start) // 12
        return (m - self.start) // 12 - (-self.start) // 12

    def rent(self, m: int) -> float:
        """第 m 月的合同基本租金（未扣免租）。"""
        if not self.start <= m <= self.end:
            return 0.0
        return self.rent_psf * (1 + self.escalation_pct / 100) ** self.escalations(m) * self.sf / 12

    def free(self, m: int) -> bool:
        return self.free_start <= m < self.free_end


def market_rent_psf(mk: Market, m: int) -> float:
    return mk.rent_psf_yr * year_step(mk.rent_growth_pct, m)


def _rollover(prev_end: int, sf: float, tenant: str, suite: str, recovery: Recovery, cre: CreInputs, *,
              renewal_prob: float) -> Segment:
    mk = cre.market
    p = renewal_prob
    downtime = _round_month((1 - p) * mk.downtime_months)
    free = _round_month(p * mk.free_rent_renew_months + (1 - p) * mk.free_rent_new_months)
    start = prev_end + 1 + downtime
    end = start + mk.lease_term_years * 12 - 1
    rent_psf = market_rent_psf(mk, start)
    seg = Segment(tenant=tenant, suite=suite, sf=sf, start=start, end=end, rent_psf=rent_psf,
                  escalation_pct=mk.escalation_pct, free_start=start, free_end=start + free, recovery=recovery,
                  base_psf=cre.opex.recoverable_psf_yr * year_step(cre.opex.growth_pct, start),
                  speculative=True, downtime_before=downtime)
    term_rent = sum(seg.rent(m) for m in range(start, end + 1))
    ti = (p * mk.ti_renew_psf + (1 - p) * mk.ti_new_psf) * sf
    lc = (p * mk.lc_renew_pct + (1 - p) * mk.lc_new_pct) / 100 * term_rent
    return Segment(**{**seg.__dict__, "ti": ti, "lc": lc})


def _chain(first: Segment, cre: CreInputs, horizon: int, *, renewal_prob: float) -> list[Segment]:
    out = [first]
    while out[-1].end < horizon - 1:
        last = out[-1]
        out.append(_rollover(last.end, last.sf, last.tenant, last.suite, last.recovery, cre,
                             renewal_prob=renewal_prob))
    return out


def _existing(lease: Lease, cre: CreInputs) -> Segment:
    s, e = month_index(lease.start, cre.analysis_start), month_index(lease.end, cre.analysis_start)
    base = lease.base_year_opex_psf if lease.base_year_opex_psf is not None else cre.opex.recoverable_psf_yr
    return Segment(tenant=lease.tenant, suite=lease.suite, sf=lease.sf, start=s, end=e, rent_psf=lease.rent_psf_yr,
                   escalation_pct=lease.escalation_pct, free_start=max(s, 0),
                   free_end=max(s, 0) + lease.free_rent_months, recovery=lease.recovery, base_psf=base,
                   speculative=False)


def expand(cre: CreInputs, horizon: int) -> list[list[Segment]]:
    """每块面积一条租期段链（签约段 + 到期续上的假设段；空置面积是一条招租链），覆盖到 horizon（不含）为止。"""
    p = cre.market.renewal_prob_pct / 100
    chains: list[list[Segment]] = []
    for lease in cre.leases:
        first = _existing(lease, cre)
        if first.end < 0:  # 分析开始前已到期：按到期续租处理（同一租户的续租概率仍适用）
            chains.append(_chain(_rollover(-1, first.sf, first.tenant, first.suite, first.recovery, cre,
                                           renewal_prob=p), cre, horizon, renewal_prob=p))
        else:
            chains.append(_chain(first, cre, horizon, renewal_prob=p))
    vacant = cre.area_sf - sum(lease.sf for lease in cre.leases)
    if vacant > 0.5:  # 空置面积：没有在位租户，续租概率为 0（全按新租招租）
        first = _rollover(-1, vacant, "（空置）", "", "nnn", cre, renewal_prob=0.0)
        chains.append(_chain(first, cre, horizon, renewal_prob=p))
    return chains
