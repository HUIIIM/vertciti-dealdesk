/* 商业核保工作台：JS 计算引擎（与 app/uw_commercial.py 逐公式对应）＋ 联动 UI */
(function () {
"use strict";

const EXPENSES = [
  ["service_contracts", "服务合同 Service Contracts"],
  ["cam", "公共区域维护 CAM"],
  ["general_admin", "综合管理 G&A"],
  ["repairs_maintenance", "维修保养 R&M"],
  ["janitor", "保洁 Janitor"],
  ["security", "安保 Security"],
  ["utilities", "水电 Utilities"],
  ["payroll", "工资 Payroll"],
  ["management_fee", "管理费 Mgmt Fee"],
  ["property_tax", "房产税 Property Tax"],
  ["insurance", "保险 Insurance"],
  ["landscape", "景观绿化 Landscape"],
];

const f = (x, d = 0) => {
  const v = parseFloat(x);
  return Number.isFinite(v) ? v : d;
};
const div = (a, b) => (f(b) === 0 ? 0 : f(a) / f(b));

/* ---------------- 计算引擎（port of uw_commercial.py） ---------------- */
function rentRoll(tenants, vacantSf) {
  const rows = (tenants || []).map((t) => {
    const sf = f(t.sf), monthly = f(t.monthly_rent);
    const annual = monthly * 12;
    const mCam = f(t.monthly_cam), mPkg = f(t.monthly_parking);
    const uw = t.underwritten_annual === "" || t.underwritten_annual == null ? annual : f(t.underwritten_annual);
    return {
      suite: t.suite || "", tenant: t.tenant || "", sf, monthly_rent: monthly,
      monthly_per_sf: div(monthly, sf), annual_rent: annual,
      annual_per_sf: div(annual, sf), underwritten_annual: uw, uw_per_sf: div(uw, sf),
      monthly_cam: mCam, monthly_parking: mPkg,
      annual_cam: mCam * 12, annual_parking: mPkg * 12,
    };
  });
  const totalSf = rows.reduce((s, r) => s + r.sf, 0);
  const totalMonthly = rows.reduce((s, r) => s + r.monthly_rent, 0);
  const totalLease = rows.reduce((s, r) => s + r.annual_rent, 0);
  const totalUw = rows.reduce((s, r) => s + r.underwritten_annual, 0);
  const totalCam = rows.reduce((s, r) => s + r.annual_cam, 0);
  const totalPkg = rows.reduce((s, r) => s + r.annual_parking, 0);
  const vac = f(vacantSf), propSf = totalSf + vac;
  rows.forEach((r) => {
    r.pct_lease = div(r.annual_rent, totalLease);
    r.pct_uw = div(r.underwritten_annual, totalUw);
  });
  return {
    tenants: rows, total_sf_existing: totalSf, total_monthly: totalMonthly,
    total_annual_lease: totalLease, total_annual_uw: totalUw,
    total_annual_cam: totalCam, total_annual_parking: totalPkg,
    vacant_sf: vac, total_sf_property: propSf, occupancy: div(totalSf, propSf),
  };
}

function scenario(inp, baseRents, netSf, purchase, autoCam, autoPkg) {
  inp = inp || {};
  // 模板 T/U 列接通：空=自动取租户表明细，手填=覆盖
  const camMan = f(inp.cam_recovery), pkgMan = f(inp.parking_income);
  const camRec = camMan || f(autoCam), parking = pkgMan || f(autoPkg);
  const other = f(inp.other_income);
  const camSrc = camMan ? "manual" : (f(autoCam) ? "rent_roll" : "none");
  const pkgSrc = pkgMan ? "manual" : (f(autoPkg) ? "rent_roll" : "none");
  const totalPotential = baseRents + camRec + parking + other;
  const vacPct = f(inp.vacancy_pct);
  const vacLoss = totalPotential * vacPct;
  const egi = totalPotential - vacLoss;
  const expenses = {};
  EXPENSES.forEach(([k]) => (expenses[k] = f(inp[k])));
  const totalExp = Object.values(expenses).reduce((a, b) => a + b, 0);
  const noi = egi - totalExp;
  const ti = f(inp.tenant_improvements), capex = f(inp.capex), lc = f(inp.leasing_commissions);
  return {
    base_rents: baseRents, cam_recovery: camRec, parking_income: parking, other_income: other,
    income_sources: { cam_recovery: camSrc, parking_income: pkgSrc },
    total_potential: totalPotential, vacancy_pct: vacPct, vacancy_loss: vacLoss, egi,
    expenses, total_expenses: totalExp, noi,
    tenant_improvements: ti, capex, leasing_commissions: lc,
    cash_flow_avail: noi - ti - capex - lc,
    cash_flow_gross: noi + other,           // 模板口径：NOI + 其他收入
    cap_rate: div(noi, purchase),
    per_sf: {
      base_rents: div(baseRents, netSf), egi: div(egi, netSf),
      total_expenses: div(totalExp, netSf), noi: div(noi, netSf),
    },
  };
}

function amortPayment(loan, rate, years) {
  loan = f(loan); rate = f(rate); const n = Math.round(f(years));
  if (loan <= 0 || n <= 0) return 0;
  if (rate <= 0) return loan / n;
  return (loan * rate) / (1 - Math.pow(1 + rate, -n));
}
function remainingBal(loan, rate, years, pmt, afterYears) {
  let bal = f(loan); const r = f(rate);
  for (let i = 0; i < Math.max(0, afterYears); i++) bal = bal * (1 + r) - pmt;
  return Math.max(0, bal);
}
function irrOf(flows) {
  const npv = (r) => flows.reduce((s, cf, i) => s + cf / Math.pow(1 + r, i), 0);
  let lo = -0.99, hi = 10, flo = npv(lo), fhi = npv(hi);
  if (flo * fhi > 0) return 0;
  for (let i = 0; i < 100; i++) {
    const mid = (lo + hi) / 2;
    if (flo * npv(mid) <= 0) { hi = mid; fhi = npv(hi); }
    else { lo = mid; flo = npv(lo); }
  }
  return (lo + hi) / 2;
}

function computeExit(a, pro, loanBal, rate, amortType, amortYears, annualDebt, netLiq) {
  const holdYears = Math.round(f(a.hold_years, 5));
  const growth = f(a.noi_growth, 0.02), exitCap = f(a.exit_cap_rate, 0.05);
  const exitFeePct = 0.04, abate = f(a.abatements);  // 模板固定 4%，2026-10-01 Miao 决定锁定
  if (holdYears <= 0 || netLiq <= 0)
    return { hold_years: holdYears, irr: 0, equity_multiple: 0, sale_price: 0, sale_proceeds: 0, remaining_loan: 0 };
  const baseNoi = pro.noi, flows = [-netLiq];
  for (let y = 1; y <= holdYears; y++)
    flows.push(baseNoi * Math.pow(1 + growth, y - 1) - abate - annualDebt);
  const noiExit = baseNoi * Math.pow(1 + growth, holdYears);
  const salePrice = div(noiExit, exitCap);
  const rem = amortType === "AMORTIZING"
    ? remainingBal(loanBal, rate, amortYears, annualDebt, holdYears) : loanBal;
  const proceeds = salePrice - rem - salePrice * exitFeePct;
  flows[flows.length - 1] += proceeds;
  const pos = flows.slice(1).filter((x) => x > 0).reduce((s, x) => s + x, 0);
  return {
    hold_years: holdYears, noi_growth: growth, exit_cap_rate: exitCap,
    sale_price: salePrice, remaining_loan: rem, sale_proceeds: proceeds,
    irr: irrOf(flows), equity_multiple: div(pos, netLiq),
  };
}

function computeAnalysis(a, hist, pro) {
  a = a || {};
  const purchase = f(a.purchase_price);
  const repairs = f(a.building_repairs), reserve = f(a.capital_reserve);
  const lenderFees = f(a.lender_fees), closing = f(a.closing_costs);
  const totalUses = purchase + repairs + reserve + lenderFees + closing;
  const downPct = f(a.down_pct), rate = f(a.rate);
  const amortType = (a.amort_type || "IO").toUpperCase();
  const amortYears = f(a.amort_years, 30);
  const loanBal = purchase * (1 - downPct);
  const annualDebt = amortType === "AMORTIZING" ? amortPayment(loanBal, rate, amortYears) : loanBal * rate;
  const netLiq = totalUses - loanBal;
  const inNoi = f(a.underwritten_noi) || hist.noi;      // F13 手工，空=取现金流
  const prNoi = f(a.projected_noi) || pro.noi;            // F15 手工，空=取现金流
  const inNoiCf = f(a.inplace_noi_cf) || hist.noi;        // I24 手工，空=取现金流
  const marketCap = f(a.market_cap_rate);
  const resale = div(prNoi, marketCap);
  const acqFees = repairs + reserve + lenderFees + closing;
  const exitFeePct = 0.04;  // 模板固定 4%，2026-10-01 Miao 决定锁定
  const exitFees = resale * exitFeePct;
  const netGains = resale - (purchase + acqFees + exitFees);
  const abate = f(a.abatements);
  const coc = (noiV, other) => {
    const netCf = noiV - abate - annualDebt;
    return {
      noi: noiV, cash_flow_gross: noiV + other, abatements: abate,
      debt_service: annualDebt, net_cash_flow: netCf,
      cash_on_cash: div(netCf, netLiq), dscr: div(noiV, annualDebt),
    };
  };
  return {
    purchase_price: purchase, total_uses: totalUses,
    down_pct: downPct, rate, amort_type: amortType, amort_years: amortYears,
    loan_bal: loanBal, annual_debt_service: annualDebt, net_liquidity: netLiq,
    inplace_noi: inNoi, inplace_cap: div(inNoi, purchase),
    projected_noi: prNoi, inplace_noi_cf: inNoiCf,
    noi_sources: {
      underwritten_noi: f(a.underwritten_noi) ? "manual" : "cashflow",
      projected_noi: f(a.projected_noi) ? "manual" : "cashflow",
      inplace_noi_cf: f(a.inplace_noi_cf) ? "manual" : "cashflow",
    },
    market_cap_rate: marketCap, projected_resale: resale,
    acquisition_fees: acqFees, exit_fee_pct: exitFeePct, exit_fees: exitFees,
    net_gains: netGains, roi: div(netGains, netLiq),
    projected: coc(prNoi, pro.other_income),
    inplace: coc(inNoiCf, hist.other_income),
    breakeven_occupancy: div(pro.total_expenses + annualDebt, pro.total_potential),
    exit: computeExit(a, pro, loanBal, rate, amortType, amortYears, annualDebt, netLiq),
  };
}

function computeAll(data) {
  data = data || {};
  const prop = data.property || {};
  const netSf = f(prop.net_rentable_sf);
  const rent = rentRoll(data.tenants, data.vacant_sf);
  const purchase = f((data.analysis || {}).purchase_price);
  const hist = scenario(data.historical, rent.total_annual_lease, netSf, purchase, rent.total_annual_cam, rent.total_annual_parking);
  const pro = scenario(data.proforma, rent.total_annual_uw, netSf, purchase, rent.total_annual_cam, rent.total_annual_parking);
  const analysis = computeAnalysis(data.analysis, hist, pro);
  const propOut = Object.assign({}, prop);
  propOut.parking_per_1000sf = div(f(prop.parking_spaces), netSf / 1000); // 模板公式 =F6/(F4/1000)
  return {
    property: propOut, rent_roll: rent, historical: hist, proforma: pro, analysis,
    per_sf: {
      price_per_sf: div(purchase, netSf),
      rent_per_sf_hist: div(rent.total_annual_lease, netSf),
      rent_per_sf_pro: div(rent.total_annual_uw, netSf),
      expense_per_sf: div(pro.total_expenses, netSf),
      noi_per_sf: div(pro.noi, netSf),
    },
  };
}

/* ---------------- state ---------------- */
let state = null;       // input dict
let result = null;      // computed
let curId = null, curName = "";
let prevVals = {};      // for flash

const $ = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

function getPath(obj, path) {
  return path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj);
}
function setPath(obj, path, val) {
  const ks = path.split(".");
  let o = obj;
  for (let i = 0; i < ks.length - 1; i++) {
    if (o[ks[i]] == null || typeof o[ks[i]] !== "object") o[ks[i]] = {};
    o = o[ks[i]];
  }
  o[ks[ks.length - 1]] = val;
}

const fmtMoney = (v) => {
  if (!Number.isFinite(v)) return "—";
  const neg = v < 0;
  return (neg ? "-$" : "$") + Math.abs(Math.round(v)).toLocaleString("en-US");
};
const fmtNum = (v) => (Number.isFinite(v) ? Math.round(v).toLocaleString("en-US") : "—");
const fmtPct = (v, d = 2) => (Number.isFinite(v) ? (v * 100).toFixed(d) + "%" : "—");
function fmtVal(v, kind) {
  if (kind === "money") return fmtMoney(v);
  if (kind === "pct") return fmtPct(v);
  if (kind === "num") return fmtNum(v);
  if (kind === "num2") return Number.isFinite(v) ? v.toFixed(2) : "—";
  if (kind === "pct1") return fmtPct(v, 1);
  return String(v);
}
function setInputVal(el, path) {
  const v = getPath(state, path);
  if (el.dataset.pct) el.value = v === 0 || v == null ? "" : (f(v) * 100).toFixed(3).replace(/\.?0+$/, "");
  else el.value = v === 0 || v == null ? (el.type === "number" ? "" : v) : v;
}

/* ---------------- render ---------------- */
function captureFocus() {
  const el = document.activeElement;
  if (!el || !el.dataset) return null;
  const d = el.dataset;
  if (d.t) return { k: "t", t: d.t, i: d.i, s: el.selectionStart, e: el.selectionEnd };
  if (d.cf) return { k: "cf", cf: d.cf, key: d.k, s: el.selectionStart, e: el.selectionEnd };
  return null;
}
function restoreFocus(cap) {
  if (!cap) return;
  let sel;
  if (cap.k === "t") sel = `input[data-t="${cap.t}"][data-i="${cap.i}"]`;
  else sel = `input[data-cf="${cap.cf}"][data-k="${cap.key}"]`;
  const el = document.querySelector(sel);
  if (el) {
    el.focus();
    try { el.setSelectionRange(cap.s, cap.e); } catch (_) {}
  }
}

function renderAll(flash) {
  const cap = captureFocus();
  const oldResult = result;
  result = computeAll(state);
  // 1) computed cells
  $$("[data-calc]").forEach((el) => {
    const path = el.dataset.calc, v = getPath(result, path);
    const txt = fmtVal(v, el.dataset.fmt);
    if (el.tagName === "INPUT") el.value = txt;
    else {
      const changed = flash && prevVals[path] !== undefined && prevVals[path] !== txt;
      el.textContent = txt;
      const host = el.closest("td") || el.parentElement;
      if (changed && host) { host.classList.remove("flash"); void host.offsetWidth; host.classList.add("flash"); }
    }
    prevVals[path] = txt;
  });
  renderRentTable();
  renderCfTables();
  renderCocTables();
  renderKvs();
  restoreFocus(cap);
}

function renderRentTable(flash) {
  const tb = $("#rentBody");
  tb.innerHTML = "";
  result.rent_roll.tenants.forEach((r, i) => {
    const tr = document.createElement("tr");
    tr.className = "rw";
    tr.innerHTML =
      `<td data-l="单元"><input class="cell-in sm" data-t="suite" data-i="${i}" value="${esc(r.suite)}"></td>` +
      `<td data-l="租户"><input class="cell-in" data-t="tenant" data-i="${i}" value="${esc(r.tenant)}" style="width:130px"></td>` +
      `<td data-l="面积 SF"><input class="cell-in sm" type="number" data-t="sf" data-i="${i}" value="${num(r.sf)}"></td>` +
      `<td data-l="月租（合同）"><input class="cell-in sm" type="number" data-t="monthly_rent" data-i="${i}" value="${num(r.monthly_rent)}"></td>` +
      `<td data-l="月租/SF" class="calc" data-p="monthly_per_sf">${money2(r.monthly_per_sf)}</td>` +
      `<td data-l="年租" class="calc" data-p="annual_rent">${fmtMoney(r.annual_rent)}</td>` +
      `<td data-l="年租/SF" class="calc" data-p="annual_per_sf">${money2(r.annual_per_sf)}</td>` +
      `<td data-l="包租年租"><input class="cell-in sm" type="number" data-t="underwritten_annual" data-i="${i}" value="${num(r.underwritten_annual)}" title="包租年租（预测口径用）"></td>` +
      `<td data-l="包租/SF" class="calc" data-p="uw_per_sf">${money2(r.uw_per_sf)}</td>` +
      `<td data-l="月 CAM"><input class="cell-in sm" type="number" data-t="monthly_cam" data-i="${i}" value="${num(r.monthly_cam)}" title="月 CAM（模板 T 列）"></td>` +
      `<td data-l="月停车费"><input class="cell-in sm" type="number" data-t="monthly_parking" data-i="${i}" value="${num(r.monthly_parking)}" title="月停车费（模板 U 列）"></td>` +
      `<td data-l=""><button class="del-tenant" data-i="${i}" title="删除">×</button></td>`;
    tb.appendChild(tr);
  });
  const rr = result.rent_roll;
  $("#rentFoot").innerHTML =
    `<tr class="total"><td data-l="" colspan="2">合计</td><td data-l="面积 SF">${fmtNum(rr.total_sf_existing)}</td>` +
    `<td data-l="月租合计">${fmtMoney(rr.total_monthly)}</td><td data-l=""></td><td data-l="年租合计" class="linked" title="→ B 现金流 · 历史基础租金">${fmtMoney(rr.total_annual_lease)}</td>` +
    `<td data-l=""></td><td data-l="包租合计" class="linked" title="→ B 现金流 · 预测基础租金">${fmtMoney(rr.total_annual_uw)}</td><td data-l=""></td>` +
    `<td data-l="CAM 年合计" class="linked" title="→ B/C 现金流 · CAM 回收（模板 T 列）">${fmtMoney(rr.total_annual_cam)}</td>` +
    `<td data-l="停车年合计" class="linked" title="→ B/C 现金流 · 停车收入（模板 U 列）">${fmtMoney(rr.total_annual_parking)}</td><td data-l=""></td></tr>`;
  // 空置率建议：空置面积隐含比例
  const vacEl = $("#vacHint");
  if (vacEl) {
    const impl = rr.total_sf_property ? rr.vacant_sf / rr.total_sf_property : 0;
    vacEl.innerHTML = rr.vacant_sf > 0
      ? `空置 ${fmtNum(rr.vacant_sf)} SF / 总 ${fmtNum(rr.total_sf_property)} SF，隐含空置率 <b>${(impl * 100).toFixed(2)}%</b> <button class="btn sm ghost" id="btnFillVac">填入两栏空置率</button>`
      : `空置面积为 0`;
  }
}

function cfTableHTML(sc, title, linkedNote) {
  const row = (lbl, val, kind, opts = {}) => {
    const cls = opts.calc ? "calc" : opts.linked ? "linked" : "lbl";
    const tit = opts.title ? ` title="${opts.title}"` : "";
    return `<tr class="${opts.trCls || ""}"><td class="${cls}"${tit}>${lbl}</td><td class="${cls}">${fmtVal(val, kind)}</td></tr>`;
  };
  const inp = (lbl, key, isPct) => {
    const v = state[title][key];
    const disp = isPct ? (v ? (f(v) * 100).toFixed(2) : "") : (v || "");
    let srcTag = "", ph = "";
    if (sc.income_sources && sc.income_sources[key]) {
      const s = sc.income_sources[key];
      if (s === "rent_roll") srcTag = ' <span class="tag live" title="自动取自租户表 T/U 列年合计">租户表自动</span>';
      else if (s === "manual") srcTag = ' <span class="tag" title="手工输入覆盖租户表">手工</span>';
      if (!v && (key === "cam_recovery" || key === "parking_income")) ph = ' placeholder="空=租户表自动"';
    }
    return `<tr><td class="lbl">${lbl}${srcTag}${isPct ? ' <span class="tag new">NEW</span>' : ""}</td>` +
      `<td><input class="cell-in" type="number" data-cf="${title}" data-k="${key}" data-ispct="${isPct ? 1 : 0}" value="${disp}" step="any"${ph}></td></tr>`;
  };
  let h = "";
  h += row("基础租金 Base Rents", sc.base_rents, "money", { linked: true, title: linkedNote });
  h += inp("CAM 回收", "cam_recovery") + inp("停车收入", "parking_income") + inp("其他收入", "other_income");
  h += row("总潜在收入", sc.total_potential, "money", { calc: true });
  h += inp("空置/坏账损失 %", "vacancy_pct", true);
  h += row("空置损失额", sc.vacancy_loss, "money", { calc: true });
  h += row("有效总收入 EGI", sc.egi, "money", { calc: true, trCls: "total" });
  h += `<tr><td colspan="2" style="text-align:left;color:#888;font-size:12px;">费用 Expenses</td></tr>`;
  EXPENSES.forEach(([k, lbl]) => { h += inp(lbl, k); });
  h += row("总费用", sc.total_expenses, "money", { calc: true, trCls: "total" });
  h += row("净营业收入 NOI", sc.noi, "money", { calc: true, trCls: "noi", title: "→ C 投资分析" });
  h += inp("租户装修 TI", "tenant_improvements") + inp("资本性支出 CapEx", "capex") + inp("租赁佣金", "leasing_commissions");
  h += row("可用于还贷现金流", sc.cash_flow_avail, "money", { calc: true });
  h += row("现金流（NOI+其他收入）", sc.cash_flow_gross, "money", { calc: true, title: "模板口径" });
  h += row("Cap 率", sc.cap_rate, "pct", { calc: true });
  h += row("NOI /SF", sc.per_sf.noi, "money", { calc: true });
  return h;
}
function renderCfTables() {
  $("#cfHist").innerHTML = cfTableHTML(result.historical, "historical", "← A 租金表 · 合同年租合计");
  $("#cfPro").innerHTML = cfTableHTML(result.proforma, "proforma", "← A 租金表 · 包租年租合计");
}

function cocTableHTML(c, tag) {
  const row = (lbl, val, kind) => `<tr><td class="lbl">${lbl}</td><td class="calc">${fmtVal(val, kind)}</td></tr>`;
  return row("NOI " + tag, c.noi, "money") +
    row("现金流（NOI+其他收入）", c.cash_flow_gross, "money") +
    row("租金减免/抵免", c.abatements, "money") +
    row("年还贷额", c.debt_service, "money") +
    `<tr class="noi"><td class="calc">净现金流</td><td class="calc">${fmtVal(c.net_cash_flow, "money")}</td></tr>` +
    row("Cash-on-Cash", c.cash_on_cash, "pct") +
    row('DSCR <span class="tag new">NEW</span>', c.dscr, "num2");
}
function renderCocTables() {
  // DSCR 显示 3 位小数
  const fix = (id, c, tag) => {
    $(id).innerHTML = cocTableHTML(c, tag).replace('data-x', '');
    const cells = $$(id + " td.calc");
    const dscrCell = cells[cells.length - 1];
    if (dscrCell) dscrCell.textContent = Number.isFinite(c.dscr) ? c.dscr.toFixed(3) + "×" : "—";
  };
  fix("#cocPro", result.analysis.projected, "（预测）");
  fix("#cocInp", result.analysis.inplace, "（在手）");
}

function kvCard(lbl, val, kind, hl, extra) {
  return `<div class="cell${hl ? " hl" : ""}">${lbl}${extra || ""}<b>${fmtVal(val, kind)}</b></div>`;
}
function renderKvs() {
  const an = result.analysis, ps = result.per_sf;
  $("#returnKvs").innerHTML =
    kvCard("在手 NOI", an.inplace_noi, "money") +
    kvCard("在手 Cap 率", an.inplace_cap, "pct", true) +
    kvCard("预测 NOI", an.projected_noi, "money") +
    kvCard("市场 Cap 率（输入）", an.market_cap_rate, "pct") +
    kvCard("预测转售价值", an.projected_resale, "money", true) +
    kvCard("收购费用", an.acquisition_fees, "money") +
    kvCard("退出费用", an.exit_fees, "money") +
    kvCard("税前净收益", an.net_gains, "money", true) +
    kvCard("投资回报率 ROI", an.roi, "pct", true);
  $("#newKvs").innerHTML =
    kvCard("预测 DSCR", an.projected.dscr, "num2", true, ' <span class="tag new">NEW</span>') +
    kvCard("在手 DSCR", an.inplace.dscr, "num2", false, ' <span class="tag new">NEW</span>') +
    kvCard("盈亏平衡出租率", an.breakeven_occupancy, "pct", true, ' <span class="tag new">NEW</span>') +
    kvCard("购买单价 /SF", ps.price_per_sf, "money", false, ' <span class="tag new">NEW</span>') +
    kvCard("预测租金 /SF", ps.rent_per_sf_pro, "money", false, ' <span class="tag new">NEW</span>') +
    kvCard("费用 /SF", ps.expense_per_sf, "money", false, ' <span class="tag new">NEW</span>');
  const dscrEl = $$("#newKvs .cell b");
  if (dscrEl[0]) dscrEl[0].textContent = fmtDscr(an.projected.dscr);
  if (dscrEl[1]) dscrEl[1].textContent = fmtDscr(an.inplace.dscr);
  const ex = an.exit;
  $("#exitKvs").innerHTML =
    kvCard("持有期", ex.hold_years + " 年", null) +
    kvCard("退出售价", ex.sale_price, "money", true) +
    kvCard("剩余贷款", ex.remaining_loan, "money") +
    kvCard("退出净得", ex.sale_proceeds, "money", true) +
    kvCard("IRR", ex.irr, "pct", true) +
    kvCard("股本倍数", ex.equity_multiple, "num2", true);
  const emEl = $$("#exitKvs .cell b");
  if (emEl[5]) emEl[5].textContent = Number.isFinite(ex.equity_multiple) ? ex.equity_multiple.toFixed(2) + "×" : "—";
  // 指挥条：物业身份（state 输入，非计算值）
  const cn = $("#cmdName"), ca = $("#cmdAddr"), pp = state.property || {};
  if (cn) cn.textContent = pp.name || "未命名物业";
  if (ca) ca.textContent = [pp.address, pp.city, pp.state, pp.zip].filter(Boolean).join(" ");
  // 承保假设血缘
  const src = an.noi_sources || {};
  const tag = (s) => s === "manual" ? "手工锁定" : "现金流实时";
  const el = $("#noiSrc");
  if (el) el.textContent = `当前口径：F13 ${tag(src.underwritten_noi)} · F15 ${tag(src.projected_noi)} · I24 ${tag(src.inplace_noi_cf)}`;
}
function fmtDscr(v) { return Number.isFinite(v) ? v.toFixed(3) + "×" : "—"; }

/* ---------------- helpers ---------------- */
const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
const num = (v) => (v === 0 || v == null ? "" : Math.round(v * 100) / 100);
const money2 = (v) => (Number.isFinite(v) ? "$" + v.toFixed(2) : "—");


/* AI 自动感：输入变化时，机器计算值做一次呼吸脉冲 */
let _pulseT = null;
function pulseAuto() {
  const m = document.querySelector("main");
  if (!m) return;
  m.classList.remove("uw-recalc");
  void m.offsetWidth; /* restart animation */
  m.classList.add("uw-recalc");
  clearTimeout(_pulseT);
  _pulseT = setTimeout(() => m.classList.remove("uw-recalc"), 550);
}

/* ---------------- events ---------------- */
function bindInputs() {
  document.addEventListener("input", (e) => {
    const el = e.target;
    if (el.dataset.in) {
      let v = el.type === "number" ? (el.value === "" ? 0 : parseFloat(el.value)) : el.value;
      if (el.dataset.pct) v = f(v) / 100;
      setPath(state, el.dataset.in, v);
      renderAll(true);
      pulseAuto();
      markDirty();
    } else if (el.dataset.t) {
      const i = +el.dataset.i, k = el.dataset.t;
      let v = el.type === "number" ? (el.value === "" ? 0 : parseFloat(el.value)) : el.value;
      if (!state.tenants[i]) state.tenants[i] = {};
      state.tenants[i][k] = v;
      renderAll(true);
      pulseAuto();
      markDirty();
    } else if (el.dataset.cf) {
      const key = el.dataset.k;
      let v = el.value === "" ? 0 : parseFloat(el.value);
      if (el.dataset.ispct === "1") v = f(v) / 100;
      state[el.dataset.cf][key] = v;
      // 只重算数字，不重建输入框（避免光标跳）
      renderAll(true);
      pulseAuto();
      markDirty();
    }
  });
  document.addEventListener("change", (e) => {
    const el = e.target;
    if (el.dataset.in && el.tagName === "SELECT") {
      setPath(state, el.dataset.in, el.value);
      renderAll(true);
      markDirty();
    }
  });
  document.addEventListener("click", (e) => {
    const del = e.target.closest(".del-tenant");
    if (del) {
      state.tenants.splice(+del.dataset.i, 1);
      renderAll(true);
      markDirty();
      return;
    }
    if (e.target.closest("#btnFillVac")) {
      const rr = result.rent_roll;
      const impl = rr.total_sf_property ? rr.vacant_sf / rr.total_sf_property : 0;
      state.historical.vacancy_pct = Math.round(impl * 10000) / 10000;
      state.proforma.vacancy_pct = Math.round(impl * 10000) / 10000;
      syncInputs(); renderAll(false); markDirty();
    }
  });
  $("#btnAddTenant").addEventListener("click", () => {
    state.tenants.push({ suite: String(state.tenants.length + 1), tenant: "", sf: 0, monthly_rent: 0, underwritten_annual: "" });
    renderAll(false);
    markDirty();
  });
}

/* ---------------- persistence ---------------- */
let dirty = false;
function markDirty() { dirty = true; $("#btnSave").textContent = "保存 *"; }

async function api(path, method, body) {
  const r = await fetch(path, {
    method: method || "GET",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error("API " + r.status);
  return r.json();
}

async function refreshList(selectId) {
  const list = await api("/api/uw/projects");
  const sel = $("#projSel");
  sel.innerHTML = `<option value="">— 选择已保存项目 —</option>` +
    list.map((p) => `<option value="${p.id}">${esc(p.name || ("项目 " + p.id))}</option>`).join("");
  if (selectId) sel.value = selectId;
  $("#btnDel").style.display = selectId ? "" : "none";
}

async function loadProject(id) {
  const p = await api("/api/uw/projects/" + id);
  curId = p.id; curName = p.name || "";
  state = p.input && p.input.property ? p.input : blankState();
  syncInputs();
  renderAll(false);
  dirty = false; $("#btnSave").textContent = "保存";
  refreshList(String(id));
}

function blankState() {
  return {
    property: { name: "", address: "", city: "", state: "", zip: "", county: "", property_type: "Retail", net_rentable_sf: 0, land_acres: 0, parking_spaces: 0, year_built: "", year_renovated: "", buildings: "", floors: "", occupancy_as_of: "" },
    tenants: [{ suite: "1", tenant: "", sf: 0, monthly_rent: 0, underwritten_annual: "" }],
    vacant_sf: 0,
    historical: baseScenario(), proforma: baseScenario(),
    analysis: { purchase_price: 0, building_repairs: 0, capital_reserve: 0, lender_fees: 0, closing_costs: 0, down_pct: 0.3, rate: 0.06, amort_type: "IO", amort_years: 30, market_cap_rate: 0.04, abatements: 0, underwritten_noi: null, projected_noi: null, inplace_noi_cf: null, hold_years: 5, noi_growth: 0.02, exit_cap_rate: 0.05 },
  };
}
function baseScenario() {
  const o = { cam_recovery: 0, parking_income: 0, other_income: 0, vacancy_pct: 0, tenant_improvements: 0, capex: 0, leasing_commissions: 0 };
  EXPENSES.forEach(([k]) => (o[k] = 0));
  return o;
}

function syncInputs() {
  $$("[data-in]").forEach((el) => {
    if (el.tagName === "SELECT") el.value = getPath(state, el.dataset.in) || "IO";
    else setInputVal(el, el.dataset.in);
  });
}

async function init() {
  bindInputs();
  // 默认空白：用户自己输入信息，自动跳出计算结果
  state = blankState();
  curId = null; curName = "";
  syncInputs();
  renderAll(false);

  $("#btnExample").addEventListener("click", async () => {
    try {
      const t = await api("/api/uw/template");
      state = t.example_39_main;
      curId = null;
      syncInputs(); renderAll(false); markDirty();
    } catch (e) {
      alert("模板示例加载失败（网络/服务异常），请稍后重试");
    }
  });
  $("#btnNew").addEventListener("click", () => {
    state = blankState(); curId = null; curName = "";
    syncInputs(); renderAll(false); markDirty();
    $("#projSel").value = "";
  });
  $("#btnSyncNoi").addEventListener("click", () => {
    const r = computeAll(state);
    state.analysis.underwritten_noi = Math.round(r.historical.noi * 100) / 100;
    state.analysis.projected_noi = Math.round(r.proforma.noi * 100) / 100;
    state.analysis.inplace_noi_cf = Math.round(r.historical.noi * 100) / 100;
    syncInputs(); renderAll(false); markDirty();
  });
  $("#btnSave").addEventListener("click", async () => {
    const name = curName || (state.property && state.property.name) || "未命名核保项目";
    const nm = prompt("项目名称", name);
    if (nm == null) return;
    try {
      if (curId) {
        await api("/api/uw/projects/" + curId, "PUT", { name: nm, input: state });
      } else {
        const p = await api("/api/uw/projects", "POST", { name: nm, input: state });
        curId = p.id;
      }
      curName = nm; dirty = false; $("#btnSave").textContent = "保存";
      refreshList(String(curId));
    } catch (e) {
      alert("保存失败（网络/服务异常），输入的内容还在页面上，请稍后重试");
    }
  });
  $("#btnDel").addEventListener("click", async () => {
    if (!curId || !confirm("删除该核保项目？")) return;
    await api("/api/uw/projects/" + curId, "DELETE");
    curId = null; state = blankState();
    syncInputs(); renderAll(false);
    refreshList();
  });
  $("#projSel").addEventListener("change", (e) => {
    if (e.target.value) loadProject(e.target.value);
  });
  window.addEventListener("beforeunload", (e) => {
    if (dirty) { e.preventDefault(); e.returnValue = ""; }
  });
  // ?pid= 直接打开指定项目（从首页搜集转入）
  const pid = new URLSearchParams(location.search).get('pid');
  // 保存列表最后加载：API 失败也不影响本地输入和计算
  try { await refreshList(pid || undefined); } catch (e) { /* 离线模式：仅本地计算可用 */ }
  if (pid) {
    try { await loadProject(pid); } catch (e) { /* 项目不存在则保持空白 */ }
  }
}

document.addEventListener("DOMContentLoaded", init);
})();
