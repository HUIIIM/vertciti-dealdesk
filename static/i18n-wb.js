/* DealDesk workbench i18n (EN layer for workbench.html / workbench.js).
 * Loads after i18n.js. zh stays the default; only runs when DD_LANG === 'en'.
 * workbench renders most of its text from JS templates, so instead of adding
 * data-i18n to hundreds of nodes this walks text nodes (and placeholder /
 * title / alt) and translates them, again on every DOM mutation:
 *   1. exact match of the trimmed node text against the dictionary;
 *   2. otherwise fragment substitution (longest first) + number patterns,
 *      applied ONLY if no Chinese is left afterwards. A node that still has
 *      Chinese (e.g. a note the user typed) is left exactly as it was — never
 *      half-translated. Input values and <textarea> content are never touched.
 */
'use strict';
(function () {
  /* language toggle on both zh and en pages (i18n.js provides mountLangToggle) */
  const mountToggle = () => {
    const host = document.querySelector('header.top');
    if (host && window.mountLangToggle) window.mountLangToggle(host);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mountToggle); else mountToggle();
  if (window.DD_LANG !== 'en') return;

  const W = {
    /* ---- page chrome ---- */
    'DealDesk · 全面分析工作台': 'DealDesk · Full Analysis Workbench',
    '统一结论口径：值得买 · BUY / 再看看 · HOLD / 别碰 · PASS（一票否决 · VETO 为独立第 4 状态）':
      'One verdict vocabulary: BUY / HOLD / PASS (a VETO is a separate 4th state)',
    '全面分析工作台': 'Full Analysis Workbench',
    'vertciti 房地产收购部 · 从一条地址开始：录入 → 测算 → 估值 → 预测 → 周边 → 市场调查，一次跑完':
      'vertciti real-estate acquisitions · Start from one address: intake → metrics → valuation → forecast → nearby → market research, in one run',
    '← 返回打分台': '← Back to scoring desk',

    /* ---- ⓪ intake ---- */
    '⓪ 智能搜集': '⓪ Smart intake', '四合一入口': 'Four ways in',
    '地址 / 房源链接 / PDF / 房源页截图 任选其一 —— pipeline 自动全网搜集并填表。每个字段标注来源＋抓取时间＋可信度；抓不到的标"需手动补"；卖方数字标"卖方口径、待验证"；截图走视觉提取，泡杯咖啡的功夫就好（约 10 分钟）。':
      'Use any one of address / listing link / PDF / listing screenshot — the pipeline searches the web and fills the form. Every field shows its source, fetch time and confidence; anything it can\'t find is marked "fill manually"; seller numbers are marked "seller-stated, unverified"; screenshots go through visual extraction (about 10 minutes).',
    '把': 'Drag a ', '房源页截图': 'listing screenshot', '（png/jpg）拖到这里；或从浏览器地址栏把': ' (png/jpg) here, or drag a ',
    '房源链接': 'listing link', '拖进来': ' in from the address bar',
    '拖入后即时显示并开始解析 pipeline（截图走视觉提取，约10分钟）':
      'Shown immediately and parsed by the pipeline (screenshots use visual extraction, about 10 minutes)',
    '① 纯地址': '① Address only', '如 123 Main St, Tampa, FL 33602': 'e.g. 123 Main St, Tampa, FL 33602',
    '② 房源链接': '② Listing link', '粘贴 Zillow / Redfin / Realtor 房源 URL': 'Paste a Zillow / Redfin / Realtor listing URL',
    '③ PDF（flyer / OM / 卖方材料）': '③ PDF (flyer / OM / seller package)', '④ 房源页截图': '④ Listing screenshot',
    '地址搜集': 'Search by address', '链接解析＋搜集': 'Parse link + search', '链接解析＋': 'Parse link + ',
    '解析 PDF': 'Parse PDF', '上传截图': 'Upload screenshot', '刷新截图提取结果': 'Refresh screenshot results',

    /* ---- ① property ---- */
    '① 物业录入': '① Property intake',
    '地址 / 类型 / 面积 / 要价 / 融资结构 / 租金 / 税费与各项费用。填完点「测算」。':
      'Address / type / size / asking price / financing / rent / taxes and expenses. Then click "Calculate".',
    '如 450 West 44th Street, New York, NY': 'e.g. 450 West 44th Street, New York, NY',
    '物业类型': 'Property type', '建筑面积 SF': 'Building area SF', '单元数': 'Units',
    '要价 / 收购价 $': 'Asking / purchase price $', '贷款余额 $': 'Loan balance $', '年利率 %': 'Interest rate %',
    '剩余年限': 'Years remaining', '其他月收入 $': 'Other monthly income $', '月 HOA $': 'Monthly HOA $',
    '业主承担水电/月 $': 'Owner-paid utilities / mo $', '维修 %（按租金）': 'Maintenance % (of rent)',
    'CapEx %（按租金）': 'CapEx % (of rent)', '管理费 %（按实收）': 'Management % (of collected)',
    '交割费用 $': 'Closing costs $', '初期维修 $': 'Initial repairs $', '储备月数（按 PITI）': 'Reserve months (of PITI)',
    '测算结果': 'Metrics', '有效租金 EGI/月': 'Effective rent EGI / mo', '营业费用/月': 'Operating expenses / mo',
    '年 NOI': 'Annual NOI', '按要价 cap rate': 'Cap rate at asking', '全口径现金需求': 'All-in cash required',
    '要价 $/SF': 'Asking $/SF', '月供（本息）': 'Monthly P&I', '月净现金流': 'Monthly net cash flow',
    '年净现金流': 'Annual net cash flow', '测算失败：': 'Calculation failed: ',

    /* ---- ② comps ---- */
    '② 可比成交 Comps': '② Comparable sales (comps)',
    '一键从 TopHap CMA 拉取可比成交（recorded sales 口径），或手动录入。统计条基于':
      'Pull comps from TopHap CMA in one click (recorded sales), or enter them by hand. Stats use',
    '已采用': 'adopted', '案例实时计算；丢弃须填理由；所有价格均为公开记录，不构成承诺。':
      'comps, live; discarding requires a reason; all prices are public records, not commitments.',
    '一键拉取': 'One-click pull', '标的地址': 'Subject address', 'e.g. 450 W 44th St, New York, NY 10036': 'e.g. 450 W 44th St, New York, NY 10036',
    '如 450 W 44th St, New York, NY 10036': 'e.g. 450 W 44th St, New York, NY 10036',
    '🔎 拉取可比成交': '🔎 Pull comps', '可比地址': 'Comp address',
    '已成交 sold': 'Sold', '已签约 under contract': 'Under contract', '在售挂牌 for sale': 'For sale',
    '已成交': 'Sold', '已签约': 'Under contract', '在售挂牌': 'For sale',
    '价格 $': 'Price $', '成交/挂牌日期': 'Sale / list date', '面积 SF': 'Area SF', '面积SF': 'Area SF',
    '距离（英里）': 'Distance (mi)', '调整 %（可±）': 'Adjustment % (±)', '年 NOI $（可选，算 cap rate）': 'Annual NOI $ (optional, for cap rate)',
    '来源（必填）': 'Source (required)', '如 手动录入 / CoStar / Redfin': 'e.g. manual / CoStar / Redfin',
    '如：需大修 / 新装修': 'e.g. needs major repair / newly renovated',
    '＋ 添加可比': '+ Add comp', '清空': 'Clear', 'CSV 导入（表头）：': 'CSV import (header row):',
    '粘贴 CSV（含表头）后点导入': 'Paste CSV (with header) then click Import', '导入 CSV': 'Import CSV',
    '三态口径：已成交=登记成交价；已签约=签约价（仅参考）；在售挂牌=挂牌价（仅参考）。估值/统计只用':
      'Three states: Sold = recorded sale price; Under contract = contract price (reference only); For sale = list price (reference only). Valuation and stats use only',
    '案例。': 'comps.', '未填': 'Not filled', '丢弃理由（必填）': 'Reason for discarding (required)',
    '已丢弃': 'Discarded', '缺来源': 'No source', '请填写丢弃理由': 'Please give a reason for discarding',
    '请填写价格': 'Please enter a price', '请填写来源（必填）': 'Please enter a source (required)',
    '请先输入标的地址': 'Please enter the subject address first',
    '⏳ 从 TopHap CMA 拉取可比成交中（约 30–90 秒）…': '⏳ Pulling comps from TopHap CMA (about 30–90 s)…',
    '请先粘贴 CSV': 'Please paste CSV first', '导入失败：': 'Import failed: ',
    '$/SF 分布（已采用案例，': '$/SF distribution (adopted comps, ', '已采用案例': 'Adopted comps', '中位 $/SF': 'Median $/SF',
    '区间': 'Range', '统计条：暂无已采用且带面积的案例。': 'Stats: no adopted comps with area yet.',
    '重新采用': 'Re-adopt', '丢弃理由：': 'Discard reason: ', '确认丢弃': 'Confirm discard', '取消': 'Cancel', '丢弃': 'Discard',
    '英里': 'mi', '日期': 'Date', '距离': 'Distance', '来源': 'Source', '操作': 'Actions',
    '暂无可比案例：点「拉取可比成交」或手动添加。': 'No comps yet: click "Pull comps" or add one manually.',
    '✅ 拉取': '✅ Pulled', '拉取失败：': 'Pull failed: ', '导入': 'Imported', '行失败：': 'rows failed: ',

    /* ---- ③ valuation ---- */
    '③ 估值': '③ Valuation',
    '比较法（Comps 栏已采用案例，距离倒数加权）＋ 收益法（NOI / cap rate）→ 调和估值。所有结果均为估算，不是承诺价格。':
      'Sales comparison (adopted comps, inverse-distance weighted) + income approach (NOI / cap rate) → reconciled value. All results are estimates, not promised prices.',
    '收益法': 'Income approach', '年 NOI $（留空=用上面测算值）': 'Annual NOI $ (blank = use the metric above)',
    '调和权重：比较法占比 %': 'Reconciliation weight: sales comparison %', '综合估值': 'Reconciled value',
    '比较法': 'Sales comparison', '个案例，加权': ' comps, weighted', '估值结果': 'Valuation', '方法': 'Method', '价值': 'Value',
    '估算区间：': 'Estimate range: ', '。以上均为估算，不是承诺价格。': '. All of the above are estimates, not promised prices.',
    '比较法权重按 1/(1+距离英里) 计算，仅用 Comps 栏': 'Sales-comparison weight = 1/(1 + distance in miles), using only',
    '案例；已签约（under contract）为签约价、在售挂牌（for sale）为挂牌价，均仅供参考。':
      'comps; under-contract uses contract price and for-sale uses list price, both for reference only.',
    '估值失败：': 'Valuation failed: ',

    /* ---- ④ history ---- */
    '④ 历史涨幅': '④ Historical appreciation',
    '嵌入的公开房价指数数据（FHFA / FRED / NAR / BLS，本会话逐条核验）。指数是指数，不是房价；各市场序列新旧不同，已分别标注。':
      'Embedded public house-price index data (FHFA / FRED / NAR / BLS, each checked). An index is an index, not a price; series vintages differ by market and are labelled.',
    '选择市场': 'Market', '自定义指数序列（粘贴你自己的数据画曲线）': 'Custom index series (paste your own data to chart)',
    '格式：每行': 'Format: one', '季度,指数值': 'quarter,index value', '，如': 'per line, e.g.',
    '（逗号分隔，不含表头）': '(comma-separated, no header)', '画涨幅曲线': 'Chart appreciation',
    '1年涨幅': '1-yr change', '5年涨幅': '5-yr change', '环比': 'QoQ', '1991年以来': 'Since 1991',
    '该市场嵌入序列待补，可在下方粘贴自定义序列，或点 FRED 链接查看最新。':
      'This market\'s embedded series is pending — paste a custom series below, or open the FRED link for the latest.',
    '见 FHFA 下载页': 'See FHFA download page', '）官方涨幅：1年': ') official change: 1-yr', '/ 5年': '/ 5-yr', '/ 1991年以来': '/ since 1991',
    '指数曲线（': 'Index curve (', '序列：': 'Series: ', '🏠 NAR 本地报告（': '🏠 NAR local report (', '）：中位价': '): median price',
    '，同比': ', YoY', '，3年': ', 3-yr', '原文': 'Original', '🔑 BLS 租金 CPI（': '🔑 BLS rent CPI (', '口径：': 'Method: ',
    '来源：': 'Source: ', '；数据更新：': '; data updated: ',
    '指数是指数，不是房价：不能把指数值直接当作 $/SF 或房产价值。各市场序列新旧不同，请以标注的更新日期为准。':
      'An index is not a price: never read an index value as $/SF or property value. Series vintages differ by market — go by the labelled update date.',
    '至少需要 2 个数据点': 'At least 2 data points are needed', '自定义序列统计': 'Custom series stats', '累计涨幅': 'Cumulative change',
    '年化 CAGR': 'Annualized CAGR', '同比': 'YoY', '数据点': 'Data points', '数据来源：用户粘贴（未核验）。区间': 'Source: pasted by user (unverified). Range',
    '计算失败：': 'Calculation failed: ',

    /* ---- ⑤ forecast ---- */
    '⑤ 未来三年预测': '⑤ Three-year forecast', '情景预测': 'Scenario forecast', '预测是情景假设，不是承诺。': 'Forecasts are scenario assumptions, not promises.',
    '下面三个情景的年涨幅假设均可手动修改；结果仅用于压力测试思路，不构成任何收益承诺。':
      'All three scenario growth rates below are editable; results are for stress-testing only and promise no return.',
    '基准价值 $（默认=调和估值）': 'Base value $ (default = reconciled value)', '保守情景年涨幅 %': 'Conservative annual growth %',
    '基准情景年涨幅 %': 'Base annual growth %', '乐观情景年涨幅 %': 'Optimistic annual growth %', '生成三年情景预测': 'Build 3-year scenarios',
    '请先填写基准价值（或先做第②步估值自动带入）': 'Enter a base value first (or run the valuation step to fill it in)',
    '%/年）': '%/yr)', '三年情景预测': 'Three-year scenarios', '情景': 'Scenario', '3年累计': '3-yr cumulative',
    '年涨幅假设：保守': 'Growth assumptions: conservative', '% / 基准': '% / base', '% / 乐观': '% / optimistic',
    '%（可调）。结果仅用于思路推演。': '% (editable). For reasoning only.', '预测失败：': 'Forecast failed: ',

    /* ---- ⑥ nearby ---- */
    '⑥ 周边价格': '⑥ Nearby prices', '汇总 Comps 栏中': 'Summarizes the',
    '的可比案例：价格 / $/SF / 面积 / 距离。数据来自 Comps 栏录入或 TopHap CMA 拉取，未录入=无数据，绝不编造。':
      'comps from the Comps step: price / $/SF / area / distance. Data comes from comps you entered or pulled from TopHap CMA; nothing entered = no data, never invented.',
    '汇总周边价格': 'Summarize nearby prices', '尚未汇总。请先在 Comps 栏拉取或添加可比案例。': 'Not summarized yet. Pull or add comps in the Comps step first.',
    '暂无已采用的可比案例，请先在 Comps 栏拉取或添加。': 'No adopted comps yet — pull or add them in the Comps step first.',
    '（含已签约/在售挂牌，仅参考）': '(includes under-contract / for-sale, reference only)', '已成交案例平均': 'Average of sold comps',
    '个已成交，': ' sold, ', '个有面积）': ' with area)', '数据来源：Comps 栏已采用案例': 'Source: adopted comps from the Comps step',
    '。未录入=无数据。': '. Not entered = no data.',

    /* ---- ⑦ research ---- */
    '⑦ 市场调查': '⑦ Market research',
    '六个维度：供给 / 需求 / 空置 / 租金趋势 / 人口 / 就业。每项填内容＋来源链接（有来源才算"已核实"）。一键生成可打印报告。':
      'Six dimensions: supply / demand / vacancy / rent trend / population / employment. Give each a finding plus a source link (only sourced items count as "verified"). One click makes a printable report.',
    '调查覆盖市场': 'Market covered', '补充说明': 'Additional notes', '生成市场调查': 'Build market research',
    '可打印报告（新窗口）': 'Printable report (new window)', '🖨️ 可打印报告（新窗口）': '🖨️ Printable report (new window)',
    '公开数据源（点击直达原文）': 'Public data sources (click to open the original)',
    '供给': 'Supply', '需求': 'Demand', '空置率': 'Vacancy', '租金趋势': 'Rent trend', '人口': 'Population', '就业': 'Employment',
    '内容（如：空置率 6.2%，环比下降）': 'Finding (e.g. vacancy 6.2%, down QoQ)',
    '来源链接或出处（必填才算已核实）': 'Source link or citation (required to count as verified)',
    '调查完整度：已填': 'Research completeness: filled', '，已核实': ', verified', '维度': 'Dimension', '填写': 'Filled', '核实': 'Verified',
    '已填': 'Filled', '✅ 已核实': '✅ Verified', '⚪ 待核实': '⚪ Unverified',
    '覆盖市场：': 'Market: ', '）· 生成时间': ') · generated', '生成失败：': 'Failed: ', '报告生成失败：': 'Report failed: ',
    '名称': 'Name', '链接': 'Link', '发布：': 'Release: ', '前后）': 'approx.)', '市场数据加载失败：': 'Market data failed to load: ',
    '从 EchoWatch 拉候选证据': 'Pull candidate evidence from EchoWatch',
    '按所选市场检索近 30 天带出处的公开提及；只给候选，点「采用」才填入。':
      'Searches the last 30 days of sourced public mentions for the selected market; candidates only — nothing is filled until you click "Adopt".',
    '正在向 EchoWatch 拉取…': 'Pulling from EchoWatch…', '采用': 'Adopt', '检索：': 'Query: ', '无匹配提及': 'No matching mentions',
    '没有可用证据': 'No usable evidence', '未拉到的维度请手填，不要猜。': 'Fill the missing dimensions by hand — don\'t guess.',
    '候选证据是公开提及，不等于已核实数据；采用前请点开原文确认。': 'Candidates are public mentions, not verified data; open the original before adopting.',
    '拉取失败：': 'Pull failed: ',

    /* ---- ⑧ score ---- */
    '⑧ 一键打分': '⑧ One-click score',
    '把本工作台录入的物业映射到现有核保引擎打分（住宅 buyer-box v2.3 / 商业 v1.3）。映射只填字段，打分逻辑零改动。':
      'Maps this property onto the existing underwriting engine (residential buyer-box v2.3 / commercial v1.3). Only fields are mapped; the scoring logic is unchanged.',
    '赛道': 'Track', '打分结果': 'Score', '总分': 'Total', '等级': 'Grade', '无一票否决': 'No veto',
    '→ 去打分台建档/存档': '→ Save it on the scoring desk', '打分失败：': 'Scoring failed: ',

    /* ---- intake results ---- */
    '卖方口径、待验证': 'Seller-stated, unverified', '高': 'High', '中': 'Medium', '可信度：': 'Confidence: ',
    '搜集失败：': 'Intake failed: ', '房源照片': 'Listing photo', '平台照片、仅供外观参考': 'Platform photo, for appearance only',
    '该地址暂无公开房源照片（TopHap/RentCast 为公共记录不含图片；挂牌网站有反爬限制）':
      'No public listing photo for this address (TopHap/RentCast are public records without images; listing sites block scraping)',
    '✅ 已填入候选': '✅ Filled as candidate', '✅ 已填入表单': '✅ Filled into form', '需手动补': 'Fill manually',
    '字段': 'Field', '值': 'Value', '抓取时间': 'Fetched at', '搜集日志（': 'Intake log (', '步）': 'steps)',
    '⏳ 卖方动机分计算中（TopHap 持有人记录＋DOB 公开违规）…': '⏳ Computing seller-motivation score (TopHap owner records + DOB violations)…',
    '卖方动机分：无数据': 'Seller-motivation score: no data', '卖方动机分暂不可用：': 'Seller-motivation score unavailable: ',
    '🎯 卖方动机分：': '🎯 Seller-motivation score: ', '（动机': '(motivation',
    '规则分仅供线索参考：无数据源的信号不计分、不虚构；': 'Rule-based score, for leads only: signals without a data source score zero and are never invented;',
    'ECB 未清偿罚金已纳入留置权/违规信号（纽约市地址）。': 'unpaid ECB penalties count toward the lien/violation signal (NYC addresses).',
    '✅ 命中': '✅ Hit', '— 未命中': '— No hit', '⚠️ 无数据': '⚠️ No data', '⚠️ 口径说明': '⚠️ Method notes',
    '⏳ 产权穿透生成中（TopHap 持有人＋NY DOS 备案）…': '⏳ Building ownership tree (TopHap owner + NY DOS filings)…',
    '产权穿透：无数据': 'Ownership tree: no data', '产权穿透暂不可用：': 'Ownership tree unavailable: ',
    '✅ 公开记录': '✅ Public record', '⚠️ 待验证': '⚠️ Unverified', '🏠 物业': '🏠 Property', '📜 持有人': '📜 Owner', '👤 穿透': '👤 Beneficial',
    '📇 联系方式（仅 verified 公开记录）': '📇 Contacts (verified public records only)', '⚠️ 待验证事项': '⚠️ To verify',
    '🌳 产权穿透树': '🌳 Ownership tree', '🌳 产权穿透树（持有人未解析）': '🌳 Ownership tree (owner not resolved)',
    '推断节点一律标注[待验证]；联系方式只采用公开记录，不编造电话/邮箱。': 'Inferred nodes are always marked [unverified]; contacts come only from public records — no invented phones or emails.',
    '以下为卖方口径、待验证：': 'Seller-stated, unverified:',
    '超时（180秒），请重试或手动录入': 'Timed out (180 s) — retry or enter manually',
    '请先输入地址': 'Please enter an address first', '请先粘贴房源链接': 'Please paste a listing link first',
    '搜集中（约 30-90 秒，多站点抓取）…': 'Searching (about 30–90 s, several sites)…',
    '引擎加载失败（网络）：': 'Engine failed to load (network): ', '请先选择 PDF 文件': 'Please choose a PDF first',
    '⏳ 检测到扫描版 PDF（无文本层），启动浏览器端 OCR…': '⏳ Scanned PDF detected (no text layer) — starting in-browser OCR…',
    '扫描版 PDF OCR 未识别出足够文字，请换更清晰的扫描件': 'OCR found too little text in the scanned PDF — try a clearer scan',
    '混合型 PDF 扫描页需 OCR，但文本层数据过大无法合并，请改用粘贴文本': 'Mixed PDF: scanned pages need OCR but the text layer is too large to merge — paste the text instead',
    '扫描页 OCR 未识别出文字，请换更清晰的扫描件': 'OCR found no text on the scanned pages — try a clearer scan',
    'PDF 解析失败：': 'PDF parsing failed: ', '页识别中…': ' being recognized…', '页为扫描图，启动逐页 OCR…': 'page(s) are scans — starting page-by-page OCR…',
    '》中…': '»…', '请先选择截图文件': 'Please choose a screenshot first', '已收到截图': 'Screenshot received',
    '✅ 已提取': '✅ Extracted', '❌ 提取失败': '❌ Extraction failed', '⏳ 提取中': '⏳ Extracting',
    '🖼️ 截图提取任务': '🖼️ Screenshot extraction jobs', '截图': 'Screenshot', '收到时间': 'Received', '状态': 'Status',
    '截图字段标"截图提取、待验证"，须独立验证后方可用于估值/打分。': 'Screenshot fields are marked "screenshot-extracted, unverified" and must be verified independently before valuation or scoring.',
    '⏳ 载入截图提取结果…': '⏳ Loading screenshot results…', '截图上传失败：': 'Screenshot upload failed: ',
    '读取截图任务失败：': 'Failed to read screenshot jobs: ', '载入失败：': 'Load failed: ', '（任务': '(job',
    '》，开始解析…': '», parsing…', '⏳ 收到链接，开始解析…': '⏳ Link received, parsing…',
    '只接受 PDF 或截图（png/jpg/webp），收到：': 'Only PDF or screenshots (png/jpg/webp) are accepted; received: ',
    '州平均估算': 'State-average estimate', '州平均税率': 'State average tax rate', '% 估算 · 待独立验证（': '% estimate · verify independently (',
    '测算': 'Calculate', '估值': 'Valuate',
    /* backend notes shown verbatim (app/workbench.py) */
    '否决：': 'Veto: ',
    '未录入可比案例，无法做比较法估值': 'No comps entered — sales-comparison valuation not possible',
    'NOI 或 cap rate 无效，无法做收益法估值': 'NOI or cap rate invalid — income-approach valuation not possible',
    '两种方法都无有效值，无法调和': 'Neither approach has a valid value — cannot reconcile',
    '调和权重：比较法': 'Reconciliation weight: sales comparison', '/ 收益法': '/ income',
    '；区间为两种方法的高低值': '; range = low/high of the two approaches',
    '每年价值按复利滚动假设涨幅；租金涨幅假设仅用于现金流情景参考': 'Value compounds yearly at the assumed growth; rent growth is for cash-flow scenarios only',
    '数据点不足，至少需要 2 个': 'Not enough data points — at least 2 are needed',
    '地址为空': 'Address is empty', 'TopHap 拉取失败': 'TopHap pull failed',
    'TopHap CMA 未返回可比成交（该地址可能无近期 recorded sales）': 'TopHap CMA returned no comps (this address may have no recent recorded sales)',
    '条可比成交（recorded sales 口径）；价格为登记成交价，非卖方报价': 'comps (recorded sales); prices are recorded sale prices, not seller asks',
    '权重=1/(1+距离英里)；': 'weight = 1/(1 + distance mi); ',
    'sold=已成交（登记成交价），under_contract=已签约（签约价，供参考），for_sale=在售挂牌（挂牌价，仅参考）':
      'sold = recorded sale price; under_contract = contract price (reference); for_sale = list price (reference only)',
  };

  /* number-bound fragments: "3 个" / "第 2 年" / "5 条" … */
  const PATTERNS = [
    [/第\s*(\d+)\s*年/g, 'Year $1'],
    [/(\d+)\s*个/g, '$1'], [/(\d+)\s*条/g, '$1'], [/(\d+)\s*年/g, '$1 yr'], [/条（/g, ' ('], [/），新增/g, '), added'], [/条。/g, '.'],
  ];
  Object.assign(W, {
    '⏳ 扫描 PDF OCR：第': '⏳ Scanned PDF OCR: page ', '⏳ 混合 PDF 扫描页 OCR：第': '⏳ Mixed PDF OCR: page ',
    '⏳ 混合型 PDF：第': '⏳ Mixed PDF: page ', '⏳ 解析 PDF《': '⏳ Parsing PDF «', '⏳ 上传截图《': '⏳ Uploading screenshot «',
    '⏳ 收到文件《': '⏳ File received «',
  });
  const CJK = /[一-鿿]/;
  const frags = Object.keys(W).filter(k => k.length >= 2).sort((a, b) => b.length - a.length);
  const BASE = window.DD_EN_DICT || {};
  const lookup = k => (Object.prototype.hasOwnProperty.call(W, k) ? W[k] : BASE[k]);

  function tr(text) {
    const t = text.trim();
    if (!t || !CJK.test(t)) return null;
    const exact = lookup(t);
    if (exact !== undefined) return text.replace(t, exact);
    let s = text;
    for (const f of frags) if (s.includes(f)) s = s.split(f).join(W[f]);
    for (const [re, rep] of PATTERNS) s = s.replace(re, rep);
    if (CJK.test(s)) return null;   // never half-translate
    return s.replace(/（/g, ' (').replace(/）/g, ')').replace(/，\s*/g, ', ').replace(/：\s*/g, ': ')
            .replace(/；\s*/g, '; ').replace(/。/g, '. ').replace(/\s{2,}/g, ' ').replace(/\(\s+/g, '(');
  }
  const SKIP = new Set(['SCRIPT', 'STYLE']);
  function walk(node) {
    if (node.nodeType === 3) {
      const p = node.parentNode;
      if (p && !SKIP.has(p.nodeName) && p.nodeName !== 'TEXTAREA') { const v = tr(node.nodeValue); if (v !== null) node.nodeValue = v; }
      return;
    }
    if (node.nodeType !== 1 || SKIP.has(node.nodeName)) return;
    for (const a of ['placeholder', 'title', 'alt', 'aria-label']) {
      if (node.hasAttribute(a)) { const v = tr(node.getAttribute(a)); if (v !== null) node.setAttribute(a, v); }
    }
    if (node.nodeName === 'TEXTAREA') return;   // its text is what the user typed: never touched
    node.childNodes.forEach(walk);   // INPUT has no children: its value is never read or written
  }
  /* exposed for tests and for alert()/confirm() strings built in JS */
  window.WB_T = s => (tr(String(s)) ?? s);
  const _alert = window.alert.bind(window), _confirm = window.confirm.bind(window);
  window.alert = m => _alert(window.WB_T(m));
  window.confirm = m => _confirm(window.WB_T(m));

  function start() {
    document.documentElement.lang = 'en';
    const t = tr(document.title); if (t !== null) document.title = t;
    walk(document.body);
    new MutationObserver(ms => ms.forEach(m => {
      if (m.type === 'characterData') walk(m.target);
      else m.addedNodes.forEach(walk);
      if (m.type === 'attributes') walk(m.target);
    })).observe(document.body, {subtree: true, childList: true, characterData: true, attributes: true,
      attributeFilter: ['placeholder', 'title', 'alt']});
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
