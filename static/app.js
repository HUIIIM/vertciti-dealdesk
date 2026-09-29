/* DealDesk 前端：住宅/商业双轨 · 全中文 */
const state = { track: 'residential', view: 'list', projects: [], editingId: null, detail: null, compareIds: [], sortCash: false };

const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const money = x => x == null ? '—' : '$' + Number(x).toLocaleString('en-US', {maximumFractionDigits: 0});
const pct1 = x => x == null ? '—' : (x * 100).toFixed(1) + '%';
const num2 = x => x == null ? '—' : Number(x).toFixed(2);
const signed = (x, f) => x == null ? '—' : `<span class="${x < 0 ? 'neg' : 'pos'}">${f(x)}</span>`;

const numOpts = n => Array.from({length: n + 1}, (_, i) => [i, String(i)]);

/* ---------------- 字段 Schema ---------------- */
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

/* ---------------- API ---------------- */
async function api(method, path, body) {
  const r = await fetch(path, {method, headers: {'Content-Type': 'application/json'},
    body: body ? JSON.stringify(body) : undefined});
  if (!r.ok) {
    const t = await r.text();
    try { const j = JSON.parse(t); throw new Error(j.detail || t || r.statusText); }
    catch (e) { if (e.message && e.message !== t) throw e; throw new Error(t || r.statusText); }
  }
  return r.json();
}

/* ---------------- 表单 ---------------- */
function fieldHtml(f) {
  const id = 'f_' + f.key;
  if (f.type === 'check')
    return `<div class="field check"><label><input type="checkbox" id="${id}" ${f.def ? 'checked' : ''}> ${esc(f.label)}</label></div>`;
  if (f.type === 'select') {
    const opts = f.options.map(([v, t]) => `<option value="${v}">${esc(t)}</option>`).join('');
    return `<div class="field"><label>${esc(f.label)}</label><select id="${id}">${opts}</select>
      ${f.hint ? `<div class="hint">${esc(f.hint)}</div>` : ''}</div>`;
  }
  return `<div class="field"><label>${esc(f.label)}</label>
    <input type="${f.type}" id="${id}" value="${esc(f.def ?? '')}" ${f.type === 'number' ? 'step="any"' : ''}>
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

function fillForm(data) {
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

/* ---------------- 评分展示 ---------------- */
const RES_METRICS = [
  ['月供 P&I', 'monthly_pi', 'money'], ['月 PITI', 'piti', 'money'],
  ['月净现金流', 'cash_flow_monthly', 'moneysigned'], ['单门现金流', 'cash_flow_per_door', 'moneysigned'],
  ['Cash-on-cash', 'cash_on_cash', 'pct'], ['DSCR', 'dscr', 'num'],
  ['Cap rate', 'cap_rate', 'pct'], ['现金总投入', 'cash_invested', 'money'],
  ['全口径现金需求 cash-to-close', 'cash_to_close', 'money'], ['交割净值', 'equity', 'moneysigned'],
];
const COM_METRICS = [
  ['年 NOI', 'noi', 'money'], ['入场 cap', 'entry_cap', 'pct'],
  ['Spread', 'spread_bps', 'bps'], ['DSCR', 'dscr', 'num'],
  ['月净现金流', 'net_cf_monthly', 'moneysigned'], ['Cash-on-cash', 'cash_on_cash', 'pct'],
  ['年还本付息', 'annual_debt_service', 'money'], ['现金总投入', 'cash_invested', 'money'],
  ['全口径现金需求 cash-to-close', 'cash_to_close', 'money'], ['交割净值', 'equity', 'moneysigned'],
];
function fmtVal(kind, x) {
  if (x == null) return '—';
  if (kind === 'money') return money(x);
  if (kind === 'moneysigned') return signed(x, money);
  if (kind === 'pct') return pct1(x);
  if (kind === 'bps') return Math.round(x) + 'bps';
  return num2(x);
}

function scoreHtml(s, track) {
  const defs = track === 'residential' ? RES_METRICS : COM_METRICS;
  const veto = s.vetoes.length
    ? `<div class="veto-banner"><b>⛔ 一票否决（${s.vetoes.length} 项）：</b><ul>` +
      s.vetoes.map(v => `<li>${esc(v.message)}</li>`).join('') + '</ul></div>'
    : `<div class="veto-banner" style="background:#eef7ee;border-color:#bfe3bf"><b style="color:var(--green)">✅ 无否决项</b></div>`;
  const dg = (s.downgrades || []).length
    ? `<div class="veto-banner" style="background:#fef6e7;border-color:#f0d9a8"><b style="color:#b45309">⚠️ 降级提示（封顶降级，非一票否决）：</b><ul>` +
      s.downgrades.map(v => `<li>${esc(v.message)}</li>`).join('') + '</ul></div>'
    : '';
  const metrics = defs.map(([label, key, kind]) =>
    `<div class="metric"><div class="k">${label}</div><div class="v">${fmtVal(kind, s.metrics[key])}</div></div>`).join('');
  const dims = s.dimensions.map(dm => `
    <div class="dim"><div class="head"><span>${esc(dm.label)}</span><span>${dm.points} / ${dm.weight} 分</span></div>
    <div class="bar"><div style="width:${Math.min(100, dm.points / dm.weight * 100)}%"></div></div>
    <div class="detail">${esc(dm.detail)}</div></div>`).join('');
  const checks = s.checks.map(c =>
    `<tr><td>${c.ok ? '✅' : '❌'} ${esc(c.label)}</td><td>${esc(c.note)}</td></tr>`).join('');
  return `
    <div class="card" style="margin-bottom:14px"><div class="row" style="margin-top:0">
      <div><span class="badge ${esc(s.grade)}">${esc(s.grade)}</span>
      <span class="score-num" style="font-size:16px;margin-left:10px"><b>${s.total}</b> / 100 分</span></div>
    </div>${veto}${dg}</div>
    <h2 class="sec">测算结果（保守全口径）</h2><div class="metrics">${metrics}</div>
    <h2 class="sec">评分明细</h2>${dims}
    <h2 class="sec">阈值对照</h2>
    <table class="data"><tr><th>检查项</th><th>状态</th></tr>${checks}</table>`;
}

/* ---------------- 视图 ---------------- */
function render() {
  const app = $('#app');
  if (state.view === 'list') renderList(app);
  else if (state.view === 'form') renderForm(app);
  else if (state.view === 'detail') renderDetail(app);
  else if (state.view === 'compare') renderCompare(app);
}

function tabsHtml() {
  return `<div class="tabs">
    <button class="${state.track === 'residential' ? 'active' : ''}" data-track="residential">🏠 住宅项目</button>
    <button class="${state.track === 'commercial' ? 'active' : ''}" data-track="commercial">🏢 商业项目</button>
  </div>`;
}

async function loadProjects() {
  const qs = '/api/projects?track=' + state.track + (state.sortCash ? '&sort=cash_to_close' : '');
  state.projects = await api('GET', qs);
}

function renderList(app) {
  const cards = state.projects.map(p => {
    const s = p.score, m = s.metrics;
    const cf = state.track === 'residential' ? m.cash_flow_per_door : m.net_cf_monthly;
    return `<div class="card">
      <h3>${esc(p.name) || '(未命名)'}</h3><div class="addr">${esc(p.address)}</div>
      <div class="row"><span class="badge ${esc(s.grade)}">${esc(s.grade)}</span>
        <span class="score-num"><b>${s.total}</b>/100</span></div>
      <div class="kv">月净现金流 <b>${money(cf)}</b> · DSCR <b>${num2(s.metrics.dscr)}</b> · CoC <b>${pct1(s.metrics.cash_on_cash)}</b></div>
      <div class="kv">cash-to-close 全口径现金需求 <b>${money(s.metrics.cash_to_close ?? s.metrics.total_cash_required)}</b></div>
      ${s.vetoes.length ? `<div class="kv" style="color:var(--red)">⛔ ${s.vetoes.length} 项否决</div>` : ''}
      ${(s.downgrades || []).length ? `<div class="kv" style="color:#b45309">⚠️ ${s.downgrades.length} 项降级</div>` : ''}
      <div class="actions">
        <button class="btn" data-act="open" data-id="${p.id}">打开</button>
        <button class="btn" data-act="report" data-id="${p.id}">🖨️ 报告</button>
        <button class="btn" data-act="edit" data-id="${p.id}">编辑</button>
        <button class="btn danger" data-act="del" data-id="${p.id}">删除</button>
        <label style="font-size:13px"><input type="checkbox" data-act="cmp" data-id="${p.id}"
          ${state.compareIds.includes(p.id) ? 'checked' : ''}> 对比</label>
      </div></div>`;
  }).join('');
  app.innerHTML = tabsHtml() + `
    <div class="toolbar">
      <button class="btn primary" data-act="new">＋ 新建项目</button>
      <button class="btn" data-act="gocompare" ${state.compareIds.length < 2 ? 'disabled' : ''}>
        📊 对比选中（${state.compareIds.length}/3）</button>
      <button class="btn" data-act="sortcash">${state.sortCash ? '🔽 已按 cash-to-close 升序（点击取消）' : '💰 按 cash-to-close 升序'}</button>
      <span style="font-size:13px;color:var(--muted);align-self:center">评分口径：${state.track === 'residential' ? 'buyer-box.md v2.1' : 'buyer-box-commercial.md v1.1'}</span>
    </div>
    ${cards ? `<div class="grid">${cards}</div>` : '<div class="empty">暂无项目，点击"新建项目"开始录入。</div>'}
    <p class="note">分级：≥80 A（日报头条）· 65–79 B（日报收录）· 50–64 C（观察名单）· &lt;50 不收录 · 任一硬否决 = 否决。<br>
    本工具为筛选辅助，不构成投资建议；真实交易须经持牌律师 / CPA / title company 审查。</p>`;
}

function renderForm(app) {
  const secs = state.track === 'residential' ? RES_SECTIONS : COM_SECTIONS;
  const secsHtml = secs.map(s => `<div class="form-sec"><h3>${esc(s.title)}</h3>
    <div class="fgrid">${s.fields.map(fieldHtml).join('')}</div></div>`).join('');
  app.innerHTML = tabsHtml() + `
    <div class="toolbar"><button class="btn" data-act="back">← 返回列表</button>
      <span style="font-size:15px;font-weight:700;align-self:center">${state.editingId ? '编辑项目' : '新建项目'}（${state.track === 'residential' ? '住宅' : '商业'}）</span></div>
    ${secsHtml}
    <div class="toolbar">
      <button class="btn" data-act="preview">⚡ 一键打分预览（不保存）</button>
      <button class="btn primary" data-act="save">${state.editingId ? '保存修改' : '保存项目'}</button>
    </div>
    <div id="preview"></div>`;
  if (state._fill) { fillForm(state._fill); state._fill = null; }
}

async function renderDetail(app) {
  const p = state.detail;
  app.innerHTML = tabsHtml() + `
    <div class="toolbar"><button class="btn" data-act="back">← 返回列表</button>
      <button class="btn" data-act="report" data-id="${p.id}">🖨️ 打印报告</button>
      <button class="btn" data-act="edit" data-id="${p.id}">编辑</button>
      <button class="btn danger" data-act="del" data-id="${p.id}">删除</button></div>
    <h2 style="margin:4px 0 2px">${esc(p.name) || '(未命名)'}</h2>
    <div style="color:var(--muted);font-size:13px;margin-bottom:6px">${esc(p.address)} · ${esc(p.score.structure_label || p.score.asset_label || '')}</div>
    <div id="scorebox">${scoreHtml(p.score, p.track)}</div>
    <h2 class="sec">敏感性分析</h2><div id="sens"><div class="empty">加载中…</div></div>`;
  try {
    const sens = await api('POST', '/api/sensitivity',
      {track: p.track, name: p.name, address: p.address, input: p.input});
    $('#sens').innerHTML = sensHtml(sens, p.track);
  } catch (e) { $('#sens').innerHTML = `<div class="empty">敏感性分析加载失败：${esc(e.message)}</div>`; }
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
    if (v == null) return '—';
    if (kind === 'moneysigned') return signed(v, money);
    if (kind === 'rawpct') return v.toFixed(1) + '%';
    return num2(v);
  };
  const table = (title, rows, cols) => `
    <h3 style="font-size:14px;margin:14px 0 4px">${title}</h3>
    <table class="data"><tr><th>情景</th>${cols.map(c => `<th class="num">${c[1]}</th>`).join('')}</tr>
    ${rows.map(r => `<tr class="${r.label === '+0%' ? 'base' : ''}"><td>${r.label}</td>` +
      cols.map(c => `<td class="num">${cell(c[2], r[c[0]])}</td>`).join('') + '</tr>').join('')}</table>`;
  return table('租金变动情景（±10%）', sens.rent_table, rentCols)
       + table('利率变动情景（±2%）', sens.rate_table, rateCols);
}

async function renderCompare(app) {
  app.innerHTML = tabsHtml() + `<div class="toolbar"><button class="btn" data-act="back">← 返回列表</button></div>
    <div id="cmp"><div class="empty">加载中…</div></div>`;
  try {
    const items = await api('GET', '/api/compare?ids=' + state.compareIds.join(','));
    const rows = [
      ['项目', p => esc(p.name) || '(未命名)'], ['地址', p => esc(p.address)],
      ['结构', p => esc(p.score.structure_label || p.score.asset_label || '')],
      ['等级', p => `<span class="badge ${esc(p.score.grade)}">${esc(p.score.grade)}</span>`],
      ['总分', p => `<b>${p.score.total}</b>/100`],
      ['月净现金流', p => money(state.track === 'residential' ? p.score.metrics.cash_flow_monthly : p.score.metrics.net_cf_monthly)],
      ['DSCR', p => num2(p.score.metrics.dscr)],
      ['Cash-on-cash', p => pct1(p.score.metrics.cash_on_cash)],
      ['全口径现金需求', p => money(p.score.metrics.total_cash_required)],
      ['否决项', p => p.score.vetoes.length ? `<span style="color:var(--red)">${p.score.vetoes.length} 项</span>` : '无'],
    ];
    $('#cmp').innerHTML = `<table class="data"><tr><th></th>${items.map(p => `<th>${esc(p.name) || '(未命名)'}</th>`).join('')}</tr>` +
      rows.map(([label, fn]) => `<tr><th>${label}</th>${items.map(p => `<td>${fn(p)}</td>`).join('')}</tr>`).join('') + '</table>';
  } catch (e) { $('#cmp').innerHTML = `<div class="empty">对比加载失败：${esc(e.message)}</div>`; }
}

/* ---------------- 事件 ---------------- */
document.addEventListener('click', async e => {
  const tab = e.target.closest('[data-track]');
  if (tab) {
    state.track = tab.dataset.track; state.view = 'list'; state.compareIds = [];
    await loadProjects(); render(); return;
  }
  const btn = e.target.closest('[data-act]');
  if (!btn) return;
  const act = btn.dataset.act, id = btn.dataset.id ? +btn.dataset.id : null;
  try {
    if (act === 'new') { state.view = 'form'; state.editingId = null; state._fill = null; render(); }
    else if (act === 'back') { state.view = 'list'; await loadProjects(); render(); }
    else if (act === 'edit') {
      const p = await api('GET', '/api/projects/' + id);
      state.track = p.track; state.view = 'form'; state.editingId = id; state._fill = p.input; render();
    }
    else if (act === 'open') {
      const p = await api('GET', '/api/projects/' + id);
      state.track = p.track; state.view = 'detail'; state.detail = p; render();
    }
    else if (act === 'report') { window.open('/api/projects/' + id + '/report', '_blank'); }
    else if (act === 'del') {
      if (confirm('确定删除该项目吗？')) { await api('DELETE', '/api/projects/' + id); state.view = 'list'; await loadProjects(); render(); }
    }
    else if (act === 'preview') {
      const input = collectForm();
      const s = await api('POST', '/api/score', {track: state.track, name: '预览', address: '', input});
      $('#preview').innerHTML = '<h2 class="sec">打分预览</h2>' + scoreHtml(s, state.track);
      $('#preview').scrollIntoView({behavior: 'smooth'});
    }
    else if (act === 'save') {
      const input = collectForm();
      const payload = {track: state.track, name: input.name || '', address: input.address || '', input};
      let p;
      if (state.editingId) p = await api('PUT', '/api/projects/' + state.editingId, payload);
      else p = await api('POST', '/api/projects', payload);
      state.view = 'detail'; state.detail = p; render();
    }
    else if (act === 'gocompare') { state.view = 'compare'; render(); }
    else if (act === 'sortcash') { state.sortCash = !state.sortCash; await loadProjects(); render(); }
  } catch (err) { alert('操作失败：' + err.message); }
});

document.addEventListener('change', e => {
  const c = e.target.closest('[data-act="cmp"]');
  if (!c) return;
  const id = +c.dataset.id;
  if (c.checked) {
    if (state.compareIds.length >= 3) { c.checked = false; alert('最多对比 3 个项目'); return; }
    state.compareIds.push(id);
  } else state.compareIds = state.compareIds.filter(x => x !== id);
  render();
});

/* ---------------- 启动 ---------------- */
setInterval(() => {
  const el = $('#clock');
  if (el) el.textContent = new Date().toLocaleString('zh-CN', {hour12: false});
}, 1000);

(async function init() {
  try { await loadProjects(); } catch (e) { $('#app').innerHTML = `<div class="empty">后端连接失败：${esc(e.message)}<br>请确认服务已启动。</div>`; return; }
  render();
})();
