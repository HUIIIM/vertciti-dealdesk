/* DealDesk v2 · 专业核保仪表盘
   层级铁律：L0 结论 hero → L1 分区 → L2 KPI → L3 数据 → L4 元信息（折叠）
   只做加法：评分引擎 / DB / API 契约零改动。新增仅前端 intake 编排（复用 /api/wb/intake/run）。 */
const state = {
  view: 'dashboard', track: 'residential', projects: [],
  editingId: null, detail: null, detailTab: 'overview', compareIds: [],
  sortKey: 'cash_to_close', sortDir: 1, query: '',
  intake: null, // {stage, steps, result, error, draftInput, draftSources, track}
  _fill: null,
};

const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = x => x == null || isNaN(x) ? '—' : '$' + Number(x).toLocaleString('en-US', {maximumFractionDigits: 0});
const moneyS = x => x == null || isNaN(x) ? '—' : (x < 0 ? '-' : '') + '$' + Math.abs(Number(x)).toLocaleString('en-US', {maximumFractionDigits: 0});
const pct1 = x => x == null || isNaN(x) ? '—' : (Number(x) * 100).toFixed(1) + '%';
const num2 = x => x == null || isNaN(x) ? '—' : Number(x).toFixed(2);
const numOpts = n => Array.from({length: n + 1}, (_, i) => [i, String(i)]);
function ago(ts) {
  const s = Math.max(0, (Date.now() / 1000 - ts));
  if (s < 3600) return Math.floor(s / 60) + ' 分钟前';
  if (s < 86400) return Math.floor(s / 3600) + ' 小时前';
  return Math.floor(s / 86400) + ' 天前';
}

async function api(method, path, body, timeoutMs) {
  const ctl = new AbortController();
  const t = timeoutMs ? setTimeout(() => ctl.abort(), timeoutMs) : null;
  try {
    const r = await fetch(path, {method, headers: {'Content-Type': 'application/json'},
      body: body ? JSON.stringify(body) : undefined, signal: ctl.signal});
    if (!r.ok) {
      const txt = await r.text();
      try { const j = JSON.parse(txt); throw new Error(j.detail || txt || r.statusText); }
      catch (e) { if (e.message && e.message !== txt) throw e; throw new Error(txt || r.statusText); }
    }
    return r.json();
  } finally { if (t) clearTimeout(t); }
}

/* ================= 字段 Schema（与旧版一致，口径零改动） ================= */
const RES_SECTIONS = [
  {title: '基本信息', fields: [
    {key: 'name', label: '项目名称', type: 'text', def: ''},
    {key: 'address', label: '地址', type: 'text', def: ''},
    {key: 'structure', label: '交易结构', type: 'select', def: 'subject_to', options: [
      ['subject_to', 'Subject-to（首选）'], ['seller_financing', 'Seller financing'],
      ['loan_assumption', 'Loan assumption（正式承接）'], ['lease_option', 'Lease option（租购）'],
      ['novation', 'Novation'], ['wholesale', '折价批发/转合同']]},
    {key: 'price', label: '收购价 $', type: 'number', def: ''},
    {key: 'units', label: '单元数', type: 'number', def: 1},
  ]},
  {title: '交易结构与贷款', fields: [
    {key: 'down_payment', label: '首付 $', type: 'number', def: 0},
    {key: 'loan_balance', label: '承接贷款余额 $', type: 'number', def: 0},
    {key: 'rate', label: '年利率 %', type: 'number', def: 0, hint: '百分制，如 3.5；只做固定利率'},
    {key: 'rate_type', label: '利率类型', type: 'select', def: 'fixed',
      options: [['fixed', '固定利率'], ['floating', '浮动/可调（否决）']]},
    {key: 'term_years_remaining', label: '剩余年限', type: 'number', def: 30},
    {key: 'balloon_years', label: 'Balloon 年限（无则留空）', type: 'number', def: '', optional: true, hint: '5 年内到期 = 一票否决'},
    {key: 'is_assumption', label: '银行正式承接（无 due-on-sale 风险，加分）', type: 'check', def: false},
    {key: 'other_liens', label: '其他留置/欠费 $', type: 'number', def: 0},
  ]},
  {title: '租金与费用（保守全口径）', fields: [
    {key: 'monthly_rent', label: '月租金 $', type: 'number', def: ''},
    {key: 'other_income_monthly', label: '其他月收入 $', type: 'number', def: 0},
    {key: 'rent_source', label: '租金依据', type: 'select', def: 'estimated', options: [
      ['comps_verified', '实测 comps'], ['estimated', '估算（未核实不进 A 级）'], ['proforma', 'pro-forma（否决）']]},
    {key: 'taxes_annual', label: '年房产税 $', type: 'number', def: 0},
    {key: 'insurance_annual', label: '年保险 $', type: 'number', def: 0},
    {key: 'hoa_monthly', label: '月 HOA $', type: 'number', def: 0},
    {key: 'utilities_owner_monthly', label: '业主承担水电/月 $', type: 'number', def: 0},
    {key: 'vacancy_pct', label: '空置率 %', type: 'number', def: 8},
    {key: 'maint_pct', label: '维修 %（按租金）', type: 'number', def: 8},
    {key: 'capex_pct', label: 'CapEx %（按租金）', type: 'number', def: 8},
    {key: 'mgmt_pct', label: '管理费 %（按实收租金）', type: 'number', def: 10},
    {key: 'closing_costs', label: '交割费用 $', type: 'number', def: 0},
    {key: 'initial_repairs', label: '初期维修 $', type: 'number', def: 0},
  ]},
  {title: '合规与退出预案', fields: [
    {key: 'seller_delinquent_days', label: '卖方贷款逾期天数', type: 'number', def: 0},
    {key: 'has_discount_hedge', label: '有深度折价对冲', type: 'check', def: false},
    {key: 'insurance_available', label: '有保险路径', type: 'check', def: true},
    {key: 'seller_signed_auth_release', label: '卖方已签 authorization to release', type: 'check', def: false},
    {key: 'hoa_arrears_severe', label: 'HOA 巨额欠费', type: 'check', def: false},
    {key: 'title_defect', label: 'Title 硬伤', type: 'check', def: false},
    {key: 'fraud_flag', label: '涉及虚假陈述/欺诈', type: 'check', def: false},
    {key: 'exit_primary', label: '主退出路径', type: 'text', def: ''},
    {key: 'exit_backup', label: '备选退出路径', type: 'text', def: ''},
    {key: 'due_on_sale_plan', label: 'Due-on-sale 备用预案（subject-to 必填）', type: 'text', def: ''},
    {key: 'reserves_months_piti', label: '储备金（几个月 PITI）', type: 'number', def: 0, hint: '硬性要求 ≥6 个月'},
  ]},
  {title: '风险旗（每 1 个实质风险旗扣 3 分）', fields: [
    {key: 'rural', label: '偏远 / rural 市场', type: 'check', flag: true},
    {key: 'insurance_volatile', label: '保险市场动荡州', type: 'check', flag: true},
    {key: 'high_property_tax', label: '房产税异常高且无对冲', type: 'check', flag: true},
    {key: 'old_property', label: '房龄 >40 年', type: 'check', flag: true},
    {key: 'flood_zone', label: '洪水区 / 灾害高风险区', type: 'check', flag: true},
    {key: 'hoa_litigation', label: 'HOA 纠纷/诉讼中', type: 'check', flag: true},
    {key: 'thin_market', label: '市场流动性薄', type: 'check', flag: true},
  ]},
  {title: '市场打分（未评估 = 0，不编造）', fields: [
    {key: 'market_pop', label: '人口流入 0-4', type: 'select', numeric: true, def: 0, options: numOpts(4)},
    {key: 'market_employment', label: '就业增长 0-4', type: 'select', numeric: true, def: 0, options: numOpts(4)},
    {key: 'market_inventory', label: '库存 / DOM 0-4', type: 'select', numeric: true, def: 0, options: numOpts(4)},
    {key: 'market_appreciation', label: '历史增值 0-3', type: 'select', numeric: true, def: 0, options: numOpts(3)},
  ]},
];

const COM_SECTIONS = [
  {title: '基本信息', fields: [
    {key: 'name', label: '项目名称', type: 'text', def: ''},
    {key: 'address', label: '地址', type: 'text', def: ''},
    {key: 'asset_class', label: '资产类别', type: 'select', def: 'retail_strip', options: [
      ['small_bay_industrial', 'Small-bay industrial'], ['retail_strip', 'Retail strip'],
      ['mixed_use', 'Mixed-use'], ['small_multifamily_5plus', 'Small multifamily 5+'],
      ['office', 'Office（办公，v1.1 纳入）'], ['hotel', 'Hotel（酒店，v1.1 纳入）'],
      ['other', '其他（范围外）']]},
    {key: 'structure', label: '交易结构', type: 'select', def: 'seller_financing', options: [
      ['seller_financing', 'Seller financing（首选）'], ['master_lease', 'Master lease / lease-option'],
      ['subject_to', 'Subject-to'], ['loan_assumption', 'Loan assumption'], ['seller_carryback_2nd', 'Seller carryback 二顺位']]},
    {key: 'price', label: '成交价 $', type: 'number', def: ''},
    {key: 'closing_costs', label: '交割费用 $', type: 'number', def: 0},
    {key: 'capex_y1', label: '首年必须投的 CapEx $', type: 'number', def: 0},
    {key: 'down_payment', label: '现金首付 $', type: 'number', def: 0, hint: '硬上限 20%，谈判目标 ≤10%'},
    {key: 'building_sf', label: '建筑面积 SF', type: 'number', def: 0},
    {key: 'units', label: '单元数（multifamily 用）', type: 'number', def: 0},
  ]},
  {title: '贷款结构（最多两档，只做固定利率）', fields: [
    {key: 't1_balance', label: '一顺位余额 $', type: 'number', def: 0},
    {key: 't1_rate', label: '一顺位年利率 %', type: 'number', def: 0},
    {key: 't1_rate_type', label: '一顺位利率类型', type: 'select', def: 'fixed',
      options: [['fixed', '固定'], ['floating', '浮动（否决）']]},
    {key: 't1_term', label: '一顺位剩余年限', type: 'number', def: 30},
    {key: 't1_balloon', label: '一顺位 balloon 年限（无则空）', type: 'number', def: '', optional: true},
    {key: 't2_balance', label: '二顺位余额 $（无则 0）', type: 'number', def: 0},
    {key: 't2_rate', label: '二顺位年利率 %', type: 'number', def: 0},
    {key: 't2_rate_type', label: '二顺位利率类型', type: 'select', def: 'fixed',
      options: [['fixed', '固定'], ['floating', '浮动（否决）']]},
    {key: 't2_term', label: '二顺位剩余年限', type: 'number', def: 30},
    {key: 't2_balloon', label: '二顺位 balloon 年限（无则空）', type: 'number', def: '', optional: true},
  ]},
  {title: '租金与 NOI（保守重算口径）', fields: [
    {key: 'annual_base_rent', label: '年合同租金 $', type: 'number', def: ''},
    {key: 'other_income_annual', label: '其他年收入 $', type: 'number', def: 0},
    {key: 'other_income_verified', label: '其他收入有实证', type: 'check', def: false},
    {key: 'vacancy_pct', label: '空置/坏账率 %', type: 'number', def: 8, hint: 'industrial 5 / retail 8 / office ≥12（引擎强制下限）/ 酒店不适用'},
    {key: 'tax_annual', label: '年房产税 $（按税单）', type: 'number', def: 0, hint: '系统自动 +10% 重估风险'},
    {key: 'insurance_annual', label: '年保险 $', type: 'number', def: 0},
    {key: 'mgmt_pct', label: '管理费 %（≥8% EGI）', type: 'number', def: 8},
    {key: 'maint_pct', label: '维修 %（≥5% EGI）', type: 'number', def: 5},
    {key: 'property_age_years', label: '房龄（年）', type: 'number', def: 0, hint: '>20 年维修按 7%'},
    {key: 'utilities_cam_gap_annual', label: '业主承担水电/CAM 缺口 $/年', type: 'number', def: 0},
    {key: 'ti_lc_annual_amort', label: 'TI/LC 年摊销 $', type: 'number', def: 0},
    {key: 'market_cap_rate_pct', label: '市场 cap rate %', type: 'number', def: 0, hint: '同类资产近12个月成交倒推'},
    {key: 'market_cap_source', label: '市场 cap 来源', type: 'text', def: ''},
    {key: 'noi_evidence', label: 'NOI 依据', type: 'select', def: 'rent_roll',
      options: [['rent_roll', 'rent roll + 租约摘要'], ['proforma', '卖方 pro-forma（否决）']]},
    {key: 'as_is_appraisal', label: 'As-is 评估值 $', type: 'number', def: 0, hint: '成交价高于此值 = 负净值否决'},
  ]},
  {title: '租约结构', fields: [
    {key: 'walt_years', label: 'WALT（年）', type: 'number', def: 0, hint: '要求 ≥3 年，A 级 ≥5 年'},
    {key: 'all_nnn', label: '全 NNN 租约', type: 'check', def: false},
    {key: 'concentration_12mo_pct', label: '12 个月内到期租金占比 %', type: 'number', def: 0, hint: '要求 ≤30%'},
    {key: 'tenant_quality_ok', label: '租户信用/分散度达标', type: 'check', def: false},
    {key: 'escalations_ok', label: '有租金递增条款（≥2%/年或挂钩 CPI）', type: 'check', def: false},
  ]},
  {title: '办公专项（office 资产必填，v1.1）', fields: [
    {key: 'occupancy_pct', label: '在租率 %', type: 'number', def: 0, hint: '要求 ≥80%（按可租面积）；低于 80% 不看'},
    {key: 'ti_lc_itemized', label: 'TI/LC 已逐项核算', type: 'check', def: false, hint: '未逐项 = 自动风险旗'},
  ]},
  {title: '酒店专项（hotel 资产必填，v1.1）', fields: [
    {key: 'hotel_revenue_annual', label: '年总营收 $（保守 RevPAR 口径）', type: 'number', def: 0,
      hint: 'RevPAR 取 trailing 12 个月与过去 3 年平均孰低 × 房间数 × 365'},
    {key: 'revpar_source', label: 'RevPAR 依据', type: 'select', def: 'verified_conservative', options: [
      ['verified_conservative', '已按孰低取值（验证）'], ['proforma', '卖方 pro-forma（否决）']]},
    {key: 'hotel_opex_annual', label: '酒店年部门/固定费用 $', type: 'number', def: 0,
      hint: '按经营 P&L 填（不含管理费/FF&E）；留空 = 风险旗（NOI 可能高估）'},
    {key: 'hotel_mgmt_pct', label: '管理费 %（≥5% 营收）', type: 'number', def: 5},
    {key: 'hotel_ff_e_pct', label: 'FF&E reserve %（≥4% 营收）', type: 'number', def: 4},
    {key: 'has_operating_history', label: '有稳定经营记录', type: 'check', def: true,
      hint: '无记录的新建/烂尾酒店 = 不收录'},
    {key: 'pip_capex', label: '品牌 PIP capex $', type: 'number', def: 0, hint: '全额计入收购成本与现金需求'},
    {key: 'franchise_term_ok', label: '特许经营协议 ≥10 年或有续期权', type: 'check', def: true},
    {key: 'low_season_covers_ds', label: '淡季月份现金流覆盖当月 debt service', type: 'check', def: false,
      hint: '未通过 = 不能进 A 级'},
  ]},
  {title: '合规与退出预案', fields: [
    {key: 'phase1_clear', label: 'Phase I 环境无未解决红旗', type: 'check', def: true},
    {key: 'zoning_ok', label: 'Zoning 合规（或有 variance 路径）', type: 'check', def: true},
    {key: 'ti_lc_unfunded_over_12mo', label: '单租约 TI/LC 超 12 个月租金且无资金覆盖', type: 'check', def: false},
    {key: 'seller_signed_auth_release', label: '卖方已签 authorization to release', type: 'check', def: false},
    {key: 'fraud_flag', label: '涉及虚假陈述/欺诈', type: 'check', def: false},
    {key: 'exit_primary', label: '主退出路径', type: 'select', def: 'hold', options: [
      ['hold', '长期持有收租'], ['refi', '价值修复后 refi'], ['sale', '到期出售（非短期抛售）'], ['other', '其他']]},
    {key: 'exit_backup', label: '备选退出路径', type: 'text', def: ''},
    {key: 'exit_flip_dependent_only', label: '退出依赖高价抛售', type: 'check', def: false,
      hint: '勾选 = 退出含抛售成分 → 挂风险旗呈报（v1.3 起不再一票否决；仅 refi/持有皆不成立时否决）'},
    {key: 'refi_cashout_viable', label: 'Refi 路径能独立算通（refi 后能拿出钱）', type: 'check', def: false,
      hint: '勾选后，含抛售成分的退出路径可接受，不否决'},
    {key: 'buyer_pool_evidence', label: '买家池证据', type: 'text', def: ''},
    {key: 'reserves_months_ds', label: '储备金（几个月 debt service）', type: 'number', def: 0, hint: '要求 ≥6 个月；value-add ≥12 个月'},
    {key: 'is_value_add_vacant', label: 'Value-add / 带空置资产', type: 'check', def: false},
    {key: 'pre_lease_pct', label: '预租率 %（value-add 进 A 级要求 ≥70%）', type: 'number', def: 0},
  ]},
  {title: '风险旗（每 1 个实质风险旗扣 3 分）', fields: [
    {key: 'insurance_unavailable', label: '保险买不到/暴涨的市场', type: 'check', flag: true},
    {key: 'tax_reassessment', label: '房产税重估激进的县', type: 'check', flag: true},
    {key: 'single_industry', label: '单一产业依赖度过高', type: 'check', flag: true},
    {key: 'weak_tenant_mix', label: '弱租户占比 >30%', type: 'check', flag: true},
    {key: 'no_escalation', label: '无递增条款租约占比 >50%', type: 'check', flag: true},
    {key: 'gross_no_hedge', label: '纯 gross 租约无费用对冲', type: 'check', flag: true},
    {key: 'high_ti_lc', label: 'TI/LC 敞口偏高', type: 'check', flag: true},
    {key: 'env_watch', label: '环境需持续监测项', type: 'check', flag: true},
    {key: 'refi_risk', label: '退出 refi 可行性存疑', type: 'check', flag: true},
  ]},
  {title: '市场打分（未评估 = 0，不编造）', fields: [
    {key: 'market_pop_employment', label: '人口/就业流入 0-3', type: 'select', numeric: true, def: 0, options: numOpts(3)},
    {key: 'market_vacancy_trend', label: '类别空置趋势 0-3', type: 'select', numeric: true, def: 0, options: numOpts(3)},
    {key: 'market_rent_trend', label: '租金走势 0-2', type: 'select', numeric: true, def: 0, options: numOpts(2)},
    {key: 'market_landlord_friendly', label: '房东友好度 0-2', type: 'select', numeric: true, def: 0, options: numOpts(2)},
  ]},
];

/* ================= 测算指标定义 ================= */
const RES_METRICS = [
  ['月供 P&I', 'monthly_pi', 'money'], ['月 PITI', 'piti', 'money'],
  ['月净现金流', 'cash_flow_monthly', 'moneysigned', 1], ['单门现金流', 'cash_flow_per_door', 'moneysigned'],
  ['Cash-on-cash', 'cash_on_cash', 'pct'], ['DSCR', 'dscr', 'num'],
  ['Cap rate', 'cap_rate', 'pct'], ['现金总投入', 'cash_invested', 'money'],
  ['全口径现金需求 cash-to-close', 'cash_to_close', 'money', 1], ['交割净值', 'equity', 'moneysigned'],
];
const COM_METRICS = [
  ['年 NOI', 'noi', 'money', 1], ['入场 cap', 'entry_cap', 'pct'],
  ['Spread', 'spread_bps', 'bps'], ['DSCR', 'dscr', 'num'],
  ['月净现金流', 'net_cf_monthly', 'moneysigned', 1], ['Cash-on-cash', 'cash_on_cash', 'pct'],
  ['年还本付息', 'annual_debt_service', 'money'], ['现金总投入', 'cash_invested', 'money'],
  ['全口径现金需求 cash-to-close', 'cash_to_close', 'money', 1], ['交割净值', 'equity', 'moneysigned'],
];
function fmtVal(kind, x) {
  if (x == null || (typeof x === 'number' && isNaN(x))) return '<span class="muted">—</span>';
  if (kind === 'money') return money(x);
  if (kind === 'moneysigned') {
    const cls = x < 0 ? 'neg' : (x > 0 ? 'pos' : '');
    return `<span class="${cls}">${moneyS(x)}</span>`;
  }
  if (kind === 'pct') return pct1(x);
  if (kind === 'bps') return Math.round(x) + '<small>bps</small>';
  return num2(x);
}

/* 评分展示：结论行 + 折叠明细（progressive disclosure） */
function scoreHtml(s, track) {
  const defs = track === 'residential' ? RES_METRICS : COM_METRICS;
  const veto = s.vetoes.length
    ? `<div class="veto-banner bad"><b>✕ 一票否决（${s.vetoes.length} 项）</b><ul>` +
      s.vetoes.map(v => `<li>${esc(v.message)}</li>`).join('') + '</ul></div>'
    : `<div class="veto-banner good"><b>✓ 无否决项</b><span class="muted"> —— 进入分级流程</span></div>`;
  const dg = (s.downgrades || []).length
    ? `<div class="veto-banner warn"><b>▲ 降级提示（封顶降级，非一票否决）</b><ul>` +
      s.downgrades.map(v => `<li>${esc(v.message)}</li>`).join('') + '</ul></div>' : '';
  const metrics = defs.map(([label, key, kind, hero]) =>
    `<div class="metric${hero ? ' hero' : ''}"><div class="k">${label}</div><div class="v">${fmtVal(kind, s.metrics[key])}</div></div>`).join('');
  const dims = s.dimensions.map(dm => `
    <details class="dim"><summary>
      <span class="dl">${esc(dm.label)}</span>
      <span class="bar"><div style="width:${Math.min(100, dm.points / dm.weight * 100)}%"></div></span>
      <span class="dp num">${dm.points} / ${dm.weight}</span><span class="chev">▾</span>
    </summary><div class="dd">${esc(dm.detail)}</div></details>`).join('');
  const checks = s.checks.map(c =>
    `<tr><td>${c.ok ? '<span class="st ok">通过</span>' : '<span class="st bad">不通过</span>'} ${esc(c.label)}</td><td class="muted">${esc(c.note)}</td></tr>`).join('');
  return `${veto}${dg}
    <h3 class="sec-t" style="margin-top:18px">测算结果 <span class="micro">保守全口径</span></h3><div class="metrics">${metrics}</div>
    <h3 class="sec-t" style="margin-top:18px">评分明细 <span class="micro">点击展开依据</span></h3>${dims}
    <h3 class="sec-t" style="margin-top:18px">阈值对照</h3>
    <div class="tbl-wrap"><table class="data"><thead><tr><th>检查项</th><th>说明</th></tr></thead><tbody>${checks}</tbody></table></div>`;
}

function sensHtml(sens, track) {
  const rentCols = track === 'residential'
    ? [['cash_flow_monthly', '月净现金流', 'moneysigned'], ['cash_flow_per_door', '单门现金流', 'moneysigned'],
       ['cash_on_cash_pct', 'CoC %', 'rawpct'], ['dscr', 'DSCR', 'num']]
    : [['net_cf_monthly', '月净现金流', 'moneysigned'], ['cash_on_cash_pct', 'CoC %', 'rawpct'],
       ['dscr', 'DSCR', 'num'], ['entry_cap_pct', '入场 cap %', 'rawpct']];
  const rateCols = track === 'residential'
    ? [['cash_flow_monthly', '月净现金流', 'moneysigned'], ['cash_on_cash_pct', 'CoC %', 'rawpct'], ['dscr', 'DSCR', 'num']]
    : [['net_cf_monthly', '月净现金流', 'moneysigned'], ['cash_on_cash_pct', 'CoC %', 'rawpct'], ['dscr', 'DSCR', 'num']];
  const cell = (kind, v) => {
    if (v == null) return '<span class="muted">—</span>';
    if (kind === 'moneysigned') { const cls = v < 0 ? 'neg' : 'pos'; return `<span class="${cls} num">${moneyS(v)}</span>`; }
    if (kind === 'rawpct') return `<span class="num">${Number(v).toFixed(1)}%</span>`;
    return `<span class="num">${num2(v)}</span>`;
  };
  const table = (title, rows, cols) => `
    <h3 class="sec-t" style="margin-top:16px">${title}</h3>
    <div class="tbl-wrap"><table class="data"><thead><tr><th>情景</th>${cols.map(c => `<th class="num">${c[1]}</th>`).join('')}</tr></thead>
    <tbody>${rows.map(r => `<tr class="${r.label === '+0%' ? 'base' : ''}"><td><b>${r.label}</b></td>` +
      cols.map(c => `<td class="num">${cell(c[2], r[c[0]])}</td>`).join('') + '</tr>').join('')}</tbody></table></div>`;
  return `<p class="micro" style="margin:4px 0 0">五情景压力测试：租金 ±10% / 利率 ±2%，基准行高亮。结论先看现金流是否转负、DSCR 是否跌破 1.0。</p>`
    + table('租金变动情景（±10%）', sens.rent_table, rentCols)
    + table('利率变动情景（±2%）', sens.rate_table, rateCols);
}

/* 可信度芯片 */
function confChip(f) {
  if (f.status === 'manual_needed') return '<span class="conf manual">需手动补</span>';
  if (f.seller_claimed) return '<span class="conf seller">卖方口径·待验证</span>';
  const c = f.confidence;
  if (c === '高') return '<span class="conf high">高·已验证</span>';
  if (c === '中') return '<span class="conf mid">中·平台数据</span>';
  return '<span class="conf low">低·估算</span>';
}

/* ================= 视图路由 ================= */
function render() {
  document.querySelectorAll('#nav button').forEach(b => b.classList.toggle('on', b.dataset.view === state.view));
  $('#cmpCount').textContent = state.compareIds.length ? state.compareIds.length + '/3' : '';
  const app = $('#app');
  if (state.view === 'dashboard') renderDashboard(app);
  else if (state.view === 'intake') renderIntake(app);
  else if (state.view === 'form') renderForm(app);
  else if (state.view === 'detail') renderDetail(app);
  else if (state.view === 'compare') renderCompare(app);
  window.scrollTo(0, 0);
}

async function loadProjects() {
  state.projects = await api('GET', '/api/projects');
  refreshDemoBanner();
}
/* 演示数据横幅：仅当存在含"演示"的项目时展示 */
function refreshDemoBanner() {
  var b = document.getElementById('demoBanner');
  if (!b) return;
  var hasDemo = (state.projects || []).some(p => (p.name || '').indexOf('演示') >= 0);
  var dismissed = false;
  try { dismissed = localStorage.getItem('dd_demo_dismissed') === '1'; } catch (e) {}
  b.hidden = !(hasDemo && !dismissed);
}

/* ================= 仪表盘 ================= */
function kpiData() {
  const ps = state.projects;
  const a = ps.filter(p => p.score.grade === 'A').length;
  const veto = ps.filter(p => p.score.grade === '否决' || (p.score.vetoes || []).length > 0).length;
  const avg = ps.length ? ps.reduce((s, p) => s + (p.score.total || 0), 0) / ps.length : null;
  const cash = ps.reduce((s, p) => s + (p.cash_to_close || 0), 0);
  return {n: ps.length, a, veto, avg, cash};
}

function insightHtml() {
  const k = kpiData();
  if (!k.n) return `<div class="insight idle"><div class="ic">○</div><div>
    <div class="t">管线还是空的——你的第一条 deal 在哪？</div>
    <div class="d">在顶部粘贴一条房源链接（Zillow / Redfin / LoopNet / Realtor），一键搜集，剩下的交给 DealDesk。</div></div>
    <div class="act"><button class="btn primary" data-act="focusIntake">去搜集第一条</button></div></div>`;
  if (k.veto) {
    const names = state.projects.filter(p => p.score.grade === '否决' || (p.score.vetoes || []).length)
      .slice(0, 3).map(p => esc(p.name || p.address || ('#' + p.id))).join('、');
    return `<div class="insight bad"><div class="ic">✕</div><div>
    <div class="t">${k.veto} 个项目触发一票否决${k.a ? `，但有 ${k.a} 个 A 级项目可推进` : '，还没有 A 级项目'}</div>
    <div class="d">否决：${names}${k.veto > 3 ? ` 等 ${k.veto} 个` : ''}。否决项在详情页逐条列出，先处理否决再谈分级。</div></div></div>`;
  }
  if (k.a) return `<div class="insight good"><div class="ic">◈</div><div>
    <div class="t">${k.a} 个 A 级项目在管线中，总全口径现金需求 ${money(k.cash)}</div>
    <div class="d">按 cash-to-close 升序排列，先看最便宜的——资金有限，贵的不先谈。</div></div></div>`;
  const b = state.projects.filter(p => p.score.grade === 'B').length;
  return `<div class="insight warn"><div class="ic">◈</div><div>
    <div class="t">还没有 A 级项目，${b} 个 B 级在观察</div>
    <div class="d">B 级进日报收录，C 级只进观察名单。点进详情看看，差的那几分能不能谈回来。</div></div></div>`;
}

function sortVal(p, key) {
  const m = p.score.metrics || {};
  switch (key) {
    case 'score': return p.score.total ?? -1;
    case 'cf': return state.track === 'residential' ? (m.cash_flow_monthly ?? -1e18) : (m.net_cf_monthly ?? -1e18);
    case 'dscr': return m.dscr ?? -1e18;
    case 'coc': return m.cash_on_cash ?? -1e18;
    case 'cash_to_close': return p.cash_to_close ?? 1e18;
    case 'updated': return p.updated_at ?? 0;
    default: return 0;
  }
}

function pipelineRows() {
  let ps = state.projects.filter(p => p.track === state.track);
  const q = state.query.trim().toLowerCase();
  if (q) ps = ps.filter(p => (p.name + ' ' + p.address).toLowerCase().includes(q));
  ps = ps.slice().sort((a, b) => (sortVal(a, state.sortKey) - sortVal(b, state.sortKey)) * state.sortDir);
  return ps;
}

function renderDashboard(app) {
  const k = kpiData();
  const rows = pipelineRows();
  const th = (label, key, num) => {
    const arrow = state.sortKey === key ? (state.sortDir === 1 ? ' ▲' : ' ▼') : '';
    return `<th class="sortable${num ? ' num' : ''}" data-sort="${key}">${label}${arrow}</th>`;
  };
  const body = rows.map(p => {
    const s = p.score, m = s.metrics || {};
    const cf = state.track === 'residential' ? m.cash_flow_monthly : m.net_cf_monthly;
    const cfCls = cf == null ? '' : (cf < 0 ? 'neg' : 'pos');
    const vetoN = (s.vetoes || []).length;
    return `<tr class="rowlink" data-open="${p.id}">
      <td><b>${esc(p.name) || '(未命名)'}</b><div class="micro">${esc(p.address)}</div></td>
      <td><span class="badge ${esc(s.grade)}">${esc(s.grade)}</span></td>
      <td class="num"><b>${s.total}</b><span class="micro">/100</span></td>
      <td class="num ${cfCls}"><b>${moneyS(cf)}</b></td>
      <td class="num">${num2(m.dscr)}</td>
      <td class="num">${pct1(m.cash_on_cash)}</td>
      <td class="num"><b>${money(p.cash_to_close)}</b></td>
      <td>${vetoN ? `<span class="st bad">${vetoN} 项否决</span>` : '<span class="st ok">无</span>'}</td>
      <td class="micro" style="white-space:nowrap">${ago(p.updated_at)}</td>
      <td style="white-space:nowrap" onclick="event.stopPropagation()">
        <button class="btn sm" data-act="report" data-id="${p.id}">报告</button>
        <label class="micro" style="margin-left:6px"><input type="checkbox" data-cmp="${p.id}"
          ${state.compareIds.includes(p.id) ? 'checked' : ''}> 对比</label>
      </td></tr>`;
  }).join('');
  const feedItems = state.projects.slice()
    .sort((a, b) => b.updated_at - a.updated_at).slice(0, 8).map(p => {
      const isNew = Math.abs(p.updated_at - p.created_at) < 5;
      const dot = p.score.grade === 'A' ? 'var(--green)' : (p.score.grade === '否决' ? 'var(--red)' : 'var(--blue)');
      return `<li><span class="fdot" style="background:${dot}"></span><div>
        <div>${isNew ? '新建' : '更新'} <b>${esc(p.name || p.address || ('#' + p.id))}</b>
        <span class="badge ${esc(p.score.grade)}" style="font-size:11px;min-width:22px;padding:0 6px">${esc(p.score.grade)}</span></div>
        <div class="fx">${p.score.total} 分 · cash-to-close ${money(p.cash_to_close)}</div></div>
        <span class="ft">${ago(p.updated_at)}</span></li>`;
    }).join('');
  app.innerHTML = `
    <div class="zone">${insightHtml()}</div>
    <div class="zone"><div class="kpis">
      <div class="kpi" style="--kc:var(--brand)"><div class="k">在管项目</div><div class="v num">${k.n}</div><div class="s">住宅 / 商业双轨</div></div>
      <div class="kpi" style="--kc:var(--green)"><div class="k">A 级项目</div><div class="v num" style="color:var(--green)">${k.a}</div><div class="s">≥80 分 · 日报头条</div></div>
      <div class="kpi" style="--kc:var(--blue)"><div class="k">平均分</div><div class="v num">${k.avg == null ? '—' : k.avg.toFixed(1)}<small>/100</small></div><div class="s">全管线加权口径一致</div></div>
      <div class="kpi" style="--kc:#f79009"><div class="k">总 cash-to-close</div><div class="v num">${money(k.cash)}</div><div class="s">全口径现金需求合计</div></div>
      <div class="kpi" style="--kc:var(--red)"><div class="k">一票否决</div><div class="v num" style="color:${k.veto ? 'var(--red)' : 'inherit'}">${k.veto}</div><div class="s">任一硬否决 = 否决</div></div>
    </div></div>
    <div class="zone cols">
      <div class="panel">
        <div class="panel-h"><h2>交易管线</h2><span class="micro">${rows.length} 个项目</span>
          <div class="tbl-tools">
            <div class="seg" id="trackSeg">
              <button data-track="residential" class="${state.track === 'residential' ? 'on' : ''}">住宅</button>
              <button data-track="commercial" class="${state.track === 'commercial' ? 'on' : ''}">商业</button>
            </div>
            <input type="search" id="q" placeholder="搜索项目 / 地址…" value="${esc(state.query)}">
            <button class="btn sm primary" data-act="new">＋ 新建</button>
          </div></div>
        <div class="panel-b tbl-wrap">
          ${rows.length ? `<table class="data"><thead><tr>
            <th>项目</th>${th('等级', 'score')}${th('总分', 'score', 1)}${th('月净现金流', 'cf', 1)}
            ${th('DSCR', 'dscr', 1)}${th('CoC', 'coc', 1)}${th('cash-to-close', 'cash_to_close', 1)}
            <th>否决</th>${th('更新', 'updated')}<th>操作</th>
          </tr></thead><tbody>${body}</tbody></table>`
          : `<div class="empty"><div class="big">○</div>这个赛道还没有项目<br><span class="micro">粘贴一条房源链接一键搜集，或点右上角「＋ 新建」手动录入——三分钟就能看到第一份打分</span></div>`}
        </div>
      </div>
      <div class="rail">
        <div class="panel"><div class="panel-h"><h2>实时动态</h2><span class="micro">本地记录</span></div>
          <ul class="feed">${feedItems || '<li><span class="muted">暂无动态</span></li>'}</ul></div>
        <div class="panel"><div class="panel-h"><h2>数据源</h2></div><div id="srcPanel">
          <div class="src-row"><span>TopHap 公共记录</span><span class="micro">检测中…</span></div>
          <div class="src-row"><span>全网公开页面搜集</span><span class="st ok">可用</span></div>
          <div class="src-row"><span>PDF / 截图 intake</span><span class="st ok">可用</span></div>
        </div></div>
      </div>
    </div>`;
  const q = $('#q');
  q.addEventListener('input', () => { state.query = q.value; renderDashboard(app); $('#q').focus();
    const el = $('#q'); el.setSelectionRange(el.value.length, el.value.length); });
}

/* ================= 智能搜集（Hero） ================= */
const INTAKE_STEPS = [
  {id: 'parse', t: '解析输入', s: '识别链接 / 地址'},
  {id: 'fetch', t: '抓取房源页', s: '公开页面直连'},
  {id: 'seller', t: '提取卖方口径', s: '标注待验证'},
  {id: 'indep', t: '全网独立搜集', s: '搜 county / 租金 / 新闻'},
  {id: 'tophap', t: 'TopHap enrich', s: '公共记录（若已授权）'},
  {id: 'merge', t: '合并字段', s: '独立源优先'},
];
/* intake 字段 → 核保表单映射（只做加法，口径零改动） */
const INTAKE_MAP = {
  residential: {price: 'asking_price', monthly_rent: 'monthly_rent', taxes_annual: 'taxes_annual', hoa_monthly: 'hoa_monthly'},
  commercial: {price: 'asking_price', tax_annual: 'taxes_annual', building_sf: 'building_sf'},
};

async function runIntake(text, track) {
  // 自动识别：LoopNet 是纯商业平台，链接直接按商业走
  if (/loopnet\.com/i.test(text)) track = 'commercial';
  state.view = 'intake';
  state.intake = {stage: 'running', steps: INTAKE_STEPS.map(s => ({...s, st: 'wait'})), result: null, error: null, track, query: text};
  render();
  // 进度动画：诚实标注"进行中"，不等后端分步回调
  let i = 0;
  const timer = setInterval(() => {
    const it = state.intake;
    if (!it || it.stage !== 'running') { clearInterval(timer); return; }
    if (i < it.steps.length) {
      it.steps.forEach((s, j) => { s.st = j < i ? 'done' : (j === i ? 'run' : 'wait'); });
      paintSteps();
      i++;
    }
  }, 2600);
  try {
    const mode = /^https?:\/\//i.test(text.trim()) ? 'url' : 'address';
    const res = await api('POST', '/api/wb/intake/run', {mode, text});
    clearInterval(timer);
    if (res.error) {
      state.intake.stage = 'error'; state.intake.error = res.error;
      state.intake.steps.forEach(s => { s.st = 'fail'; });
    } else {
      state.intake.stage = 'done'; state.intake.result = res;
      // 按真实 log 回填步骤状态
      const logTxt = (res.log || []).map(l => (l.step + l.status + l.note)).join(' ');
      const blocked = /blocked|拦截|禁止|拒绝抓取|forbidden|denied/i.test(logTxt);
      state.intake.steps.forEach(s => {
        if (s.id === 'fetch' && blocked && !(res.fields || []).length && !(res.seller_fields || []).length) s.st = 'fail';
        else if (s.id === 'tophap' && /TopHap.*(skipped|失败|降级)/.test(logTxt)) s.st = 'skip';
        else s.st = 'done';
      });
      // 商业：搜集完成即自动转入商业核保，无需手动点按钮
      if (track === 'commercial') {
        clearInterval(timer);
        state.intake.stage = 'routing';
        render();
        try {
          const uwInput = buildUwInput(res);
          const filledN = (res.fields || []).filter(f => f.value != null && typeof f.value === 'number').length;
          const p = await api('POST', '/api/uw/projects',
            {name: (uwInput.property.name || '商业核保') + '（自动填入' + filledN + '项）', input: uwInput});
          location.href = '/uw-commercial.html?pid=' + p.id;
        } catch (e) {
          // 转入失败：留在本页显示搜集结果，数据不丢
          state.intake.stage = 'done';
          state.intake.error = '自动转入失败（' + e.message + '），搜集结果保留在下方';
        }
        render();
        return;
      }
    }
  } catch (e) {
    clearInterval(timer);
    state.intake.stage = 'error';
    state.intake.error = '搜集请求失败：' + e.message;
    state.intake.steps.forEach(s => { s.st = 'fail'; });
  }
  render();
}

function paintSteps() {
  const el = $('#pipeSteps');
  if (el && state.intake) el.innerHTML = stepsHtml(state.intake.steps);
}
function stepsHtml(steps) {
  return steps.map(s => {
    const icon = s.st === 'done' ? '✓' : s.st === 'run' ? '…' : s.st === 'fail' ? '✕' : s.st === 'skip' ? '–' : (INTAKE_STEPS.indexOf(INTAKE_STEPS.find(x => x.id === s.id)) + 1);
    return `<div class="pstep ${s.st}"><div class="n">${icon}</div><div class="t">${s.t}</div><div class="s">${s.s}</div></div>`;
  }).join('');
}

function buildDraft(track, res) {
  const map = INTAKE_MAP[track];
  const fields = res.fields || [];
  const byKey = {}; fields.forEach(f => { byKey[f.key] = f; });
  const values = {}, sources = {};
  for (const [formKey, pipeKey] of Object.entries(map)) {
    const f = byKey[pipeKey];
    if (f && f.value != null && typeof f.value === 'number') {
      values[formKey] = f.value; sources[formKey] = f;
    }
  }
  if (track === 'residential' && byKey.monthly_rent) values.rent_source = 'estimated';
  if (res.address) { values.address = res.address; values.name = res.address; }
  else if (res.parsed && res.parsed.full) { values.address = res.parsed.full; values.name = res.parsed.full; }
  return {values, sources};
}

function renderIntake(app) {
  const it = state.intake;
  if (!it) {
    app.innerHTML = `<div class="panel" style="padding:34px 28px;max-width:760px;margin:20px auto">
      <h2 class="sec-t">◆ 智能搜集</h2>
      <p class="muted" style="font-size:13.5px">在顶部输入框粘贴房源链接（Zillow / Redfin / LoopNet / Realtor）或输入地址，点"开始搜集"。
      后端会自动抓取公开页面、做全网独立搜集、跑 TopHap 公共记录 enrich，每个字段都标注来源与可信度——抓不到就明说，绝不编数。</p>
      <div class="kvline"><span class="kk">支持站点</span><span class="vv" style="font-weight:400">Zillow / Redfin / Realtor / LoopNet / county assessor（.gov）等公开页面</span></div>
      <div class="kvline"><span class="kk">诚实铁律</span><span class="vv" style="font-weight:400">卖方口径一律标"待验证"；平台估值仅参考，不进收购价</span></div>
      <div class="kvline"><span class="kk">反爬预期</span><span class="vv" style="font-weight:400">Zillow/Redfin 大概率 403 拦截——这是预期内的降级路径，会自动转手动补</span></div>
    </div>`;
    return;
  }
  let body = '';
  if (it.stage === 'running') {
    body = `<div class="pipe-steps" id="pipeSteps">${stepsHtml(it.steps)}</div>
      <div class="empty"><span class="spinner"></span>正在全网搜集公开信息，约需 30–90 秒…<br>
      <span class="micro">只碰公开页面；robots.txt 禁止的不碰；被反爬拦截立刻停手并记录</span></div>`;
  } else if (it.stage === 'routing') {
    body = `<div class="pipe-steps">${stepsHtml(it.steps)}</div>
      <div class="empty"><span class="spinner"></span>搜集完成，正在自动转入商业核保…<br>
      <span class="micro">搜集到的字段已自动填入，缺失的进页面后手工补</span></div>`;
  } else if (it.stage === 'error') {
    body = `<div class="pipe-steps">${stepsHtml(it.steps)}</div>
      <div class="veto-banner bad"><b>搜集失败</b><div style="margin-top:6px">${esc(it.error)}</div>
      <div class="micro" style="margin-top:6px">降级路径：手动输入地址跑"地址模式"，或直接进"＋ 新建项目"手动录入。</div></div>
      <div class="toolbar"><button class="btn" data-act="intakeRetry">↻ 换地址模式重试</button>
      <button class="btn primary" data-act="gotoForm">直接手动录入 →</button></div>`;
  } else {
    body = intakeResultHtml(it);
  }
  app.innerHTML = `<div class="zone"><div class="panel" style="padding:20px 22px">
    <h2 class="sec-t">◆ 智能搜集 <span class="micro">房源链接 / 地址 → 全网公开信息自动搜集</span></h2>${body}</div></div>`;
}

function intakeResultHtml(it) {
  const res = it.result;
  const fields = res.fields || [];
  const manual = res.manual_needed || [];
  const filledN = fields.filter(f => f.status !== 'manual_needed').length;
  const sellerN = fields.filter(f => f.seller_claimed).length;
  const addrLine = esc(res.address || (res.parsed && res.parsed.full) || it.query || '');
  const fieldRows = fields.map(f => {
    let disp = f.display || String(f.value);
    if (Array.isArray(f.value)) disp = f.value.length + ' 条记录（见日志/新闻）';
    else if (typeof f.value === 'object') disp = JSON.stringify(f.value).slice(0, 80);
    return `<tr><td><b>${esc(f.label)}</b></td><td class="num"><b>${esc(disp)}</b></td>
      <td class="micro">${esc(f.source || '')}<br>${esc(f.fetched_at || '')}</td>
      <td>${confChip(f)}</td></tr>`;
  }).join('');
  const manualRows = manual.map(m =>
    `<tr><td><b>${esc(m.label)}</b></td><td class="micro" colspan="2">${esc(m.note || '')}</td><td>${confChip({status: 'manual_needed'})}</td></tr>`).join('');
  const logRows = (res.log || []).map(l => {
    const cls = l.status === 'ok' ? 'ok' : (l.status === 'blocked' || l.status === 'failed' ? 'bad' : 'wr');
    return `<div><span class="${cls}">[${esc(l.status)}]</span> ${esc(l.step)} <span style="color:#8ba3c2">${esc(l.note || '')}</span> <span style="color:#5b6b82">${esc(l.at || '')}</span></div>`;
  }).join('');
  const draft = it.draft;
  return `
    <div class="pipe-steps">${stepsHtml(it.steps)}</div>
    <div class="insight ${filledN ? 'good' : 'warn'}"><div class="ic">${filledN ? '✓' : '▲'}</div><div>
      <div class="t">${addrLine || '搜集完成'}：填入 ${filledN} 个字段${sellerN ? `（其中 ${sellerN} 个为卖方口径、待验证）` : ''}，${manual.length} 个需手动补</div>
      <div class="d">${res.independent_note ? esc(res.independent_note) + '。' : ''}平台估值（zestimate）仅参考，不进收购价；抓不到的字段已标"需手动补"。</div></div>
      <div class="act" style="display:flex;gap:8px">${filledN
        ? `<button class="btn primary big" data-act="makeDraft">→ 生成核保草稿</button>`
        : `<button class="btn primary" data-act="manualWithAddr">→ 手动录入（地址已带入）</button>`}</div></div>
    <h3 class="sec-t">搜集字段 <span class="micro">每个字段：值 / 来源 / 可信度</span></h3>
    <div class="tbl-wrap"><table class="data"><thead><tr><th>字段</th><th class="num">值</th><th>来源</th><th>可信度</th></tr></thead>
    <tbody>${fieldRows}${manualRows}</tbody></table></div>
    ${draft ? `<h3 class="sec-t" style="margin-top:18px">核保初筛 <span class="micro">草稿自动打分（未保存）</span></h3>
      <div class="dhero" style="margin-bottom:0"><div class="dhero-top">
        <span class="badge big ${esc(draft.score.grade)}">${esc(draft.score.grade)}</span>
        <div><div class="score-big num">${draft.score.total}<small>/100</small></div></div>
        <div><h1 style="font-size:16px">${esc(draft.name)}</h1><div class="addr">${esc(draft.address)}</div></div>
        <div style="margin-left:auto;display:flex;gap:8px">
          <button class="btn primary" data-act="saveDraft">保存为项目 →</button>
          <button class="btn" data-act="editDraft">去表单微调</button></div>
      </div>${draft.score.vetoes.length ? `<div class="veto-banner bad"><b>✕ 一票否决（${draft.score.vetoes.length}）</b><ul>` +
        draft.score.vetoes.map(v => `<li>${esc(v.message)}</li>`).join('') + '</ul></div>' : ''}
      <div class="metrics" style="margin-top:14px">${(it.track === 'residential' ? RES_METRICS : COM_METRICS)
        .filter(([, , , hero]) => hero).map(([label, key, kind]) =>
        `<div class="metric hero"><div class="k">${label}</div><div class="v">${fmtVal(kind, draft.score.metrics[key])}</div></div>`).join('')}</div>
      </div>
      <p class="micro" style="margin-top:8px">自动填入的字段在表单里以绿色高亮＋来源标注；保存前请逐项核对，未补的字段用保守值。</p>` : ''}
    <details class="fold"><summary>搜集过程日志（${(res.log || []).length} 步）<span class="micro">点击展开</span></summary>
      <div class="fb"><div class="logbox">${logRows || '<span class="muted">无日志</span>'}</div></div></details>`;
}

/* 搜集结果 → 商业核保输入：能对上的全自动填入，对不上的留空手工补 */
function buildUwInput(res) {
  const byKey = {};
  (res.fields || []).forEach(f => { byKey[f.key] = f; });
  const num = k => { const f = byKey[k]; return (f && typeof f.value === 'number') ? f.value : 0; };
  const str = k => { const f = byKey[k]; return (f && f.value != null) ? String(f.value) : ''; };
  const addr = res.address || ((res.parsed && res.parsed.full) || '');
  const parsed = res.parsed || {};
  const tax = num('taxes_annual');
  const scenario = () => ({
    cam_recovery: 0, parking_income: 0, other_income: 0, vacancy_pct: 0,
    tenant_improvements: 0, capex: 0, leasing_commissions: 0,
    service_contracts: 0, cam: 0, general_admin: 0, repairs_maintenance: 0,
    janitor: 0, security: 0, utilities: 0, payroll: 0, management_fee: 0,
    property_tax: tax, insurance: 0, landscape: 0,
  });
  return {
    property: {
      name: addr, address: addr,
      city: parsed.city || '', state: parsed.state || '', zip: parsed.zip || '',
      county: '', property_type: 'Retail',
      net_rentable_sf: num('building_sf'),
      land_acres: num('lot_sf') ? Math.round(num('lot_sf') / 43560 * 100) / 100 : 0,
      parking_spaces: 0, year_built: num('year_built') || '',
      year_renovated: '', buildings: '', floors: '', occupancy_as_of: '',
    },
    tenants: [],
    vacant_sf: 0,
    historical: scenario(),
    proforma: scenario(),
    analysis: {
      purchase_price: num('asking_price'),
      building_repairs: 0, capital_reserve: 0, lender_fees: 0, closing_costs: 0,
      down_pct: 0.3, rate: 0.06, amort_type: 'IO', amort_years: 30,
      market_cap_rate: 0.04, abatements: 0,
      underwritten_noi: null, projected_noi: null, inplace_noi_cf: null,
      hold_years: 5, noi_growth: 0.02, exit_cap_rate: 0.05,
    },
  };
}

async function makeDraft() {  const it = state.intake;
  if (!it || !it.result) return;
  const {values, sources} = buildDraft(it.track, it.result);
  // 补全表单默认值后打分
  const secs = it.track === 'residential' ? RES_SECTIONS : COM_SECTIONS;
  const input = {risk_flags: []};
  for (const s of secs) for (const f of s.fields) {
    if (f.flag) continue;
    if (values[f.key] !== undefined) input[f.key] = values[f.key];
    else if (f.type === 'check') input[f.key] = !!f.def;
    else if (f.type === 'number') input[f.key] = f.def === '' ? 0 : f.def;
    else if (f.type === 'select') input[f.key] = f.def;
    else input[f.key] = f.def ?? '';
  }
  if (it.track === 'commercial') input.tranches = [];
  try {
    const score = await api('POST', '/api/score', {track: it.track, name: values.name || '草稿', address: values.address || '', input});
    it.draft = {input, score, sources, name: values.name || '草稿', address: values.address || ''};
  } catch (e) {
    it.draft = null;
    alert('草稿打分失败：' + e.message + '\n可先去表单手动补全必填项。');
  }
  render();
}

/* ================= 表单 ================= */
function fieldHtml(f, src) {
  const id = 'f_' + f.key;
  const tag = src ? ` <span class="srctag">◆ ${esc(src.display || src.value)} · ${esc(src.source || '')}</span>` : '';
  if (f.type === 'check')
    return `<div class="field check"><label><input type="checkbox" id="${id}" ${f.def ? 'checked' : ''}> ${esc(f.label)}${tag}</label>${f.hint ? `<div class="hint">${esc(f.hint)}</div>` : ''}</div>`;
  if (f.type === 'select') {
    const opts = f.options.map(([v, t]) => `<option value="${v}">${esc(t)}</option>`).join('');
    return `<div class="field"><label>${esc(f.label)}${tag}</label><select id="${id}" class="${src ? 'autofill' : ''}">${opts}</select>
      ${f.hint ? `<div class="hint">${esc(f.hint)}</div>` : ''}</div>`;
  }
  return `<div class="field"><label>${esc(f.label)}${tag}</label>
    <input type="${f.type}" id="${id}" value="${esc(f.def ?? '')}" ${f.type === 'number' ? 'step="any"' : ''} class="${src ? 'autofill' : ''}">
    ${f.hint ? `<div class="hint">${esc(f.hint)}</div>` : ''}</div>`;
}

function collectForm() {
  const secs = state.track === 'residential' ? RES_SECTIONS : COM_SECTIONS;
  const d = {risk_flags: []};
  for (const s of secs) for (const f of s.fields) {
    const el = document.getElementById('f_' + f.key);
    if (!el) continue;
    if (f.flag) { if (el.checked) d.risk_flags.push(f.key); continue; }
    if (f.type === 'check') d[f.key] = el.checked;
    else if (f.type === 'number') {
      const v = el.value.trim();
      d[f.key] = v === '' ? (f.optional ? null : (f.def === '' ? 0 : f.def)) : parseFloat(v);
    }
    else if (f.type === 'select') d[f.key] = f.numeric ? parseInt(el.value, 10) : el.value;
    else d[f.key] = el.value.trim();
  }
  if (state.track === 'commercial') {
    d.tranches = [];
    for (const n of [1, 2]) {
      const bal = d['t' + n + '_balance'] || 0;
      if (bal > 0) d.tranches.push({
        balance: bal, rate: d['t' + n + '_rate'] || 0,
        rate_type: d['t' + n + '_rate_type'] || 'fixed',
        term_years: d['t' + n + '_term'] || 30,
        balloon_years: d['t' + n + '_balloon'] ?? null});
      for (const k of ['balance', 'rate', 'rate_type', 'term', 'balloon']) delete d['t' + n + '_' + k];
    }
  }
  return d;
}

function fillForm(data, sources) {
  const secs = state.track === 'residential' ? RES_SECTIONS : COM_SECTIONS;
  const flat = {...data};
  if (state.track === 'commercial' && Array.isArray(data.tranches)) {
    data.tranches.slice(0, 2).forEach((t, i) => {
      const n = i + 1;
      flat['t' + n + '_balance'] = t.balance; flat['t' + n + '_rate'] = t.rate;
      flat['t' + n + '_rate_type'] = t.rate_type; flat['t' + n + '_term'] = t.term_years;
      flat['t' + n + '_balloon'] = t.balloon_years ?? '';
    });
  }
  for (const s of secs) for (const f of s.fields) {
    const el = document.getElementById('f_' + f.key);
    if (!el) continue;
    let v;
    if (f.flag) v = (data.risk_flags || []).includes(f.key);
    else v = flat[f.key] !== undefined ? flat[f.key] : f.def;
    if (f.type === 'check') el.checked = !!v;
    else el.value = v ?? '';
  }
}

function renderForm(app) {
  const secs = state.track === 'residential' ? RES_SECTIONS : COM_SECTIONS;
  const sources = (state._fill && state._fill.sources) || {};
  const secsHtml = secs.map(s => `<div class="form-sec"><h3>${esc(s.title)} <span class="cnt">${s.fields.length} 项</span></h3>
    <div class="fgrid">${s.fields.map(f => fieldHtml(f, sources[f.key])).join('')}</div></div>`).join('');
  const fromIntake = state._fill && state._fill.fromIntake;
  app.innerHTML = `
    <div class="toolbar"><button class="btn" data-act="back">← 返回仪表盘</button>
      <div class="seg">
        <button data-track="residential" class="${state.track === 'residential' ? 'on' : ''}">住宅</button>
        <button data-track="commercial" class="${state.track === 'commercial' ? 'on' : ''}">商业</button>
      </div>
      <span style="font-size:14px;font-weight:700">${state.editingId ? '编辑项目' : '新建项目'}</span>
      <span class="micro">评分口径：${state.track === 'residential' ? 'buyer-box v2.3' : 'commercial v1.3'}</span></div>
    ${fromIntake ? `<div class="insight good"><div class="ic">◆</div><div>
      <div class="t">已从智能搜集自动填入 ${Object.keys(sources).length} 个字段</div>
      <div class="d">绿色高亮的字段带来源标注；保存前请逐项核对，未补字段用保守值。卖方口径数字已标待验证，不直接采信。</div></div></div>` : ''}
    ${secsHtml}
    <div class="toolbar" style="position:sticky;bottom:0;background:rgba(242,245,249,.96);padding:10px 0">
      <button class="btn big" data-act="preview">◆ 一键打分预览（不保存）</button>
      <button class="btn primary big" data-act="save">${state.editingId ? '保存修改' : '保存项目'}</button>
    </div>
    <div id="preview"></div>`;
  if (state._fill) { fillForm(state._fill.values || state._fill, sources); state._fill = null; }
}

/* ================= 详情 ================= */
function heroMetrics(p) {
  const m = p.score.metrics || {};
  if (p.track === 'residential') return [
    ['全口径现金需求', m.cash_to_close, 'money', 1],
    ['月净现金流', m.cash_flow_monthly, 'moneysigned', 0],
    ['DSCR', m.dscr, 'num', 0],
    ['Cash-on-cash', m.cash_on_cash, 'pct', 0],
  ];
  return [
    ['全口径现金需求', m.cash_to_close, 'money', 1],
    ['年 NOI', m.noi, 'money', 0],
    ['入场 cap', m.entry_cap, 'pct', 0],
    ['DSCR', m.dscr, 'num', 0],
  ];
}

async function renderDetail(app) {
  const p = state.detail;
  const s = p.score;
  const tabs = [['overview', '核保总览'], ['finance', '财务测算'], ['sens', '敏感性分析']];
  let panel = '';
  if (state.detailTab === 'overview' || state.detailTab === 'finance') {
    panel = scoreHtml(s, p.track);
  } else {
    panel = '<div id="sens"><div class="empty"><span class="spinner"></span>敏感性分析加载中…</div></div>';
  }
  app.innerHTML = `
    <div class="toolbar"><button class="btn" data-act="back">← 返回仪表盘</button><span class="spacer"></span>
      <button class="btn primary" data-act="pdf" data-id="${p.id}">生成 PDF 报告</button>
      <button class="btn" data-act="edit" data-id="${p.id}">编辑</button>
      <button class="btn danger" data-act="del" data-id="${p.id}">删除</button></div>
    <div class="dhero"><div class="dhero-top">
      <span class="badge big ${esc(s.grade)}">${esc(s.grade)}</span>
      <div class="score-big num">${s.total}<small>/100</small></div>
      <div><h1>${esc(p.name) || '(未命名)'}</h1>
        <div class="addr">${esc(p.address)} · ${esc(s.structure_label || s.asset_label || '')} · ${p.track === 'residential' ? '住宅' : '商业'}</div></div>
    </div>
    ${s.vetoes.length
      ? `<div class="veto-banner bad"><b>✕ 一票否决（${s.vetoes.length} 项）——直接结论：否决</b><ul>` +
        s.vetoes.map(v => `<li>${esc(v.message)}</li>`).join('') + '</ul></div>'
      : `<div class="veto-banner good"><b>✓ 无否决项</b><span class="muted"> —— 按总分定级：${esc(s.grade)} 级</span></div>`}
    ${(s.downgrades || []).length ? `<div class="veto-banner warn"><b>▲ 降级提示</b><ul>` +
      s.downgrades.map(v => `<li>${esc(v.message)}</li>`).join('') + '</ul></div>' : ''}
    <div class="dhero-metrics">${heroMetrics(p).map(([k, v, kind]) =>
      `<div class="hm"><div class="k">${k}</div><div class="v">${fmtVal(kind, v)}</div></div>`).join('')}</div>
    </div>
    <div class="dtabs">${tabs.map(([id, t]) =>
      `<button data-dtab="${id}" class="${state.detailTab === id ? 'on' : ''}">${t}</button>`).join('')}</div>
    <div id="dpanel">${panel}</div>`;
  if (state.detailTab === 'sens') {
    try {
      const sens = await api('POST', '/api/sensitivity',
        {track: p.track, name: p.name, address: p.address, input: p.input});
      const el = $('#sens');
      if (el) el.innerHTML = sensHtml(sens, p.track);
    } catch (e) {
      const el = $('#sens');
      if (el) el.innerHTML = `<div class="empty">敏感性分析加载失败：${esc(e.message)}</div>`;
    }
  }
}

/* ================= 对比 ================= */
async function renderCompare(app) {
  app.innerHTML = `<div class="toolbar"><button class="btn" data-act="back">← 返回仪表盘</button>
    <span class="micro">勾选管线中的项目（最多 3 个）进入对比</span></div>
    <div class="panel"><div class="panel-h"><h2>项目对比</h2></div>
    <div class="panel-b tbl-wrap" id="cmp"><div class="empty"><span class="spinner"></span>加载中…</div></div></div>`;
  if (!state.compareIds.length) {
    $('#cmp').innerHTML = '<div class="empty">还没选中要对比的项目<br><span class="micro">回仪表盘，在管线表格右侧勾选「对比」，最多四个并排看</span></div>';
    return;
  }
  try {
    const items = await api('GET', '/api/compare?ids=' + state.compareIds.join(','));
    const cfOf = p => p.track === 'residential' ? p.score.metrics.cash_flow_monthly : p.score.metrics.net_cf_monthly;
    const rows = [
      ['项目', p => `<b>${esc(p.name) || '(未命名)'}</b><div class="micro">${esc(p.address)}</div>`],
      ['轨道', p => p.track === 'residential' ? '住宅' : '商业'],
      ['结构', p => esc(p.score.structure_label || p.score.asset_label || '')],
      ['等级', p => `<span class="badge ${esc(p.score.grade)}">${esc(p.score.grade)}</span>`],
      ['总分', p => `<b class="num" style="font-size:18px">${p.score.total}</b><span class="micro">/100</span>`],
      ['月净现金流', p => { const v = cfOf(p); return `<span class="${v < 0 ? 'neg' : 'pos'} num"><b>${moneyS(v)}</b></span>`; }],
      ['DSCR', p => `<span class="num">${num2(p.score.metrics.dscr)}</span>`],
      ['Cash-on-cash', p => `<span class="num">${pct1(p.score.metrics.cash_on_cash)}</span>`],
      ['cash-to-close', p => `<b class="num">${money(p.cash_to_close)}</b>`],
      ['否决项', p => p.score.vetoes.length ? `<span class="st bad">${p.score.vetoes.length} 项</span>` : '<span class="st ok">无</span>'],
      ['', p => `<button class="btn sm" data-act="open" data-id="${p.id}">打开 →</button>`],
    ];
    $('#cmp').innerHTML = `<table class="data cmp-table"><thead><tr><th></th>${items.map(p =>
      `<th>${esc(p.name) || '(未命名)'}</th>`).join('')}</tr></thead><tbody>` +
      rows.map(([label, fn]) => `<tr><td>${label}</td>${items.map(p => `<td>${fn(p)}</td>`).join('')}</tr>`).join('') +
      '</tbody></table>';
  } catch (e) { $('#cmp').innerHTML = `<div class="empty">对比加载失败：${esc(e.message)}</div>`; }
}

/* ================= 事件 ================= */
document.addEventListener('click', async e => {
  const nav = e.target.closest('#nav button');
  if (nav) {
    state.view = nav.dataset.view;
    if (state.view === 'dashboard') await loadProjects();
    render(); return;
  }
  const seg = e.target.closest('.seg button');
  if (seg && seg.dataset.track) {
    state.track = seg.dataset.track; state.compareIds = [];
    if (state.view === 'form' && !state.editingId) { /* 新建时切换轨道保留空表单 */ }
    render(); return;
  }
  const dtab = e.target.closest('[data-dtab]');
  if (dtab) { state.detailTab = dtab.dataset.dtab; render(); return; }
  const th = e.target.closest('th.sortable');
  if (th) {
    const k = th.dataset.sort;
    if (state.sortKey === k) state.sortDir *= -1;
    else { state.sortKey = k; state.sortDir = k === 'cash_to_close' ? 1 : -1; }
    render(); return;
  }
  const row = e.target.closest('tr.rowlink');
  if (row && row.dataset.open) {
    try {
      const p = await api('GET', '/api/projects/' + row.dataset.open);
      state.track = p.track; state.view = 'detail'; state.detail = p; state.detailTab = 'overview'; render();
    } catch (err) { alert('打开失败：' + err.message); }
    return;
  }
  const btn = e.target.closest('[data-act]');
  if (!btn) return;
  const act = btn.dataset.act, id = btn.dataset.id ? +btn.dataset.id : null;
  try {
    if (act === 'focusIntake') { $('#ihInput').focus(); window.scrollTo(0, 0); }
    else if (act === 'new') { state.view = 'form'; state.editingId = null; state._fill = null; render(); }
    else if (act === 'gotoForm') { state.view = 'form'; state.editingId = null; state._fill = null; render(); }
    else if (act === 'manualWithAddr') {
      const it = state.intake, res = it.result || {};
      const addr = res.address || (res.parsed && res.parsed.full) || it.query || '';
      state.track = it.track; state.view = 'form'; state.editingId = null;
      state._fill = {values: {name: addr, address: addr}, sources: {}}; render();
    }
    else if (act === 'back') { state.view = 'dashboard'; await loadProjects(); render(); }
    else if (act === 'intakeRetry') { const v = $('#ihInput').value.trim(); if (v) runIntake(v, state.intake.track); }
    else if (act === 'edit') {
      const p = await api('GET', '/api/projects/' + id);
      state.track = p.track; state.view = 'form'; state.editingId = id;
      state._fill = {values: p.input, sources: {}}; render();
    }
    else if (act === 'open') {
      const p = await api('GET', '/api/projects/' + id);
      state.track = p.track; state.view = 'detail'; state.detail = p; state.detailTab = 'overview'; render();
    }
    else if (act === 'pdf') {
      const a = document.createElement('a');
      a.href = '/api/projects/' + id + '/pdf';
      a.download = '';
      document.body.appendChild(a); a.click(); a.remove();
    }
    else if (act === 'report') {
      window.open('/api/projects/' + id + '/report', '_blank');
    }
    else if (act === 'del') {
      if (confirm('确定删除该项目吗？')) {
        await api('DELETE', '/api/projects/' + id);
        state.compareIds = state.compareIds.filter(x => x !== id);
        state.view = 'dashboard'; await loadProjects(); render();
      }
    }
    else if (act === 'preview') {
      const input = collectForm();
      const s = await api('POST', '/api/score', {track: state.track, name: '预览', address: input.address || '', input});
      $('#preview').innerHTML = '<h3 class="sec-t" style="margin-top:20px">打分预览 <span class="micro">未保存</span></h3>' +
        `<div class="dhero" style="margin-bottom:14px"><div class="dhero-top">
          <span class="badge big ${esc(s.grade)}">${esc(s.grade)}</span>
          <div class="score-big num">${s.total}<small>/100</small></div></div></div>` + scoreHtml(s, state.track);
      $('#preview').scrollIntoView({behavior: 'smooth'});
    }
    else if (act === 'save') {
      const input = collectForm();
      const payload = {track: state.track, name: input.name || '', address: input.address || '', input};
      let p;
      if (state.editingId) p = await api('PUT', '/api/projects/' + state.editingId, payload);
      else p = await api('POST', '/api/projects', payload);
      state.view = 'detail'; state.detail = p; state.detailTab = 'overview'; render();
    }
    else if (act === 'makeDraft') { await makeDraft(); }
    else if (act === 'editDraft') {
      const it = state.intake;
      state.track = it.track; state.view = 'form'; state.editingId = null;
      state._fill = {values: it.draft.input, sources: it.draft.sources, fromIntake: true};
      render();
    }
    else if (act === 'saveDraft') {
      const it = state.intake;
      const p = await api('POST', '/api/projects',
        {track: it.track, name: it.draft.name, address: it.draft.address, input: it.draft.input});
      state.view = 'detail'; state.detail = p; state.detailTab = 'overview'; render();
    }
  } catch (err) { alert('操作失败：' + err.message); }
});

document.addEventListener('change', e => {
  const c = e.target.closest('[data-cmp]');
  if (!c) return;
  const id = +c.dataset.cmp;
  if (c.checked) {
    if (state.compareIds.length >= 3) { c.checked = false; alert('最多对比 3 个项目'); return; }
    state.compareIds.push(id);
  } else state.compareIds = state.compareIds.filter(x => x !== id);
  render();
});

/* ================= 统一智能输入：意图检测 + chip =================
   检测层级 T1 URL 主机白名单 → T2 双语命令 → T3 地址。
   检测只展示意图（chip），粘贴永不自动执行；Enter/点击才确认。IME 拼写中不检测不提交。 */
const IH_COM_HOSTS = ['loopnet.com', 'crexi.com', 'costar.com'];
const IH_RES_HOSTS = ['zillow.com', 'redfin.com', 'realtor.com'];
const IH_CMD_COM = ['商业', '商业核保', '商用', 'commercial'];
const IH_CMD_RES = ['住宅', '住宅核保', 'residential'];
function ihNorm(s) {
  return (s || '')
    .replace(/[！-～]/g, c => String.fromCharCode(c.charCodeAt(0) - 0xFEE0)) // 全角→半角
    .replace(/　/g, ' ')
    .trim();
}
function ihHostOf(t) {
  const m = /^https?:\/\/([^\/\s?#]+)/i.exec(t.trim());
  return m ? m[1].toLowerCase().replace(/^www\./, '') : '';
}
function detectIntent(raw) {
  const t = ihNorm(raw);
  if (!t) return null;
  const low = t.toLowerCase();
  const host = ihHostOf(t);
  if (host) {
    if (IH_COM_HOSTS.some(h => host === h || host.endsWith('.' + h))) return {kind: 'com-url', host, raw: t};
    if (IH_RES_HOSTS.some(h => host === h || host.endsWith('.' + h))) return {kind: 'res-url', host, raw: t};
    return {kind: 'url-unknown', host, raw: t};
  }
  if (IH_CMD_COM.indexOf(low) !== -1) return {kind: 'cmd-com', raw: t};
  if (IH_CMD_RES.indexOf(low) !== -1) return {kind: 'cmd-res', raw: t};
  return {kind: 'address', raw: t, addrTrack: 'residential'};
}
let ihDet = null;
function dismissIhChip() { ihDet = null; renderIhChip(); }
function renderIhChip() {
  const chip = $('#ihChip'), input = $('#ihInput'), go = $('#ihGo');
  if (!chip) return;
  if (!ihDet) {
    chip.hidden = true; chip.innerHTML = '';
    input.setAttribute('aria-expanded', 'false');
    go.textContent = '开始搜集';
    return;
  }
  input.setAttribute('aria-expanded', 'true');
  const d = ihDet;
  const xBtn = '<button class="cx" data-act="x" aria-label="取消">×</button>';
  let inner = '', goLabel = '开始搜集';
  if (d.kind === 'com-url') {
    goLabel = '开始搜集 → 商业';
    inner = `<div class="ck"><span class="badge com">商业房源</span></div><div class="cd">${esc(d.host)} · 检测到商业房源 → 将进入商业核保</div><div class="ca"><button class="btn primary" data-act="go">开始搜集</button>${xBtn}</div>`;
  } else if (d.kind === 'res-url') {
    inner = `<div class="ck"><span class="badge res">住宅房源</span></div><div class="cd">${esc(d.host)} · 检测到住宅房源 → 将进入住宅核保</div><div class="ca"><button class="btn primary" data-act="go">开始搜集</button>${xBtn}</div>`;
  } else if (d.kind === 'url-unknown') {
    inner = `<div class="ck"><span class="badge cmd">链接</span></div><div class="cd">${esc(d.host)} · 未识别出房源平台，将按地址搜集</div><div class="ca"><button class="btn primary" data-act="go">按地址搜集</button>${xBtn}</div>`;
  } else if (d.kind === 'cmd-com') {
    goLabel = '进入商业核保';
    inner = `<div class="ck"><span class="badge cmd">命令</span></div><div class="cd">进入商业核保工作台</div><div class="ca"><button class="btn primary" data-act="go">进入</button>${xBtn}</div>`;
  } else if (d.kind === 'cmd-res') {
    inner = `<div class="ck"><span class="badge cmd">命令</span></div><div class="cd">住宅核保工作台即本页，已在当前页面</div><div class="ca">${xBtn}</div>`;
  } else {
    inner = `<div class="ck"><span class="badge res">地址</span></div><div class="cd">将按地址搜集房源公开信息</div><div class="ca"><button class="btn primary" data-act="go-res">住宅搜集</button><button class="btn" data-act="go-com">商业搜集</button>${xBtn}</div>`;
  }
  chip.innerHTML = inner;
  chip.hidden = false;
  go.textContent = goLabel;
}
function ihPrimary() {
  const inp = $('#ihInput');
  const d = ihDet;
  dismissIhChip();
  if (!d) {
    const t = ihNorm(inp.value);
    if (!t) { inp.focus(); return; }
    runIntake(t, 'residential');
    return;
  }
  if (d.kind === 'com-url') runIntake(d.raw, 'commercial');
  else if (d.kind === 'res-url' || d.kind === 'url-unknown') runIntake(d.raw, 'residential');
  else if (d.kind === 'cmd-com') location.href = '/uw-commercial.html';
  else if (d.kind === 'cmd-res') window.scrollTo({top: 0, behavior: 'smooth'});
  else if (d.kind === 'address') runIntake(d.raw, d.addrTrack || 'residential');
}
let ihDeb = null;
function ihDetectSoon() {
  clearTimeout(ihDeb);
  ihDeb = setTimeout(() => { ihDet = detectIntent($('#ihInput').value); renderIhChip(); }, 120);
}
$('#ihGo').addEventListener('click', ihPrimary);
$('#ihInput').addEventListener('input', e => {
  if (e.isComposing) return; // IME 拼写中不检测
  ihDetectSoon();
});
$('#ihInput').addEventListener('compositionend', ihDetectSoon);
$('#ihInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') {
    if (e.isComposing || e.keyCode === 229) return; // IME 确认选词不提交（Safari/WebKit 兼容）
    e.preventDefault();
    ihPrimary();
  } else if (e.key === 'Escape') {
    dismissIhChip();
  }
});
$('#ihChip').addEventListener('click', e => {
  const b = e.target.closest('[data-act]');
  if (!b) return;
  const act = b.dataset.act;
  if (act === 'x') { dismissIhChip(); $('#ihInput').focus(); return; }
  if (act === 'go-com' && ihDet && ihDet.kind === 'address') ihDet.addrTrack = 'commercial';
  if (act === 'go-res' && ihDet && ihDet.kind === 'address') ihDet.addrTrack = 'residential';
  ihPrimary();
});
/* Cmd+K / Ctrl+K 聚焦同一输入框（桌面端次级加速键，非第二搜索框） */
document.addEventListener('keydown', e => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    const inp = $('#ihInput');
    if (!inp) return;
    e.preventDefault();
    inp.focus(); inp.select();
  }
});

/* ================= 启动 ================= */
setInterval(() => {
  const el = $('#clock');
  if (el) el.textContent = new Date().toLocaleString('zh-CN', {hour12: false});
}, 1000);

async function checkTophap() {
  const el = $('#tophapChip');
  try {
    const s = await api('GET', '/api/tophap/status', null, 8000);
    const ok = s && (s.core_ready || s.ok);
    el.className = 'tophap ' + (ok ? 'ok' : 'warn');
    el.innerHTML = `<span class="dot"></span><span>TopHap ${ok ? '已连接' : '未就绪'}</span>`;
    const sp = $('#srcPanel');
    if (sp) sp.innerHTML = `
      <div class="src-row"><span>TopHap 公共记录</span>${ok ? '<span class="st ok">已连接</span>' : '<span class="st warn">未授权/未启用</span>'}</div>
      <div class="src-row"><span>全网公开页面搜集</span><span class="st ok">可用</span></div>
      <div class="src-row"><span>PDF / 截图 intake</span><span class="st ok">可用</span></div>
    `;
  } catch (e) {
    el.className = 'tophap';
    el.innerHTML = '<span class="dot"></span><span>TopHap 未启用</span>';
  }
}

(async function init() {
  try { await loadProjects(); }
  catch (e) {
    $('#app').innerHTML = `<div class="empty"><div class="big">○</div>后端连接失败：${esc(e.message)}<br><span class="micro">请确认服务已启动（127.0.0.1:8100）</span></div>`;
    return;
  }
  render();
  checkTophap();
})();
