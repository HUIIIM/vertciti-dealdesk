"""按月物业现金流。

基本租金 → 免租 → 费用回收 → 周转空置 / 一般空置 → 信用损失 → 有效总收入 → 运营费用 → NOI
→ TI / LC / 资本储备 → 债前现金流（无杠杆）。

一般空置按潜在总收入（含空置面积按市场租金应收的部分）计提，但先扣除已建模的周转空置（Argus “reduce by
absorption & turnover vacancy”），避免空置被重复扣。管理费按有效总收入计、不回收。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.v2.cre.inputs import CreInputs
from app.domain.v2.cre.leases import Segment, market_rent_psf, year_step

LINES = ("potential_rent", "loss_to_lease", "premium", "non_revenue", "turnover_vacancy", "free_rent", "base_rent",
         "recoveries", "general_vacancy",
         "credit_loss", "egr", "opex_recoverable", "opex_non_recoverable", "mgmt_fee", "opex", "noi",
         "ti", "lc", "reserves", "capex", "dev_costs", "cf_before_debt", "occupancy_pct")
# loss_to_lease / premium / non_revenue / capex 只有多户公寓有值（见 multifamily.py）；按租约物业恒为 0


@dataclass
class Monthly:
    n: int
    lines: dict[str, list[float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.lines = {k: [0.0] * self.n for k in LINES}

    def add(self, key: str, m: int, v: float) -> None:
        self.lines[key][m] += v


def _recovery(seg: Segment, rec_psf: float, area: float, m: int) -> float:
    if seg.recovery == "gross" or not seg.start <= m <= seg.end:
        return 0.0
    if seg.recovery == "nnn":
        return rec_psf * area / 12 * (seg.sf / area)
    return max(0.0, rec_psf - seg.base_psf) * seg.sf / 12  # 基年：只回收超过基年的部分


def _vacant_potential(seg: Segment, cre: CreInputs, rec_psf: float, m: int) -> float:
    """空置期内这块面积按市场条件本可收到的租金与回收（周转空置损失）。"""
    rent = market_rent_psf(cre.mla(), m) * seg.sf / 12
    rec = rec_psf * seg.sf / 12 if seg.recovery == "nnn" else 0.0
    return rent + rec


def project(cre: CreInputs, chains: list[list[Segment]], months: int) -> Monthly:
    out = Monthly(months)
    o, area = cre.opex, cre.area_sf
    for m in range(months):
        g = year_step(o.growth_pct, m)
        rec_psf, nonrec_psf = o.recoverable_psf_yr * g, o.non_recoverable_psf_yr * g
        occupied_sf = 0.0
        for chain in chains:
            active = next((s for s in chain if s.start <= m <= s.end), None)
            if active is None:  # 两段之间的空置期
                gap = next((s for s in chain if s.start > m), None)
                if gap is not None:
                    loss = _vacant_potential(gap, cre, rec_psf, m)
                    out.add("potential_rent", m, loss)
                    out.add("turnover_vacancy", m, -loss)
                continue
            occupied_sf += active.sf
            rent = active.rent(m)
            out.add("potential_rent", m, rent + _recovery(active, rec_psf, area, m))
            out.add("base_rent", m, rent)
            if active.free(m):
                out.add("free_rent", m, -rent)
            out.add("recoveries", m, _recovery(active, rec_psf, area, m))
            if m == max(active.start, 0) and active.speculative:
                out.add("ti", m, -active.ti)
                out.add("lc", m, -active.lc)
        line = out.lines
        gross = line["base_rent"][m] + line["free_rent"][m] + line["recoveries"][m]
        gv_target = cre.general_vacancy_pct / 100 * line["potential_rent"][m]
        gv = max(0.0, gv_target + line["turnover_vacancy"][m])  # 周转空置（负数）已抵减一般空置
        out.add("general_vacancy", m, -gv)
        credit = cre.credit_loss_pct / 100 * (gross - gv)
        out.add("credit_loss", m, -credit)
        egr = gross - gv - credit
        out.add("egr", m, egr)
        mgmt = o.mgmt_fee_pct_egr / 100 * egr
        out.add("opex_recoverable", m, -rec_psf * area / 12)
        out.add("opex_non_recoverable", m, -nonrec_psf * area / 12)
        out.add("mgmt_fee", m, -mgmt)
        opex = rec_psf * area / 12 + nonrec_psf * area / 12 + mgmt
        out.add("opex", m, -opex)
        out.add("noi", m, egr - opex)
        out.add("reserves", m, -o.reserves_psf_yr * g * area / 12)
        out.add("cf_before_debt", m, egr - opex + line["ti"][m] + line["lc"][m] + line["reserves"][m])
        out.add("occupancy_pct", m, occupied_sf / area * 100)
    return out
