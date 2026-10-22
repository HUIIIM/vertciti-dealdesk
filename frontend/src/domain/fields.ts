// 两条赛道的表单字段（路径、标签、单位、说明）。路径与后端输入结构一致，护照（来源）按同一路径登记。
import { T } from "@/i18n";
import type { Unit } from "@/lib/format";
import type { JsonObj } from "@/lib/paths";

export type Track = "residential" | "commercial";
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
  const base = track === "commercial" ? blankCommercial(name, address) : blankResidential();
  if (price && price > 0) {
    if (track === "commercial") (base.analysis as JsonObj).purchase_price = price;
    else base.price = price;
  }
  return base;
}

/** 输入路径 → 中文标签（数字护照、矛盾登记、版本对比里不露内部字段名）。 */
const LABELS: Record<string, string> = Object.fromEntries([
  ...[...COM_ANALYSIS, ...COM_PROPERTY, ...RES_DEAL, ...RES_INCOME, ...RES_EXPENSES, ...RES_EXIT].map((f) => [f.path, f.label]),
  ...[...COM_INCOME, ...COM_EXPENSES, ...COM_BELOW_LINE].flatMap(([k, l]) => [[`proforma.${k}`, T("{0}（预测）", [l])], [`historical.${k}`, T("{0}（历史）", [l])]]),
  ["proforma.vacancy_pct", T("空置率（预测）")], ["historical.vacancy_pct", T("空置率（历史）")],
  ["tenants.*.monthly_rent", T("租金水平（各租户月租）")], ["tenants.*.underwritten_annual", T("租金水平（承销年租）")],
]);
export function fieldLabel(path: string): string {
  if (LABELS[path]) return LABELS[path]!;
  const m = /^tenants\.(\d+)\.(\w+)$/.exec(path);
  if (m) return T("第 {0} 户 · {1}", [Number(m[1]) + 1, { monthly_rent: T("月租"), sf: T("面积"), tenant: T("租户"), suite: T("单元"), underwritten_annual: T("承销年租") }[m[2]!] ?? m[2]]);
  return path;
}

/** 卡片 / 结论卡要展示的指标（按赛道）。 */
export const CARD_METRICS: Record<Track, string[]> = {
  commercial: ["irr_pct", "cap_rate_pct", "dscr", "coc_pct", "equity_multiple"],
  residential: ["coc_pct", "cap_rate_pct", "dscr", "annual_cash_flow", "score"],
};

export const STAGES: [string, string][] = [
  ["sourcing", T("发现")], ["screening", T("初筛")], ["underwriting", T("承销")], ["committee", T("投委会")],
  ["diligence", T("尽调")], ["closing", T("交割")], ["holding", T("持有")],
];
export const STAGE_LABEL: Record<string, string> = Object.fromEntries([...STAGES, ["passed", T("已放弃")]]);
