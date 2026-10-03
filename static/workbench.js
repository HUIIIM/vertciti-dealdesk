/* 全面分析工作台前端 */
const WB = {
  markets: null, comps: [], lastValuation: null, lastForecast: null, lastMetrics: null,
};

const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const money = x => x == null ? '—' : '$' + Number(x).toLocaleString('en-US', {maximumFractionDigits: 0});
const pct1 = x => x == null ? '—' : (Number(x) * 100).toFixed(1) + '%';
const pctp = x => x == null ? '—' : (Number(x) > 0 ? '+' : '') + Number(x).toFixed(2) + '%';
const signed = x => x == null ? '—' : `<span class="${x < 0 ? 'neg' : 'pos'}">${money(x)}</span>`;
const num = id => { const v = parseFloat($('#' + id).value); return isNaN(v) ? 0 : v; };

async function post(url, body) {
  const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  if (!r.ok) { const t = await r.text(); throw new Error(t.slice(0, 300)); }
  return r.json();
}

function propPayload() {
  return {
    address: $('#p-address').value, prop_type: $('#p-type').value,
    building_sf: num('p-sf'), units: Math.max(1, Math.round(num('p-units'))),
    asking_price: num('p-asking'), down_payment: num('p-down'),
    loan_balance: num('p-loan'), rate: num('p-rate'), term_years: num('p-term') || 30,
    monthly_rent: num('p-rent'), other_income_monthly: num('p-other'),
    vacancy_pct: num('p-vac'), taxes_annual: num('p-tax'), insurance_annual: num('p-ins'),
    hoa_monthly: num('p-hoa'), utilities_owner_monthly: num('p-util'),
    maint_pct: num('p-maint'), capex_pct: num('p-capex'), mgmt_pct: num('p-mgmt'),
    closing_costs: num('p-closing'), initial_repairs: num('p-repairs'),
    reserves_months: num('p-resv'),
  };
}

WB.calcMetrics = async function () {
  try {
    const d = await post('/api/wb/metrics', {property: propPayload()});
    WB.lastMetrics = d.metrics;
    const m = d.metrics;
    const cell = (k, v, raw) => `<div class="cell">${k}<b>${raw ? v : v}</b></div>`;
    $('#metrics-out').innerHTML = `<h4>测算结果</h4><div class="kv">`
      + cell('有效租金 EGI/月', money(m.egi_monthly))
      + cell('营业费用/月', money(m.opex_monthly))
      + cell('年 NOI', money(m.noi_annual))
      + `<div class="cell">月净现金流<b>${signed(m.cash_flow_monthly)}</b></div>`
      + `<div class="cell">年净现金流<b>${signed(m.cash_flow_annual)}</b></div>`
      + cell('DSCR', m.dscr == null ? '—' : Number(m.dscr).toFixed(2))
      + cell('按要价 cap rate', m.cap_rate_on_asking == null ? '—' : (m.cap_rate_on_asking * 100).toFixed(2) + '%')
      + cell('全口径现金需求', money(m.cash_to_close))
      + cell('Cash-on-cash', m.cash_on_cash == null ? '—' : (m.cash_on_cash * 100).toFixed(1) + '%')
      + cell('要价 $/SF', m.price_per_sf == null ? '—' : '$' + m.price_per_sf)
      + cell('月供（本息）', money(m.debt_service_monthly))
      + `</div>`;
  } catch (e) { $('#metrics-out').innerHTML = `<p class="neg">测算失败：${esc(e.message)}</p>`; }
};

/* ---------- 可比案例 ---------- */
WB.renderComps = function () {
  const rows = WB.comps.map((c, i) =>
    `<tr><td>${esc(c.address) || '—'}</td><td>${c.status === 'sold' ? '已成交' : '在售'}</td>`
    + `<td>${money(c.price)}</td><td>${c.sf || '—'}</td>`
    + `<td>${c.sf ? '$' + (c.price / c.sf).toFixed(0) : '—'}</td>`
    + `<td>${c.distance_miles}</td><td>${c.adjustment_pct}%</td>`
    + `<td>${esc(c.note)}</td><td><button class="btn ghost" onclick="WB.delComp(${i})">删</button></td></tr>`).join('');
  $('#comps-table').innerHTML = WB.comps.length
    ? `<table class="t"><tr><th>地址</th><th>状态</th><th>价格</th><th>SF</th><th>$/SF</th><th>距离(英里)</th><th>调整%</th><th>备注</th><th></th></tr>${rows}</table>`
    : `<p class="src">暂无可比案例。</p>`;
};
WB.addComp = function () {
  const price = num('c-price');
  if (!price) { alert('请填写价格'); return; }
  WB.comps.push({address: $('#c-address').value, status: $('#c-status').value, price,
    sf: num('c-sf'), distance_miles: num('c-dist'), adjustment_pct: num('c-adj'), note: $('#c-note').value});
  ['c-address','c-price','c-sf','c-dist','c-note'].forEach(id => $('#' + id).value = '');
  $('#c-adj').value = 0; WB.renderComps();
};
WB.delComp = i => { WB.comps.splice(i, 1); WB.renderComps(); };
WB.clearComps = () => { WB.comps = []; WB.renderComps(); };
WB.importCsv = async function () {
  const t = $('#csv-input').value;
  if (!t.trim()) { $('#csv-msg').textContent = '请先粘贴 CSV'; return; }
  try {
    const d = await post('/api/wb/comps/parse', {csv: t});
    WB.comps = WB.comps.concat(d.rows); WB.renderComps();
    $('#csv-msg').textContent = `导入 ${d.rows.length} 条` + (d.errors.length ? `，${d.errors.length} 行失败：` + d.errors.slice(0, 3).join('；') : '');
  } catch (e) { $('#csv-msg').textContent = '导入失败：' + e.message; }
};

WB.valuate = async function () {
  try {
    const noi = $('#v-noi').value === '' ? null : num('v-noi');
    const d = await post('/api/wb/valuate', {
      property: propPayload(), comps: WB.comps,
      income_noi_annual: noi, income_cap_rate_pct: num('v-cap') || null,
      comp_weight: num('v-w') / 100,
    });
    WB.lastValuation = d;
    const r = d.reconciled;
    const crow = d.comps.count ? `<tr><td>比较法<span class="tag est">估算</span></td><td>${money(d.comps.estimate)}</td><td>${d.comps.count} 个案例，加权</td></tr>` : '';
    const irow = d.income.value ? `<tr><td>收益法<span class="tag est">估算</span></td><td>${money(d.income.value)}</td><td>NOI ${money(d.income.noi_annual)} / cap ${d.income.cap_rate_pct}%</td></tr>` : '';
    $('#val-out').innerHTML = `<h4>估值结果 <span class="tag est">估算</span></h4>
      <table class="t"><tr><th>方法</th><th>价值</th><th>说明</th></tr>${crow}${irow}
      <tr><td><b>调和估值</b></td><td><b>${r.reconciled == null ? '—' : money(r.reconciled)}</b></td><td>${esc(r.note || '')}</td></tr></table>
      <p class="src">估算区间：${r.range ? money(r.range[0]) + ' – ' + money(r.range[1]) : '—'}。以上均为估算，不是承诺价格。</p>
      <div class="disclaimer">比较法权重按 1/(1+距离英里) 计算；在售挂牌（active）仅供参考，不等同于成交价。</div>`;
    const bv = $('#f-base'); if (!bv.value && r.reconciled) bv.value = Math.round(r.reconciled);
  } catch (e) { $('#val-out').innerHTML = `<p class="neg">估值失败：${esc(e.message)}</p>`; }
};

/* ---------- 历史涨幅 ---------- */
function svgLine(points, labels) {
  const W = 640, H = 200, P = 36;
  const vals = points.map(p => p.value);
  const mn = Math.min(...vals), mx = Math.max(...vals), rg = (mx - mn) || 1;
  const X = i => P + i * (W - 2 * P) / Math.max(1, points.length - 1);
  const Y = v => H - P - (v - mn) / rg * (H - 2 * P);
  const line = points.map((p, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(p.value).toFixed(1)}`).join(' ');
  const dots = points.map((p, i) => `<circle cx="${X(i)}" cy="${Y(p.value)}" r="4" fill="#1a56db"><title>${esc(labels[i])}: ${p.value}</title></circle>`).join('');
  const xl = points.map((p, i) => `<text x="${X(i)}" y="${H - 10}" font-size="11" text-anchor="middle" fill="#666">${esc(labels[i])}</text>`).join('');
  return `<svg class="chart" viewBox="0 0 ${W} ${H}"><path d="${line}" stroke="#1a56db" stroke-width="2.5" fill="none"/>${dots}${xl}`
    + `<text x="${P}" y="18" font-size="11" fill="#666">max ${mx}</text><text x="${P}" y="${H - P + 16}" font-size="11" fill="#666">min ${mn}</text></svg>`;
}

WB.renderMarket = function () {
  const key = $('#hpi-market').value;
  const m = WB.markets.markets.find(x => x.key === key);
  const series = (WB.markets.series[key] || []);
  let bars = '';
  const ch = m.changes || {};
  const order = [['1y', '1年涨幅'], ['5y', '5年涨幅'], ['qq', '环比'], ['since_1991', '1991年以来']];
  const maxv = Math.max(1, ...order.map(([k]) => Math.abs(ch[k] || 0)));
  for (const [k, lbl] of order) {
    if (ch[k] == null) continue;
    const v = ch[k], w = Math.abs(v) / maxv * 320;
    bars += `<div class="bar-row"><span class="bar-lbl">${lbl}</span><div class="bar ${v < 0 ? 'neg' : ''}" style="width:${w.toFixed(0)}px"></div><span class="bar-val">${pctp(v)}</span></div>`;
  }
  let msad = '';
  if (m.msad_changes) {
    msad = `<p class="src">MSAD（${esc(m.geo)}）官方涨幅：1年 ${pctp(m.msad_changes['1y'])} / 5年 ${pctp(m.msad_changes['5y'])} / 1991年以来 ${pctp(m.msad_changes['since_1991'])}</p>`;
  }
  let chart = '';
  if (series.length >= 2) {
    chart = `<h4>指数曲线（${esc(m.units)}）</h4>` + svgLine(series, series.map(p => p.q))
      + `<p class="src">序列：${series.map(p => p.q + ' ' + p.value).join(' → ')}</p>`;
  } else {
    chart = `<p class="src">${esc(m.series_note || '该市场嵌入序列待补，可在下方粘贴自定义序列，或点 FRED 链接查看最新。')}</p>`;
  }
  let nar = '';
  if (m.nar_local) {
    const n = m.nar_local;
    nar = `<p>🏠 NAR 本地报告（${esc(n.period)}）：中位价 <b>${money(n.median_price)}</b>，同比 ${pctp(n.yoy)}，3年 ${pctp(n.y3)} <span class="src">（<a href="${esc(n.url)}" target="_blank">原文</a>）</span></p>`;
  }
  let rent = '';
  if (m.bls_rent_cpi) {
    const b = m.bls_rent_cpi;
    const vs = Object.entries(b.values).map(([y, v]) => `${y} ${v}`).join(' → ');
    rent = `<p>🔑 BLS 租金 CPI（${esc(b.units)}）：<span class="mono">${vs}</span> <span class="src">（<a href="${esc(b.url)}" target="_blank">FRED ${esc(b.series)}</a>）</span></p>`;
  }
  const fred = m.fred_url ? `<a href="${esc(m.fred_url)}" target="_blank">FRED ${esc(m.fred_series)} ↗</a>` : '见 FHFA 下载页';
  $('#hpi-out').innerHTML = `<h4>${esc(m.label)} <span class="src">${esc(m.geo)}</span></h4>${bars}${msad}${chart}${nar}${rent}
    <p class="src">口径：${esc(WB.markets.methodology)}</p>
    <p class="src">来源：${esc(m.source)}；数据更新：${esc(m.vintage)}${m.series_vintage ? '；' + esc(m.series_vintage) : ''} · ${fred}</p>
    <div class="disclaimer">指数是指数，不是房价：不能把指数值直接当作 $/SF 或房产价值。各市场序列新旧不同，请以标注的更新日期为准。</div>`;
};

WB.customSeries = async function () {
  const pts = $('#series-input').value.split('\n').map(l => l.trim()).filter(Boolean)
    .map(l => { const [q, v] = l.split(',').map(s => s.trim()); return {q, value: parseFloat(v)}; })
    .filter(p => p.q && !isNaN(p.value));
  if (pts.length < 2) { $('#series-out').innerHTML = '<p class="neg">至少需要 2 个数据点</p>'; return; }
  try {
    const s = await post('/api/wb/series', {points: pts});
    $('#series-out').innerHTML = `<h4>自定义序列统计</h4>`
      + svgLine(pts.slice().sort((a, b) => String(a.q).localeCompare(String(b.q))), pts.slice().sort((a, b) => String(a.q).localeCompare(String(b.q))).map(p => p.q))
      + `<div class="kv"><div class="cell">累计涨幅<b>${pctp(s.cumulative_pct)}</b></div>`
      + `<div class="cell">年化 CAGR<b>${s.cagr_pct == null ? '—' : pctp(s.cagr_pct)}</b></div>`
      + `<div class="cell">同比<b>${s.yoy_pct == null ? '—' : pctp(s.yoy_pct)}</b></div>`
      + `<div class="cell">数据点<b>${s.count}</b></div></div>
      <p class="src">数据来源：用户粘贴（未核验）。区间 ${esc(s.first.q)} → ${esc(s.latest.q)}。</p>`;
  } catch (e) { $('#series-out').innerHTML = `<p class="neg">计算失败：${esc(e.message)}</p>`; }
};

/* ---------- 预测 ---------- */
WB.forecast = async function () {
  const base = num('f-base');
  if (!base) { $('#fc-out').innerHTML = '<p class="neg">请先填写基准价值（或先做第②步估值自动带入）</p>'; return; }
  try {
    const d = await post('/api/wb/forecast', {base_value: base, years: 3, scenarios: [
      {name: 'conservative', label: '保守', annual_rate_pct: num('f-c')},
      {name: 'base', label: '基准', annual_rate_pct: num('f-b')},
      {name: 'optimistic', label: '乐观', annual_rate_pct: num('f-o')},
    ]});
    WB.lastForecast = d;
    const heads = [1, 2, 3].map(i => `<th>第${i}年</th>`).join('');
    const rows = d.scenarios.map(s => `<tr><td>${esc(s.label)}（${s.annual_rate_pct >= 0 ? '+' : ''}${s.annual_rate_pct}%/年）</td>`
      + s.value_path.map(v => `<td>${money(v)}</td>`).join('')
      + `<td><b>${s.total_return_pct >= 0 ? '+' : ''}${s.total_return_pct}%</b></td></tr>`).join('');
    $('#fc-out').innerHTML = `<h4>三年情景预测 <span class="tag fc">情景预测</span></h4>
      <table class="t"><tr><th>情景</th>${heads}<th>3年累计</th></tr>${rows}</table>
      <div class="disclaimer">⚠️ <b>${esc(d.disclaimer)}</b>年涨幅假设：保守 ${num('f-c')}% / 基准 ${num('f-b')}% / 乐观 ${num('f-o')}%（可调）。结果仅用于思路推演。</div>`;
  } catch (e) { $('#fc-out').innerHTML = `<p class="neg">预测失败：${esc(e.message)}</p>`; }
};

/* ---------- 周边价格 ---------- */
WB.nearby = function () {
  if (!WB.comps.length) { $('#nearby-out').innerHTML = '<p class="src">暂无可比案例，请先在第②步添加。</p>'; return; }
  const rows = WB.comps.map(c => `<tr><td>${esc(c.address) || '—'}</td><td>${c.status === 'sold' ? '已成交' : '在售'}</td><td>${money(c.price)}</td><td>${c.sf ? '$' + (c.price / c.sf).toFixed(0) : '—'}</td><td>${c.sf || '—'}</td><td>${c.distance_miles} 英里</td></tr>`).join('');
  const sold = WB.comps.filter(c => c.status === 'sold' && c.sf);
  const avg = sold.length ? sold.reduce((a, c) => a + c.price / c.sf, 0) / sold.length : null;
  $('#nearby-out').innerHTML = `<table class="t"><tr><th>地址</th><th>状态</th><th>价格</th><th>$/SF</th><th>面积SF</th><th>距离</th></tr>${rows}</table>
    <p>已成交案例平均 <b>${avg ? '$' + avg.toFixed(0) + ' /SF' : '—'}</b>（${sold.length} 个有面积的已成交案例）</p>
    <p class="src">数据来源：用户录入${WB.comps.some(c => c.status === 'active') ? '（含在售挂牌，仅参考）' : ''}。未录入=无数据。</p>`;
};

/* ---------- 市场调查 ---------- */
const DIMS = [['supply', '供给'], ['demand', '需求'], ['vacancy', '空置率'], ['rent_trend', '租金趋势'], ['population', '人口'], ['employment', '就业']];
WB.renderDims = function () {
  $('#research-dims').innerHTML = DIMS.map(([k, lbl]) =>
    `<div class="dim"><h4>${lbl}</h4><input id="r-${k}-note" placeholder="内容（如：空置率 6.2%，环比下降）"><input id="r-${k}-src" placeholder="来源链接或出处（必填才算已核实）"></div>`).join('');
};
function researchPayload() {
  const r = {address: $('#p-address').value, market_key: $('#r-market').value, extra_notes: $('#r-extra').value};
  for (const [k] of DIMS) { r[k + '_note'] = $('#r-' + k + '-note').value; r[k + '_source'] = $('#r-' + k + '-src').value; }
  return r;
}
WB.research = async function () {
  try {
    const d = await post('/api/wb/research', {research: researchPayload(), valuation: WB.lastValuation, forecast: WB.lastForecast});
    const c = d.completeness;
    const items = c.items.map(i => `<tr><td>${esc(i.dim)}</td><td>${i.filled ? '已填' : '未填'}</td><td>${i.sourced ? '✅ 已核实' : '⚪ 待核实'}</td></tr>`).join('');
    $('#research-out').innerHTML = `<h4>调查完整度：已填 ${c.filled}/${c.total}，已核实 ${c.sourced}/${c.total}</h4>
      <table class="t"><tr><th>维度</th><th>填写</th><th>核实</th></tr>${items}</table>
      <p class="src">覆盖市场：${esc(d.market.label)}（${esc(d.market.geo)}）· 生成时间 ${esc(d.generated_at)}</p>
      <button class="btn ghost" onclick="WB.researchReport()">🖨️ 可打印报告（新窗口）</button>`;
  } catch (e) { $('#research-out').innerHTML = `<p class="neg">生成失败：${esc(e.message)}</p>`; }
};
WB.researchReport = async function () {
  try {
    const r = await fetch('/api/wb/research/report', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({research: researchPayload(), valuation: WB.lastValuation, forecast: WB.lastForecast})});
    if (!r.ok) throw new Error(await r.text().then(t => t.slice(0, 200)));
    const html = await r.text();
    const w = window.open('', '_blank');
    w.document.write(html); w.document.close();
  } catch (e) { alert('报告生成失败：' + e.message); }
};

/* ---------- 一键打分 ---------- */
WB.score = async function () {
  try {
    const d = await post('/api/wb/score', {track: $('#s-track').value, property: propPayload()});
    const s = d.score;
    $('#score-out').innerHTML = `<h4>打分结果 <span class="src">${esc(d.note)}</span></h4>
      <div class="kv"><div class="cell">总分<b>${s.total}</b></div><div class="cell">等级<b>${esc(s.grade)}</b></div>
      <div class="cell">全口径现金需求<b>${money((s.metrics || {}).cash_to_close)}</b></div></div>
      ${(s.vetoes || []).length ? `<p class="neg">否决：${s.vetoes.map(v => esc(v.message)).join('；')}</p>` : '<p class="pos">无一票否决</p>'}
      <p><a href="/" target="_blank">→ 去打分台建档/存档</a></p>`;
  } catch (e) { $('#score-out').innerHTML = `<p class="neg">打分失败：${esc(e.message)}</p>`; }
};

/* ---------- ⓪ 智能搜集 intake ---------- */
WB.intakeData = null;

function confBadge(f) {
  if (f.seller_claimed) return `<span class="badge seller">${esc(f.claim_label || '卖方口径、待验证')}</span>`;
  const c = f.confidence;
  const cls = c === '高' ? 'high' : c === '中' ? 'mid' : 'low';
  return `<span class="badge ${cls}">可信度：${esc(c)}</span>`;
}

WB.renderIntake = function (d) {
  WB.intakeData = d;
  if (d.error && !(d.fields || []).length) {
    $('#intake-results').innerHTML = `<p class="neg">搜集失败：${esc(d.error)}</p>`;
  } else {
    const _fields = (d.fields || []).filter(f => f.key !== 'property_photos');
    const _photoF = (d.fields || []).find(f => f.key === 'property_photos');
    const _photos = (_photoF && Array.isArray(_photoF.value)) ? _photoF.value.slice(0, 6) : [];
    const _shortSrc = u => String(u || '').replace(/\s*页面$/, '').replace(/^www\./, '');
    const photoHtml = _photos.length
      ? `<div style="display:flex;justify-content:flex-end;margin-bottom:2px;"><span class="badge seller">平台照片、仅供外观参考</span></div>`
        + `<div class="photo-strip">`
        + _photos.map(q => `<div class="photo-item"><a href="${esc(q.url)}" target="_blank" rel="noopener">`
          + `<img src="${esc(q.url)}" loading="lazy" referrerpolicy="no-referrer" alt="房源照片"`
          + ` onerror="this.closest('.photo-item').style.display='none'"></a>`
          + `<div class="photo-cap">${esc(_shortSrc(q.source))} · ${esc(String(q.fetched_at || '').slice(5))}</div></div>`).join('')
        + `</div>`
      : `<p class="no-photo">该地址暂无公开房源照片（TopHap/RentCast 为公共记录不含图片；挂牌网站有反爬限制）</p>`;
    const rows = _fields.map(f => {
      let disp = esc(f.display || '');
      if (f.key === 'market_news' && Array.isArray(f.value)) {
        disp = '<ul style="margin:4px 0;padding-left:18px">' + f.value.map(n =>
          `<li><a href="${esc(n.url)}" target="_blank">${esc(n.title)}</a></li>`).join('') + '</ul>';
      } else if (f.key === 'price_history' && Array.isArray(f.value)) {
        disp = f.value.slice(0, 5).map(h => `${esc(h.date)} ${esc(h.event)} $${Number(h.price).toLocaleString()}`).join('<br>');
      } else if (f.key === 'seller_points' && Array.isArray(f.value)) {
        disp = '<ul style="margin:4px 0;padding-left:18px">' + f.value.map(p => `<li>${esc(p)}</li>`).join('') + '</ul>';
      }
      return `<tr><td><b>${esc(f.label)}</b></td><td>${disp}</td><td>${esc(f.source || '—')}</td>`
        + `<td class="src">${esc(f.fetched_at || '')}</td><td>${confBadge(f)}</td>`
        + `<td>${f.seller_claimed ? `<span class="badge seller">待验证</span>` : '✅ 已填入候选'}</td></tr>`;
    }).join('');
    const manual = (d.manual_needed || []).map(m =>
      `<tr><td><b>${esc(m.label)}</b></td><td colspan="3"><span class="badge manual">需手动补</span> <span class="src">${esc(m.note || '')}</span></td><td></td><td></td></tr>`).join('');
    const notice = d.claim_notice ? `<div class="disclaimer">⚠️ ${esc(d.claim_notice)}</div>`
      : (d.independent_note ? `<p class="src">ℹ️ ${esc(d.independent_note)}</p>` : '');
    $('#intake-results').innerHTML = `${notice}
      ${photoHtml}
      <table class="t"><tr><th>字段</th><th>值</th><th>来源</th><th>抓取时间</th><th>可信度</th><th>状态</th></tr>${rows}${manual}</table>
      ${(d.fields || []).length ? `<button class="btn" onclick="WB.fillForm()">📝 一键填入下方表单</button> <span class="src">卖方口径字段会填入但保留"待验证"提示</span>` : ''}`;
  }
  const logs = (d.log || []).map(l =>
    `<div class="logline"><span class="st-${l.status}">[${l.status}]</span> ${esc(l.step)} <span class="src">${esc(l.note || '')} · ${esc(l.at)}</span></div>`).join('');
  $('#intake-log').innerHTML = logs ? `<h4>搜集日志（${d.log.length} 步）</h4>${logs}` : '';
  $('#intake-status').textContent = '';
};

WB.fillForm = function () {
  const d = WB.intakeData;
  if (!d || !d.fields) return;
  const map = {address: 'p-address', asking_price: 'p-asking', building_sf: 'p-sf',
               monthly_rent: 'p-rent', taxes_annual: 'p-tax', hoa_monthly: 'p-hoa'};
  const sellerTouched = [];
  for (const f of d.fields) {
    const id = map[f.key];
    if (id && f.value != null && typeof f.value !== 'object') {
      document.getElementById(id).value = Math.round(Number(f.value) * 100) / 100;
      if (f.seller_claimed) sellerTouched.push(f.label);
    }
  }
  if (d.address) document.getElementById('p-address').value = d.address;
  document.getElementById('sec-prop').scrollIntoView({behavior: 'smooth'});
  $('#intake-status').innerHTML = sellerTouched.length
    ? `<span class="badge seller">以下为卖方口径、待验证：${esc(sellerTouched.join('、'))}</span>`
    : '✅ 已填入表单';
};

WB._intakeRun = async function (mode, text, label) {
  $('#intake-status').textContent = `⏳ ${label}搜集中（约 30-90 秒，多站点抓取）…`;
  $('#intake-results').innerHTML = ''; $('#intake-log').innerHTML = '';
  try {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 180000);
    const r = await fetch('/api/wb/intake/run', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({mode, text}), signal: ctl.signal});
    clearTimeout(timer);
    if (!r.ok) throw new Error((await r.text()).slice(0, 200));
    WB.renderIntake(await r.json());
  } catch (e) {
    $('#intake-status').innerHTML = `<span class="neg">搜集失败：${esc(e.name === 'AbortError' ? '超时（180秒），请重试或手动录入' : e.message)}</span>`;
  }
};

WB.intakeAddress = function () {
  const t = $('#in-address').value.trim();
  if (!t) { alert('请先输入地址'); return; }
  WB._intakeRun('address', t, '地址');
};
WB.intakeUrl = function () {
  const t = $('#in-url').value.trim();
  if (!t) { alert('请先粘贴房源链接'); return; }
  WB._intakeRun('url', t, '链接解析＋');
};
WB.intakePdf = async function () {
  const f = $('#in-pdf').files[0];
  if (!f) { alert('请先选择 PDF 文件'); return; }
  $('#intake-status').textContent = `⏳ 解析 PDF《${f.name}》中…`;
  try {
    const fd = new FormData(); fd.append('file', f, f.name);
    const r = await fetch('/api/wb/intake/pdf', {method: 'POST', body: fd});
    if (!r.ok) throw new Error((await r.text()).slice(0, 200));
    const d = await r.json();
    if (d.error) $('#intake-status').innerHTML = `<span class="neg">${esc(d.error)}</span>`;
    WB.renderIntake(d);
  } catch (e) {
    $('#intake-status').innerHTML = `<span class="neg">PDF 解析失败：${esc(e.message)}</span>`;
  }
};

/* 截图 intake：上传房源页截图 → pending 队列 → 视觉提取（约10分钟） */
WB.intakeImage = async function (file) {
  const f = file || $('#in-img').files[0];
  if (!f) { alert('请先选择截图文件'); return; }
  $('#intake-status').textContent = `⏳ 上传截图《${f.name}》中…`;
  try {
    const fd = new FormData(); fd.append('file', f, f.name);
    const r = await fetch('/api/wb/intake/image', {method: 'POST', body: fd});
    if (!r.ok) throw new Error((await r.text()).slice(0, 200));
    const d = await r.json();
    $('#intake-status').innerHTML = `✅ ${esc(d.message || '已收到截图')}（任务 ${esc(d.task_id.slice(0, 8))}…）`;
    WB.refreshScreenshots();
  } catch (e) {
    $('#intake-status').innerHTML = `<span class="neg">截图上传失败：${esc(e.message)}</span>`;
  }
};

WB.refreshScreenshots = async function () {
  const box = $('#screenshot-tasks');
  try {
    const r = await fetch('/api/wb/intake/pending');
    if (!r.ok) throw new Error((await r.text()).slice(0, 200));
    const d = await r.json();
    const tasks = d.tasks || [];
    if (!tasks.length) { box.innerHTML = ''; return; }
    const badge = s => s === 'done' ? '<span class="badge">✅ 已提取</span>'
      : s === 'failed' ? '<span class="badge seller">❌ 提取失败</span>'
      : '<span class="badge manual">⏳ 提取中</span>';
    box.innerHTML = '<h4>🖼️ 截图提取任务</h4><table class="t"><tr><th>截图</th><th>收到时间</th><th>状态</th><th></th></tr>'
      + tasks.map(t => `<tr><td>${esc(t.filename)}</td><td class="src">${esc(t.received_at)}</td>`
        + `<td>${badge(t.status)}${t.note ? ` <span class="src">${esc(t.note)}</span>` : ''}</td>`
        + `<td>${t.has_result ? `<button class="btn ghost" onclick="WB.loadScreenshotResult('${t.task_id}')">载入结果</button>` : ''}</td></tr>`).join('')
      + '</table><p class="src">截图字段标"截图提取、待验证"，须独立验证后方可用于估值/打分。</p>';
  } catch (e) {
    box.innerHTML = `<span class="neg">读取截图任务失败：${esc(e.message)}</span>`;
  }
};

WB.loadScreenshotResult = async function (taskId) {
  $('#intake-status').textContent = '⏳ 载入截图提取结果…';
  try {
    const r = await fetch('/api/wb/intake/extracted/' + encodeURIComponent(taskId));
    if (!r.ok) throw new Error((await r.text()).slice(0, 200));
    WB.renderIntake(await r.json());
  } catch (e) {
    $('#intake-status').innerHTML = `<span class="neg">载入失败：${esc(e.message)}</span>`;
  }
};

/* 拖拽：PDF / 截图 / 链接（地址栏拖入）/ 纯文本地址 */
WB.initDropzone = function () {
  const z = document.getElementById('dropzone');
  if (!z) return;
  ['dragenter', 'dragover'].forEach(ev => z.addEventListener(ev, e => { e.preventDefault(); z.classList.add('over'); }));
  ['dragleave', 'drop'].forEach(ev => z.addEventListener(ev, e => { e.preventDefault(); z.classList.remove('over'); }));
  z.addEventListener('drop', e => {
    const dt = e.dataTransfer;
    if (dt.files && dt.files.length) {
      const files = [...dt.files];
      const pdf = files.find(f => /\.pdf$/i.test(f.name));
      const img = files.find(f => /\.(png|jpe?g|webp)$/i.test(f.name));
      const file = pdf || img || files[0];
      if (pdf) {
        $('#intake-status').textContent = `⏳ 收到文件《${file.name}》，开始解析…`;
        const input = $('#in-pdf');
        const dTrans = new DataTransfer(); dTrans.items.add(file); input.files = dTrans.files;
        WB.intakePdf();
      } else if (img) {
        WB.intakeImage(img);
      } else {
        $('#intake-status').innerHTML = '<span class="neg">只接受 PDF 或截图（png/jpg/webp），收到：' + esc(file.name) + '</span>';
      }
      return;
    }
    const uri = dt.getData('text/uri-list') || dt.getData('text/x-moz-url') || '';
    const txt = (dt.getData('text/plain') || '').trim();
    const link = (uri.split('\n')[0] || '').trim() || (/^https?:\/\//i.test(txt) ? txt : '');
    if (link) {
      $('#in-url').value = link;
      $('#intake-status').textContent = `⏳ 收到链接，开始解析…`;
      WB._intakeRun('url', link, '链接解析＋');
    } else if (txt) {
      $('#in-address').value = txt;
      WB._intakeRun('address', txt, '地址');
    }
  });
};

/* ---------- 初始化 ---------- */
/* 地址 → 州平均税率 → 自动填年房产税（realyzer 思路，静态表+零key实现） */
WB.autoFillTax = async function () {
  const addrEl = document.getElementById('p-address');
  const taxEl = document.getElementById('p-tax');
  if (!addrEl || !taxEl) return;
  const addr = addrEl.value.trim();
  const price = parseFloat(document.getElementById('p-asking').value) || 0;
  if (!addr || !price) return;
  if (taxEl.dataset.autofilled === '1' && taxEl.value) return; // 用户手改过，不覆盖
  try {
    const r = await fetch('/api/tax/estimate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ address: addr, price })
    });
    const d = await r.json();
    if (d.annual_tax) {
      taxEl.dataset.autofilling = '1';
      taxEl.value = d.annual_tax;
      delete taxEl.dataset.autofilling;
      taxEl.dataset.autofilled = '1';
      const tip = `${d.state} 州平均税率 ${(d.rate * 100).toFixed(2)}% 估算 · 待独立验证（${d.source}）`;
      taxEl.title = tip;
      // 可见 badge（title 只在悬停时显示，badge 常显）
      let badge = document.getElementById('p-tax-badge');
      if (!badge) {
        badge = document.createElement('span');
        badge.id = 'p-tax-badge';
        badge.className = 'tag live';
        badge.style.marginLeft = '6px';
        taxEl.parentElement.appendChild(badge);
      }
      badge.textContent = '州平均估算';
      badge.title = tip;
      if (typeof WB.recalc === 'function') WB.recalc();
    }
  } catch (e) { /* 静默降级：不填，不打断 */ }
};

WB.init = async function () {
  WB.renderComps(); WB.renderDims(); WB.initDropzone(); WB.refreshScreenshots();
  const _addrEl = document.getElementById('p-address');
  if (_addrEl) _addrEl.addEventListener('blur', WB.autoFillTax);
  const _taxEl = document.getElementById('p-tax');
  if (_taxEl) _taxEl.addEventListener('input', () => {
    if (_taxEl.dataset.autofilling) return;
    _taxEl.dataset.autofilled = '';
    const b = document.getElementById('p-tax-badge');
    if (b) b.remove();
  });
  try {
    const r = await fetch('/api/wb/markets'); WB.markets = await r.json();
    const opts = WB.markets.markets.map(m => `<option value="${m.key}">${esc(m.label)}（${esc(m.geo)}）</option>`).join('');
    $('#hpi-market').innerHTML = opts; $('#r-market').innerHTML = opts;
    $('#hpi-market').value = 'phoenix'; $('#r-market').value = 'tampa';
    $('#hpi-market').onchange = WB.renderMarket;
    WB.renderMarket();
    $('#csv-template').textContent = 'address,status,price,sf,distance_miles,adjustment_pct,note';
    $('#sources-out').innerHTML = `<table class="t"><tr><th>名称</th><th>链接</th><th>说明</th></tr>`
      + WB.markets.public_sources.map(s => `<tr><td>${esc(s.name)}</td><td><a href="${esc(s.url)}" target="_blank">${esc(s.url)}</a></td><td>${esc(s.note)}</td></tr>`).join('') + `</table>
      <p class="src">发布：${esc(WB.markets.release)}（${esc(WB.markets.release_date)}前后）</p>`;
  } catch (e) { $('#hpi-out').innerHTML = `<p class="neg">市场数据加载失败：${esc(e.message)}</p>`; }
};
document.addEventListener('DOMContentLoaded', WB.init);
