/* DealDesk 统一 dashboard（/d?addr=…&type=res|com）
 * 数据链：comps/pull → wb/valuate → score → confidence → verdict（全部现有端点＋Phase3 新端点）
 * 缺数据一律诚实标注（待接数据源/估算待核验），格子里不许出现编造的数字。
 */
'use strict';
const $ = s => document.querySelector(s);
const Q = new URLSearchParams(location.search);

const state = {
  addr: (Q.get('addr') || '').trim(),
  type: Q.get('type') === 'com' ? 'com' : 'res',
  ask: parseFloat(Q.get('price')) || null,
  ptype: Q.get('ptype') || '',
  comps: [], compsErr: null, selected: new Set(),
  valuation: null, markets: null, forecast: null, intake: null,
  score: null, confidence: null, verdict: null,
  uw: null, rentRoll: null,
  fetchedAt: new Date(),
  assumptions: {}, // Zone7 可编辑假设
  rentComps: [],  // 租金 comps（手动录入）
};

const TIERS = {rate_bps: [100, 200, 300], vacancy_pp: [0, 2, 5, 10], rent_pct: [-20, -10, -5, 0], combo: true};

function toast(msg, ms = 2600) {
  const t = $('#toast'); t.textContent = msg; t.style.display = 'block';
  clearTimeout(t._h); t._h = setTimeout(() => t.style.display = 'none', ms);
}
function esc(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function fmt$ (x, d = 0) {
  if (x == null || !isFinite(x)) return '—';
  const a = Math.abs(x);
  if (a >= 1e6) return '$' + (x / 1e6).toFixed(2) + 'M';
  if (a >= 1e3) return '$' + (x / 1e3).toFixed(d > 0 ? 1 : 0) + 'K';
  return '$' + x.toFixed(d);
}
function fmtPct(x, d = 1) { return (x == null || !isFinite(x)) ? '—' : (x * 100).toFixed(d) + '%'; }
function fmtNum(x, d = 0) { return (x == null || !isFinite(x)) ? '—' : x.toLocaleString('en-US', {maximumFractionDigits: d}); }
async function api(method, path, body) {
  const r = await fetch(path, {method, headers: {'Content-Type': 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body)});
  if (!r.ok) { const t = await r.text(); throw new Error(t.slice(0, 160) || ('HTTP ' + r.status)); }
  const ct = r.headers.get('content-type') || '';
  return ct.includes('json') ? r.json() : r.text();
}
const srcTag = k => k === 'g' ? '<span class="src g"><i></i>实数已验证</span>'
  : k === 'y' ? '<span class="src y"><i></i>估算待核验</span>'
  : '<span class="src w"><i></i>待接数据源</span>';
const pf = '<span class="pf">PF</span>';

/* ---------------- loading 步骤 ---------------- */
const STEPS = [
  ['comps', '拉取 TopHap 可比成交（recorded sales）'],
  ['valuate', '跑比较法估值'],
  ['markets', '查市场指数'],
  ['intake', '搜集物业档案（公开记录 enrich）'],
  ['forecast', '生成趋势外推（实验）'],
];
function renderSteps(status) {
  $('#loadSteps').innerHTML = STEPS.map(([id, label]) => {
    const s = status[id] || 'wait';
    const mark = s === 'done' ? '✓' : s === 'run' ? '<span class="spin"></span>' : s === 'fail' ? '✗' : '·';
    return `<div class="step ${s}"><span class="st">${mark}</span><span>${esc(label)}</span></div>`;
  }).join('');
}
function setStep(status, id, s) { status[id] = s; renderSteps(status); }

/* ---------------- 启动链 ---------------- */
async function boot() {
  $('#z0Addr').textContent = state.addr || '未输入地址';
  $('#z0Type').textContent = state.type === 'res' ? '住宅 · 小白模式' : '商业 · 专业模式';
  const status = {};
  renderSteps(status);

  // 1) comps
  setStep(status, 'comps', 'run');
  try {
    const r = await api('POST', '/api/wb/comps/pull', {address: state.addr});
    state.comps = (r.rows || []).map((c, i) => ({...c, _id: i}));
    state.comps.forEach(c => state.selected.add(c._id));
    setStep(status, 'comps', 'done');
  } catch (e) { state.compsErr = e.message; setStep(status, 'comps', 'fail'); }

  // 2) 估值（比较法；收益法待 score 后补）
  setStep(status, 'valuate', 'run');
  try {
    const comps = state.comps.filter(c => state.selected.has(c._id)).map(c => ({
      address: c.address, status: c.status || 'sold', price: c.price || 0,
      sale_date: c.sale_date || '', sf: c.sf || 0, distance_miles: c.distance_miles || 0,
      adjustment_pct: c.adjustment_pct || 0, noi_annual: c.noi_annual || 0,
      source: c.source || '', note: c.note || ''}));
    const v = await api('POST', '/api/wb/valuate', {
      property: {address: state.addr, prop_type: state.type === 'res' ? 'residential' : 'commercial'},
      comps, comp_weight: 0.5});
    state.valuation = v;
    setStep(status, 'valuate', 'done');
  } catch (e) { setStep(status, 'valuate', 'fail'); }

  // 3) 市场指数
  setStep(status, 'markets', 'run');
  try { state.markets = await api('GET', '/api/wb/markets'); setStep(status, 'markets', 'done'); }
  catch (e) { setStep(status, 'markets', 'fail'); }

  // 4) 物业档案（慢，不阻塞）
  setStep(status, 'intake', 'run');
  api('POST', '/api/wb/intake/run', {mode: 'address', text: state.addr})
    .then(r => { state.intake = r; setStep(status, 'intake', 'done'); renderZone7(); })
    .catch(() => setStep(status, 'intake', 'fail'));

  // 5) 预测
  setStep(status, 'forecast', 'run');
  try {
    const base = state.valuation?.reconciled?.reconciled || state.valuation?.comps?.estimate;
    if (base) {
      state.forecast = await api('POST', '/api/wb/forecast',
        {base_value: base, years: 5,
         scenarios: [
           {name: 'conservative', label: '保守', annual_rate_pct: 1.0},
           {name: 'base', label: '基准', annual_rate_pct: 3.0},
           {name: 'optimistic', label: '乐观', annual_rate_pct: 5.0}]});
      setStep(status, 'forecast', 'done');
    } else setStep(status, 'forecast', 'fail');
  } catch (e) { setStep(status, 'forecast', 'fail'); }

  $('#zLoad').hidden = true;
  for (const z of ['z1', 'z2', 'z3', 'z4', 'z5', 'z6', 'z7']) $('#' + z).hidden = false;
  $('#z0Stamp').textContent = '数据截至 ' + state.fetchedAt.toLocaleString('zh-CN', {hour12: false});
  initAccordions();
  renderAll();
  // 有要价 → 自动跑 score 链
  if (state.ask) { setAssumption('ask', state.ask); runScoreChain(); }
  else renderVerdictEmpty();
}

function initAccordions() {
  document.querySelectorAll('[data-acc]').forEach(btn => {
    if (btn._bound) return; btn._bound = true;
    const zone = document.getElementById(btn.dataset.acc);
    // 默认只展开 Zone 1-2（结论＋KPI 零点击）；移动端手风琴
    if (['z3', 'z4', 'z5', 'z6', 'z7'].includes(btn.dataset.acc)) zone.classList.add('closed');
    btn.addEventListener('click', () => {
      zone.classList.toggle('closed');
      btn.querySelector('.chev').textContent = zone.classList.contains('closed') ? '▸' : '▾';
    });
    btn.querySelector('.chev').textContent = zone.classList.contains('closed') ? '▸' : '▾';
  });
}

document.addEventListener('DOMContentLoaded', () => {
  if (!state.addr) {
    $('#loadSteps').innerHTML = '<div class="empty">没有地址参数。<a href="/">回 landing 输入地址</a></div>';
    return;
  }
  // 顶栏动作
  $('#btnToggle').addEventListener('click', () => {
    const t = state.type === 'res' ? 'com' : 'res';
    location.href = '/d?addr=' + encodeURIComponent(state.addr) + '&type=' + t
      + (state.ask ? '&price=' + state.ask : '') + (state.ptype ? '&ptype=' + encodeURIComponent(state.ptype) : '');
  });
  $('#btnPdf').addEventListener('click', () => $('#ddPdf').classList.toggle('open'));
  document.addEventListener('click', e => { if (!e.target.closest('#ddPdf')) $('#ddPdf').classList.remove('open'); });
  $('#btnPdfMemo').addEventListener('click', exportPdfMemo);
  $('#btnPrint').addEventListener('click', () => window.print());
  $('#btnXlsx').addEventListener('click', exportXlsx);
  $('#svExport').addEventListener('click', () => window.scrollTo({top: 0, behavior: 'smooth'}));
  boot();
});

/* ---------------- Zone 7 假设（可编辑）→ score 链 ---------------- */
const RES_FIELDS = [
  ['ask', '收购价/要价 $', true], ['rent', '月租金 $', true],
  ['rate', '年利率 %（百分制）', false], ['down', '首付 $', false],
  ['vac', '空置率 %', false], ['tax', '年房产税 $', false], ['ins', '年保险 $', false],
];
const COM_FIELDS = [
  ['ask', '收购价/要价 $', true], ['rentA', '年租金总收入 $', true],
  ['rate', '年利率 %（百分制）', false], ['downPct', '首付比例 %', false],
  ['amort', '摊销年数', false], ['vac', '空置率 %', false], ['capMkt', '市场 cap %', false],
];
const DEFAULTS = {rate: 6.5, down: 0, vac: 8, tax: 0, ins: 0, downPct: 30, amort: 25, capMkt: 6, rent: 0, rentA: 0};

function setAssumption(k, v) { state.assumptions[k] = v; }
function getA(k) {
  const v = state.assumptions[k];
  if (v === undefined || v === null || v === '') return DEFAULTS[k] ?? 0;
  return parseFloat(v) || 0;
}

function buildScoreInput() {
  if (state.type === 'res') {
    return {price: getA('ask'), monthly_rent: getA('rent'), rate: getA('rate'),
      down_payment: getA('down'), vacancy_pct: getA('vac'),
      taxes_annual: getA('tax'), insurance_annual: getA('ins')};
  }
  const ask = getA('ask'), downPct = getA('downPct') / 100;
  const loan = ask * (1 - downPct);
  return {price: ask, annual_base_rent: getA('rentA'), vacancy_pct: getA('vac'),
    market_cap_rate_pct: getA('capMkt'),
    tranches: loan > 0 ? [{balance: loan, rate: getA('rate'), term_years: getA('amort')}] : []};
}

async function runScoreChain() {
  const ask = getA('ask');
  if (!ask) { renderVerdictEmpty(); return; }
  toast('正在计算打分与 verdict…');
  try {
    const input = buildScoreInput();
    const score = await api('POST', '/api/score',
      {track: state.type === 'res' ? 'residential' : 'commercial',
       name: state.addr, address: state.addr, input});
    state.score = score;
    // 商业：跑 compute-plus（rent roll 若已导入则带入）
    if (state.type === 'com') await runUwPlus();
    // confidence
    const noiEv = state.type === 'res' ? 'seller_unverified'
      : (state.rentRoll && state.rentRoll.length ? 'seller_unverified' : 'proforma');
    const methods = buildMethodsEvidence();
    state.confidence = await api('POST', '/api/confidence', {
      track: state.type === 'res' ? 'residential' : 'commercial',
      comps: state.comps.filter(c => state.selected.has(c._id)),
      evidence: {noi_evidence: noiEv, cap_evidence: 'none', methods}});
    // verdict
    const ev = buildVerdictEvidence();
    state.verdict = await api('POST', '/api/verdict', {
      track: state.type === 'res' ? 'residential' : 'commercial',
      score, confidence: state.confidence.score, evidence: ev});
    toast('计算完成');
  } catch (e) { toast('计算失败：' + e.message, 4000); }
  renderAll();
}

function buildMethodsEvidence() {
  // 三法：sales（comps 区间）/ income（NOI÷cap）/ cost（缺）
  const sales = state.valuation?.comps?.range;
  let income = null;
  const capPct = state.type === 'res' ? 5 : getA('capMkt');
  const noiA = state.type === 'res'
    ? (state.score?.metrics?.noi_monthly || 0) * 12
    : (state.uw?.plus?.noi_bank_bridge?.bank_noi || state.score?.metrics?.noi || 0);
  if (noiA > 0 && capPct > 0) {
    const v = noiA / (capPct / 100);
    income = [v * 0.92, v * 1.08]; // cap ±50bps 等效区间
  }
  const m = {};
  if (sales && sales[0]) m.sales = sales;
  if (income) m.income = income;
  return Object.keys(m).length ? m : null;
}

function buildVerdictEvidence() {
  const rec = state.valuation?.reconciled;
  const ev = {ask_price: getA('ask')};
  if (rec?.range?.[1]) { ev.value_lo = rec.range[0]; ev.value_hi = rec.range[1]; }
  const gaps = [];
  if (state.comps.filter(c => state.selected.has(c._id)).length < 3) gaps.push('comps 不足 3 个');
  if (state.type === 'com') {
    if (state.uw) gaps.push(...(state.uw.plus.p0_gaps || []));
    else gaps.push('缺结构化 rent roll（WALT/到期集中度/租户集中度无法验证，NOI 可信度降级）');
  } else {
    gaps.push('租金为估算（待与租约/市场核验）');
  }
  ev.p0_gaps = gaps;
  // 三法分歧
  const vals = [];
  const compV = rec?.comp_value, incV = rec?.income_value;
  if (compV) vals.push(compV); if (incV) vals.push(incV);
  const m = buildMethodsEvidence();
  if (m?.sales && m?.income) {
    const cs = (m.sales[0] + m.sales[1]) / 2, ci = (m.income[0] + m.income[1]) / 2;
    ev.divergence_pct = Math.abs(cs - ci) / ((cs + ci) / 2) * 100;
  }
  return ev;
}

/* 商业 compute-plus：rent roll（已导入）＋ Zone7 假设 → 最小 uw 输入 */
async function runUwPlus() {
  const ask = getA('ask'), downPct = getA('downPct') / 100, rate = getA('rate') / 100;
  const tenants = (state.rentRoll || []).map(t => ({
    suite: t.suite, tenant: t.tenant, sf: t.sf, monthly_rent: t.monthly_rent,
    lease_start: t.lease_start, lease_end: t.lease_end,
    escalation: t.escalation, expense_structure: t.expense_structure}));
  const totalSf = tenants.reduce((s, t) => s + (t.sf || 0), 0);
  const input = {
    property: {name: state.addr, address: state.addr,
      property_type: state.ptype || 'commercial', net_rentable_sf: totalSf},
    tenants, vacant_sf: 0,
    historical: {vacancy_pct: getA('vac') / 100},
    proforma: {vacancy_pct: getA('vac') / 100},
    analysis: {purchase_price: ask, down_pct: downPct, rate, amort_years: getA('amort')},
  };
  try {
    state.uw = await api('POST', '/api/uw/compute-plus',
      {input, with_stress: true, valuation_range: null});
  } catch (e) { state.uw = null; }
}

/* ---------------- 导出 ---------------- */
async function exportPdfMemo() {
  $('#ddPdf').classList.remove('open');
  if (!state.score) { toast('先填 Zone 7 假设并计算', 3000); return; }
  toast('正在生成投资备忘录 PDF…');
  try {
    const track = state.type === 'res' ? 'residential' : 'commercial';
    const input = buildScoreInput();
    const r = await fetch('/api/memo/pdf', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({track, name: state.addr, address: state.addr, input,
        variant: state.type === 'com' ? 'enhanced' : 'classic'})});
    if (!r.ok) throw new Error(await r.text().then(t => t.slice(0, 120)));
    const blob = await r.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = r.headers.get('content-disposition')?.match(/filename\*?=(?:UTF-8''")?([^";]+)/)?.[1] || 'dealdesk_memo.pdf';
    a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    toast('已导出 PDF');
  } catch (e) { toast('PDF 生成失败：' + e.message, 4000); }
}

async function exportXlsx() {
  toast('正在生成 Excel…');
  try {
    let url, body;
    if (state.type === 'com') {
      if (!state.uw) { toast('商业 Excel 需要先导入 rent roll 并计算（Zone 4）', 3500); return; }
      // 用 compute-plus 的底层输入重建：直接调 xlsx 端点需 uw input，这里用 rentRoll＋假设重建
      const ask = getA('ask'), downPct = getA('downPct') / 100, rate = getA('rate') / 100;
      const tenants = (state.rentRoll || []).map(t => ({...t}));
      body = {input: {property: {name: state.addr, address: state.addr,
        property_type: state.ptype || 'commercial',
        net_rentable_sf: tenants.reduce((s, t) => s + (t.sf || 0), 0)},
        tenants, vacant_sf: 0,
        historical: {vacancy_pct: getA('vac') / 100},
        proforma: {vacancy_pct: getA('vac') / 100},
        analysis: {purchase_price: ask, down_pct: downPct, rate, amort_years: getA('amort')}},
        comps: state.comps.filter(c => state.selected.has(c._id))};
      url = '/api/uw/report/xlsx';
    } else {
      if (!state.score) { toast('先填 Zone 7 假设并计算', 3000); return; }
      body = {score: state.score, input: buildScoreInput(), address: state.addr,
        verdict: state.verdict, confidence: state.confidence,
        comps: state.comps.filter(c => state.selected.has(c._id))};
      url = '/api/res/report/xlsx';
    }
    const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)});
    if (!r.ok) throw new Error(await r.text().then(t => t.slice(0, 120)));
    const blob = await r.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = decodeURIComponent(r.headers.get('content-disposition')?.match(/filename\*=UTF-8''([^;]+)/)?.[1] || 'dealdesk.xlsx');
    a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    toast('已导出 Excel');
  } catch (e) { toast('Excel 生成失败：' + e.message, 4000); }
}

/* ---------------- 渲染 ---------------- */
function renderAll() {
  renderZone1(); renderZone2(); renderZone3(); renderZone4(); renderZone5(); renderZone6(); renderZone7();
  const v = state.verdict;
  $('#svWord').textContent = v ? v.verdict : '待计算';
  $('#svWord').className = 'sv-word ' + verdictClass(v?.verdict);
  $('#svMeta').textContent = v && !v.circuit_broken
    ? (state.valuation?.reconciled?.range
        ? fmt$(state.valuation.reconciled.range[0]) + '–' + fmt$(state.valuation.reconciled.range[1]) : '')
    : '';
}
function verdictClass(v) {
  if (!v) return 'v-na';
  if (['值得买', 'BUY'].includes(v)) return 'v-buy';
  if (['再看看', 'HOLD'].includes(v)) return 'v-hold';
  if (['别碰', 'PASS'].includes(v)) return 'v-pass';
  return 'v-na';
}

/* Zone 1 */
function renderVerdictEmpty() {
  const z1 = $('#z1'); z1.hidden = false;
  $('#vWord').textContent = '缺收购价';
  $('#vWord').className = 'verdict-word v-na';
  $('#vOne').textContent = '填一下"要价/收购价"（下方 Zone 7），我才能算值不值得买。comps 和估值已经就绪。';
  $('#vConfNum').textContent = '';
  $('#vConfLabel').textContent = '';
  $('#vRange').textContent = '';
  $('#vCash').textContent = '';
  $('#vVetoes').innerHTML = ''; $('#vReasons').innerHTML = '';
  $('#vUsage').textContent = state.type === 'res'
    ? '筛选辅助工具，不构成投资建议。' : '投资筛选用，非 USPAP 合规评估报告，不能用于贷款/诉讼；未实地勘察、未审阅租约原件。';
  $('#z1Gaps').innerHTML = '';
  renderZone2(); renderZone3(); renderZone4(); renderZone5(); renderZone6(); renderZone7();
}

function renderZone1() {
  const z1 = $('#z1'); z1.hidden = false;
  const v = state.verdict;
  if (!v) { renderVerdictEmpty(); return; }
  const w = $('#vWord');
  w.textContent = v.verdict;
  w.className = 'verdict-word ' + verdictClass(v.verdict);
  $('#vOne').textContent = v.one_liner || '';
  const c = state.confidence;
  if (c) {
    $('#vConfFill').style.width = Math.min(100, c.score) + '%';
    $('#vConfNum').textContent = c.score + '/100';
    $('#vConfLabel').textContent = '（' + c.label + '）';
  }
  const rec = state.valuation?.reconciled;
  $('#vRange').textContent = rec?.range?.[1]
    ? '估值区间 ' + fmt$(rec.range[0]) + '–' + fmt$(rec.range[1]) + '（永远区间，不给单点）'
    : '估值区间待计算';
  const m = state.score?.metrics || {};
  const cash = m.cash_to_close ?? m.total_cash_required;
  $('#vCash').textContent = cash ? '全口径现金需求 ≈ ' + fmt$(cash) + '（首付＋交割＋储备金）' : '';
  const vetoes = state.score?.vetoes || [];
  $('#vVetoes').innerHTML = vetoes.slice(0, 2).map(x =>
    `<p class="veto">一票否决：${esc(x.message || x.code)}</p>`).join('');
  $('#vReasons').innerHTML = (v.reasons || []).map(r =>
    `<p class="reason">· ${esc(r)}</p>`).join('');
  $('#vUsage').textContent = v.usage || '';
  // P0 缺口（Zone1 右侧）
  const gaps = state.type === 'com' && state.uw ? state.uw.plus.p0_gaps : [];
  $('#z1Gaps').innerHTML = gaps.length
    ? `<div class="amber"><b>缺口（已保守降级）：</b><br>${gaps.map(g => '· ' + esc(g)).join('<br>')}</div>` : '';
}

/* Zone 2 */
function renderZone2() {
  const z2 = $('#z2'); z2.hidden = false;
  const m = state.score?.metrics || {};
  const cards = [];
  const kpi = (label, val, sub, note, cls) =>
    `<div class="kpi"><div class="k-label">${label}</div><div class="k-val ${cls || ''}">${val}</div>
     <div class="k-sub">${sub || ''}</div>${note ? `<div class="k-note">${note}</div>` : ''}</div>`;
  if (state.type === 'res') {
    const cf = m.cash_flow_monthly;
    cards.push(kpi('月现金流', fmt$(cf), cf >= 0 ? '租金覆盖月供还有剩' : '贴钱持有',
      '比存银行高，但要自己管租客', cf >= 0 ? 'k-ok' : 'k-bad'));
    cards.push(kpi('现金回报率 CoC', fmtPct(m.cash_on_cash), '年净现金流 ÷ 全口径现金投入', ''));
    cards.push(kpi('租金 vs 月供', fmt$(getA('rent')) + ' vs ' + fmt$(m.piti),
      '租金能覆盖 ' + (m.piti ? ((getA('rent') / m.piti * 100).toFixed(0) + '%') : '—') + ' 的月供', ''));
    cards.push(kpi('空置假设', fmtPct(getA('vac') / 100), '租金打 ' + (100 - getA('vac')).toFixed(0) + ' 折计', ''));
    if (!state.score) cards.push(kpi('打分', '待计算', 'Zone 7 填要价后计算', ''));
  } else {
    const uw = state.uw?.plus, a = state.uw?.analysis || {};
    const bankNoi = uw?.noi_bank_bridge?.bank_noi;
    const askV = getA('ask');
    cards.push(kpi('价格', askV ? fmt$(askV) : '待填要价', '收购价/要价', ''));
    cards.push(kpi('NOI（双口径）',
      bankNoi != null ? fmt$(bankNoi) : '—',
      '银行口径' + (m.noi ? '；标准 NOI ' + fmt$(m.noi) : ''), uw ? '' : '待 rent roll 导入'));
    const capIn = bankNoi && getA('ask') ? bankNoi / getA('ask') : null;
    cards.push(kpi('Trailing cap', fmtPct(capIn, 2),
      '市场区间待接 ' + srcTag('w'), '单个 cap 数字不许单独出现'));
    if (uw) {
      const dd = uw.dscr_dual;
      cards.push(kpi('DSCR 双轨',
        dd.trailing.dscr.toFixed(2) + 'x / ' + dd.proforma.dscr.toFixed(2) + 'x' + pf,
        'trailing 主 / pro forma 辅', dd.trailing.label,
        dd.trailing.dscr >= 1.2 ? 'k-ok' : 'k-bad'));
      cards.push(kpi('Debt Yield', fmtPct(uw.debt_yield, 2),
        'NOI（银行口径）÷ 拟贷款额', '≥8-10% 舒适；<6% 机构资金出局',
        uw.debt_yield >= 0.08 ? 'k-ok' : uw.debt_yield >= 0.06 ? 'k-warn' : 'k-bad'));
      const be = a.breakeven_occupancy;
      cards.push(kpi('盈亏平衡', fmtPct(be),
        '缓冲垫 ' + fmtPct(Math.max(0, (uw.rent_roll_detail.occupancy || 0) - be)) ,
        be > 1 ? '满租都不够还贷 → PASS' : be > 0.9 ? '偏薄' : '安全边际厚',
        be > 1 ? 'k-bad' : be > 0.9 ? 'k-warn' : 'k-ok'));
    } else {
      cards.push(kpi('DSCR', '待 rent roll', '导入租约明细后计算', ''));
      cards.push(kpi('Debt Yield', '待 rent roll', '', ''));
      cards.push(kpi('盈亏平衡', '待 rent roll', '', ''));
    }
  }
  z2.innerHTML = cards.join('');
}

/* Zone 3：价格公允性 */
function renderZone3() {
  const body = $('#z3Body');
  const val = state.valuation, comps = state.comps;
  if (!val && !comps.length) {
    body.innerHTML = `<div class="empty">还没有 comps 数据——TopHap 没返回该地址的可比成交，换个地址或手动导入 CSV ${srcTag('w')}</div>`;
    return;
  }
  const cv = val?.comps || {};
  const sel = comps.filter(c => state.selected.has(c._id));
  const psfs = sel.map(c => c.price_per_sf).filter(x => x > 0).sort((a, b) => a - b);
  const medPsf = psfs.length ? psfs[Math.floor(psfs.length / 2)] : null;
  const ask = getA('ask');
  const overPct = (ask && cv.median_adjusted) ? (ask - cv.median_adjusted) / cv.median_adjusted : null;
  const verdictLine = overPct == null ? '填要价后对比 comps 中位'
    : overPct <= -0.05 ? `低于 comps 中位 ${fmtPct(-overPct, 0)}` 
    : overPct >= 0.05 ? `高于 comps 中位 ${fmtPct(overPct, 0)}` : '与 comps 中位基本持平';

  // 三法区间（商业）
  let methodsHtml = '';
  if (state.type === 'com') {
    const me = buildMethodsEvidence() || {};
    const bar = (name, range, note) => {
      if (!range) return `<div class="note">${name}：缺数据 ${srcTag('w')}（${note}）</div>`;
      return `<div class="frow"><span class="fl">${name}</span>
        <span class="fv">${fmt$(range[0])} – ${fmt$(range[1])}</span></div>`;
    };
    methodsHtml = `<p class="zsub">三法区间并列（hero 只给调和结果）</p><div class="formula">
      ${bar('收益法 Income', me.income, 'NOI÷cap，需 cap 证据')}
      ${bar('比较法 Sales', me.sales, 'recorded sales')}
      ${bar('成本法 Cost', null, '待接数据源')}
      <div class="frow"><span class="fl">权重披露</span><span class="fv" style="font-weight:500;font-size:12px">收益法 50%（NOI 经租约支持）/ 比较法 50%</span></div>
    </div>`;
  }

  // 横向柱
  const maxP = Math.max(ask || 0, ...sel.map(c => c.adjusted_price || c.price || 0), 1);
  const bars = [
    ask ? `<div class="hbar-row me"><span>本物业（要价）</span>
      <div class="hbar-track"><div class="hbar-fill" style="width:${(ask / maxP * 100).toFixed(1)}%"></div></div>
      <span class="hbar-val">${fmt$(ask)}</span></div>` : '',
    ...sel.map(c => {
      const p = c.adjusted_price || c.price || 0;
      return `<div class="hbar-row"><span>${esc(c.address || 'comp')}</span>
        <div class="hbar-track"><div class="hbar-fill" style="width:${(p / maxP * 100).toFixed(1)}%"></div></div>
        <span class="hbar-val">${fmt$(p)}</span></div>`;
    })].join('');

  // comp 勾选器
  const rows = comps.map(c => {
    const on = state.selected.has(c._id);
    const bigAdj = Math.abs(c.adjustment_pct || 0) > 25;
    return `<tr class="${on ? '' : 'off'} ${bigAdj ? 'hl-yellow' : ''}" data-cid="${c._id}">
      <td><input type="checkbox" data-comp="${c._id}" ${on ? 'checked' : ''} aria-label="选用"></td>
      <td>${esc(c.address || '')}<br><span class="note">${esc(c.sale_date || '')} · ${esc(c.source || '')}</span></td>
      <td class="num">${fmt$(c.price)}</td><td class="num">${fmtNum(c.sf)}</td>
      <td class="num">${fmt$(c.price_per_sf, 0)}</td>
      <td class="num">${bigAdj ? '⚠ ' : ''}${fmtPct((c.adjustment_pct || 0) / 100, 0)}</td></tr>`;
  }).join('');

  body.innerHTML = `
    <p class="zsub">${esc(verdictLine)}${srcTag(state.compsErr ? 'w' : 'g')}</p>
    ${methodsHtml}
    <div class="formula">
      <div class="frow"><span class="fl">Base Estimate（比较法）</span><span class="fv">${fmt$(cv.estimate)}</span></div>
      <div class="frow"><span class="fl">Condition Adjustment</span><span class="fv" id="condAdjVal">未调整（无依据不做）</span></div>
      <div class="frow hero"><span class="fl">Value Range（调和）</span><span class="fv">${state.valuation?.reconciled?.range ? fmt$(state.valuation.reconciled.range[0]) + ' – ' + fmt$(state.valuation.reconciled.range[1]) : '—'}</span></div>
      <div class="frow"><span class="fl">Confidence Score</span><span class="fv">${state.confidence ? state.confidence.score + '/100' : '待计算'}</span></div>
    </div>
    <div class="fgrid">
      <div class="field"><label>标的成色（五档）</label>
        <select id="condTier"><option>Excellent</option><option>Good</option><option selected>Average</option><option>Fair</option><option>Poor</option></select></div>
      <div class="field"><label>调整依据（必填，无依据不做）</label>
        <input id="condBasis" placeholder="如：基于 $45/SF 翻新成本 × 12,000 SF"></div>
      <div class="field"><label>&nbsp;</label><button class="btn" id="condApply">应用成色调整</button></div>
    </div>
    <p class="zsub">本物业 vs 选中 comps（降序）</p>
    ${bars || '<div class="empty">无 comps</div>'}
    <p class="zsub" style="margin-top:14px">comp 勾选器（勾选/剔除实时重算汇总）${sel.length} / ${comps.length} 选中 ·
      中位 $/SF ${medPsf ? fmt$(medPsf, 0) : '—'}</p>
    <table class="data"><thead><tr><th></th><th>地址</th><th class="num">成交价</th><th class="num">面积</th><th class="num">$/SF</th><th class="num">调整%</th></tr></thead>
    <tbody>${rows}</tbody></table>
    <p class="note">comps 只是起点，出价前请核验相似度/日期/位置/成色/市场动向。gross adjustment &gt; 25% 的 comp 已标黄。只认 recorded sales；listing 挂牌价不是证据。</p>
    ${state.type === 'com' ? renderRentCompsTab() : ''}`;

  body.querySelectorAll('[data-comp]').forEach(cb => cb.addEventListener('change', async () => {
    const id = parseInt(cb.dataset.comp);
    cb.checked ? state.selected.add(id) : state.selected.delete(id);
    // 重跑估值（只用选中 comps）
    try {
      const comps = state.comps.filter(c => state.selected.has(c._id)).map(c => ({
        address: c.address, status: c.status || 'sold', price: c.price || 0,
        sale_date: c.sale_date || '', sf: c.sf || 0, distance_miles: c.distance_miles || 0,
        adjustment_pct: c.adjustment_pct || 0, source: c.source || ''}));
      state.valuation = await api('POST', '/api/wb/valuate', {
        property: {address: state.addr, prop_type: state.type === 'res' ? 'residential' : 'commercial'},
        comps, comp_weight: 0.5});
    } catch (e) { /* 保持旧估值 */ }
    renderZone3(); renderZone1();
  }));
  const caBtn = $('#condApply');
  if (caBtn) caBtn.addEventListener('click', applyConditionAdjust);
}

async function applyConditionAdjust() {
  const basis = $('#condBasis').value.trim();
  const tier = $('#condTier').value;
  if (!basis) { toast('调整依据必填：无依据宁可不做', 3000); return; }
  try {
    const r = await api('POST', '/api/condition/adjust',
      {subject_tier: tier, comp_tier: 'Average', comp_price: state.valuation?.comps?.median_adjusted || 0, basis});
    $('#condAdjVal').textContent = r.applied
      ? `${r.direction}${(r.rate * 100).toFixed(1)}%（${r.basis.slice(0, 24)}…）`
      : r.reason;
    toast(r.applied ? '已应用成色调整' : r.reason, 3000);
  } catch (e) { toast('调整失败：' + e.message, 3000); }
}

/* 租金 comps 页签（商业） */
function renderRentCompsTab() {
  const rows = state.rentComps.map((r, i) =>
    `<tr><td>${esc(r.address)}</td><td>${esc(r.date)}</td><td class="num">${fmt$(r.rentNnn, 0)}/SF/年</td>
     <td class="num">${esc(r.freeRent)}</td><td class="num">${fmt$(r.ti, 0)}</td>
     <td><button class="btn ghost" data-rdel="${i}" style="min-height:36px">删</button></td></tr>`).join('');
  return `<div style="margin-top:18px"><p class="zsub">租金 comps（lease comps，独立页签）${srcTag(state.rentComps.length ? 'y' : 'w')}</p>
  ${state.rentComps.length ? `<table class="data"><thead><tr><th>地址</th><th>签约时间</th><th class="num">租金 NNN 等值</th><th class="num">免租期</th><th class="num">TI</th><th></th></tr></thead><tbody>${rows}</tbody></table>`
    : `<div class="amber"><b>待接数据源：</b>租金 comps 库未接入。字段要求：地址/签约时间/租金 NNN 等值/免租期/TI；所有租金统一 NNN 等值口径（Gross − 当年实际运营费用）。可先手动录入。</div>`}
  <div class="fgrid">
    <div class="field"><label>地址</label><input id="rcAddr"></div>
    <div class="field"><label>签约时间</label><input id="rcDate" placeholder="2026-03"></div>
    <div class="field"><label>租金 NNN 等值（$/SF/年）</label><input id="rcRent" type="number"></div>
    <div class="field"><label>免租期</label><input id="rcFree" placeholder="如：3 个月"></div>
    <div class="field"><label>TI $</label><input id="rcTi" type="number"></div>
    <div class="field"><label>&nbsp;</label><button class="btn" id="rcAdd">手动录入</button></div>
  </div>
  <p class="note">缺免租期和 TI 的租金没有可比性。</p></div>`;
}
document.addEventListener('click', e => {
  if (e.target.id === 'rcAdd') {
    const rent = parseFloat($('#rcRent').value);
    if (!$('#rcAddr').value.trim() || !rent) { toast('地址和租金必填', 2500); return; }
    state.rentComps.push({address: $('#rcAddr').value.trim(), date: $('#rcDate').value.trim(),
      rentNnn: rent, freeRent: $('#rcFree').value.trim(), ti: parseFloat($('#rcTi').value) || 0});
    renderZone3(); toast('已录入 1 条租金 comp');
  }
  if (e.target.dataset.rdel !== undefined) {
    state.rentComps.splice(parseInt(e.target.dataset.rdel), 1); renderZone3();
  }
});

/* ---------------- Zone 4：现金流 ---------------- */
function renderZone4() {
  const body = $('#z4Body');
  if (state.type === 'res') {
    const m = state.score?.metrics || {};
    if (!state.score) {
      body.innerHTML = `<div class="empty">填 Zone 7 假设并计算后，这里显示现金流构成与 what-if 滑杆。</div>`;
      return;
    }
    const rent = getA('rent'), vac = getA('vac') / 100;
    const parts = [
      ['租金', rent, 'var(--green)'], ['− 空置', -rent * vac, 'var(--amber)'],
      ['− 税/险/杂', -(m.opex - rent * vac) || 0, 'var(--amber)'],
      ['− 月供', -m.piti || 0, 'var(--red)'], ['= 净现金流', m.cash_flow_monthly, 'var(--teal)'],
    ];
    const maxA = Math.max(...parts.map(p => Math.abs(p[1])), 1);
    const bars = parts.map(([l, v, c]) =>
      `<div class="hbar-row"><span>${l}</span>
       <div class="hbar-track"><div class="hbar-fill" style="width:${(Math.abs(v) / maxA * 100).toFixed(1)}%;background:${c}"></div></div>
       <span class="hbar-val">${fmt$(v)}</span></div>`).join('');
    body.innerHTML = `
      <p class="zsub">每月净剩 ${fmt$(m.cash_flow_monthly)} ${srcTag('y')}</p>
      ${bars}
      <p class="zsub" style="margin-top:12px">what-if（拖动实时重算）</p>
      <div class="slider-row"><span>租金</span>
        <input type="range" id="slRent" min="-20" max="20" value="0" step="1" aria-label="租金调整">
        <span class="slider-val" id="slRentV">±0%</span></div>
      <div class="slider-row"><span>利率</span>
        <input type="range" id="slRate" min="-2" max="2" value="0" step="0.25" aria-label="利率调整">
        <span class="slider-val" id="slRateV">±0%</span></div>
      <p class="note">这意味着什么：月现金流 ${fmt$(m.cash_flow_monthly)}，${m.cash_flow_monthly >= 0 ? '租金能覆盖月供还有剩' : '每月要贴钱'}。</p>`;
    const rerun = async () => {
      const rp = parseFloat($('#slRent').value), rt = parseFloat($('#slRate').value);
      $('#slRentV').textContent = (rp >= 0 ? '+' : '') + rp + '%';
      $('#slRateV').textContent = (rt >= 0 ? '+' : '') + rt + '%';
      const input = buildScoreInput();
      input.monthly_rent = input.monthly_rent * (1 + rp / 100);
      input.rate = Math.max(0, input.rate + rt);
      try {
        state.score = await api('POST', '/api/score',
          {track: 'residential', name: state.addr, address: state.addr, input});
        const ev = buildVerdictEvidence();
        state.verdict = await api('POST', '/api/verdict',
          {track: 'residential', score: state.score, confidence: state.confidence.score, evidence: ev});
        renderZone1(); renderZone2(); renderZone4();
      } catch (e) { /* 保持 */ }
    };
    $('#slRent').addEventListener('change', rerun);
    $('#slRate').addEventListener('change', rerun);
    return;
  }
  // ---- 商业 ----
  const uw = (state.uw && state.uw.plus && state.uw.plus.has_rent_roll) ? state.uw.plus : null;
  if (!uw) {
    body.innerHTML = `
      <div class="amber"><b>租约明细待补充：</b>WALT / 到期集中度 / 租户集中度无法验证，NOI 可信度降级。
      ${state.type === 'com' ? '无 rent roll 的 deal 最高只给 HOLD。' : ''}</div>
      <p class="zsub">导入 rent roll（Excel 模板 / 粘贴），再跑银行口径核保</p>
      <div class="fgrid">
        <div class="field"><label>&nbsp;</label>
          <a class="btn" style="display:inline-block;text-decoration:none;line-height:44px;text-align:center" href="/api/uw/rentroll/template.xlsx">下载 Excel 模板</a></div>
        <div class="field"><label>上传填好的模板</label><input type="file" id="rrFile" accept=".xlsx"></div>
        <div class="field"><label>&nbsp;</label><button class="btn primary" id="rrGo">导入并核保</button></div>
      </div>
      <p class="note">顺序：rent roll 明细 → NOI 调整桥 → DSCR 双轨 → 盈亏平衡 → 压力测试。NOI 是 rent roll 的孩子。</p>`;
    const go = async () => {
      const f = $('#rrFile').files[0];
      if (!f) { toast('先选择 Excel 文件', 2500); return; }
      toast('正在导入 rent roll…');
      const fd = new FormData(); fd.append('file', f);
      try {
        const r = await fetch('/api/uw/rentroll/parse', {method: 'POST', body: fd});
        if (!r.ok) throw new Error(await r.text().then(t => t.slice(0, 120)));
        const j = await r.json();
        state.rentRoll = j.tenants;
        toast(`导入 ${j.count} 个租户，正在核保…`);
        await runUwPlus();
        if (state.score) await runScoreChain(); else { renderAll(); }
        toast('核保完成');
      } catch (e) { toast('导入失败：' + e.message, 4000); }
    };
    $('#rrGo').addEventListener('click', go);
    return;
  }
  const rr = uw.rent_roll_detail;
  const rows = rr.rows.map(t =>
    `<tr><td>${esc(t.suite)}</td><td>${esc(t.tenant)}</td><td class="num">${fmtNum(t.sf)}</td>
     <td class="num">${fmt$(t.monthly_rent)}</td><td>${esc(t.lease_start)} → ${esc(t.lease_end)}</td>
     <td>${esc(t.expense_structure)}</td></tr>`).join('');
  const bridge = uw.noi_bank_bridge.rows.map(r =>
    `<div class="wf-row ${r.item === '银行口径 NOI' ? 'total' : ''}">
       <span class="wi">${esc(r.item)} ${srcTag(r.tag === 'green' ? 'g' : 'y')}</span>
       <span class="wv">${fmt$(r.amount)}</span></div>
     <div class="note" style="margin:0 0 4px">${esc(r.basis)}</div>`).join('');
  const buckets = uw.rent_roll_detail.expiry_buckets;
  const maxB = Math.max(...Object.values(buckets), 1);
  const ladder = Object.entries(buckets).map(([y, v]) =>
    `<div class="hbar-row"><span>${y}</span>
     <div class="hbar-track"><div class="hbar-fill" style="width:${(v / maxB * 100).toFixed(1)}%;${v / maxB > 0.4 ? 'background:var(--red)' : ''}"></div></div>
     <span class="hbar-val">${fmt$(v)}</span></div>`).join('');
  const st = uw.stress.rows.map(r => {
    const b = r.breaks;
    const cell = (v, bad, fmt) => `<td class="num ${bad ? 'cell-bad' : ''}">${fmt(v)}</td>`;
    return `<tr><td>${esc(r.scenario)}</td>${cell(r.dscr_trailing, b.dscr, x => x.toFixed(2) + 'x')}
      ${cell(r.debt_yield, b.debt_yield, x => fmtPct(x, 1))}${cell(r.breakeven, b.breakeven, x => fmtPct(x, 0))}</tr>`;
  }).join('');
  const dd = uw.dscr_dual;
  body.innerHTML = `
    <p class="zsub">rent roll 明细（${rr.tenant_count} 租户）${srcTag('y')}</p>
    <table class="data"><thead><tr><th>单元</th><th>租户</th><th class="num">面积</th><th class="num">月租金</th><th>租期</th><th>费用结构</th></tr></thead>
    <tbody>${rows || '<tr><td colspan="6">无租户行</td></tr>'}</tbody></table>
    <p class="note">WALT ${rr.walt_years != null ? rr.walt_years + ' 年（租金加权）' : '—：' + esc(rr.walt_note)} ·
      前三租户集中度 ${fmtPct(rr.top3_concentration)}${rr.top3_flag ? '（>60% 单租户风险）' : ''}</p>
    <p class="zsub">NOI 银行调整桥 waterfall</p>${bridge}
    <p class="zsub">未来 5 年到期租金（到期悬崖标红）</p>${ladder}
    <p class="zsub">DSCR 双轨</p>
    <div class="formula">
      <div class="frow hero"><span class="fl">Trailing 主</span><span class="fv">${dd.trailing.dscr.toFixed(2)}x</span></div>
      <div class="frow"><span class="fl" colspan="2" style="font-size:12px;color:var(--muted)">${esc(dd.trailing.label)}</span></div>
      <div class="frow"><span class="fl">Pro forma 辅 ${pf}</span><span class="fv">${dd.proforma.dscr.toFixed(2)}x</span></div>
      <div class="frow"><span class="fl" colspan="2" style="font-size:12px;color:var(--muted)">${esc(dd.proforma.label)}</span></div>
    </div>
    <p class="zsub">压力测试表（破红线标红；+200bps 后 DSCR&lt;1.20 即条件通过，破 1.0 结构不可行）</p>
    <table class="data"><thead><tr><th>档位</th><th class="num">DSCR</th><th class="num">Debt Yield</th><th class="num">Breakeven</th></tr></thead>
    <tbody>${st}</tbody></table>
    <p class="note">红线：DSCR ≥1.20 / Debt Yield ≥6% / Breakeven ≤100%。</p>`;
}

/* ---------------- Zone 5：市场 ---------------- */
function renderZone5() {
  const body = $('#z5Body');
  const mk = state.markets;
  const zip = (state.addr.match(/\b\d{5}\b/) || [])[0] || '';
  let zipBlock = '';
  if (mk && zip) {
    const found = (mk.markets || []).some(m =>
      JSON.stringify(m).includes(zip));
    zipBlock = found
      ? `<div class="note">该邮编 ${zip} 有市场指数覆盖 ${srcTag('g')}</div>`
      : `<div class="amber"><b>该邮编 ${zip} 暂无市场指数</b>——不许静默用 MSA 代替 ${srcTag('w')}</div>`;
  } else {
    zipBlock = `<div class="amber"><b>市场指数待查：</b>地址中未识别邮编，或市场库未覆盖 ${srcTag('w')}</div>`;
  }
  // cap 直方图（商业，用 comps 的 cap 代理：成交 NOI 缺失 → 诚实说明）
  let hist = '';
  if (state.type === 'com') {
    const withNoi = state.comps.filter(c => c.noi_annual > 0 && c.price > 0);
    hist = withNoi.length
      ? `<p class="note">cap 分布基于 ${withNoi.length} 个有 NOI 的 comps</p>`
      : `<div class="empty">cap 分布：成交 NOI 非公开，整列灰显，仅供参考 ${srcTag('w')}</div>`;
  }
  // 合同 vs 市场租金 reversion（商业）
  let rev = '';
  if (state.type === 'com') {
    rev = `<p class="zsub">合同 vs 市场租金 reversion</p>
      <div class="amber"><b>待接数据源：</b>市场租金缺口——租金 comps 库未接入，reversion 无法计算 ${srcTag('w')}</div>
      <p class="note">冲突检查：listing 租金涨幅假设 vs 市场实际增速——市场数据缺失时不做断言。</p>`;
  }
  body.innerHTML = `
    ${zipBlock}${hist}${rev}
    <p class="zsub">市场指标（公开指数）</p>
    <p class="note">数据源：${esc(mk?.methodology || 'FHFA 公开房价指数')} ·
      发布：${esc(mk?.release || '')} ${esc(mk?.release_date || '')}</p>
    <table class="data"><thead><tr><th>市场</th><th>说明</th></tr></thead><tbody>
    ${(mk?.markets || []).slice(0, 8).map(m =>
      `<tr><td>${esc(m.name || m.id || '')}</td><td class="note">${esc(m.note || '')}</td></tr>`).join('')}
    </tbody></table>
    <p class="note">每行误差标注：基于公开指数，历史误差约 ±X%（以发布机构口径为准）。新增供给 pipeline：待接数据源 ${srcTag('w')}</p>`;
}

/* ---------------- Zone 6：预测 ---------------- */
function renderZone6() {
  const body = $('#z6Body');
  const fc = state.forecast;
  const sleeve = '<span class="tag exp">趋势外推（实验）</span>';
  if (!fc || !fc.scenarios) {
    body.innerHTML = `<div class="empty">预测缺数据 ${sleeve} ${srcTag('w')}</div>`;
    return;
  }
  const base = fc.base_value || 0;
  const rows = fc.scenarios.map(s => {
    const pts = (s.points || []).map((p, i) => `Y${i}: ${fmt$(p.value)}`).join(' · ');
    const end = s.points?.length ? s.points[s.points.length - 1].value : 0;
    return `<div class="frow"><span class="fl">${esc(s.label)}（${s.annual_rate_pct}%/年）${s.name !== 'base' ? '' : ''}</span>
      <span class="fv">${fmt$(end)}</span></div><div class="note" style="margin:0 0 6px">${esc(pts)}</div>`;
  }).join('');
  // SVG 折线
  const W = 560, H = 180, P = 30;
  const all = fc.scenarios.flatMap(s => (s.points || []).map(p => p.value)).filter(v => v > 0);
  const lo = Math.min(...all, base) * 0.95, hi = Math.max(...all, base) * 1.05;
  const X = i => P + i * (W - 2 * P) / 4, Y = v => H - P - (v - lo) / (hi - lo) * (H - 2 * P);
  const colors = {conservative: '#60a5fa', base: '#2dd4bf', optimistic: '#fbbf24'};
  const paths = fc.scenarios.map(s => {
    const pts = (s.points || []).map((p, i) => `${X(i).toFixed(0)},${Y(p.value).toFixed(0)}`).join(' ');
    return `<polyline points="${pts}" fill="none" stroke="${colors[s.name] || '#a3b1c9'}" stroke-width="2" stroke-dasharray="${s.name === 'base' ? 'none' : '5,4'}"/>`;
  }).join('');
  body.innerHTML = `
    <p class="zsub">模型预测 5 年后值 ${fmt$(fc.scenarios.find(s => s.name === 'base')?.points?.[5]?.value)} ${sleeve}</p>
    <svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:640px;background:var(--bg1);border:1px solid var(--line);border-radius:6px" role="img" aria-label="5 年估值预测">
      ${paths}
      <text x="${P}" y="${H - 8}" fill="#64748f" font-size="10">现在</text>
      <text x="${W - P - 30}" y="${H - 8}" fill="#64748f" font-size="10">5 年后</text>
    </svg>
    <div class="formula" style="margin-top:10px">${rows}</div>
    <p class="note">模型预测，基于过去 N 年趋势外推，方法未公开；历史回测误差约 ±Z%（如可得）；不构成投资建议；银行承销不采用。forecast 输出绝不回流进 DSCR/NOI/verdict 计算。</p>
    ${state.type === 'com' ? '<p class="note">商业逐年表：见上方分情景行（持有/出售决策参考，reversion 故事约束涨幅：预测涨幅不得超过 reversion 能支撑的幅度）。</p>' : ''}`;
}

/* ---------------- Zone 7：假设与明细 ---------------- */
function renderZone7() {
  const body = $('#z7Body');
  const fields = (state.type === 'res' ? RES_FIELDS : COM_FIELDS).map(([k, label, req]) =>
    `<div class="field"><label class="${req ? 'req' : ''}">${label}</label>
     <input data-a="${k}" type="number" value="${esc(state.assumptions[k] ?? (k === 'ask' && state.ask ? state.ask : ''))}"></div>`).join('');
  const comps = state.comps.filter(c => state.selected.has(c._id));
  const compRows = comps.map(c =>
    `<tr><td>${esc(c.address || '')}</td><td>${esc(c.sale_date || '')}</td>
     <td class="num">${fmt$(c.price)}</td><td class="num">${fmtNum(c.sf)}</td>
     <td class="num">${fmt$(c.price_per_sf, 0)}</td><td class="num">${fmtPct((c.adjustment_pct || 0) / 100, 0)}</td></tr>`).join('');
  const intake = state.intake;
  const intakeHtml = intake ? `<p class="zsub">物业档案（${esc(intake.primary_provider || '')}，${esc(intake.fetched_at || '')}）</p>
    <table class="data"><tbody>
    ${(intake.fields || []).slice(0, 12).map(f =>
      `<tr><td>${esc(f.label)}</td><td>${esc(f.display || f.value || '')}</td>
       <td><span class="note">${esc(f.source || '')}</span></td></tr>`).join('')}
    </tbody></table>
    ${(intake.manual_needed || []).length ? `<p class="note">待手动补：${intake.manual_needed.map(m => esc(m.label)).join('、')}</p>` : ''}`
    : '<p class="note">物业档案搜集中…</p>';
  const checklists = state.type === 'com' ? `
    <p class="zsub">交割前必备文件 checklist（银行会要）</p>
    <table class="data"><thead><tr><th>文件</th><th>为什么</th><th>找谁要</th><th>状态</th></tr></thead><tbody>
    <tr><td>Estoppel 租户确认函</td><td>核验租约真实性</td><td>卖方/租户</td><td>${srcTag('w')}</td></tr>
    <tr><td>Phase I 环境报告</td><td>排除污染责任</td><td>环境顾问</td><td>${srcTag('w')}</td></tr>
    <tr><td>PCA 物业状况报告</td><td>量化 deferred capex</td><td>工程顾问</td><td>${srcTag('w')}</td></tr>
    </tbody></table>
    <p class="note">Sponsor 声明：本工具评估物业与交易结构，不评估借款人信用。</p>` : '';
  const conf = state.confidence;
  const confHtml = conf ? `<p class="zsub">Confidence 因子拆解（公式公开）</p>
    <table class="data"><thead><tr><th>因子</th><th class="num">权重</th><th class="num">得分</th><th>备注</th></tr></thead><tbody>
    ${Object.entries(conf.factors).map(([k, f]) =>
      `<tr><td>${esc(k)}</td><td class="num">${f.weight}%</td><td class="num">${f.score}</td><td><span class="note">${esc(f.note)}</span></td></tr>`).join('')}
    </tbody></table><p class="note">${esc(conf.formula)}</p>
    ${(conf.notes || []).map(n => `<p class="note">${esc(n)}</p>`).join('')}` : '';
  body.innerHTML = `
    <p class="zsub">假设参数（可编辑，改数重算；凡影响 verdict 的输入旁边都有改数入口）</p>
    <div class="fgrid">${fields}</div>
    <button class="btn primary" id="btnRecalc">重新计算</button>
    ${state.type === 'com' ? `<div class="fgrid" style="margin-top:12px">
      <div class="field"><label>拟贷款额 $（Debt Yield 用；空=模板贷款额）</label><input data-a="loanAmt" type="number"></div>
    </div>` : ''}
    <p class="zsub" style="margin-top:16px">comps 明细（数字右对齐）</p>
    <table class="data"><thead><tr><th>地址</th><th>成交日</th><th class="num">成交价</th><th class="num">面积</th><th class="num">$/SF</th><th class="num">调整%</th></tr></thead>
    <tbody>${compRows || '<tr><td colspan="6">无 comps</td></tr>'}</tbody></table>
    ${confHtml}
    <div style="margin-top:16px">${intakeHtml}</div>
    ${checklists}
    <p class="zsub" style="margin-top:16px">方法论脚注</p>
    <p class="note">比较法：距离倒数加权，调整后单价用中位数带（抗异常值）；gross adjustment &gt; 25% 标黄。收益法：NOI ÷ cap，cap 无市场提取证据时用投资带法并放宽区间。成本法：待接数据源。估值基准日：${state.fetchedAt.toLocaleDateString('zh-CN')}。用途限制：${state.type === 'res' ? '筛选辅助工具，不构成投资建议。' : '投资筛选用，非 USPAP 合规评估报告，不能用于贷款/诉讼；未实地勘察、未审阅租约原件。'}</p>`;
  body.querySelectorAll('[data-a]').forEach(inp =>
    inp.addEventListener('change', () => setAssumption(inp.dataset.a, inp.value)));
  $('#btnRecalc').addEventListener('click', runScoreChain);
}
