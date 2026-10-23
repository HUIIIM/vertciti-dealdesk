// 三条赛道的表单字段（路径、标签、单位、说明）。路径与后端输入结构一致，护照（来源）按同一路径登记。
import { T } from "@/i18n";
import type { Unit } from "@/lib/format";
import type { JsonObj } from "@/lib/paths";

export type Track = "residential" | "commercial" | "institutional";

export function trackLabel(t: string): string {
  return t === "commercial" ? T("商业") : t === "institutional" ? T("机构级") : T("住宅");
}
export interface FieldSpec { path: string; label: string; unit: Unit | "select" | "bool"; hint?: string; options?: [string, string][]; step?: number }

// ---------------------------------------------------------------- 商业（v1 机构级核保模型）
export const COM_EXPENSES: [string, string][] = [
  ["property_tax", T("房产税")], ["insurance", T("保险")], ["management_fee", T("管理费")], ["repairs_maintenance", T("维修保养")],
  ["utilities", T("水电")], ["cam", "CAM"], ["service_contracts", T("服务合同")], ["general_admin", T("行政管理")],
  ["janitor", T("保洁")], ["security", T("安保")], ["payroll", T("人员")], ["landscape", T("绿化")],
];
export const COM_INCOME: [string, string][] = [
  ["cam_recovery", T("CAM 回收")], ["parking_income", T("停车收入")], ["other_income", T("其他收入")],
];
export const COM_BELOW_LINE: [string, string][] = [
  ["tenant_improvements", T("租户改造 TI")], ["leasing_commissions", T("租赁佣金 LC")], ["capex", T("资本支出")],
];

export const COM_ANALYSIS: FieldSpec[] = [
  { path: "analysis.purchase_price", label: T("收购价"), unit: "usd" },
  { path: "analysis.closing_costs", label: T("交割费用"), unit: "usd" },
  { path: "analysis.lender_fees", label: T("贷款费用"), unit: "usd" },
  { path: "analysis.building_repairs", label: T("交割即修"), unit: "usd" },
  { path: "analysis.capital_reserve", label: T("资本储备"), unit: "usd" },
  { path: "analysis.down_pct", label: T("首付比例"), unit: "pct" },
  { path: "analysis.rate", label: T("贷款利率"), unit: "pct", step: 0.05 },
  { path: "analysis.amort_type", label: T("还款方式"), unit: "select", options: [["IO", T("只付息 IO")], ["AMORTIZING", T("等额摊还")]] },
  { path: "analysis.amort_years", label: T("摊销年数"), unit: "int" },
  { path: "analysis.market_cap_rate", label: T("市场 Cap Rate"), unit: "pct", step: 0.05, hint: T("驱动转售价值（F15/F16）") },
  { path: "analysis.hold_years", label: T("持有年数"), unit: "int" },
  { path: "analysis.noi_growth", label: T("NOI 年增长"), unit: "pct", step: 0.1 },
  { path: "analysis.exit_cap_rate", label: T("退出 Cap Rate"), unit: "pct", step: 0.05, hint: T("空 → 联动市场 cap；都空用 5% 并标“默认”") },
  { path: "analysis.abatements", label: T("减免（年）"), unit: "usd" },
];

export const COM_PROPERTY: FieldSpec[] = [
  { path: "property.property_type", label: T("物业类型"), unit: "select", options: [["Retail", T("零售")], ["Office", T("写字楼")], ["Industrial", T("工业")], ["Multifamily", T("多户")], ["Mixed-Use", T("综合")]] },
  { path: "property.net_rentable_sf", label: T("可出租面积"), unit: "int", hint: "SF" },
  { path: "property.year_built", label: T("建成年份"), unit: "text" },
  { path: "vacant_sf", label: T("空置面积"), unit: "int", hint: "SF" },
];

export function blankCommercial(name = "", address = ""): JsonObj {
  const zeros = (pairs: [string, string][]) => Object.fromEntries(pairs.map(([k]) => [k, 0]));
  const lines = { ...zeros(COM_INCOME), vacancy_pct: 0, ...zeros(COM_EXPENSES), ...zeros(COM_BELOW_LINE) };
  return {
    property: { name, address, city: "", state: "", zip: "", county: "", property_type: "Retail", net_rentable_sf: 0, land_acres: 0,
      parking_spaces: 0, year_built: "", year_renovated: "", buildings: "", floors: "", occupancy_as_of: "" },
    tenants: [], vacant_sf: 0, historical: { ...lines }, proforma: { ...lines },
    analysis: { purchase_price: 0, building_repairs: 0, capital_reserve: 0, lender_fees: 0, closing_costs: 0, down_pct: 30, rate: 6.5,
      amort_type: "IO", amort_years: 30, market_cap_rate: 6, abatements: 0, underwritten_noi: null, projected_noi: null,
      inplace_noi_cf: null, hold_years: 5, noi_growth: 2, exit_cap_rate: 5 },
  };
}

// ---------------------------------------------------------------- 机构级（逐租约按月引擎，cre-1.0；百分比一律按百分比数）
export const INST_DEAL: FieldSpec[] = [
  { path: "purchase_price", label: T("收购价"), unit: "usd" },
  { path: "closing_costs_pct", label: T("交割成本"), unit: "pct", step: 0.1 },
  { path: "analysis_start", label: T("交割月"), unit: "text", hint: "YYYY-MM" },
  { path: "hold_years", label: T("持有年数"), unit: "int" },
  { path: "area_sf", label: T("可租面积"), unit: "int", hint: "SF" },
  { path: "general_vacancy_pct", label: T("一般空置率"), unit: "pct", step: 0.5, hint: T("会先扣除已建模的周转空置") },
  { path: "credit_loss_pct", label: T("信用损失"), unit: "pct", step: 0.25 },
  { path: "exit_cap_pct", label: T("退出 Cap Rate"), unit: "pct", step: 0.05, hint: T("按下一年 NOI") },
  { path: "exit_noi_basis", label: T("退出 NOI 口径"), unit: "select", options: [["forward", T("下一年 NOI 原值")], ["stabilized", T("稳定化（加回周转空置与免租）")]],
    hint: T("退出年有租约周转时，原值会压低售价") },
  { path: "selling_costs_pct", label: T("卖方成本"), unit: "pct", step: 0.25 },
  { path: "discount_rate_pct", label: T("折现率"), unit: "pct", step: 0.25, hint: "NPV" },
];
export const INST_MARKET: FieldSpec[] = [
  { path: "market.rent_psf_yr", label: T("市场租金"), unit: "usd", hint: T("$/SF/年") },
  { path: "market.rent_growth_pct", label: T("市场租金增长"), unit: "pct", step: 0.25 },
  { path: "market.renewal_prob_pct", label: T("续租概率"), unit: "pct", step: 5 },
  { path: "market.downtime_months", label: T("新租空置月数"), unit: "int" },
  { path: "market.free_rent_new_months", label: T("新租免租月"), unit: "int" },
  { path: "market.free_rent_renew_months", label: T("续租免租月"), unit: "int" },
  { path: "market.ti_new_psf", label: T("新租 TI"), unit: "usd", hint: "$/SF" },
  { path: "market.ti_renew_psf", label: T("续租 TI"), unit: "usd", hint: "$/SF" },
  { path: "market.lc_new_pct", label: T("新租佣金"), unit: "pct", step: 0.5, hint: T("占租期租金总额") },
  { path: "market.lc_renew_pct", label: T("续租佣金"), unit: "pct", step: 0.5 },
  { path: "market.lease_term_years", label: T("新租期"), unit: "int", hint: T("年") },
  { path: "market.escalation_pct", label: T("新租年递增"), unit: "pct", step: 0.25 },
];
export const INST_OPEX: FieldSpec[] = [
  { path: "opex.recoverable_psf_yr", label: T("可回收费用"), unit: "usd", hint: T("税 / 保险 / CAM，$/SF/年") },
  { path: "opex.non_recoverable_psf_yr", label: T("不可回收费用"), unit: "usd", hint: T("$/SF/年") },
  { path: "opex.growth_pct", label: T("费用增长"), unit: "pct", step: 0.25 },
  { path: "opex.mgmt_fee_pct_egr", label: T("管理费"), unit: "pct", step: 0.25, hint: T("占有效总收入") },
  { path: "opex.reserves_psf_yr", label: T("资本储备"), unit: "usd", hint: T("$/SF/年") },
];
export const INST_DEBT: FieldSpec[] = [
  { path: "debt.ltv_pct", label: "LTV", unit: "pct", step: 1 },
  { path: "debt.rate_type", label: T("利率类型"), unit: "select", options: [["fixed", T("固定")], ["floating", T("浮动（SOFR + 利差）")]] },
  { path: "debt.rate_pct", label: T("固定利率"), unit: "pct", step: 0.05 },
  { path: "debt.spread_bps", label: T("利差"), unit: "int", hint: "bp" },
  { path: "debt.cap_strike_pct", label: T("利率上限"), unit: "pct", step: 0.25, hint: T("SOFR 上限，空 = 无") },
  { path: "debt.io_months", label: T("只付息月数"), unit: "int" },
  { path: "debt.amort_years", label: T("摊还年数"), unit: "int" },
  { path: "debt.orig_fee_pct", label: T("贷款开办费"), unit: "pct", step: 0.25 },
];
export const INST_MEZZ: FieldSpec[] = [
  { path: "mezz.ltv_pct", label: T("夹层比例"), unit: "pct", step: 1, hint: T("占收购价，在优先贷款之上") },
  { path: "mezz.rate_pct", label: T("夹层利率"), unit: "pct", step: 0.25, hint: T("固定，只付息") },
  { path: "mezz.orig_fee_pct", label: T("夹层开办费"), unit: "pct", step: 0.25 },
];
export const MEZZ_DEFAULTS: JsonObj = { ltv_pct: 10, rate_pct: 11, orig_fee_pct: 1 };
export const INST_REFI: FieldSpec[] = [
  { path: "refinance.month", label: T("再融资月"), unit: "int", hint: T("交割后第几个月") },
  { path: "refinance.value_cap_pct", label: T("估值资本化率"), unit: "pct", step: 0.05, hint: T("届时 12 个月 NOI ÷ 资本化率 = 价值") },
  { path: "refinance.ltv_pct", label: T("再融资 LTV"), unit: "pct", step: 1 },
  { path: "refinance.min_dscr", label: T("最低 DSCR"), unit: "x", step: 0.05, hint: T("限额；空 = 不限") },
  { path: "refinance.min_debt_yield_pct", label: T("最低债务收益率"), unit: "pct", step: 0.25, hint: T("限额；空 = 不限") },
  { path: "refinance.rate_pct", label: T("新贷款利率"), unit: "pct", step: 0.05 },
  { path: "refinance.io_months", label: T("新贷款只付息月数"), unit: "int" },
  { path: "refinance.amort_years", label: T("新贷款摊还年数"), unit: "int" },
  { path: "refinance.costs_pct", label: T("再融资费用"), unit: "pct", step: 0.25, hint: T("占新贷款") },
  { path: "refinance.repay_mezz", label: T("一并偿清夹层"), unit: "bool" },
];
export const REFI_DEFAULTS: JsonObj = { month: 36, value_cap_pct: 6.5, ltv_pct: 65, min_dscr: 1.25, min_debt_yield_pct: null, rate_pct: 6.0,
  io_months: 0, amort_years: 30, costs_pct: 1, repay_mezz: true };
export const INST_WATERFALL: FieldSpec[] = [
  { path: "waterfall.lp_equity_pct", label: T("LP 出资比例"), unit: "pct", step: 1 },
  { path: "waterfall.pref_pct", label: T("优先回报"), unit: "pct", step: 0.5, hint: T("LP IRR 门槛") },
  { path: "waterfall.final_lp_share_pct", label: T("最后一档 LP 份额"), unit: "pct", step: 5 },
  { path: "waterfall.frequency", label: T("分配频率"), unit: "select", options: [["annual", T("按年")], ["monthly", T("按月（门槛按月复利）")]] },
  { path: "waterfall.catch_up_target_pct", label: T("GP catch-up 目标"), unit: "pct", step: 5, hint: T("GP 补到累计利润的比例；空 = 无 catch-up") },
  { path: "waterfall.catch_up_rate_pct", label: T("catch-up 期间 GP 份额"), unit: "pct", step: 10 },
  { path: "waterfall.clawback", label: T("期末回拨（clawback）"), unit: "bool", hint: T("LP 未达优先回报时 GP 退回 promote") },
];

// 多户公寓（按户型；租金一律“每户每月”）
export const INST_MF_REVENUE: FieldSpec[] = [
  { path: "multifamily.rent_growth_pct", label: T("市场租金增长"), unit: "pct", step: 0.25 },
  { path: "multifamily.lease_term_months", label: T("租期"), unit: "int", hint: T("月；在租租约在这段时间里均匀到期、调到市场租金") },
  { path: "multifamily.concessions_pct", label: T("租金优惠"), unit: "pct", step: 0.25, hint: T("占在租租金") },
  { path: "multifamily.non_revenue_units", label: T("不产生租金的户"), unit: "int", hint: T("样板间、员工房") },
  { path: "multifamily.other_income_per_unit", label: T("其他收入"), unit: "usd", hint: T("每户每月：停车、RUBS、杂费") },
  { path: "multifamily.other_income_growth_pct", label: T("其他收入增长"), unit: "pct", step: 0.25 },
];
export const INST_MF_OPEX: FieldSpec[] = [
  { path: "multifamily.opex_per_unit_yr", label: T("运营费用"), unit: "usd", hint: T("每户每年：人工、维修、公用事业、行政、营销") },
  { path: "multifamily.taxes_yr", label: T("房产税"), unit: "usd", hint: T("全年") },
  { path: "multifamily.insurance_yr", label: T("保险"), unit: "usd", hint: T("全年") },
  { path: "multifamily.turnover_pct", label: T("年换租率"), unit: "pct", step: 5 },
  { path: "multifamily.make_ready_per_turn", label: T("每次翻房成本"), unit: "usd" },
  { path: "opex.growth_pct", label: T("费用增长"), unit: "pct", step: 0.25 },
  { path: "opex.mgmt_fee_pct_egr", label: T("管理费"), unit: "pct", step: 0.25, hint: T("占有效总收入") },
  { path: "multifamily.reserves_per_unit_yr", label: T("资本储备"), unit: "usd", hint: T("每户每年") },
];
export const INST_MF_RENO: FieldSpec[] = [
  { path: "multifamily.reno_start_month", label: T("翻新开工"), unit: "int", hint: T("交割后第几个月") },
  { path: "multifamily.reno_units_per_month", label: T("每月翻新户数"), unit: "int" },
  { path: "multifamily.reno_downtime_months", label: T("每户停用月数"), unit: "int" },
];
export const MF_DEFAULTS: JsonObj = {
  rent_growth_pct: 3, lease_term_months: 12, concessions_pct: 1, non_revenue_units: 0, other_income_per_unit: 0, other_income_growth_pct: 3,
  turnover_pct: 50, make_ready_per_turn: 0, opex_per_unit_yr: 0, taxes_yr: 0, insurance_yr: 0, reserves_per_unit_yr: 250,
  reno_start_month: 0, reno_units_per_month: 4, reno_downtime_months: 1,
};
export const blankUnit = (): JsonObj => ({ name: "", units: 1, avg_sf: 0, in_place_rent: 0, market_rent: 1000, renovate_units: 0,
  reno_cost_per_unit: 0, reno_premium: 0 });

export function blankInstitutional(price?: number | null): JsonObj {
  const now = new Date();
  const start = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  return {
    analysis_start: start, hold_years: 7, area_sf: 0, purchase_price: price && price > 0 ? price : 0, closing_costs_pct: 1.5,
    leases: [], general_vacancy_pct: 5, credit_loss_pct: 1, exit_cap_pct: 7, selling_costs_pct: 2, discount_rate_pct: 8,
    market: { rent_psf_yr: 30, rent_growth_pct: 3, renewal_prob_pct: 65, downtime_months: 6, free_rent_new_months: 3,
      free_rent_renew_months: 1, ti_new_psf: 40, ti_renew_psf: 15, lc_new_pct: 6, lc_renew_pct: 3, lease_term_years: 5, escalation_pct: 3 },
    opex: { recoverable_psf_yr: 10, non_recoverable_psf_yr: 1.5, growth_pct: 3, mgmt_fee_pct_egr: 3, reserves_psf_yr: 0.25 },
    debt: { ltv_pct: 60, rate_type: "fixed", rate_pct: 6.5, sofr_curve_pct: [], spread_bps: 250, cap_strike_pct: null, io_months: 24,
      amort_years: 30, orig_fee_pct: 1 },
    waterfall: { lp_equity_pct: 90, pref_pct: 8, tiers: [{ irr_pct: 12, lp_share_pct: 80 }], final_lp_share_pct: 70 },
  };
}

// ---------------------------------------------------------------- 住宅（v1 打分引擎）
export const RES_DEAL: FieldSpec[] = [
  { path: "price", label: T("收购价"), unit: "usd" },
  { path: "structure", label: T("交易结构"), unit: "select", options: [["standard", T("普通购买")], ["new_loan", T("新办贷款")], ["subject_to", T("Subject-to（承接贷款）")],
    ["seller_financing", T("卖方融资")], ["loan_assumption", T("贷款承接")], ["lease_option", T("租购")], ["novation", "Novation"], ["wholesale", T("批发")]] },
  { path: "down_payment", label: T("首付"), unit: "usd" },
  { path: "loan_balance", label: T("贷款额 / 余额"), unit: "usd" },
  { path: "rate", label: T("利率"), unit: "pct", step: 0.05 },
  { path: "rate_type", label: T("利率类型"), unit: "select", options: [["fixed", T("固定")], ["floating", T("浮动")]] },
  { path: "term_years_remaining", label: T("剩余年限"), unit: "int" },
  { path: "closing_costs", label: T("交割费用"), unit: "usd" },
  { path: "initial_repairs", label: T("初始维修"), unit: "usd" },
  { path: "reserves_months_piti", label: T("储备金（月 PITI）"), unit: "int" },
];
export const RES_INCOME: FieldSpec[] = [
  { path: "monthly_rent", label: T("月租金"), unit: "usd_month" },
  { path: "other_income_monthly", label: T("其他收入（月）"), unit: "usd_month" },
  { path: "units", label: T("套数"), unit: "int" },
  { path: "rent_source", label: T("租金依据"), unit: "select", options: [["comps_verified", T("可比已核实")], ["estimated", T("估算")], ["proforma", T("卖方 pro forma")]] },
];
export const RES_EXPENSES: FieldSpec[] = [
  { path: "taxes_annual", label: T("房产税（年）"), unit: "usd" },
  { path: "insurance_annual", label: T("保险（年）"), unit: "usd" },
  { path: "hoa_monthly", label: T("HOA（月）"), unit: "usd_month" },
  { path: "utilities_owner_monthly", label: T("房东承担水电（月）"), unit: "usd_month" },
  { path: "vacancy_pct", label: T("空置率"), unit: "pct" },
  { path: "maint_pct", label: T("维修比例"), unit: "pct" },
  { path: "capex_pct", label: T("资本支出比例"), unit: "pct" },
  { path: "mgmt_pct", label: T("管理费比例"), unit: "pct" },
];
export const RES_EXIT: FieldSpec[] = [
  { path: "exit_primary", label: T("主退出路径"), unit: "text" },
  { path: "exit_backup", label: T("备用退出"), unit: "text" },
  { path: "due_on_sale_plan", label: T("due-on-sale 预案"), unit: "text" },
];

export function blankResidential(): JsonObj {
  return { structure: "standard", price: 0, down_payment: 0, loan_balance: 0, rate: 6.5, rate_type: "fixed", term_years_remaining: 30,
    balloon_years: null, is_assumption: false, monthly_rent: 0, other_income_monthly: 0, units: 1, rent_source: "estimated",
    taxes_annual: 0, insurance_annual: 0, hoa_monthly: 0, utilities_owner_monthly: 0, vacancy_pct: 8, maint_pct: 8, capex_pct: 8,
    mgmt_pct: 10, closing_costs: 0, initial_repairs: 0, other_liens: 0, seller_delinquent_days: 0, has_discount_hedge: false,
    insurance_available: true, seller_signed_auth_release: false, hoa_arrears_severe: false, title_defect: false, fraud_flag: false,
    exit_primary: "", exit_backup: "", due_on_sale_plan: "", reserves_months_piti: 0, risk_flags: [], market_pop: 0,
    market_employment: 0, market_inventory: 0, market_appreciation: 0 };
}

export function blankInputs(track: Track, name = "", address = "", price?: number | null): JsonObj {
  if (track === "institutional") return blankInstitutional(price);
  const base = track === "commercial" ? blankCommercial(name, address) : blankResidential();
  if (price && price > 0) {
    if (track === "commercial") (base.analysis as JsonObj).purchase_price = price;
    else base.price = price;
  }
  return base;
}

/** 输入路径 → 中文标签（数字护照、矛盾登记、版本对比里不露内部字段名）。 */
const LABELS: Record<string, string> = Object.fromEntries([
  ...[...COM_ANALYSIS, ...COM_PROPERTY, ...RES_DEAL, ...RES_INCOME, ...RES_EXPENSES, ...RES_EXIT,
    ...INST_DEAL, ...INST_MARKET, ...INST_OPEX, ...INST_DEBT, ...INST_WATERFALL].map((f) => [f.path, f.label]),
  ...[...INST_MF_REVENUE, ...INST_MF_OPEX, ...INST_MF_RENO].map((f) => [f.path, f.label]),
  ["leases.*.rent_psf_yr", T("租金水平（各租约 $/SF）")],
  ["unit_mix.*.in_place_rent", T("在租月租（各户型）")], ["unit_mix.*.market_rent", T("市场月租（各户型）")],
  ["unit_mix.*.reno_premium", T("翻新溢价（各户型）")], ["unit_mix.*.reno_cost_per_unit", T("翻新成本（各户型）")],
  ...[...COM_INCOME, ...COM_EXPENSES, ...COM_BELOW_LINE].flatMap(([k, l]) => [[`proforma.${k}`, T("{0}（预测）", [l])], [`historical.${k}`, T("{0}（历史）", [l])]]),
  ["proforma.vacancy_pct", T("空置率（预测）")], ["historical.vacancy_pct", T("空置率（历史）")],
  ["tenants.*.monthly_rent", T("租金水平（各租户月租）")], ["tenants.*.underwritten_annual", T("租金水平（承销年租）")],
]);
export function fieldLabel(path: string): string {
  if (LABELS[path]) return LABELS[path]!;
  const lm = /^leases\.(\d+)\.(\w+)$/.exec(path);
  if (lm) return T("第 {0} 份租约 · {1}", [Number(lm[1]) + 1, { rent_psf_yr: T("租金 $/SF"), sf: T("面积"), tenant: T("租户"), suite: T("单元"),
    start: T("起租"), end: T("到期"), escalation_pct: T("年递增"), free_rent_months: T("免租月"), recovery: T("回收方式") }[lm[2]!] ?? lm[2]]);
  const um = /^unit_mix\.(\d+)\.(\w+)$/.exec(path);
  if (um) return T("第 {0} 个户型 · {1}", [Number(um[1]) + 1, { name: T("户型"), units: T("户数"), avg_sf: T("户均面积"), in_place_rent: T("在租月租"),
    market_rent: T("市场月租"), renovate_units: T("翻新户数"), reno_cost_per_unit: T("每户翻新成本"), reno_premium: T("翻新溢价") }[um[2]!] ?? um[2]]);
  const m = /^tenants\.(\d+)\.(\w+)$/.exec(path);
  if (m) return T("第 {0} 户 · {1}", [Number(m[1]) + 1, { monthly_rent: T("月租"), sf: T("面积"), tenant: T("租户"), suite: T("单元"), underwritten_annual: T("承销年租") }[m[2]!] ?? m[2]]);
  return path;
}

/** 卡片 / 结论卡要展示的指标（按赛道）。 */
export const CARD_METRICS: Record<Track, string[]> = {
  commercial: ["irr_pct", "cap_rate_pct", "dscr", "coc_pct", "equity_multiple"],
  residential: ["coc_pct", "cap_rate_pct", "dscr", "annual_cash_flow", "score"],
  institutional: ["irr_pct", "unlevered_irr_pct", "cap_rate_pct", "dscr", "debt_yield_pct"],
};

export const STAGES: [string, string][] = [
  ["sourcing", T("发现")], ["screening", T("初筛")], ["underwriting", T("承销")], ["committee", T("投委会")],
  ["diligence", T("尽调")], ["closing", T("交割")], ["holding", T("持有")],
];
export const STAGE_LABEL: Record<string, string> = Object.fromEntries([...STAGES, ["passed", T("已放弃")]]);
