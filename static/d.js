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
  typeExplicit: Q.has('type'),   // B：type 由 URL 显式传入？否则允许自动识别横幅
  ask: parseFloat(Q.get('price')) || null,
  ptype: Q.get('ptype') || '',
  struct: Q.get('struct') || 'standard', // P0-10：交易结构，默认普通购买
  comps: [], compsErr: null, selected: new Set(),
  valuation: null, markets: null, forecast: null, intake: null,
  score: null, confidence: null, verdict: null,
  uw: null, rentRoll: null,
  fetchedAt: new Date(),
  assumptions: {structure: Q.get('struct') || 'standard', exitStrategy: ''}, // Zone7 可编辑假设
  rentComps: [],  // 租金 comps（手动录入）
};

const STRUCT_LABELS = {standard: '普通购买', new_loan: '贷款购买', subject_to: 'subject-to（承接现有贷款）'};
const EXIT_OPTIONS = [
  ['', '未选择'],
  ['出售', '出售'],
  ['refi', 'refi（重新贷款）'],
  ['转租购', '转租购'],
  ['持有收租', '持有收租'],
];
/* 退出策略 → due-on-sale 备用预案：只有 refi/出售/转租购能应对银行提前收贷；
   持有收租不能（银行要求还钱时持有解决不了问题），如实保留否决。 */
const DOS_OK = s => ['出售', 'refi', '转租购'].includes(s);

const TIERS = {rate_bps: [100, 200, 300], vacancy_pp: [0, 2, 5, 10], rent_pct: [-20, -10, -5, 0], combo: true};

function toast(msg, ms = 2600) {
  const t = $('#toast'); t.textContent = msg; t.style.display = 'block';
  clearTimeout(t._h); t._h = setTimeout(() => t.style.display = 'none', ms);
}
function esc(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function fmt$ (x, d = 0) {
  if (x == null || !isFinite(x)) return '—';
  const a = Math.abs(x), s = x < 0 ? '-$' : '$';
  // Phase 5 第六轮微修复 #8（newbie）：负号放 $ 前面（-$8K），不许 $-8K
  if (a >= 1e6) return s + (a / 1e6).toFixed(2) + 'M';
  if (a >= 1e3) return s + (a / 1e3).toFixed(d > 0 ? 1 : 0) + 'K';
  return s + a.toFixed(d);
}
function fmtPct(x, d = 1) { return (x == null || !isFinite(x)) ? '—' : (x * 100).toFixed(d) + '%'; }
/* Phase 5 第三轮 R5：$/SF 精确显示——不许 $1K 截断（三行 $1,390/$1,078/$1,091 无法区分） */
function fmtPsf(x) { return (x == null || !isFinite(x)) ? '—' : '$' + fmtNum(x, 0); }
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
/* B1-09①：数字强制口径后缀。real=实测(green) / est=估算(yellow) / tbd=待验证(white) / calc=测算(yellow)。
   无口径数字不得渲染——调用方必须传口径。 */
const caliberBadge = k => k === 'real' ? '<span class="caliber c-real">实测</span>'
  : k === 'est' ? '<span class="caliber c-est">估算</span>'
  : k === 'tbd' ? '<span class="caliber">待验证</span>'
  : k === 'calc' ? '<span class="caliber c-est">测算</span>' : '';
const pf = '<span class="pf">PF</span>';
/* Phase 5 第八轮 P1：pro forma 预测数字旁的角标（与图例"角标 PF = 基于卖方预测（pro forma），非实数"承诺一致） */
const pfSup = '<sup class="pf">PF</sup>';

/* P0-9：小白术语表——每个术语一句话人话，tooltip 展示 */
const GLOSSARY = {
  'subject-to': '不用自己贷款，直接接着还卖家原来的房贷来买房；银行有权要求一次性还清（见 due-on-sale）。',
  'due-on-sale': '银行条款：一旦房子换主人，银行可以要求立刻还清全部贷款。subject-to 最大的风险点。',
  'refi': '重新贷款：用一笔新贷款把旧贷款换掉，常用来应对 due-on-sale 或降低月供。',
  'pro forma': '卖家"预测"的数字（比如预测租金），不是实际发生的实数，只能参考不能当真。',
  'PITI': '月供全口径：本金+利息+房产税+保险（Principal, Interest, Tax, Insurance）。',
  'EGI': '有效总收入：全部租金打完空置折扣后，真正能收到的钱。',
  'NOI': '净营业收入：租金收入减去税、保险、维修、管理等全部运营开支，是房子自己赚的钱（还没还贷款）。',
  'comps': '可比成交：附近最近卖掉的类似房子，用来判断这房子值多少钱。只认真实成交，不认挂牌价。',
  'CMA': '比较市场分析：经纪人用 comps 给房子估价的方法。',
  'DSCR': '还贷覆盖率：NOI ÷ 年还本付息。1.2 表示房子赚的钱是年供款的 1.2 倍；低于 1.0 就是贴钱持有。银行一般要求 ≥1.2。',
  'cap rate': '资本化率：年 NOI ÷ 房价。cap 越高，同样价格下房子越赚钱。',
  'WALT': '加权平均剩余租期：所有租约按租金加权算出的平均还剩几年。越短，下期招租压力越大。',
  'TI/LC': '租户装修补贴 / 招租佣金：为留住租户花的钱，是商业地产的大头隐性成本。',
  'balloon': '气球贷：前面只还利息、到期一次性还本金。到期还不上就得卖房或再融资。',
  'estoppel': '租户确认函：让租户亲笔确认"租约是真的、租金是这个数"，防卖家造假。',
  'NNN': '净租赁：租户除了租金，还掏税、保险、维修。房东收的是净钱。',
  'P0 缺口': '做决定前必须补上的关键缺失信息（如真实租约、贷款条件）。有缺口时结论会自动保守降一档。',
  '三法分歧': '三种估值方法（比较法/收益法/成本法）算出的价格差太多，机器不敢下结论，转人工。',
};
const gterm = t => {
  const d = GLOSSARY[t];
  return d ? `<span class="gloss" tabindex="0" title="${esc(d)}">${esc(t)}</span>` : esc(t);
};
/* 估值区间诚实展示（P0-5）：单点不许包装成区间 */
const fmtRange = (range, singleNote) => {
  if (!range || !range[1]) return '估值区间待计算';
  if (range[0] === range[1])
    return '估值 ' + fmt$(range[0]) + '（' + (singleNote || 'comps 高度一致，单点') + '）';
  return '估值区间 ' + fmt$(range[0]) + '–' + fmt$(range[1]);
};
/* Phase 5 第三轮 R4：单点注释按 $/SF 离散度条件化——spread 大时不许说"高度一致" */
/* Phase 5 第四轮 C5：核验结论——旧条件只看 $/SF 离散（且需 ≥3 条有面积数据），
   总价离散 21 倍（$2.48M–$53.00M）时若 $/SF 离散 ≤3 或面积数据不足，条件不触发，
   仍印"comps 高度一致，单点"——属实，覆盖缺口。修：$/SF 离散、总价离散任一超
   阈值（>3）即强制给区间（选中 comps 调整价极值），不再给单点。 */
const compsSpread = () => {
  const sel = (state.comps || []).filter(c => state.selected.has(c._id));
  const spreadOf = arr => {
    const xs = arr.filter(x => x > 0);
    return xs.length >= 3 ? Math.max(...xs) / Math.min(...xs) : 0;
  };
  const psfSpread = spreadOf(sel.map(c => c.price_per_sf));
  const priceSpread = spreadOf(sel.map(c => c.adjusted_price || c.price));
  const prices = sel.map(c => c.adjusted_price || c.price || 0).filter(x => x > 0);
  return {discrete: psfSpread > 3 || priceSpread > 3, psfSpread, priceSpread,
          lo: prices.length ? Math.min(...prices) : 0,
          hi: prices.length ? Math.max(...prices) : 0};
};
const singlePointNote = () => {
  const sp = compsSpread();
  if (sp.discrete) return 'comps 离散度高，估值置信度已下调，给区间';
  return 'comps 高度一致，单点';
};
/* C5：估值展示——离散超阈值强制给区间；不离散时走原单点逻辑 */
const valuationDisplay = (emptyText) => {
  const rec = state.valuation?.reconciled;
  const sp = compsSpread();
  if (sp.discrete && sp.lo > 0 && sp.hi > sp.lo)
    return '估值区间 ' + fmt$(sp.lo) + '–' + fmt$(sp.hi) + '（comps 离散度高，给区间）';
  const t = fmtRange(rec?.range, singlePointNote());
  return (t === '估值区间待计算' && emptyText) ? emptyText : t;
};
const intakeField = key => (state.intake?.fields || []).find(f => f.key === key);

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
      adjustment_pct: c.adjustment_pct || 0,
      // LINT-04 / D 铁律：缺失 noi 必须保持 null（渲染 N/A），禁止 || 0 回退
      noi_annual: c.noi_annual ?? null,
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
    .then(r => { state.intake = r; setStep(status, 'intake', 'done'); renderZone7(); typeNudge(r); })
    .catch(() => setStep(status, 'intake', 'fail'));

/* B：地址类型自动识别——intake 的 property_type_detail / property_type /
   description 含商业关键词，且 URL 未显式指定 type、当前为住宅视角时，
   顶部弹一键切换横幅（不再让用户进错入口）。商业→住宅不打扰（商业视角是强意图）。 */
function typeNudge(intake) {
  try {
    if (state.typeExplicit || state.type !== 'res') return;
    const fields = (intake && intake.fields) || [];
    const txt = fields.filter(f => /type|usage|description|class/i.test(f.key || ''))
      .map(f => String(f.value || '')).join(' ').toLowerCase();
    const KW = /retail|office|industrial|commercial|strip|mall|plaza|warehouse|mixed[\s-]*use|hospitality|hotel|restaurant|auto[\s-]*repair|gas[\s-]*station|self[\s-]*storage|church|school|daycare|laundromat|car[\s-]*wash/;
    if (!KW.test(txt)) return;
    const bar = $('#typeNudge');
    $('#typeNudgeText').textContent = '检测到该地址疑似商业物业（' +
      fields.map(f => String(f.value || '')).join(' ').slice(0, 60) + '），是否切换到商业视角？';
    bar.hidden = false;
    $('#typeNudgeGo').onclick = () => {
      location.href = '/d?addr=' + encodeURIComponent(state.addr) + '&type=com'
        + (state.ask ? '&price=' + state.ask : '')
        + '&struct=' + encodeURIComponent(state.assumptions.structure || 'standard');
    };
    $('#typeNudgeNo').onclick = () => { bar.hidden = true; };
  } catch (e) { /* 识别失败不打断主流程 */ }
}

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
  // Phase 5 第七轮 #6（xiaobai）/#9（remote R8）：数据截至必须按用户时区
  // America/New_York 显示＋标注"（美东时间）"——此前用浏览器本地时区，
  // UTC 机器上会显示成"明天"的日期。
  $('#z0Stamp').textContent = '数据截至 '
    + state.fetchedAt.toLocaleString('zh-CN', {hour12: false, timeZone: 'America/New_York'})
    + '（美东时间）';
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
  // Phase 5 第七轮 #1（xiaobai）：手风琴点击必须在 DOM 就绪后立即绑定——
  // 此前在 boot() 全部 API 跑完后才绑定，加载慢时点标题文字无反应（被误认为卡死）。
  // 整行（标题文字＋箭头）都是同一个 <button>，点哪里都展开。
  initAccordions();
  // Phase 5 第七轮 R7（remote）：商业线"怎么看这页"不许用住宅 verdict 词表
  // （值得买/再看看/别碰）——商业线换商业词表（BUY/HOLD/PASS，一票否决为 VETO）。
  if (state.type === 'com') {
    $('#howto').innerHTML = '怎么看这页：<b>先看结论</b>（BUY / HOLD / PASS，一票否决为 VETO）'
      + '· <b>再看价格证据</b>（Zone 3）· <b>最后看假设</b>（Zone 7，可改数重算）';
  }
  if (!state.addr) {
    $('#loadSteps').innerHTML = '<div class="empty">没有地址参数。<a href="/">回 landing 输入地址</a></div>';
    return;
  }
  // 顶栏动作
  // P0-11：切换视角是破坏性操作（清空重跑）→ 加确认弹窗，不再静默清空
  $('#btnToggle').addEventListener('click', () => {
    if (!confirm('切换视角会清空当前分析结果并重新计算，继续吗？')) return;
    const t = state.type === 'res' ? 'com' : 'res';
    location.href = '/d?addr=' + encodeURIComponent(state.addr) + '&type=' + t
      + (state.ask ? '&price=' + state.ask : '') + (state.ptype ? '&ptype=' + encodeURIComponent(state.ptype) : '')
      + '&struct=' + encodeURIComponent(state.assumptions.structure || 'standard');
  });
  // P1：结果页"换地址"入口
  $('#btnChangeAddr').addEventListener('click', () => { location.href = '/'; });
  // P1：要价显眼条
  const askGo = () => {
    // P0 bug#1（2026-10-05）：与 Zone 7 的"重新计算"同语义——resolveAsk 按"新编辑"裁决，
    // 无论价格改在哪边，点哪边重算都生效（"改价/改假设后点重新计算刷新"）
    const v = parseFloat(resolveAsk()) || 0;
    if (!v) { $('#askBarInput').focus(); return; }
    writeAsk(v); // 假设＋双 DOM 一起写，防 syncZone7Inputs 把陈旧 DOM 误判成新编辑
    state.ask = v;
    runScoreChain();
  };
  $('#askBarGo').addEventListener('click', askGo);
  $('#askBarInput').addEventListener('keydown', e => { if (e.key === 'Enter') askGo(); });
  $('#btnPdf').addEventListener('click', () => $('#ddPdf').classList.toggle('open'));
  document.addEventListener('click', e => { if (!e.target.closest('#ddPdf')) $('#ddPdf').classList.remove('open'); });
  $('#btnPdfMemo').addEventListener('click', exportPdfMemo);
  $('#btnPdfComClassic').addEventListener('click', () => exportUwPdf('classic'));
  $('#btnPdfComPlus').addEventListener('click', () => exportUwPdf('enhanced'));
  $('#btnPrint').addEventListener('click', () => window.print());
  $('#btnXlsx').addEventListener('click', exportXlsx);
  // P0-12：sticky 栏"导出备忘录"名实相符——真导出 PDF，不再是 scroll-to-top
  $('#svExport').addEventListener('click', exportPdfMemo);
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
/* Phase 5 第四轮 B2：PDF"关键假设"诚实披露——列出所有实际使用的假设（含默认
   值，标注"默认"）。isDefaultA 判定用户是否亲手填过该项。 */
function isDefaultA(k) {
  const v = state.assumptions[k];
  return v === undefined || v === null || v === '';
}
const COM_ASSUMP_KEYS = [
  ['rate', '年利率', v => v + '%'],
  ['downPct', '首付比例', v => v + '%'],
  ['amort', '摊销年数', v => v + ' 年'],
  ['vac', '空置率', v => v + '%'],
  ['capMkt', '市场 cap', v => v + '%'],
];
const RES_ASSUMP_KEYS = [
  ['rate', '年利率', v => v + '%'],
  ['down', '首付', v => '$' + Number(v).toLocaleString('en-US')],
  ['vac', '空置率', v => v + '%'],
  ['tax', '年房产税', v => '$' + Number(v).toLocaleString('en-US')],
  ['ins', '年保险', v => '$' + Number(v).toLocaleString('en-US')],
];
function effectiveAssumptions() {
  const keys = state.type === 'com' ? COM_ASSUMP_KEYS : RES_ASSUMP_KEYS;
  return keys.map(([k, label, fmt]) => ({
    key: k, label, value: getA(k), display: fmt(getA(k)),
    is_default: isDefaultA(k),
  }));
}

function buildScoreInput() {
  const struct = state.assumptions.structure || 'standard';
  const exitS = state.assumptions.exitStrategy || '';
  if (state.type === 'res') {
    const ask = getA('ask'), down = getA('down');
    // P0-14：贷款余额必须送达后端——此前漏发导致月供=0、现金流虚高（NOI 被当成净现金流）
    const loanBalRaw = state.assumptions.loanBal;
    const loanBal = (loanBalRaw !== undefined && loanBalRaw !== null && loanBalRaw !== '')
      ? Math.max(parseFloat(loanBalRaw) || 0, 0)
      : Math.max(ask - down, 0);
    return {price: ask, monthly_rent: getA('rent'), rate: getA('rate'),
      down_payment: down, loan_balance: loanBal,
      vacancy_pct: getA('vac'), taxes_annual: getA('tax'), insurance_annual: getA('ins'),
      structure: struct, exit_primary: exitS,
      due_on_sale_plan: DOS_OK(exitS) ? exitS : ''};
  }
  const ask = getA('ask'), downPct = getA('downPct') / 100;
  const loan = ask * (1 - downPct);
  // item 2/3：已导入 rent roll 但未手填年租金时，用租约实际租金汇总做 score 输入——
  // 否则 score 的 DSCR 按 0 租金算出 0.00，与 rent roll 口径（0.92）打架
  const rentAInput = getA('rentA');
  const rrAnnual = (state.rentRoll || [])
    .reduce((s, t) => s + (parseFloat(t.monthly_rent) || 0) * 12, 0);
  const hasRR = !!(state.rentRoll && state.rentRoll.length);
  return {price: ask, annual_base_rent: rentAInput || rrAnnual, vacancy_pct: getA('vac'),
    market_cap_rate_pct: getA('capMkt'),
    tranches: loan > 0 ? [{balance: loan, rate: getA('rate'), term_years: getA('amort')}] : [],
    structure: struct, exit_primary: exitS,
    due_on_sale_plan: DOS_OK(exitS) ? exitS : '',
    has_rent_roll: hasRR};
}

/* P0 bug#1（2026-10-05）：价格双入口写回——假设＋两个 DOM 输入永远一致，
   之后 resolveAsk 的"差异检测"才不会把陈旧 DOM 误判成新编辑。 */
function writeAsk(v) {
  const num = parseFloat(v) || 0;
  setAssumption('ask', num);
  const ab = $('#askBarInput'); if (ab) ab.value = num;
  const z7 = document.querySelector('#z7Body [data-a="ask"]'); if (z7) z7.value = num;
  return num;
}

/* P0 bug#1（2026-10-05）：价格有两个入口（页顶要价条 #askBarInput / Zone 7 假设 data-a="ask"）。
   以"与已同步假设的差异"判定哪边是新编辑（程序化填值不触发事件也能识别）；
   只有一边变 → 用那一边；两边都变/都没变 → 页顶条优先。 */
function resolveAsk() {
  const ab = $('#askBarInput');
  const z7 = document.querySelector('#z7Body [data-a="ask"]');
  const barVal = ab && ab.value ? String(ab.value).trim() : '';
  const z7Val = z7 && z7.value ? String(z7.value).trim() : '';
  const cur = String(getA('ask') || '');
  const norm = s => { const n = parseFloat(s); return n ? String(n) : ''; };
  const barNew = norm(barVal) !== '' && norm(barVal) !== norm(cur);
  const z7New = norm(z7Val) !== '' && norm(z7Val) !== norm(cur);
  if (barNew && !z7New) return barVal;
  if (z7New && !barNew) return z7Val;
  return barVal || z7Val || cur;
}

/* item 14：Zone 7 输入只在 change 事件才同步 state——用户键入后直接点"重新计算"
   （或程序化填值）时 change 可能没触发。重算前强制同步一次，根治"补填收购价失效"。
   P0 bug#1（2026-10-05）：价格走 resolveAsk 裁决（防页顶条陈旧值覆盖 Zone 7 新编辑，
   反之亦然），裁决后双向回写，两处输入永远一致。 */
function syncZone7Inputs() {
  document.querySelectorAll('#z7Body [data-a]').forEach(inp => {
    if (inp.dataset.a !== 'ask') setAssumption(inp.dataset.a, inp.value);
  });
  // P0 bug#1（2026-10-05）：价格走 resolveAsk 裁决（防页顶条陈旧值覆盖 Zone 7 新编辑，
  // 反之亦然），裁决后 writeAsk 双向回写，两处输入永远一致。
  const v = resolveAsk();
  if (v !== '') writeAsk(v);
}

async function runScoreChain() {
  syncZone7Inputs();
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
    // P0-5（2026-10-05）：商业敏感性矩阵（退出 cap × 租金增长率，25 格）——
    // 失败静默（state.sens 保持 null，不出表），绝不编数字
    if (state.type === 'com') await runSensitivity();
    // confidence
    // Phase 5 第五轮 B5（remote R5）：住宅租金是用户 Zone 7 自填的估算，
    // 从不是"卖方提供"——用 user_estimate（与 verdict 依据"租金为估算"统一口径；
    // 分值与 seller_unverified 同档，数学不变）
    const noiEv = state.type === 'res' ? 'user_estimate'
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
  // Phase 5 第五轮 D11（xiaobai）：comps 拉取失败时 verdict 必须显式标注
  // "数据拉取失败，重试后结论可能变化"，不许静默熔断（verdict 词本身不动）
  ev.comps_pull_failed = !!state.compsErr;
  // Phase 5 第三轮 A1：verdict 引擎需要知道有无 rent roll——无 RR 时 DSCR
  // 回退 0.0 不许套"DSCR 0.00"模板
  if (state.type === 'com')
    ev.has_rent_roll = !!(state.rentRoll && state.rentRoll.length);
  // P0-4：verdict 一句话里的 DSCR 必须与 KPI 卡（compute-plus trailing）为同一个数
  const dd = state.uw?.plus?.dscr_dual;
  if (state.type === 'com' && state.uw?.plus?.has_rent_roll && dd &&
      dd.trailing.dscr != null && isFinite(dd.trailing.dscr)) {
    ev.dscr_display = dd.trailing.dscr;
  }
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

/* 商业 compute-plus 输入（P0-8：PDF 备忘录复用同一份富输入，不再用贫输入算出全零） */
function buildUwInput() {
  // 标准 v1.0 §1.1：uw 输入层 [PCT] 原样（getA('downPct')/('rate')/('capMkt')/('vac')
  // 已是百分制），不再预除 /100；后端 normalize_pct() 归一化
  const ask = getA('ask'), downPct = getA('downPct'), rate = getA('rate');
  const tenants = (state.rentRoll || []).map(t => ({
    suite: t.suite, tenant: t.tenant, sf: t.sf, monthly_rent: t.monthly_rent,
    lease_start: t.lease_start, lease_end: t.lease_end,
    escalation: t.escalation, expense_structure: t.expense_structure}));
  const totalSf = tenants.reduce((s, t) => s + (t.sf || 0), 0);
  // Phase 5 第四轮 B4：单价 $/SF 数据流 bug——无 rent roll 时 totalSf=0 导致 PDF
  // "单价 $/SF $0.00"；回退到物业档案的建筑面积（TopHap enrich），再无才为 0
  const bldgSf = parseFloat(intakeField('building_sf')?.value) || 0;
  const netSf = totalSf > 0 ? totalSf : bldgSf;
  return {
    property: {name: state.addr, address: state.addr,
      property_type: state.ptype || 'commercial', net_rentable_sf: netSf},
    tenants, vacant_sf: 0,
    // P0-1 (2026-10-05): vacancy_pct 统一百分制（后端 /100），此处不再预除
    historical: {vacancy_pct: getA('vac')},
    proforma: {vacancy_pct: getA('vac')},
    analysis: {purchase_price: ask, down_pct: downPct, rate, amort_years: getA('amort'),
      // item 7⑤：市场 cap 必须进 PDF 富输入——否则"预测转售价值"算不出（—）而退出节
      // 又有退出售价，两处打架；同时"税前净收益/ROI"会算出 -333% 这类无意义数
      market_cap_rate: getA('capMkt'),
      // Phase 5 第四轮 B4：退出 cap 联动标记——后端判定退出 cap 用的是用户输入/
      // 联动市场 cap/硬默认，供 PDF 标注"默认"
      market_cap_rate_is_default: isDefaultA('capMkt')},
  };
}

/* 商业 compute-plus：rent roll（已导入）＋ Zone7 假设 → 最小 uw 输入 */
async function runUwPlus() {
  const input = buildUwInput();
  try {
    state.uw = await api('POST', '/api/uw/compute-plus',
      {input, with_stress: true, valuation_range: null});
  } catch (e) { state.uw = null; }
}

/* P0-5（2026-10-05）：商业二维敏感性矩阵（退出 cap × 租金增长率 → IRR / EM）。
   输入与 runUwPlus 同源（buildUwInput），25 格复用后端 compute_all。 */
async function runSensitivity() {
  try {
    state.sens = await api('POST', '/api/com/sensitivity', {input: buildUwInput()});
  } catch (e) { state.sens = null; }
}

/* P0-5：敏感性矩阵表（商业 Zone 2 KPI 卡之后）。state.sens 为空时不出表。 */
function sensTableHtml() {
  const s = state.sens;
  if (!s || !s.cells || s.cells.length !== 5) return '';
  const offLbl = bps => (bps > 0 ? '+' : '') + bps + 'bps';
  let h = `<div class="sens-wrap"><p class="zlabel">敏感性矩阵：退出 cap × 租金增长率</p>
    <div class="tbl-scroll"><table class="sens-table"><thead><tr><th>租金增长 ＼ 退出 cap</th>`;
  s.exit_caps.forEach(c => { h += `<th>${fmtPct(c, 2)}</th>`; });
  h += '</tr></thead><tbody>';
  s.cells.forEach((row, i) => {
    h += `<tr><td class="sens-axis">${offLbl(s.growth_offsets_bps[i])}</td>`;
    row.forEach((cell, j) => {
      const base = (i === 2 && j === 2) ? ' sens-base' : '';
      h += `<td class="sens-cell${base}"><span class="sens-irr">${fmtPct(cell.irr, 1)}</span>`
        + `<span class="sens-em">${Number(cell.equity_multiple).toFixed(2)}x</span></td>`;
    });
    h += '</tr>';
  });
  h += `</tbody></table></div>
    <p class="sens-note">格子 = IRR / Equity Multiple；中心格（±0bps）为当前基准假设；退出 cap 假设必须披露。改价 / 改假设后点"重新计算"刷新。</p></div>`;
  return h;
}

/* ---------------- 导出 ---------------- */
async function exportPdfMemo() {
  $('#ddPdf').classList.remove('open');
  /* Phase 5 第八轮 P2：待计算态（无 score，或 score 陈旧但收购价被清空——
     renderVerdictEmpty 不清 state.score）点击导出必须弹提示，不许静默无响应 */
  if (!state.score || !getA('ask')) { toast('请先完成分析再导出', 3000); return; }
  toast('正在生成投资备忘录 PDF…');
  try {
    const track = state.type === 'res' ? 'residential' : 'commercial';
    const input = buildScoreInput();
    // item 1/6：verdict 显示词（否决态为独立第 4 状态：住宅"否决"/商业"VETO"）＋否决数＋银行口径 DSCR 与网页同源发给 PDF
    const vd = verdictDisplay();
    const dd = state.type === 'com' && state.uw?.plus ? state.uw.plus.dscr_dual : null;
    // P0-8：把当前 deal 真实数据（verdict/KPI/comps/假设）一起发给后端，不再导出全零模板
    // Phase 5 第三轮 A2：dscr_trailing 沿用 Excel 的 has_rent_roll 门——
    // 无 rent roll 时传 null（不许把 compute-plus 回退的 0.0 透传给 PDF 印成 0.00×）
    const plus = state.uw?.plus || {};
    const hasRR = !!plus.has_rent_roll;
    const body = {track, name: state.addr, address: state.addr, input,
      variant: state.type === 'com' ? 'enhanced' : 'classic',
      verdict: state.verdict, score: state.score,
      comps: state.comps.filter(c => state.selected.has(c._id)),
      assumptions: state.assumptions,
      // Phase 5 第五轮 C9：网页 Zone 1 的估值结论（valuationDisplay 同源文案）
      // 必须进备忘录 PDF（放贷人必看）
      valuation_display: valuationDisplay(),
      // Phase 5 第四轮 B2：实际生效的假设清单（含默认值，标"默认"）——PDF"关键假设"栏用
      effective_assumptions: effectiveAssumptions(),
      verdict_word: vd.word, veto_count: vd.vetoes,
      has_rent_roll: hasRR,
      dscr_trailing: (hasRR && dd && dd.trailing.dscr != null && isFinite(dd.trailing.dscr))
        ? dd.trailing.dscr : null};
    if (state.type === 'com') body.uw_input = buildUwInput();
    const r = await fetch('/api/memo/pdf', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)});
    if (!r.ok) throw new Error(await r.text().then(t => t.slice(0, 120)));
    const blob = await r.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = r.headers.get('content-disposition')?.match(/filename\*?=(?:UTF-8''")?([^";]+)/)?.[1] || 'dealdesk_memo.pdf';
    a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    toast('已导出 PDF');
  } catch (e) { toast('PDF 生成失败：' + e.message, 4000); }
}

/* C：一键导出——商业核保 PDF（经典版 / 增强版），复用 /api/uw/report.
   经典版 = Manny Khoshbin 模板口径；增强版 = DSCR 双轨＋压力测试 */
async function exportUwPdf(variant) {
  $('#ddPdf').classList.remove('open');
  if (!state.uw) { toast('商业 PDF 需要先导入 rent roll 并计算（Zone 4）', 3500); return; }
  toast('正在生成商业核保 PDF（' + (variant === 'classic' ? '经典版' : '增强版') + '）…');
  try {
    const plus = state.uw.plus || {};
    const body = {variant, input: buildUwInput(),
      comps: state.comps.filter(c => state.selected.has(c._id)),
      assumptions: state.assumptions,
      verdict: state.verdict, verdict_word: verdictDisplay().word,
      has_rent_roll: !!plus.has_rent_roll,
      bank_noi: plus.has_rent_roll ? (plus.noi_bank_bridge?.bank_noi ?? null) : null};
    const r = await fetch('/api/uw/report', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)});
    if (!r.ok) throw new Error(await r.text().then(t => t.slice(0, 120)));
    const blob = await r.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = r.headers.get('content-disposition')?.match(/filename\*?=(?:UTF-8''")?([^";]+)/)?.[1] || ('dealdesk_uw_' + variant + '.pdf');
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
      const ask = getA('ask'), downPct = getA('downPct'), rate = getA('rate');
      const tenants = (state.rentRoll || []).map(t => ({...t}));
      // item 6：银行口径 NOI 随包发给 Excel（与网页 KPI 卡 / PDF 同数）；无 rent roll 时为 null
      const plus = state.uw.plus || {};
      const vd2 = verdictDisplay();
      // Phase 5 第四轮 B4：同 buildUwInput——无 rent roll 时回退物业档案建筑面积，防 $/SF $0.00
      const _tSf = tenants.reduce((s, t) => s + (t.sf || 0), 0);
      const _bSf = parseFloat(intakeField('building_sf')?.value) || 0;
      body = {input: {property: {name: state.addr, address: state.addr,
        property_type: state.ptype || 'commercial',
        net_rentable_sf: _tSf > 0 ? _tSf : _bSf},
        tenants, vacant_sf: 0,
        // P0-1 (2026-10-05): vacancy_pct 统一百分制（后端 /100），此处不再预除
        historical: {vacancy_pct: getA('vac')},
        proforma: {vacancy_pct: getA('vac')},
        analysis: {purchase_price: ask, down_pct: downPct, rate, amort_years: getA('amort'),
          market_cap_rate: getA('capMkt'), market_cap_rate_is_default: isDefaultA('capMkt')}},
        comps: state.comps.filter(c => state.selected.has(c._id)),
        // Phase 5 第三轮 A3：has_rent_roll 门＋verdict 行随包发给 Excel
        has_rent_roll: !!plus.has_rent_roll,
        verdict: state.verdict, verdict_word: vd2.word, veto_count: vd2.vetoes,
        bank_noi: plus.has_rent_roll ? (plus.noi_bank_bridge?.bank_noi ?? null) : null};
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
  const vd = verdictDisplay();
  $('#svWord').textContent = vd.word;
  $('#svWord').className = 'sv-word ' + verdictClass(vd.code);
  // P0-3＋item 1：有否决项时 verdict 永不裸奔——否决徽标与 verdict 词同行
  $('#svVetoBadge').innerHTML = vetoBadgeHtml(vd.vetoes);
  const rec = state.valuation?.reconciled;
  $('#svMeta').textContent = v && !v.circuit_broken ? valuationDisplay() : '';
  // P1：要价显眼条同步
  const askInp = $('#askBarInput');
  if (askInp && document.activeElement !== askInp) askInp.value = getA('ask') || '';
}
/* B1-06：唯一 verdict 口径表（与 app/verdict.py VERDICT_TAXONOMY 同源，单点定义）。
   全站统一双语渲染："值得买 · BUY"。旧 divergent 口径（住宅纯中文／商业纯英文）作废。 */
const VERDICT_TAX = [
  {code:'BUY', zh:'值得买', cls:'v-buy'},
  {code:'HOLD', zh:'再看看', cls:'v-hold'},
  {code:'PASS', zh:'别碰', cls:'v-pass'},
  {code:'VETO', zh:'一票否决', cls:'v-veto'},
];
const VERDICT_WORD2CODE = {'值得买':'BUY','再看看':'HOLD','别碰':'PASS','否决':'VETO','一票否决':'VETO','BUY':'BUY','HOLD':'HOLD','PASS':'PASS','VETO':'VETO'};
function verdictBilingual(word) {
  const code = VERDICT_WORD2CODE[word];
  if (!code) return word;
  const t = VERDICT_TAX.find(t => t.code === code);
  return t ? `${t.zh} · ${t.code}` : word;
}
function verdictClass(code) {
  const t = VERDICT_TAX.find(t => t.code === code);
  return t ? t.cls : 'v-na';
}
/* Phase 5 第四轮 A1：否决态独立成第 4 状态——有否决时 verdict 主词不许再是三档词：
   全 track 统一显示"一票否决 · VETO"（红），配"一票否决 ×N"徽标＋否决理由。
   三档文案只在无否决时使用。熔断态（数据不足/需人工复核）不进否决态。 */
const TIER_WORDS = ['值得买', '再看看', '别碰', 'BUY', 'HOLD', 'PASS'];
function vetoCount() { return (state.score?.vetoes || []).length; }
function verdictDisplay() {
  const v = state.verdict;
  const n = vetoCount();
  const raw = v ? v.verdict : '待计算';
  const code = VERDICT_WORD2CODE[raw] || null;
  if (v && n > 0 && !v.circuit_broken && code && code !== 'VETO')
    return {word: verdictBilingual('VETO'), code: 'VETO', vetoes: n};
  return {word: code ? verdictBilingual(raw) : raw, code, vetoes: n};
}
function vetoBadgeHtml(n) {
  return n > 0 ? `<span class="veto-badge">一票否决 ×${n}</span>` : '';
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
  $('#vZeroDown').textContent = '';
  $('#vVetoes').innerHTML = ''; $('#vReasons').innerHTML = '';
  $('#vVetoBadge').innerHTML = '';
  $('#vUsage').textContent = state.type === 'res'
    ? '筛选辅助工具，不构成投资建议。' : '投资筛选用，非 USPAP 合规评估报告，不能用于贷款/诉讼；未实地勘察、未审阅租约原件。';
  $('#z1Gaps').innerHTML = '';
  renderZone2(); renderZone3(); renderZone4(); renderZone5(); renderZone6(); renderZone7();
}

/* veto/原因文案里的术语自动配人话解释（P0-9）。
   Phase 5 第二轮 item 11：必须单遍扫描原文替换——此前多轮 replace 会把术语
   再套进刚插入的 title 属性里，产生嵌套 <span> 导致可见乱码 `">`。 */
function glossify(text) {
  const src = String(text ?? '');
  const terms = Object.keys(GLOSSARY).sort((a, b) => b.length - a.length);
  const re = new RegExp(
    terms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|'), 'g');
  let out = '', last = 0, m;
  re.lastIndex = 0;
  while ((m = re.exec(src)) !== null) {
    out += esc(src.slice(last, m.index));
    const t = m[0];
    out += `<span class="gloss" tabindex="0" title="${esc(GLOSSARY[t])}">${esc(t)}</span>`;
    last = m.index + t.length;
    if (m.index === re.lastIndex) re.lastIndex++;
  }
  out += esc(src.slice(last));
  return out;
}

function renderZone1() {
  const z1 = $('#z1'); z1.hidden = false;
  const v = state.verdict;
  if (!v) { renderVerdictEmpty(); return; }
  const vd = verdictDisplay();
  const w = $('#vWord');
  w.textContent = vd.word;
  w.className = 'verdict-word ' + verdictClass(vd.code);
  // Phase 5 第八轮 P1：pro forma 路径（商业无 rent roll）下 verdict 行里的 DSCR 预测数
  // 强制标注 PF 角标——verdict 文案本身不动（红线），只在数字旁加 <sup> 标记；
  // 有 rent roll（trailing 实数）路径不许加（别误伤）
  const proformaMode = state.type === 'com' && !(state.uw?.plus?.has_rent_roll);
  const pfMark = (html, text) =>
    (proformaMode && /DSCR\s*[\d.]+/.test(text)) ? html + pfSup : html;
  // Phase 5 第七轮 R11（remote）：一句话原因与下方"一票否决："行逐字重复时去重
  // （如"无 rent roll，DSCR 无法核保（待接数据）"出现两次）——verdict 词本身不动（红线）。
  const _vetoTxts = (state.score?.vetoes || []).map(x => x.message || x.code).filter(Boolean);
  const _one = v.one_liner || '';
  const _oneTxt = (_one && _vetoTxts.some(t => t === _one || t.includes(_one) || _one.includes(t)))
    ? '' : _one;
  $('#vOne').innerHTML = pfMark(esc(_oneTxt), _oneTxt);
  const c = state.confidence;
  if (c) {
    $('#vConfFill').style.width = Math.min(100, c.score) + '%';
    $('#vConfNum').textContent = c.score + '/100';
    $('#vConfLabel').textContent = '（' + c.label + '）';
  }
  const rec = state.valuation?.reconciled;
  // P0-5：单点不许包装成区间（R4：注释按 $/SF 离散度条件化）
  $('#vRange').innerHTML = valuationDisplay() + (rec ? caliberBadge('est') : '');
  const m = state.score?.metrics || {};
  const cash = m.cash_to_close ?? m.total_cash_required;
  $('#vCash').innerHTML = cash ? '全口径现金需求 ≈ ' + fmt$(cash) + caliberBadge('calc') + '（首付＋交割＋储备金）' : '';
  // Phase 5 第三轮 D11：0 首付默认值透明化——小白必须一眼看到当前按 0 首付测算
  const zeroDown = state.type === 'res' ? !(getA('down') > 0) : !(getA('downPct') > 0);
  $('#vZeroDown').textContent = zeroDown ? '当前按 0 首付（100% 贷款）测算 → 去 Zone 7 调整首付' : '';
  // P0-3＋item 1：否决态徽标与 verdict 词同行——verdict 词永不单独出现
  $('#vVetoBadge').innerHTML = vetoBadgeHtml(vd.vetoes);
  $('#vVetoes').innerHTML = (state.score?.vetoes || []).slice(0, 2).map(x => {
    const msg = x.message || x.code;
    return `<p class="veto">一票否决：${pfMark(glossify(msg), msg)}</p>`;
  }).join('');
  // Phase 5 第三轮 R7 去重：verdict 依据里与上方一票否决红字逐字重复的理由不再重复显示
  const _vetoMsgs = (state.score?.vetoes || []).map(x => x.message || x.code).filter(Boolean);
  $('#vReasons').innerHTML = (v.reasons || []).filter(r => {
    const t = String(r || '');
    return !(t.startsWith('一票否决：') && _vetoMsgs.some(m => t.includes(m)));
  }).map(r =>
    `<p class="reason">· ${glossify(r)}</p>`).join('');
  $('#vUsage').textContent = v.usage || '';
  // P0 缺口（Zone1 右侧）
  const gaps = state.type === 'com' && state.uw ? state.uw.plus.p0_gaps : [];
  $('#z1Gaps').innerHTML = gaps.length
    ? `<div class="amber"><b>缺口（已保守降级）：</b><br>${gaps.map(g => '· ' + esc(g)).join('<br>')}</div>` : '';
  // B1-07：verdict hero 下 5×5 敏感性矩阵（异步，不阻塞）
  renderSensMatrix();
}

/* B1-07：verdict hero 下 5×5 敏感性矩阵。
   商业 = 退出 cap × 租金增长率 → IRR（复用 state.sens，/api/com/sensitivity 原生 5×5）；
   住宅 = 利率 × 空置率 → 月现金流（调 /api/sensitivity，tiers 必须为合法数组，P0-2 标量 422）。
   失败静默不出表，绝不编数字。 */
async function renderSensMatrix() {
  const wrap = $('#sensMatrixWrap'), tbl = $('#sensMatrix');
  if (!wrap || !tbl) return;
  wrap.hidden = true; tbl.innerHTML = '';
  try {
    if (state.type === 'com') {
      const s = state.sens;
      if (!s || !s.cells || s.cells.length !== 5) return;
      const offLbl = bps => (bps > 0 ? '+' : '') + bps + 'bps';
      let h = '<thead><tr><th>租金增长 ＼ 退出 cap</th>';
      s.exit_caps.forEach(c => { h += `<th>${fmtPct(c, 2)}</th>`; });
      h += '</tr></thead><tbody>';
      s.cells.forEach((row, i) => {
        h += `<tr><th>${offLbl(s.growth_offsets_bps[i])}</th>`;
        row.forEach((cell, j) => {
          const v = cell.irr;
          const cls = v == null ? 'sm-na' : (v >= 0 ? 'sm-pos' : 'sm-neg');
          const base = (i === 2 && j === 2) ? ' style="outline:2px solid var(--teal)"' : '';
          h += `<td class="${cls}"${base}>${fmtPct(v, 1)}</td>`;
        });
        h += '</tr>';
      });
      tbl.innerHTML = h + '</tbody>';
      $('#sensMatrixNote').textContent = '格子 = IRR；中心格为当前基准假设。改价/改假设后点"重新计算"刷新。';
    } else {
      const input = buildScoreInput();
      const tiers = {rate_bps: [-200, -100, 0, 100, 200],
                     vacancy_pp: [-4, -2, 0, 2, 4],
                     grid2d: ['rate_bps', 'vacancy_pp']};
      const r = await api('POST', '/api/sensitivity', {track: 'residential', input, tiers});
      const m = r && r.matrix;
      if (!m || !m.cells || m.cells.length !== 5) return;
      let h = '<thead><tr><th>空置 ＼ 利率</th>';
      m.x_labels.forEach(l => { h += `<th>${esc(l)}</th>`; });
      h += '</tr></thead><tbody>';
      m.cells.forEach((row, i) => {
        h += `<tr><th>${esc(m.y_labels[i])}</th>`;
        row.forEach((cell, j) => {
          const v = cell.cash_flow_monthly;
          const cls = v == null ? 'sm-na' : (v >= 0 ? 'sm-pos' : 'sm-neg');
          const base = (i === 2 && j === 2) ? ' style="outline:2px solid var(--teal)"' : '';
          h += `<td class="${cls}"${base}>${fmt$(v)}</td>`;
        });
        h += '</tr>';
      });
      tbl.innerHTML = h + '</tbody>';
      $('#sensMatrixNote').textContent = '格子 = 月现金流；中心格为当前基准假设。改价/改假设后点"重新计算"刷新。';
    }
    wrap.hidden = false;
  } catch (e) { /* 静默，不出表 */ }
}

/* P0-2（2026-10-05）：打分等级用户可见显示：A/B/C/D → "X 档"，"否决"保持原样 */
function gradeDisplay(g) { return g === '否决' ? '否决' : (g ? g + ' 档' : ''); }

/* Zone 2 */
function renderZone2() {
  const z2 = $('#z2'); z2.hidden = false;
  const m = state.score?.metrics || {};
  const cards = [];
  const kpi = (label, val, sub, note, cls, cal) =>
    `<div class="kpi"><div class="k-label">${label}</div><div class="k-val ${cls || ''}">${val}${caliberBadge(cal)}</div>
     <div class="k-sub">${sub || ''}</div>${note ? `<div class="k-note">${note}</div>` : ''}</div>`;
  cards.push(`<p class="zlabel">Zone 2 · 关键指标</p>`);
  if (state.type === 'res') {
    const cf = m.cash_flow_monthly;
    const askV0 = getA('ask');
    // Phase 5 第三轮 D13：未填价默认态文案中性化——不许"贴钱持有"＋"比存银行高"混搭
    let cfSub, cfNote, cfCls;
    if (!askV0) {
      cfSub = '待填收购价'; cfNote = ''; cfCls = '';
    } else if (cf != null && cf < 0) {
      // item 13：文案按正负切换——负现金流时不许再写"比存银行高"
      cfSub = '贴钱持有'; cfNote = `每月倒贴 ${fmt$(-cf)}，现金流为负`; cfCls = 'k-bad';
    } else {
      cfSub = '租金覆盖月供还有剩'; cfNote = '比存银行高，但要自己管租客'; cfCls = 'k-ok';
    }
    cards.push(kpi('月现金流', fmt$(cf), cfSub, cfNote, cfCls, 'calc'));
    cards.push(kpi('现金回报率 CoC', fmtPct(m.cash_on_cash), '年净现金流 ÷ 全口径现金投入', '', '', 'calc'));
    // P0-14：月供为 0/未计算时不许显示"$0 vs $0 / 租金能覆盖 — 的月供"破损占位符
    // Phase 5 第七轮 #5（xiaobai）：租金未填时不许写"租金能覆盖 0% 的月供"——
    // 未知≠0，误读成"房子租不出去"。isDefaultA 判定用户亲手填过没有。
    const piti = m.piti;
    const rentMissing = isDefaultA('rent');
    cards.push(kpi('租金 vs 月供',
      piti ? fmt$(getA('rent')) + ' vs ' + fmt$(piti) : '待计算',
      piti ? (rentMissing ? '租金待补，覆盖率无法计算（未知≠0）'
                         : '租金能覆盖 ' + (getA('rent') / piti * 100).toFixed(0) + '% 的月供（本息+税+保险）')
           : '填要价并计算后显示', '', '', piti ? 'calc' : 'tbd'));
    cards.push(kpi('空置假设', fmtPct(getA('vac') / 100), '租金打 ' + (100 - getA('vac')).toFixed(0) + ' 折计', '', '', 'tbd'));
    // Phase 5 第七轮 #2（xiaobai）：打分卡必须与 Zone 1 的 deal 评分同步——
    // 此前重算后 state.score 已更新但 Zone 2 没有任何打分卡（只有"待计算"分支），
    // 造成"Zone 1 有 43 分、Zone 2 还在待计算"的脱节。
    if (!state.score) cards.push(kpi('打分', '待计算', '填要价后计算（上方要价条）', '', '', 'tbd'));
    else cards.push(kpi('打分', (state.score.total != null ? state.score.total : '—') + ' 分',
      'deal 评分（' + gradeDisplay(state.score.grade) + '），与 Zone 1 同源',
      // Phase 5 第七轮 #4（xiaobai）：首付 25% 后 43→28 反直觉——核验结论：
      // 15 分全掉在"首付比例"维度（浮动制：首付越低基础分越高，0%→15 分、25%→0 分），
      // 其余四维没变（租金缺失→现金流维本来就是 0 分；CoC 0 首付"未计算"→25% 后 -22.8% 仍 0 分）。
      // 打的是买盒"策略匹配度"（低首付高杠杆），不是"首付越高越危险"。
      '首付维按浮动制打"策略匹配度"：首付越低基础分越高（0%→15 分、25%→0 分）；其余维度没变。多付首付≠更危险。', '', 'calc'));
  } else {
    const uw = state.uw?.plus, a = state.uw?.analysis || {};
    const hasRR = !!(uw && uw.has_rent_roll);
    const bankNoi = uw?.noi_bank_bridge?.bank_noi;
    const askV = getA('ask');
    cards.push(kpi('价格', askV ? fmt$(askV) : '待填要价', '收购价/要价', '', '', 'tbd'));
    // item 3：无 rent roll 时 NOI 也不许出现 $0 硬数字——与 DSCR 卡同理显示"待 rent roll"
    // Phase 5 第八轮 P1：无 rent roll = pro forma 路径，标准 NOI 是预测数——强制标注 PF 角标；
    // 有 rent roll 时是实数，不许加（别误伤）
    cards.push(kpi('NOI（双口径）',
      hasRR ? (bankNoi != null ? fmt$(bankNoi) : '—') : '待 rent roll',
      '银行口径' + (m.noi ? '；标准 NOI ' + fmt$(m.noi) + (hasRR ? '' : pfSup) : ''),
      hasRR ? '' : '导入租约明细后计算（Zone 4）', '', hasRR ? 'real' : 'tbd'));
    const capIn = bankNoi && getA('ask') ? bankNoi / getA('ask') : null;
    // Phase 5 第六轮微修复 #1（remote N2）：无 rent roll 时 bank_noi 是瀑布
    // 调整的残差（0 起扣管理费/储备金/空置调整，常为小负数），truthy 导致
    // Zone 2 出现幽灵 "-0.34%"——无 NOI 时卡片必须显示"—"，不许单独出数。
    const capDisp = hasRR ? fmtPct(capIn, 2) : '—';
    cards.push(kpi('Trailing cap', capDisp,
      hasRR ? '市场区间待接 ' + srcTag('w') : '待 rent roll（无 NOI，不单独出数）',
      '单个 cap 数字不许单独出现', '', hasRR ? 'est' : 'tbd'));
    // P0-4/P0-7：无 rent roll 时 DSCR 不许显示 0.00x——显示"待 rent roll"
    if (hasRR) {
      const dd = uw.dscr_dual;
      const td = dd.trailing.dscr, pd = dd.proforma.dscr;
      cards.push(kpi('DSCR 双轨',
        (td != null && isFinite(td) ? td.toFixed(2) : '—') + 'x' + caliberBadge('real') + ' / ' +
        (pd != null && isFinite(pd) ? pd.toFixed(2) : '—') + 'x' + caliberBadge('est') + pf,
        'trailing 主 / pro forma 辅', dd.trailing.label,
        td >= 1.2 ? 'k-ok' : 'k-bad'));
      cards.push(kpi('Debt Yield', fmtPct(uw.debt_yield, 2),
        'NOI（银行口径）÷ 拟贷款额', '≥8-10% 舒适；<6% 机构资金出局',
        uw.debt_yield >= 0.08 ? 'k-ok' : uw.debt_yield >= 0.06 ? 'k-warn' : 'k-bad'));
      const be = a.breakeven_occupancy;
      cards.push(kpi('盈亏平衡', fmtPct(be),
        '缓冲垫 ' + fmtPct(Math.max(0, (uw.rent_roll_detail.occupancy || 0) - be)) ,
        be > 1 ? '满租都不够还贷 → 别碰' : be > 0.9 ? '偏薄' : '安全边际厚',
        be > 1 ? 'k-bad' : be > 0.9 ? 'k-warn' : 'k-ok'));
    } else {
      cards.push(kpi('DSCR', '待 rent roll', '导入租约明细后计算（Zone 4）', ''));
      cards.push(kpi('Debt Yield', '待 rent roll', '', ''));
      cards.push(kpi('盈亏平衡', '待 rent roll', '', ''));
    }
  }
  // P0-5（2026-10-05）：商业敏感性矩阵表放 Zone 2 KPI 卡之后
  if (state.type === 'com') cards.push(sensTableHtml());
  z2.innerHTML = cards.join('');
}

/* Zone 3：价格公允性 */
/* Phase 5 第三轮 E14：comps 拉取失败后的显式重试（重拉＋补跑比较法估值） */
async function retryCompsPull() {
  const btn = $('#compsRetry');
  if (btn) btn.disabled = true;
  toast('正在重新拉取 comps…');
  try {
    const r = await api('POST', '/api/wb/comps/pull', {address: state.addr});
    state.comps = (r.rows || []).map((c, i) => ({...c, _id: i}));
    state.selected = new Set(state.comps.map(c => c._id));
    state.compsErr = null;
    try {
      const comps = state.comps.map(c => ({address: c.address, status: c.status || 'sold',
        price: c.price || 0, sale_date: c.sale_date || '', sf: c.sf || 0,
        distance_miles: c.distance_miles || 0, adjustment_pct: c.adjustment_pct || 0,
        // LINT-04 / D 铁律：缺失 noi 必须保持 null（渲染 N/A），禁止 || 0 回退
        noi_annual: c.noi_annual ?? null, source: c.source || '', note: c.note || ''}));
      state.valuation = await api('POST', '/api/wb/valuate', {
        property: {address: state.addr,
                   prop_type: state.type === 'res' ? 'residential' : 'commercial'},
        comps, comp_weight: 0.5});
    } catch (e2) { /* 估值失败保持空态 */ }
    toast('comps 拉取成功，估值已更新');
  } catch (e) {
    state.compsErr = e.message;
    toast('拉取失败：' + e.message + '，可再点重试', 4000);
  }
  renderZone3();
}

function renderZone3() {
  const body = $('#z3Body');
  const val = state.valuation, comps = state.comps;
  // Phase 5 第五轮 D10（flipper P1）：comps 拉取失败时 Zone 3 必须自动展开＋
  // 标题行红色失败徽标——否则重试块藏在折叠区里（height=0），用户看不见重试入口
  const z3 = $('#z3'), z3head = z3.querySelector('[data-acc="z3"]');
  const oldBadge = z3head.querySelector('.fail-badge');
  if (state.compsErr) {
    z3.classList.remove('closed');
    const chev = z3head.querySelector('.chev');
    if (chev) chev.textContent = '▾';
    if (!oldBadge)
      z3head.querySelector('h2').insertAdjacentHTML('beforeend', ' <span class="fail-badge">拉取失败</span>');
  } else if (oldBadge) {
    oldBadge.remove();
  }
  // Phase 5 第四轮 D7（flipper 打回）：拉取失败必须优先显式——旧代码要求 !val 才显示重试块，
  // 但 /api/wb/valuate 空 comps 也会成功返回，val 非空导致失败态被吞。现 compsErr 优先判定，
  // 并区分"拉取失败"（给"重新拉取"按钮，只重试 comps/pull）与"零结果"两种文案。
  if (state.compsErr) {
    body.innerHTML = `<div class="empty"><b>comps 拉取失败</b>（${esc(state.compsErr)}）<br>
      <span class="note">不是"没有可比成交"，是数据没拉下来——点下面只重试拉取，不重跑全流程。</span><br>
      <button class="btn" id="compsRetry" style="margin-top:8px">重新拉取</button></div>`;
    $('#compsRetry').addEventListener('click', retryCompsPull);
    return;
  }
  if (!val && !comps.length) {
    body.innerHTML = `<div class="empty">还没有 comps 数据——TopHap 没返回该地址的可比成交（零结果），换个地址或手动导入 CSV ${srcTag('w')}</div>`;
    return;
  }
  const cv = val?.comps || {};
  const sel = comps.filter(c => state.selected.has(c._id));
  const psfs = sel.map(c => c.price_per_sf).filter(x => x > 0).sort((a, b) => a - b);
  // item 4：真中位数——偶数个时取中间两数的平均（此前取排序后第 n/2+1 个，$771 vs 真 $739.5）
  const medPsf = psfs.length
    ? (psfs.length % 2 ? psfs[(psfs.length - 1) / 2]
       : (psfs[psfs.length / 2 - 1] + psfs[psfs.length / 2]) / 2) : null;
  const ask = getA('ask');
  const overPct = (ask && cv.median_adjusted) ? (ask - cv.median_adjusted) / cv.median_adjusted : null;
  // item 4：口径写死——这是"可比成交调整价的中位数"（价格口径），不是 $/SF 口径，
  // 与下方"中位 $/SF"行区分，避免"均值/中位"混淆
  const verdictLine = overPct == null ? '填要价后对比 comps 调整价中位'
    : overPct <= -0.05 ? `低于 comps 调整价中位 ${fmtPct(-overPct, 0)}`
    : overPct >= 0.05 ? `高于 comps 调整价中位 ${fmtPct(overPct, 0)}` : '与 comps 调整价中位基本持平';

  // 三法区间（商业）
  let methodsHtml = '';
  if (state.type === 'com') {
    const me = buildMethodsEvidence() || {};
    const bar = (name, range, note) => {
      if (!range) return `<div class="note">${name}：缺数据 ${srcTag('w')}（${note}）</div>`;
      return `<div class="frow"><span class="fl">${name}</span>
        <span class="fv">${fmt$(range[0])} – ${fmt$(range[1])}</span></div>`;
    };
    // Phase 5 第三轮 C6（remote R2）：权重披露不许写死——无 rent roll 时
    // "NOI 经租约支持"是无源断言；有 rent roll 时才显示权重
    const hasRR3 = !!(state.rentRoll && state.rentRoll.length);
    const weightLine = hasRR3
      ? '收益法 50%（NOI 经租约支持）/ 比较法 50%'
      : '收益法：待租约数据（暂不参与）/ 比较法：当前唯一有效方法';
    // Phase 5 第七轮 R9（remote）：标题"三法区间并列"overclaim——
    // 收益法常缺数据（待租约）、成本法从未接入，根本不是"三法并列"。改诚实标题。
    methodsHtml = `<p class="zsub">估值方法对照</p><div class="formula">
      ${bar('收益法 Income', me.income, 'NOI÷cap，需 cap 证据')}
      ${bar('比较法 Sales', me.sales, 'recorded sales')}
      ${bar('成本法 Cost', null, '待接数据源')}
      <div class="frow"><span class="fl">权重披露</span><span class="fv" style="font-weight:500;font-size:12px">${weightLine}</span></div>
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
  // Phase 5 第七轮 R10（remote）：重复抓取的 comps（同地址＋同成交日＋同价，
  // 如 72 NASSAU ST 两条）必须标注"重复"，不许静默并列两条。
  const dupKey = c => [String(c.address || '').toLowerCase().replace(/\s+/g, ' ').trim(),
    String(c.sale_date || ''), String(c.price || 0)].join('|');
  const keyCount = {};
  comps.forEach(c => { const k = dupKey(c); keyCount[k] = (keyCount[k] || 0) + 1; });
  const rows = comps.map(c => {
    const on = state.selected.has(c._id);
    const bigAdj = Math.abs(c.adjustment_pct || 0) > 25;
    const dup = keyCount[dupKey(c)] > 1;
    return `<tr class="${on ? '' : 'off'} ${bigAdj ? 'hl-yellow' : ''}" data-cid="${c._id}">
      <td><input type="checkbox" data-comp="${c._id}" ${on ? 'checked' : ''} aria-label="选用"></td>
      <td>${esc(c.address || '')}${dup ? ' <span class="dup-tag">重复</span>' : ''}<br><span class="note">${esc(c.sale_date || '')} · ${esc(c.source || '')}</span></td>
      <td class="num">${fmt$(c.price)}</td><td class="num">${fmtNum(c.sf)}</td>
      <td class="num">${fmtPsf(c.price_per_sf)}</td>
      <td class="num">${bigAdj ? '⚠ ' : ''}${fmtPct((c.adjustment_pct || 0) / 100, 0)}</td></tr>`;
  }).join('');

  // P0-6：价格对账——四个价格并列，每行一句话解释口径差异
  const thMV = intakeField('market_value'), thAVM = intakeField('tophap_value'),
    thTax = intakeField('tax_assessed_value');
  const reconRows = [
    [thMV ? thMV.display : (thAVM ? thAVM.display : null),
     thMV ? 'TopHap 市场价值（公共记录口径）' : 'TopHap AVM 模型值',
     thMV ? 'TopHap 公共记录的市场价值口径' : 'TopHap 算法估算，未考虑房屋实际成色与内部状况'],
    [cv.estimate ? fmt$(cv.estimate) : null, '比较法估值',
     '周边真实成交（recorded sales）调整后加权，反映市场实际愿意付的价格'],
    [ask ? fmt$(ask) : null, '要价',
     '卖方要价，是谈判起点，不是房子值多少钱'],
    [thTax ? thTax.display : null, '计税估值',
     '政府为征税定的价值（' + (thTax ? esc(thTax.note || '') : '') + '），常年滞后于市场，不代表市场价'],
  ];
  // Phase 5 第四轮 C6：价格锚 sanity check——四个价格最大/最小比超 5 倍时红色警告
  const _anchorVals = [
    thMV ? parseFloat(thMV.value) : (thAVM ? parseFloat(thAVM.value) : 0),
    cv.estimate || 0, ask || 0,
    thTax ? parseFloat(thTax.value) : 0,
  ].filter(x => x > 0);
  let _anchorWarn = '';
  if (_anchorVals.length >= 2) {
    const _ax = Math.max(..._anchorVals) / Math.min(..._anchorVals);
    if (_ax > 5)
      _anchorWarn = `<p class="anchor-warn">价格锚差异巨大（${_ax >= 10 ? Math.round(_ax) : _ax.toFixed(1)} 倍），需人工核验数据口径</p>`;
  }
  const reconHtml = `<p class="zsub">价格对账（四个价格，口径不同不许直接比大小）</p>${_anchorWarn}<div class="formula">${
    reconRows.map(([val, label, note]) =>
      `<div class="frow"><span class="fl">${esc(label)}<br><span class="note">${esc(note)}</span></span>
       <span class="fv">${val ? esc(val) : '— 待接'}</span></div>`).join('')
  }</div>`;

  body.innerHTML = `
    <p class="zsub">${esc(verdictLine)}${srcTag(state.compsErr ? 'w' : 'g')}</p>
    ${methodsHtml}
    <div class="formula">
      <div class="frow"><span class="fl">比较法估值</span><span class="fv">${fmt$(cv.estimate)}</span></div>
      <div class="frow"><span class="fl">成色调整</span><span class="fv" id="condAdjVal">未调整（无依据不做）</span></div>
      <div class="frow hero"><span class="fl">调和估值</span><span class="fv">${esc(valuationDisplay('—'))}</span></div>
      <div class="frow"><span class="fl">置信度评分</span><span class="fv">${state.confidence ? state.confidence.score + '/100' : '待计算'}</span></div>
    </div>
    ${reconHtml}
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
      中位 $/SF ${medPsf ? fmtPsf(medPsf) : '—'}</p>
    <table class="data"><thead><tr><th></th><th>地址</th><th class="num">成交价 ${caliberBadge('real')}</th><th class="num">面积</th><th class="num">$/SF</th><th class="num">调整%</th></tr></thead>
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
    // P0-14：瀑布分项必须加总等于净现金流。
    // 后端：cash_flow = rent*(1-vac) − opex − monthly_pi。此前前端错写成
    // rent − vac − (opex − rent*vac) − piti，导致 12000−960−5000−3000=3040 ≠ 净剩 $5K。
    const parts = [
      ['租金', rent, 'var(--green)'], ['− 空置', -rent * vac, 'var(--amber)'],
      ['− 税/险/杂', -(m.opex || 0), 'var(--amber)'],
      ['− 月供（本息）', -(m.monthly_pi || 0), 'var(--red)'], ['= 净现金流', m.cash_flow_monthly, 'var(--teal)'],
    ];
    const maxA = Math.max(...parts.map(p => Math.abs(p[1])), 1);
    // Phase 5 第五轮 B4（remote R4）：瀑布行标签自带"−"时，数值必须显示绝对值——
    // 否则"− 月供（本息）"＋fmt$ 的 "$-7K" 形成双重负号。"= 净现金流"是结果行，保留符号。
    const bars = parts.map(([l, v, c]) =>
      `<div class="hbar-row"><span>${l}</span>
       <div class="hbar-track"><div class="hbar-fill" style="width:${(Math.abs(v) / maxA * 100).toFixed(1)}%;background:${c}"></div></div>
       <span class="hbar-val">${l.startsWith('−') ? fmt$(-v) : fmt$(v)}</span></div>`).join('');
    // Phase 5 第五轮 B4（remote R4）："税/险/杂 $0 含税、保险、维修…"自相矛盾——
    // $0（未填）时不许写"含五项"，改写为未填标注
    // Phase 5 第六轮微修复 #6（newbie）：档案有税数（TopHap 公共记录）但测算
    // 用 $0——必须一句话解释"已知但未采用"（公共记录未经核验不直接采用），
    // 否则小白会问"你们不是知道税吗"。数字取 intake 档案字段，不硬编码。
    const _thTaxesAnnual = intakeField('taxes_annual');
    const opexNote = (m.opex || 0) > 0
      ? `税/险/杂 ${fmt$(m.opex)}（含税、保险、维修、capex、管理费）`
      : `税/险/杂 $0（未填/待核验：税、保险、维修、capex、管理费）` +
        ((_thTaxesAnnual && _thTaxesAnnual.display)
          ? `；档案税 ${esc(_thTaxesAnnual.display)} 为公共记录未经核验，本次测算未采用`
          : '');
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
      <p class="note">这意味着什么：月现金流 ${fmt$(m.cash_flow_monthly)}，${m.cash_flow_monthly >= 0 ? '租金能覆盖月供还有剩' : '每月要贴钱'}。
      月供口径=等额本息 ${fmt$(m.monthly_pi)}（贷款 ${fmt$(Math.max(getA('ask') - getA('down'), 0))}、年利率 ${getA('rate')}%、30 年摊还）＋税/险；${opexNote}。</p>`;
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
      无 rent roll 的 deal 最高只给 HOLD；若触发一票否决，结论为独立的否决态（住宅"否决"/商业"VETO"，红）。</div>
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
        // P0-13：如实报告跳过的模板示例行与日期解析失败行
        let msg = `导入 ${j.count} 个租户`;
        if (j.skipped_example) msg += `（跳过模板示例行 ${j.skipped_example}）`;
        if (j.bad_dates) msg += `（${j.bad_dates} 行日期解析失败，租期已置空请核对）`;
        toast(msg + '，正在核保…');
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
    ${(() => {
      // Phase 5 第七轮 #3（xiaobai）：市场指数 0 行时不许渲染空表头＋空白行
      // （看起来像渲染 bug）——收起表格，只留一句话说明。
      const rows = (mk?.markets || []).slice(0, 8);
      if (!rows.length)
        return `<div class="empty">暂无市场指数数据（待接数据源） ${srcTag('w')}</div>`;
      return `<table class="data"><thead><tr><th>市场</th><th>说明</th></tr></thead><tbody>
        ${rows.map(m =>
          `<tr><td>${esc(m.name || m.id || '')}</td><td class="note">${esc(m.note || '')}</td></tr>`).join('')}
        </tbody></table>`;
    })()}
    <p class="note">每行误差标注：基于公开指数；历史回测误差未在本页披露，以发布机构（FHFA/FRED）口径为准。新增供给 pipeline：待接数据源 ${srcTag('w')}</p>`;
}

/* ---------------- Zone 6：预测 ---------------- */
function renderZone6() {
  const body = $('#z6Body');
  const fc = state.forecast;
  const sleeve = '<span class="tag exp">趋势外推（实验）</span>';
  // P0-7：无预测数据时显示"暂无预测数据"，格子里不许出现 $0
  if (!fc || !fc.scenarios || !fc.scenarios.length) {
    body.innerHTML = `<div class="empty">暂无预测数据 ${sleeve} ${srcTag('w')}</div>`;
    return;
  }
  const base = fc.base_value || 0;
  // P0-7：后端 forecast 返回 value_path（数字数组），兼容 points 形态
  const ptsOf = s => {
    const vp = s.value_path || [];
    if (vp.length) return vp.map((v, i) => ({value: v, label: 'Y' + (i + 1)}));
    return (s.points || []).map((p, i) => ({value: p.value, label: 'Y' + (i + 1)}));
  };
  const rows = fc.scenarios.map(s => {
    const pts = ptsOf(s);
    const ptsTxt = pts.map(p => `${p.label}: ${fmt$(p.value)}`).join(' · ');
    const end = pts.length ? pts[pts.length - 1].value : 0;
    return `<div class="frow"><span class="fl">${esc(s.label)}（${s.annual_rate_pct}%/年）</span>
      <span class="fv">${end ? fmt$(end) : '暂无预测数据'}</span></div><div class="note" style="margin:0 0 6px">${esc(ptsTxt)}</div>`;
  }).join('');
  // SVG 折线
  const W = 560, H = 180, P = 30;
  const all = fc.scenarios.flatMap(s => ptsOf(s).map(p => p.value)).filter(v => v > 0);
  if (!all.length) {
    body.innerHTML = `<div class="empty">暂无预测数据 ${sleeve} ${srcTag('w')}</div>`;
    return;
  }
  const lo = Math.min(...all, base) * 0.95, hi = Math.max(...all, base) * 1.05;
  const n = Math.max(...fc.scenarios.map(s => ptsOf(s).length), 1);
  const X = i => P + i * (W - 2 * P) / Math.max(n - 1, 1), Y = v => H - P - (v - lo) / (hi - lo) * (H - 2 * P);
  const colors = {conservative: '#60a5fa', base: '#2dd4bf', optimistic: '#fbbf24'};
  const paths = fc.scenarios.map(s => {
    const pts = ptsOf(s).map((p, i) => `${X(i).toFixed(0)},${Y(p.value).toFixed(0)}`).join(' ');
    return `<polyline points="${pts}" fill="none" stroke="${colors[s.name] || '#a3b1c9'}" stroke-width="2" stroke-dasharray="${s.name === 'base' ? 'none' : '5,4'}"/>`;
  }).join('');
  const baseEnd = ptsOf(fc.scenarios.find(s => s.name === 'base') || {});
  body.innerHTML = `
    <p class="zsub">模型预测 5 年后值 ${baseEnd.length ? fmt$(baseEnd[baseEnd.length - 1].value) : '暂无预测数据'} ${sleeve}</p>
    <svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:640px;background:var(--bg1);border:1px solid var(--line);border-radius:6px" role="img" aria-label="5 年估值预测">
      ${paths}
      <text x="${P}" y="${H - 8}" fill="#64748f" font-size="10">现在</text>
      <text x="${W - P - 30}" y="${H - 8}" fill="#64748f" font-size="10">5 年后</text>
    </svg>
    <div class="formula" style="margin-top:10px">${rows}</div>
    <p class="note">模型预测，基于过去趋势外推，方法未公开；历史回测误差无公开数据，不做断言；不构成投资建议；银行承销不采用。forecast 输出绝不回流进 DSCR/NOI/verdict 计算。</p>
    ${state.type === 'com' ? '<p class="note">商业逐年表：见上方分情景行（持有/出售决策参考，reversion 故事约束涨幅：预测涨幅不得超过 reversion 能支撑的幅度）。</p>' : ''}`;
}

/* ---------------- Zone 7：假设与明细 ---------------- */
function renderZone7() {
  const body = $('#z7Body');
  const fields = (state.type === 'res' ? RES_FIELDS : COM_FIELDS).map(([k, label, req]) =>
    `<div class="field"><label class="${req ? 'req' : ''}">${label}</label>
     <input data-a="${k}" type="number" value="${esc(state.assumptions[k] ?? (k === 'ask' && state.ask ? state.ask : ''))}"></div>`).join('');
  // P0-10：交易结构选择（默认普通购买）；P0-2：退出策略输入（选了即解除对应否决）
  const struct = state.assumptions.structure || 'standard';
  const exitS = state.assumptions.exitStrategy || '';
  const structHtml = `
    <div class="fgrid" style="margin-top:12px">
      <div class="field"><label>交易结构（决定 verdict 否决规则）</label>
        <select data-a="structure">
          ${Object.entries(STRUCT_LABELS).map(([v, l]) =>
            `<option value="${v}"${v === struct ? ' selected' : ''}>${esc(l)}</option>`).join('')}
        </select></div>
      <div class="field"><label>退出策略（选了即解除"无退出预案"否决）</label>
        <select data-a="exitStrategy">
          ${EXIT_OPTIONS.map(([v, l]) =>
            `<option value="${v}"${v === exitS ? ' selected' : ''}>${esc(l)}</option>`).join('')}
        </select></div>
      ${state.type === 'res' && struct === 'subject_to' ? `
      <div class="field"><label>承接贷款余额 $（subject-to：卖家现有贷款余额，空=要价−首付）</label>
        <input data-a="loanBal" type="number" value="${esc(state.assumptions.loanBal ?? '')}"></div>` : ''}
    </div>
    <p class="note">subject-to 才有"无退出预案 / due-on-sale 备用预案"否决项；普通购买/贷款购买永不触发。
    ${gterm('subject-to')} ${gterm('due-on-sale')} ${gterm('refi')}</p>
    ${struct === 'subject_to' && exitS === '持有收租'
      ? '<p class="note">提醒：持有收租不能应对银行执行 due-on-sale（要求提前还款），"due-on-sale 备用预案"否决仍在；需另选 refi/出售/转租购之一才能解除。</p>' : ''}`;
  const comps = state.comps.filter(c => state.selected.has(c._id));
  const compRows = comps.map(c =>
    `<tr><td>${esc(c.address || '')}</td><td>${esc(c.sale_date || '')}</td>
     <td class="num">${fmt$(c.price)}</td><td class="num">${fmtNum(c.sf)}</td>
     <td class="num">${fmtPsf(c.price_per_sf)}</td><td class="num">${fmtPct((c.adjustment_pct || 0) / 100, 0)}</td></tr>`).join('');
  const intake = state.intake;
  const intakeHtml = intake ? `<p class="zsub">物业档案（${esc(intake.primary_provider || '')}，${esc(intake.fetched_at || '')}）</p>
    <table class="data"><tbody>
    ${(intake.fields || []).slice(0, 12).map(f =>
      `<tr><td>${esc(f.label)}</td><td>${esc(f.display || f.value || '')}</td>
       <td><span class="note">${esc(f.source || '')}</span></td></tr>`).join('')}
    </tbody></table>
    ${(intake.manual_needed || []).length ? `<p class="note">待手动补：${intake.manual_needed.map(m => esc(m.label)).join('、')}</p>` : ''}`
    : '<p class="note">物业档案搜集中…</p>';
  // P0-1：交割 checklist——"authorization to release"只是待办项，永不自动否决
  const authRow = `<tr><td>Authorization to release（卖方向贷款方索取）</td><td>核实贷款真实余额/利率/逾期</td><td>卖方</td><td>${srcTag('w')}</td></tr>
    <tr><td colspan="4"><span class="note">状态：未验证——交割前向卖方索取，此项永不作为自动一票否决。</span></td></tr>`;
  const checklists = state.type === 'com' ? `
    <p class="zsub">交割前必备文件 checklist（银行会要）</p>
    <table class="data"><thead><tr><th>文件</th><th>为什么</th><th>找谁要</th><th>状态</th></tr></thead><tbody>
    <tr><td>${gterm('estoppel')} 租户确认函</td><td>核验租约真实性</td><td>卖方/租户</td><td>${srcTag('w')}</td></tr>
    <tr><td>Phase I 环境报告</td><td>排除污染责任</td><td>环境顾问</td><td>${srcTag('w')}</td></tr>
    <tr><td>PCA 物业状况报告</td><td>量化 deferred capex</td><td>工程顾问</td><td>${srcTag('w')}</td></tr>
    ${authRow}
    </tbody></table>
    <p class="note">Sponsor 声明：本工具评估物业与交易结构，不评估借款人信用。</p>`
    : `
    <p class="zsub">交割前 checklist</p>
    <table class="data"><thead><tr><th>事项</th><th>为什么</th><th>找谁要</th><th>状态</th></tr></thead><tbody>
    <tr><td>房屋检查（inspection）</td><td>发现结构/水电隐患</td><td>验房师</td><td>${srcTag('w')}</td></tr>
    <tr><td>产权调查（title search）</td><td>排除留置/欠费/纠纷</td><td>产权公司</td><td>${srcTag('w')}</td></tr>
    ${authRow}
    </tbody></table>`;
  const conf = state.confidence;
  // P0-9：Confidence 因子用中文名，不再裸奔英文代码
  const confHtml = conf ? `<p class="zsub">Confidence 因子拆解（公式公开）</p>
    <table class="data"><thead><tr><th>因子</th><th class="num">权重</th><th class="num">得分</th><th>备注</th></tr></thead><tbody>
    ${Object.entries(conf.factors).map(([k, f]) =>
      `<tr><td>${esc(f.label || k)}</td><td class="num">${f.weight}%</td><td class="num">${f.score}</td><td><span class="note">${esc(f.note)}</span></td></tr>`).join('')}
    </tbody></table><p class="note">${esc(conf.formula)}</p>
    ${(conf.notes || []).map(n => `<p class="note">${esc(n)}</p>`).join('')}` : '';
  body.innerHTML = `
    <p class="zsub">假设参数（可编辑，改数重算；凡影响 verdict 的输入旁边都有改数入口）</p>
    <div class="fgrid">${fields}</div>
    ${structHtml}
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
    <p class="zsub" style="margin-top:16px">方法论脚注（人话版）</p>
    <p class="note">房子值多少，我们看三路证据：① <b>比较法</b>——附近最近真实卖掉的类似房子，按远近加权、取中间值，最抗忽悠；单套调整超过 25% 的标黄提醒。② <b>收益法</b>——房子一年净赚的钱 ÷ 市场回报率（cap），cap 没有市场证据时用"投资带法"估一个宽区间。③ <b>成本法</b>——重盖要花多少钱，数据源还没接。三路价格差太多（分歧>40%）机器就不下结论，转人工。估值基准日：${state.fetchedAt.toLocaleDateString('zh-CN', {timeZone: 'America/New_York'})}（美东时间）。用途限制：${state.type === 'res' ? '筛选辅助工具，不构成投资建议。' : '投资筛选用，非 USPAP 合规评估报告，不能用于贷款/诉讼；未实地勘察、未审阅租约原件。'}</p>
    <p class="note">术语表：${['subject-to', 'due-on-sale', 'refi', 'pro forma', 'PITI', 'EGI', 'NOI', 'comps', 'CMA', 'DSCR', 'cap rate', 'WALT', 'TI/LC', 'balloon', 'estoppel', 'NNN'].map(gterm).join(' · ')}</p>`;
  body.querySelectorAll('[data-a]').forEach(inp =>
    inp.addEventListener('change', () => {
      setAssumption(inp.dataset.a, inp.value);
      // P0 bug#1（2026-10-05）：Zone 7 改价即时同步页顶条，双入口不分叉
      if (inp.dataset.a === 'ask') { const ab = $('#askBarInput'); if (ab && inp.value) ab.value = inp.value; }
      // 结构切换影响输入项（subject-to 显示承接贷款余额），重渲染本区
      if (inp.dataset.a === 'structure' || inp.dataset.a === 'exitStrategy') renderZone7();
    }));
  $('#btnRecalc').addEventListener('click', runScoreChain);
}
