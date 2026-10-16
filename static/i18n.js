/* DealDesk i18n（2026-10-16，PH launch EN 界面）.
 * 规则：默认 zh；?lang=en 深链优先，其次 localStorage('dd_lang')，切换状态刷新不丢。
 * T(zh, ...args)：lang=en 时查 EN 字典（缺项回退 zh 原文，绝不空白），{0}{1} 占位替换。
 * 静态 HTML 文案走 data-i18n（文本节点按 key 匹配替换）/ data-i18n-html / data-i18n-ph。
 * verdict 结论词（BUY/HOLD/PASS/VETO）为 B1-06 双语口径，不在本字典动。 */
'use strict';
(function () {
  const Q = new URLSearchParams(location.search);
  let lang = Q.get('lang');
  if (lang !== 'en' && lang !== 'zh') lang = null;
  if (lang) { try { localStorage.setItem('dd_lang', lang); } catch (e) {} }
  if (!lang) { try { lang = localStorage.getItem('dd_lang'); } catch (e) {} }
  if (lang !== 'en') lang = 'zh';
  window.DD_LANG = lang;

  const EN = {
    /* ---- 通用 chrome ---- */
    '换地址': 'Change address', '切换视角': 'Switch view',
    '导出 PDF ▾': 'Export PDF ▾', '投资备忘录 PDF': 'Investment memo PDF',
    '页面原样打印': 'Print page as-is', '商业核保 PDF·经典版': 'Commercial UW PDF · Classic',
    '商业核保 PDF·增强版': 'Commercial UW PDF · Enhanced', '导出 Excel': 'Export Excel',
    '导出备忘录': 'Export memo', '切换商业视角': 'Switch to commercial view',
    '继续住宅': 'Stay residential', '重新计算': 'Recalculate',
    '收购价 / 要价 $': 'Purchase price / Asking $', '如 850000': 'e.g. 850000',
    '正在分析': 'Analyzing', '待计算': 'Pending', '待接数据源': 'Data source pending',
    '实数已验证': 'Verified actuals', '估算待核验': 'Estimate — unverified',
    '实测': 'Actual', '估算': 'Estimate', '待验证': 'Unverified', '测算': 'Modelled',
    '筛选辅助工具，不构成投资建议。': 'Screening aid only — not investment advice.',
    '投资筛选用，非 USPAP 合规评估报告，不能用于贷款/诉讼；未实地勘察、未审阅租约原件。':
      'For investment screening only; not a USPAP-compliant appraisal, not for lending or litigation use; no site inspection performed; original leases not reviewed.',
    '否决': 'VETO', ' 档': ' tier', '、': ', ', '；': '; ', '（暂无）': '(none yet)',
    '关键指标': 'Key metrics', '市场区间 ': 'Market range ',
    '待接数据源：': 'Data source pending:', '/SF/年': '/SF/yr',
    '暂无预测数据': 'No forecast data yet',
    '保守': 'Conservative', '基准': 'Base case', '乐观': 'Optimistic',
    /* ---- d.html 静态层 ---- */
    'DealDesk · 买房决策单页': 'DealDesk · One-Page Buy Decision',
    'Zone 1 · 结论': 'Zone 1 · Verdict',
    '价格公不公允': 'Is the price fair?', '现金流构成': 'Cash-flow breakdown',
    '市场水温': 'Market temperature', '未来估价会是多少': 'Future value estimate',
    '趋势外推（实验）': 'Trend extrapolation (experimental)', '假设与明细': 'Assumptions & details',
    '怎么看这页：<b>先看结论</b>（值得买/再看看/别碰）· <b>再看价格证据</b>（Zone 3）· <b>最后看假设</b>（Zone 7，可改数重算）':
      'How to read this page: <b>verdict first</b> (Worth it / Keep looking / Walk away) · <b>then the price evidence</b> (Zone 3) · <b>assumptions last</b> (Zone 7 — change numbers and recompute)',
    '怎么看这页：<b>先看结论</b>（BUY / HOLD / PASS，一票否决为 VETO）· <b>再看价格证据</b>（Zone 3）· <b>最后看假设</b>（Zone 7，可改数重算）':
      'How to read this page: <b>verdict first</b> (BUY / HOLD / PASS; a veto shows as VETO) · <b>then the price evidence</b> (Zone 3) · <b>assumptions last</b> (Zone 7 — change numbers and recompute)',
    '置信度 = 证据质量分（0-100），不是推荐强度：它回答"证据有多硬"，不回答"该不该买"。deal 评分是买卖打分（<50 别碰），置信度是证据质量分——两码事。':
      'Confidence = an evidence-quality score (0-100), not recommendation strength: it answers "how solid is the evidence", not "should you buy". The deal score grades the buy (<50 = PASS); confidence grades the evidence — two different things.',
    '数据来源图例（常驻）': 'Data-source legend (always on)',
    '角标 <span class="pf">PF</span> = 基于卖方预测（pro forma），非实数。':
      'The <span class="pf">PF</span> flag = based on seller projections (pro forma), not actuals.',
    '换个地址重新分析': 'Change the address and re-analyze',
    '切换住宅/商业视角': 'Switch residential / commercial view',
    '导出当前 deal 的投资备忘录 PDF': 'Export this deal\'s investment memo PDF',
    '收购价或要价': 'Purchase or asking price', '物业地址': 'Property address',
    '敏感性矩阵': 'Sensitivity matrix',
    '筛选辅助工具，不构成投资建议。估值给区间；comps 高度一致时诚实标注单点，不拿"区间"包装单点。comps 只是起点，出价前请核验相似度/日期/位置/成色/市场动向。':
      'Screening aid only — not investment advice. Valuations come as ranges; when comps agree tightly we honestly label a single point instead of dressing it up as a range. Comps are only a starting point — verify similarity, dates, location, condition and market direction before offering.',
    /* ---- index.html 落地页＋输入 ---- */
    'DealDesk · 一页纸的买房决策': 'DealDesk · The One-Page Buy Decision',
    ' 一页纸的买房决策': ' The One-Page Buy Decision',
    '一页纸的买房决策': ' The One-Page Buy Decision',
    '打开这个页面，3 秒知道要不要深入看，再往下翻知道为什么。':
      'Open this page and know in 3 seconds whether to dig deeper — scroll down to see why.',
    '选好类型、输入地址——所有分析都在': 'Pick the type, enter the address — every analysis happens on the ',
    '统一决策单页': 'one unified decision page',
    '上完成，没有第二入口。': ', with no second entrance.',
    '住宅 / 个人': 'Residential / Personal', '住宅': 'Residential', '商业': 'Commercial',
    '小白模式': 'Beginner mode', '专业模式': 'Pro mode',
    '买来自住或收租': 'Buy to live in, or to rent out',
    '买来做生意或收租': 'Buy to run a business in, or to rent out',
    '大白话结论：值得买 / 再看看 / 别碰': 'Plain-language verdict: Worth it / Keep looking / Walk away',
    '零术语，每个数字配"这意味着什么"': 'Zero jargon — every number comes with a "what this means"',
    '全程有人带着走': 'Guided the whole way',
    'cap rate / NOI / DSCR / 压力测试全开': 'Cap rate / NOI / DSCR / stress tests — all on',
    '缺口明确标出来，不假装有数据': 'Gaps are flagged openly — no pretending the data exists',
    '术语不解释，默认你懂': 'Terms unexplained — you are expected to know them',
    '· 第一步：告诉我地址': ' · Step 1: tell me the address',
    '输入物业地址，或粘贴 Zillow / Redfin 房源链接或房源文本':
      'Enter the property address, or paste a Zillow / Redfin listing link or listing text',
    '物业类型（选填，用于调 comps 过滤器）': 'Property type (optional — tunes the comps filter)',
    '未选择': 'Not selected', '写字楼': 'Office', '零售': 'Retail', '多户': 'Multifamily', '工业': 'Industrial',
    '收购价 / 要价 $（选填，不填可在结果页补）': 'Purchase / asking price $ (optional — can be added on the results page)',
    '交易结构（决定 verdict 用哪套否决规则，默认普通购买）':
      'Deal structure (decides which veto rule set the verdict uses; default: standard purchase)',
    '普通购买': 'Standard purchase', '贷款购买': 'Purchase with a loan',
    '贷款购买（新办贷款）': 'Purchase with a loan (new loan)',
    'subject-to（承接现有贷款）': 'Subject-to (take over the existing loan)',
    'subject-to 才有"退出预案 / due-on-sale 备用预案"否决项；普通购买/贷款购买永不触发。':
      'Only subject-to carries the "exit plan / due-on-sale backup plan" vetoes; standard and loan purchases never trigger them.',
    '开始分析': 'Start analysis', '← 重选住宅 / 商业': '← Re-pick residential / commercial',
    '商业核保': 'Commercial underwriting', '住宅工作台': 'Residential workbench',
    '旧版住宅': 'Legacy residential', '（只读）': ' (read-only)',
    '已从链接识别地址：{0}（{1}）': 'Address recognized from the link: {0} ({1})',
    '无法识别该链接，请粘贴纯地址': 'That link could not be recognized — paste a plain address',
    '未识别出地址/价格，请粘贴纯地址': 'No address/price recognized — paste a plain address',
    '已从房源文本识别：{0}': 'Recognized from the listing text: {0}',
    '地址': 'Address', '价格 {0}': 'Price {0}',
    '正在拉取 TopHap 数据…': 'Pulling TopHap data…', '正在跑 comps…': 'Running comps…',
    '正在打开决策单页…': 'Opening the decision page…',
    /* ---- d.js：结构/步骤/字段 ---- */
    '未选择 ': 'Not selected', '出售': 'Sell', 'refi（重新贷款）': 'Refi (new loan)',
    '转租购': 'Lease-option', '持有收租': 'Hold & rent',
    '拉取 TopHap 可比成交（recorded sales）': 'Pulling TopHap comps (recorded sales)',
    '跑比较法估值': 'Running the sales-comparison valuation',
    '查市场指数': 'Checking market indices',
    '搜集物业档案（公开记录 enrich）': 'Gathering the property file (public-record enrich)',
    '生成趋势外推（实验）': 'Generating the trend extrapolation (experimental)',
    '未输入地址': 'No address entered',
    '住宅 · 小白模式': 'Residential · Beginner mode', '商业 · 专业模式': 'Commercial · Pro mode',
    '数据截至 {0}（美东时间）': 'Data as of {0} (Eastern Time)',
    '检测到该地址疑似商业物业（{0}），是否切换到商业视角？':
      'This address looks like a commercial property ({0}). Switch to the commercial view?',
    '<div class="empty">没有地址参数。<a href="/">回 landing 输入地址</a></div>':
      '<div class="empty">No address parameter. <a href="/">Back to the landing page to enter an address</a></div>',
    '切换视角会清空当前分析结果并重新计算，继续吗？':
      'Switching views clears the current analysis and recomputes. Continue?',
    '收购价/要价 $': 'Purchase / asking price $', '月租金 $': 'Monthly rent $',
    '年利率 %（百分制）': 'Annual rate % (percent units)', '首付 $': 'Down payment $',
    '空置率 %': 'Vacancy %', '年房产税 $': 'Annual property tax $', '年保险 $': 'Annual insurance $',
    '年租金总收入 $': 'Annual gross rent $', '首付比例 %': 'Down payment %',
    '摊销年数': 'Amortization (years)', '市场 cap %': 'Market cap %',
    '年利率': 'Annual rate', '首付比例': 'Down payment %', '空置率': 'Vacancy',
    '市场 cap': 'Market cap', '首付': 'Down payment', '年房产税': 'Annual property tax',
    '年保险': 'Annual insurance', '{0} 年': '{0} yrs',
    '正在计算打分与 verdict…': 'Scoring and computing the verdict…',
    '计算完成': 'Done', '计算失败：{0}': 'Computation failed: {0}',
    'comps 不足 3 个': 'Fewer than 3 comps',
    '缺结构化 rent roll（WALT/到期集中度/租户集中度无法验证，NOI 可信度降级）':
      'No structured rent roll (WALT / expiry concentration / tenant concentration unverifiable — NOI credibility downgraded)',
    '租金为估算（待与租约/市场核验）': 'Rent is an estimate (pending lease/market verification)',
    '估值区间待计算': 'Valuation range pending',
    '估值 {0}（{1}）': 'Valuation {0} ({1})',
    '估值区间 {0}–{1}': 'Valuation range {0}–{1}',
    '估值区间 {0}–{1}（comps 离散度高，给区间）': 'Valuation range {0}–{1} (comps widely dispersed — range given)',
    'comps 高度一致，单点': 'Comps agree tightly — single point',
    'comps 离散度高，估值置信度已下调，给区间': 'Comps are widely dispersed — confidence cut, range given',
  };
  Object.assign(EN, {
    /* ---- Zone 1 / verdict ---- */
    '待填收购价': 'Asking price needed', '缺收购价': 'Asking price missing',
    '填一下"要价/收购价"（下方 Zone 7），我才能算值不值得买。comps 和估值已经就绪。':
      'Enter the asking/purchase price (Zone 7 below) so I can judge whether it is worth buying. Comps and valuation are ready.',
    '一票否决：': 'Veto: ', '一票否决 ×{0}': 'VETO ×{0}',
    '全口径现金需求 ≈ ': 'Total cash needed ≈ ',
    '（首付＋交割＋储备金）': ' (down payment + closing + reserves)',
    '当前按 0 首付（100% 贷款）测算 → 去 Zone 7 调整首付':
      'Currently modelled at $0 down (100% financing) → adjust the down payment in Zone 7',
    '缺口（已保守降级）：': 'Gaps (verdict conservatively downgraded):',
    '敏感性矩阵：退出 cap × 租金增长率': 'Sensitivity matrix: exit cap × rent growth',
    '租金增长 ＼ 退出 cap': 'Rent growth ＼ Exit cap',
    '格子 = IRR / Equity Multiple；中心格（±0bps）为当前基准假设；退出 cap 假设必须披露。改价 / 改假设后点"重新计算"刷新。':
      'Cells = IRR / Equity Multiple; the center cell (±0bps) is the current base case; the exit-cap assumption must be disclosed. Change the price/assumptions and click "Recalculate" to refresh.',
    '格子 = IRR；中心格为当前基准假设。改价/改假设后点"重新计算"刷新。':
      'Cells = IRR; the center cell is the current base case. Change the price/assumptions and click "Recalculate" to refresh.',
    '空置 ＼ 利率': 'Vacancy ＼ Rate',
    '格子 = 月现金流；中心格为当前基准假设。改价/改假设后点"重新计算"刷新。':
      'Cells = monthly cash flow; the center cell is the current base case. Change the price/assumptions and click "Recalculate" to refresh.',
    /* ---- 数据质量门 / 导出 ---- */
    '⛔ 数据质量门拦截': '⛔ Data-quality gate: blocked',
    '⚠️ 数据质量门告警': '⚠️ Data-quality gate: warning',
    '✅ 数据质量门通过': '✅ Data-quality gate: passed',
    '⛔ 拦截': '⛔ Block', '⚠️ 复核': '⚠️ Review',
    '数据质量门拦截（{0}）：': 'Data-quality gate blocked ({0}):',
    '\n\n请修正矛盾数据后重试。': '\n\nFix the conflicting data and retry.',
    '数据质量门告警（{0}）：': 'Data-quality gate warning ({0}):',
    '\n\n标黄字段请先核实。仍要继续导出吗？': '\n\nVerify the highlighted fields first. Export anyway?',
    '备忘录导出': 'memo export', '商业核保 PDF 导出': 'commercial UW PDF export', 'Excel 导出': 'Excel export',
    '请先完成分析再导出': 'Finish the analysis before exporting',
    '正在生成投资备忘录 PDF…': 'Generating the investment memo PDF…',
    '已导出 PDF': 'PDF exported', 'PDF 生成失败：{0}': 'PDF generation failed: {0}',
    '商业 PDF 需要先导入 rent roll 并计算（Zone 4）': 'Commercial PDF needs a rent roll imported and computed first (Zone 4)',
    '正在生成商业核保 PDF（{0}）…': 'Generating the commercial UW PDF ({0})…',
    '经典版': 'Classic', '增强版': 'Enhanced',
    '商业 Excel 需要先导入 rent roll 并计算（Zone 4）': 'Commercial Excel needs a rent roll imported and computed first (Zone 4)',
    '先填 Zone 7 假设并计算': 'Fill in the Zone 7 assumptions and compute first',
    '正在生成 Excel…': 'Generating Excel…', '已导出 Excel': 'Excel exported',
    'Excel 生成失败：{0}': 'Excel generation failed: {0}',
    /* ---- Zone 2 ---- */
    'Zone 2 · 关键指标': 'Zone 2 · Key metrics',
    '月现金流': 'Monthly cash flow', '贴钱持有': 'Feeding it monthly',
    '每月倒贴 {0}，现金流为负': 'You feed it {0} a month — cash flow is negative',
    '租金覆盖月供还有剩': 'Rent covers the mortgage, with room to spare',
    '比存银行高，但要自己管租客': 'Beats a bank deposit, but you manage the tenants yourself',
    '现金回报率 CoC': 'Cash-on-Cash return',
    '年净现金流 ÷ 全口径现金投入': 'Annual net cash flow ÷ total cash in',
    '租金 vs 月供': 'Rent vs mortgage',
    '租金待补，覆盖率无法计算（未知≠0）': 'Rent not entered — coverage cannot be computed (unknown ≠ 0)',
    '租金能覆盖 {0}% 的月供（本息+税+保险）': 'Rent covers {0}% of the mortgage (P&I + tax + insurance)',
    '填要价并计算后显示': 'Shown after you enter a price and compute',
    '空置假设': 'Vacancy assumption', '租金打 {0} 折计': 'Rent counted at {0}% after vacancy',
    '打分': 'Score', '填要价后计算（上方要价条）': 'Enter a price above and compute',
    '{0} 分': '{0} pts', 'deal 评分（{0}），与 Zone 1 同源': 'Deal score ({0}) — same source as Zone 1',
    '首付维按浮动制打"策略匹配度"：首付越低基础分越高（0%→15 分、25%→0 分）；其余维度没变。多付首付≠更危险。':
      'The down-payment dimension scores "strategy fit" on a sliding scale: the lower the down payment, the higher the base score (0% → 15 pts, 25% → 0 pts); other dimensions are unchanged. A bigger down payment ≠ more dangerous.',
    '价格': 'Price', '待填要价': 'Asking price needed',
    'NOI（双口径）': 'NOI (dual basis)', '银行口径': 'Bank basis',
    '；标准 NOI ': '; standard NOI ',
    '导入租约明细后计算（Zone 4）': 'Computed after importing the lease detail (Zone 4)',
    '待 rent roll': 'Awaiting rent roll', '市场区间待接 ': 'Market range pending ',
    '待 rent roll（无 NOI，不单独出数）': 'Awaiting rent roll (no NOI — no standalone figure)',
    '单个 cap 数字不许单独出现': 'A lone cap figure is never shown on its own',
    'DSCR 双轨': 'DSCR (dual track)', 'trailing 主 / pro forma 辅': 'Trailing primary / pro forma secondary',
    'NOI（银行口径）÷ 拟贷款额': 'NOI (bank basis) ÷ proposed loan',
    '≥8-10% 舒适；<6% 机构资金出局': '8-10%+ comfortable; <6% institutional capital walks',
    '盈亏平衡': 'Breakeven', '缓冲垫 ': 'Cushion ',
    '满租都不够还贷 → 别碰': 'Even full occupancy cannot service the debt → PASS',
    '偏薄': 'Thin', '安全边际厚': 'Thick safety margin',
    /* ---- Zone 3 ---- */
    '正在重新拉取 comps…': 'Re-pulling comps…', 'comps 拉取成功，估值已更新': 'Comps pulled — valuation updated',
    '拉取失败：{0}，可再点重试': 'Pull failed: {0} — click retry to try again',
    '拉取失败': 'Pull failed', '重新拉取': 'Re-pull',
    '<b>comps 拉取失败</b>': '<b>Comps pull failed</b>',
    '不是"没有可比成交"，是数据没拉下来——点下面只重试拉取，不重跑全流程。':
      'This is not "no comparable sales" — the data simply did not download. The button below retries the pull only, not the whole flow.',
    '还没有 comps 数据——TopHap 没返回该地址的可比成交（零结果），换个地址或手动导入 CSV ':
      'No comps yet — TopHap returned no comparable sales for this address (zero results). Try another address or import a CSV manually ',
    '填要价后对比 comps 调整价中位': 'Enter an asking price to compare with the comps adjusted median',
    '低于 comps 调整价中位 {0}': '{0} below the comps adjusted median',
    '高于 comps 调整价中位 {0}': '{0} above the comps adjusted median',
    '与 comps 调整价中位基本持平': 'Roughly in line with the comps adjusted median',
    '估值方法对照': 'Valuation approaches side by side',
    '收益法 Income': 'Income approach', '比较法 Sales': 'Sales approach', '成本法 Cost': 'Cost approach',
    '缺数据 ': 'No data ', 'NOI÷cap，需 cap 证据': 'NOI ÷ cap — needs cap evidence',
    '收益法 50%（NOI 经租约支持）/ 比较法 50%': 'Income 50% (NOI lease-supported) / Sales 50%',
    '收益法：待租约数据（暂不参与）/ 比较法：当前唯一有效方法':
      'Income: awaiting lease data (not participating) / Sales: the only valid method right now',
    '权重披露': 'Weight disclosure',
    '比较法估值': 'Sales-comparison value', '成色调整': 'Condition adjustment',
    '未调整（无依据不做）': 'Not adjusted (no basis, no adjustment)',
    '调和估值': 'Reconciled value', '置信度评分': 'Confidence score',
    '价格对账（四个价格，口径不同不许直接比大小）':
      'Price reconciliation (four prices — different bases, never compare raw)',
    'TopHap 市场价值（公共记录口径）': 'TopHap market value (public-record basis)',
    'TopHap AVM 模型值': 'TopHap AVM model value',
    'TopHap 公共记录的市场价值口径': 'TopHap public-record market-value basis',
    'TopHap 算法估算，未考虑房屋实际成色与内部状况': 'TopHap algorithmic estimate — ignores actual condition and interiors',
    '周边真实成交（recorded sales）调整后加权，反映市场实际愿意付的价格':
      'Weighted from nearby recorded sales after adjustment — what the market actually pays',
    '要价': 'Asking price',
    '卖方要价，是谈判起点，不是房子值多少钱': 'The seller\'s ask — a negotiation start, not what the property is worth',
    '计税估值': 'Tax-assessed value',
    '政府为征税定的价值（{0}），常年滞后于市场，不代表市场价':
      'The government\'s tax value ({0}) — chronically lags the market and is not a market price',
    '— 待接': '— pending',
    '价格锚差异巨大（{0} 倍），需人工核验数据口径':
      'Price anchors diverge wildly ({0}×) — verify the data bases manually',
    '标的成色（五档）': 'Subject condition (5 tiers)',
    '调整依据（必填，无依据不做）': 'Adjustment basis (required — no basis, no adjustment)',
    '如：基于 $45/SF 翻新成本 × 12,000 SF': 'e.g. based on $45/SF renovation cost × 12,000 SF',
    '应用成色调整': 'Apply condition adjustment',
    '本物业（要价）': 'Subject (asking)', '本物业 vs 选中 comps（降序）': 'Subject vs selected comps (descending)',
    '无 comps': 'No comps',
    'comp 勾选器（勾选/剔除实时重算汇总）{0} / {1} 选中 · 中位 $/SF {2}':
      'Comp picker (toggling recomputes live) {0} / {1} selected · median $/SF {2}',
    '地址': 'Address', '成交价': 'Sale price', '面积': 'Area', '调整%': 'Adj. %',
    '选用': 'Include', '重复': 'Duplicate',
    'comps 只是起点，出价前请核验相似度/日期/位置/成色/市场动向。gross adjustment > 25% 的 comp 已标黄。只认 recorded sales；listing 挂牌价不是证据。':
      'Comps are only a starting point — verify similarity, dates, location, condition and market direction before offering. Comps with gross adjustment > 25% are highlighted. Recorded sales only; listing prices are not evidence.',
    '调整依据必填：无依据宁可不做': 'Adjustment basis is required — no basis, no adjustment',
    '已应用成色调整': 'Condition adjustment applied', '调整失败：{0}': 'Adjustment failed: {0}',
    /* ---- 租金 comps 页签 ---- */
    '租金 comps（lease comps，独立页签）': 'Rent comps (lease comps, separate tab)',
    '签约时间': 'Signing date', '租金 NNN 等值': 'Rent (NNN equiv.)', '免租期': 'Free rent', '删': 'Delete',
    '<b>待接数据源：</b>租金 comps 库未接入。字段要求：地址/签约时间/租金 NNN 等值/免租期/TI；所有租金统一 NNN 等值口径（Gross − 当年实际运营费用）。可先手动录入。':
      '<b>Data source pending:</b> the rent-comps library is not connected. Required fields: address / signing date / rent (NNN equiv.) / free rent / TI. All rents use the NNN-equivalent basis (gross minus actual operating expenses for the year). You can enter them manually for now.',
    '租金 NNN 等值（$/SF/年）': 'Rent, NNN equiv. ($/SF/yr)', '如：3 个月': 'e.g. 3 months',
    '手动录入': 'Add manually', '缺免租期和 TI 的租金没有可比性。': 'Rent without free-rent and TI terms is not comparable.',
    '地址和租金必填': 'Address and rent are required', '已录入 1 条租金 comp': '1 rent comp added',
    /* ---- Zone 4 ---- */
    '填 Zone 7 假设并计算后，这里显示现金流构成与 what-if 滑杆。':
      'After you fill in the Zone 7 assumptions and compute, the cash-flow breakdown and what-if sliders appear here.',
    '租金': 'Rent', '− 空置': '− Vacancy', '− 税/险/杂': '− Tax/ins/Other',
    '− 月供（本息）': '− Mortgage (P&I)', '= 净现金流': '= Net cash flow',
    '每月净剩 {0} ': 'Net per month {0} ',
    'what-if（拖动实时重算）': 'What-if (drag to recompute live)',
    '利率': 'Rate', '租金调整': 'Rent adjustment', '利率调整': 'Rate adjustment',
    '这意味着什么：月现金流 {0}，{1}。': 'What this means: monthly cash flow {0}, {1}.',
    '月供口径=等额本息 {0}（贷款 {1}、年利率 {2}%、30 年摊还）＋税/险；{3}。':
      'Mortgage basis = level-payment amortization {0} (loan {1}, annual rate {2}%, 30-year amortization) plus tax/insurance; {3}.',
    '每月要贴钱': 'you feed it money every month',
    '税/险/杂 {0}（含税、保险、维修、capex、管理费）': 'Tax/ins/other {0} (tax, insurance, repairs, capex, management)',
    '税/险/杂 $0（未填/待核验：税、保险、维修、capex、管理费）':
      'Tax/ins/other $0 (not entered / unverified: tax, insurance, repairs, capex, management)',
    '；档案税 {0} 为公共记录未经核验，本次测算未采用':
      '; the file tax figure {0} is an unverified public record and was not used in this run',
    '租约明细待补充：': 'Lease detail needed:',
    'WALT / 到期集中度 / 租户集中度无法验证，NOI 可信度降级。':
      'WALT / expiry concentration / tenant concentration cannot be verified, and NOI credibility is downgraded.',
    '无 rent roll 的 deal 最高只给 HOLD；若触发一票否决，结论为独立的否决态（住宅"否决"/商业"VETO"，红）。':
      'A deal with no rent roll caps at HOLD; if a veto fires, the verdict is the standalone veto state (residential "Veto" / commercial "VETO", red).',
    '导入 rent roll（Excel 模板 / 粘贴），再跑银行口径核保':
      'Import the rent roll (Excel template / paste), then run bank-basis underwriting',
    '下载 Excel 模板': 'Download the Excel template', '上传填好的模板': 'Upload the completed template',
    '导入并核保': 'Import & underwrite',
    '顺序：rent roll 明细 → NOI 调整桥 → DSCR 双轨 → 盈亏平衡 → 压力测试。NOI 是 rent roll 的孩子。':
      'Order: rent-roll detail → NOI adjustment bridge → dual-track DSCR → breakeven → stress test. NOI is the child of the rent roll.',
    '先选择 Excel 文件': 'Choose an Excel file first', '正在导入 rent roll…': 'Importing the rent roll…',
    '导入 {0} 个租户': 'Imported {0} tenants',
    '（跳过模板示例行 {0}）': ' (skipped {0} template example rows)',
    '（{0} 行日期解析失败，租期已置空请核对）': ' ({0} rows had unparseable dates — lease terms blanked, please verify)',
    '，正在核保…': ' — underwriting…', '核保完成': 'Underwriting complete',
    '导入失败：{0}': 'Import failed: {0}',
    'rent roll 明细（{0} 租户）': 'Rent-roll detail ({0} tenants)',
    '单元': 'Suite', '租户': 'Tenant', '月租金': 'Monthly rent', '租期': 'Lease term', '费用结构': 'Expense structure',
    '无租户行': 'No tenant rows',
    'WALT {0} · 前三租户集中度 {1}{2}': 'WALT {0} · Top-3 tenant concentration {1}{2}',
    ' 年（租金加权）': ' yrs (rent-weighted)', '（>60% 单租户风险）': ' (>60% single-tenant risk)',
    'NOI 银行调整桥 waterfall': 'NOI bank-adjustment bridge (waterfall)',
    '未来 5 年到期租金（到期悬崖标红）': 'Rent expiring in the next 5 years (expiry cliffs in red)',
    'Trailing 主': 'Trailing (primary)', 'Pro forma 辅 ': 'Pro forma (secondary) ',
    '压力测试表（破红线标红；+200bps 后 DSCR<1.20 即条件通过，破 1.0 结构不可行）':
      'Stress test (red-line breaks in red; after +200bps, DSCR <1.20 = conditional pass, breaking 1.0 = structurally infeasible)',
    '档位': 'Scenario',
    '红线：DSCR ≥1.20 / Debt Yield ≥6% / Breakeven ≤100%。': 'Red lines: DSCR ≥1.20 / Debt Yield ≥6% / Breakeven ≤100%.',
    /* ---- Zone 5/6 ---- */
    '该邮编 {0} 有市场指数覆盖 ': 'ZIP {0} has market-index coverage ',
    '该邮编 {0} 暂无市场指数': 'No market index for ZIP {0} yet',
    '——不许静默用 MSA 代替 ': ' — never silently substitute the MSA ',
    '市场指数待查：': 'Market index pending:',
    '地址中未识别邮编，或市场库未覆盖 ': 'No ZIP recognized in the address, or the market library has no coverage ',
    'cap 分布基于 {0} 个有 NOI 的 comps': 'Cap distribution based on {0} comps with NOI',
    'cap 分布：成交 NOI 非公开，整列灰显，仅供参考 ': 'Cap distribution: transaction NOI is not public — the column is greyed out, for reference only ',
    '合同 vs 市场租金 reversion': 'In-place vs market rent (reversion)',
    '市场租金缺口——租金 comps 库未接入，reversion 无法计算 ':
      'Market-rent gap — the rent-comps library is not connected, so reversion cannot be computed ',
    '冲突检查：listing 租金涨幅假设 vs 市场实际增速——市场数据缺失时不做断言。':
      'Conflict check: listing rent-growth assumptions vs actual market growth — no assertions while market data is missing.',
    '市场指标（公开指数）': 'Market indicators (public indices)',
    '数据源：': 'Source: ', ' · 发布：': ' · Release: ',
    '暂无市场指数数据（待接数据源） ': 'No market-index data yet (data source pending) ',
    '市场': 'Market', '说明': 'Notes',
    '每行误差标注：基于公开指数；历史回测误差未在本页披露，以发布机构（FHFA/FRED）口径为准。新增供给 pipeline：待接数据源 ':
      'Error note: based on public indices; historical backtest error is not disclosed on this page — refer to the publishing agencies (FHFA/FRED). New-supply pipeline: data source pending ',
    '暂无预测数据 ': 'No forecast data yet ',
    '模型预测 5 年后值 ': 'Model forecast — value in 5 years ',
    '现在': 'Now', '5 年后': 'In 5 years', '5 年估值预测': '5-year value forecast',
    '模型预测，基于过去趋势外推，方法未公开；历史回测误差无公开数据，不做断言；不构成投资建议；银行承销不采用。forecast 输出绝不回流进 DSCR/NOI/verdict 计算。':
      'Model forecast from past-trend extrapolation; methodology not public; no public backtest-error data, so no claims are made; not investment advice; not used in bank underwriting. Forecast output never feeds back into DSCR/NOI/verdict calculations.',
    '商业逐年表：见上方分情景行（持有/出售决策参考，reversion 故事约束涨幅：预测涨幅不得超过 reversion 能支撑的幅度）。':
      'Commercial year-by-year table: see the scenario rows above (for hold/sell decisions; the reversion story caps growth — forecast growth may not exceed what reversion can support).',
    '（{0}%/年）': ' ({0}%/yr)',
    /* ---- Zone 7 ---- */
    '假设参数（可编辑，改数重算；凡影响 verdict 的输入旁边都有改数入口）':
      'Assumptions (editable — change a number and recompute; every verdict-affecting input has an edit entry beside it)',
    '交易结构（决定 verdict 否决规则）': 'Deal structure (drives the verdict veto rules)',
    '退出策略（选了即解除"无退出预案"否决）': 'Exit strategy (selecting one clears the "no exit plan" veto)',
    '承接贷款余额 $（subject-to：卖家现有贷款余额，空=要价−首付）':
      'Assumed loan balance $ (subject-to: the seller\'s existing balance; blank = price − down payment)',
    'subject-to 才有"无退出预案 / due-on-sale 备用预案"否决项；普通购买/贷款购买永不触发。':
      'Only subject-to carries the "no exit plan / due-on-sale backup plan" vetoes; standard and new-loan purchases never trigger them.',
    '提醒：持有收租不能应对银行执行 due-on-sale（要求提前还款），"due-on-sale 备用预案"否决仍在；需另选 refi/出售/转租购之一才能解除。':
      'Note: hold-and-rent cannot answer a due-on-sale call (the bank demands early repayment), so the "due-on-sale backup plan" veto still stands; pick refi / sell / lease-option to clear it.',
    '拟贷款额 $（Debt Yield 用；空=模板贷款额）': 'Proposed loan $ (for Debt Yield; blank = template loan amount)',
    'comps 明细（数字右对齐）': 'Comps detail (numbers right-aligned)',
    '成交日': 'Sale date',
    '物业档案（{0}，{1}）': 'Property file ({0}, {1})',
    '待手动补：': 'To fill in manually: ', '物业档案搜集中…': 'Gathering the property file…',
    '交割前必备文件 checklist（银行会要）': 'Pre-closing document checklist (the bank will ask)',
    '文件': 'Document', '为什么': 'Why', '找谁要': 'Who to ask', '状态': 'Status',
    ' 租户确认函': ' tenant estoppel certificate',
    '核验租约真实性': 'Verify lease authenticity', '卖方/租户': 'Seller / tenants',
    'Phase I 环境报告': 'Phase I environmental report',
    '排除污染责任': 'Rule out contamination liability', '环境顾问': 'Environmental consultant',
    'PCA 物业状况报告': 'PCA property condition report',
    '量化 deferred capex': 'Quantify deferred capex', '工程顾问': 'Engineering consultant',
    'Authorization to release（卖方向贷款方索取）': 'Authorization to release (seller requests it from the lender)',
    '核实贷款真实余额/利率/逾期': 'Verify the loan\'s true balance / rate / delinquency', '卖方': 'Seller',
    '状态：未验证——交割前向卖方索取，此项永不作为自动一票否决。':
      'Status: unverified — request it from the seller before closing; this item never acts as an automatic veto.',
    'Sponsor 声明：本工具评估物业与交易结构，不评估借款人信用。':
      'Sponsor note: this tool evaluates the property and deal structure, not borrower credit.',
    '交割前 checklist': 'Pre-closing checklist', '事项': 'Item',
    '房屋检查（inspection）': 'Home inspection',
    '发现结构/水电隐患': 'Find structural / plumbing / electrical issues', '验房师': 'Home inspector',
    '产权调查（title search）': 'Title search',
    '排除留置/欠费/纠纷': 'Rule out liens / arrears / disputes', '产权公司': 'Title company',
    'Confidence 因子拆解（公式公开）': 'Confidence factor breakdown (formula is public)',
    '因子': 'Factor', '权重': 'Weight', '得分': 'Score', '备注': 'Notes',
    '房子值多少，我们看三路证据：① <b>比较法</b>——附近最近真实卖掉的类似房子，按远近加权、取中间值，最抗忽悠；单套调整超过 25% 的标黄提醒。② <b>收益法</b>——房子一年净赚的钱 ÷ 市场回报率（cap），cap 没有市场证据时用"投资带法"估一个宽区间。③ <b>成本法</b>——重盖要花多少钱，数据源还没接。三路价格差太多（分歧>40%）机器就不下结论，转人工。估值基准日：{0}（美东时间）。用途限制：{1}':
      'How we value a property — three lines of evidence: ① <b>Sales comparison</b> — similar nearby homes that actually sold recently, weighted by distance, median taken; the hardest to game. Single-comp adjustments over 25% are flagged. ② <b>Income approach</b> — the property\'s annual net income ÷ the market return (cap); with no market cap evidence, a wide band-of-investment range is used. ③ <b>Cost approach</b> — what it would cost to rebuild; data source not connected yet. If the three lines diverge too far (>40%), the machine gives no verdict and routes to manual review. Valuation date: {0} (Eastern Time). Use limits: {1}',
    '术语表：': 'Glossary: ',
    '方法论脚注（人话版）': 'Methodology footnote (plain language)',
  });
  window.DD_EN_DICT = EN;

  window.T = function (zh, ...args) {
    let s = (lang === 'en' && Object.prototype.hasOwnProperty.call(EN, zh)) ? EN[zh] : zh;
    args.forEach((a, i) => { s = s.split('{' + i + '}').join(String(a)); });
    return s;
  };

  /* 术语表 EN 定义（key 与 d.js GLOSSARY 同名；术语名本身多为英文，仅 P0 缺口/三法分歧需改名） */
  window.GLOSSARY_EN = {
    'subject-to': 'Buying by simply keeping the seller\'s existing mortgage payments going — no new loan of your own; the bank can demand full repayment (see due-on-sale).',
    'due-on-sale': 'A loan clause: once the property changes hands, the bank may demand immediate repayment in full. The biggest risk in subject-to deals.',
    'refi': 'Refinancing: replacing the old loan with a new one — often used to answer a due-on-sale call or cut the monthly payment.',
    'pro forma': 'The seller\'s "projected" numbers (e.g. forecast rent) — not actuals; reference only, never take them at face value.',
    'PITI': 'The full monthly payment: Principal + Interest + Tax + Insurance.',
    'EGI': 'Effective Gross Income: total rent after the vacancy haircut — what you actually collect.',
    'NOI': 'Net Operating Income: rental income minus all operating expenses (tax, insurance, repairs, management) — what the property itself earns, before debt service.',
    'comps': 'Comparable sales: similar nearby properties that recently sold — used to judge what this one is worth. Recorded sales only, never asking prices.',
    'CMA': 'Comparative Market Analysis: how brokers price a property from comps.',
    'DSCR': 'Debt Service Coverage Ratio: NOI ÷ annual debt service. 1.2 means the property earns 1.2x its annual payments; below 1.0 you are feeding it. Banks usually require ≥ 1.2.',
    'cap rate': 'Capitalization rate: annual NOI ÷ price. The higher the cap, the more a property earns for the same price.',
    'WALT': 'Weighted Average Lease Term: the rent-weighted average years remaining across leases. Shorter means more re-leasing pressure soon.',
    'TI/LC': 'Tenant Improvements / Leasing Commissions: money spent to keep tenants — a major hidden cost in commercial real estate.',
    'balloon': 'A balloon loan: interest-only (or partial) payments, then the whole principal at maturity. Miss it and you must sell or refinance.',
    'estoppel': 'A tenant estoppel certificate: the tenant confirms in writing "the lease is real and the rent is this" — protection against seller fabrication.',
    'NNN': 'Triple-net lease: the tenant pays tax, insurance and maintenance on top of rent; the landlord collects net money.',
    'P0 缺口': 'Key missing information that must be filled before deciding (e.g. the real leases, the loan terms). With gaps open, the verdict is automatically downgraded one notch.',
    '三法分歧': 'The three valuation approaches (sales / income / cost) produce prices too far apart — the machine gives no verdict and routes to manual review.',
  };
  window.TERM_EN = {'P0 缺口': 'P0 gap', '三法分歧': 'Three-approach divergence'};

  function applyDom() {
    if (lang !== 'en') return;
    document.documentElement.lang = 'en';
    if (EN[document.title]) document.title = EN[document.title];
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const key = el.getAttribute('data-i18n');
      const val = Object.prototype.hasOwnProperty.call(EN, key) ? EN[key] : EN[key.trim()];
      if (val === undefined) return;
      if (el.hasAttribute('data-i18n-html')) { el.innerHTML = val; return; }
      const nodes = [];
      (function walk(n) { n.childNodes.forEach(c => { if (c.nodeType === 3) nodes.push(c); else walk(c); }); })(el);
      const hit = nodes.find(n => n.textContent.trim() === key.trim());
      if (hit) hit.textContent = val;
      else if (!el.children.length) el.textContent = val;
    });
    document.querySelectorAll('[data-i18n-ph]').forEach(el => {
      const key = el.getAttribute('data-i18n-ph');
      if (EN[key]) el.setAttribute('placeholder', EN[key]);
    });
    document.querySelectorAll('[data-i18n-title]').forEach(el => {
      const key = el.getAttribute('data-i18n-title');
      if (EN[key]) el.setAttribute('title', EN[key]);
    });
    document.querySelectorAll('[data-i18n-aria]').forEach(el => {
      const key = el.getAttribute('data-i18n-aria');
      if (EN[key]) el.setAttribute('aria-label', EN[key]);
    });
  }
  document.addEventListener('DOMContentLoaded', applyDom);
  window.DD_applyDom = applyDom;

  /* 语言切换按钮：点击后写 localStorage + 更新 ?lang= 并 reload（状态可保持、刷新不丢） */
  window.mountLangToggle = function (parent) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'btn ghost';
    b.textContent = lang === 'en' ? '中文' : 'EN';
    b.title = lang === 'en' ? '切换到中文' : 'Switch to English';
    b.addEventListener('click', () => {
      const next = lang === 'en' ? 'zh' : 'en';
      try { localStorage.setItem('dd_lang', next); } catch (e) {}
      const u = new URL(location.href);
      u.searchParams.set('lang', next);
      location.href = u.toString();
    });
    (parent || document.body).appendChild(b);
    return b;
  };
})();
