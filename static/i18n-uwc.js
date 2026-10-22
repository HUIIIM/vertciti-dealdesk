/* DealDesk commercial underwriting (uw-commercial.html) — EN dictionary.
 * Loaded before i18n-wb.js, which merges window.DD_EXTRA_DICT into its own
 * dictionary and does the translating (same rules: exact match first, then
 * fragments, never half-translate, user input untouched). zh is the default. */
'use strict';
window.DD_EXTRA_DICT = Object.assign(window.DD_EXTRA_DICT || {}, {
  /* ---- command bar ---- */
  '商业核保 · DealDesk': 'Commercial Underwriting · DealDesk', '未命名物业': 'Untitled property',
  '随输入自动重算': 'Recalculates as you type', '· 预测净现金流': '· Pro forma net cash flow',
  '已保存的核保项目': 'Saved underwriting projects', '— 选择已保存项目 —': '— Choose a saved project —',
  '新建': 'New', '保存': 'Save', '保存 *': 'Save *', '导出经典版 PDF': 'Export classic PDF', '导出增强版 PDF': 'Export enhanced PDF',
  '一键 Tear Sheet': 'One-click tear sheet', '载入模板示例': 'Load template example', '删除': 'Delete',
  '项目': 'Project', '未命名核保项目': 'Untitled underwriting project', '项目名称': 'Project name',
  '删除该核保项目？': 'Delete this underwriting project?', '生成中…': 'Generating…', '报告导出': 'Report export',
  '模板示例加载失败（网络/服务异常），请稍后重试': 'Template example failed to load (network/service error) — please retry',
  '保存失败（网络/服务异常），输入的内容还在页面上，请稍后重试': 'Save failed (network/service error). Your input is still on the page — please retry',
  '数据质量门拦截：请修正矛盾数据后重试': 'Blocked by the data-quality gate: fix the conflicting data and retry',
  '报告生成失败（网络/服务异常），请稍后重试': 'Report generation failed (network/service error) — please retry',
  'Tear Sheet 生成失败（网络/服务异常），请稍后重试': 'Tear sheet generation failed (network/service error) — please retry',

  /* ---- smart intake ---- */
  '智能录取': 'Smart intake', '上传 PDF（OM / Flyer / 卖方材料）': 'Upload PDF (OM / flyer / seller package)',
  '上传截图（房源页/照片）': 'Upload screenshot (listing page / photo)', '粘贴文本（OM / Flyer 文本）': 'Paste text (OM / flyer)',
  '自动提取价格/面积/NOI/租户，填入下表；截图与扫描版 PDF 走浏览器端 OCR（结果标"OCR 口径"），全部标"卖方口径、待验证"':
    'Extracts price / area / NOI / tenants into the table below; screenshots and scanned PDFs use in-browser OCR (marked "OCR"), and everything is marked "seller-stated, unverified"',
  '粘贴 OM / Flyer 文本': 'Paste OM / flyer text', '关闭': 'Close',
  '把 OM、flyer、卖方材料里的文本粘贴到这里（英文/中文均可），点「提取并填表」自动识别价格、面积、NOI、租户…\n\n全部结果标「卖方材料口径、待独立验证」。':
    'Paste text from the OM, flyer or seller package here (English or Chinese), then click "Extract & fill" to pick out price, area, NOI, tenants…\n\nEvery result is marked "seller-stated, verify independently".',
  '提取并填表': 'Extract & fill', '（无对应输入项）': '(no matching input)', '已填': 'Filled', '个字段': ' fields', '个租户': ' tenants',
  '未映射': 'Unmapped', '（全部为截图 OCR 提取、卖方口径、待独立验证）': '(all from screenshot OCR — seller-stated, verify independently)',
  '（全部为扫描版 PDF OCR 提取、卖方口径、待独立验证）': '(all from scanned-PDF OCR — seller-stated, verify independently)',
  '（全部为卖方口径、待独立验证）': '(all seller-stated — verify independently)',
  '⛔ 门拦截': '⛔ Gate blocked', '项：修正后才能导出报告/Tear Sheet': 'item(s): fix before exporting the report / tear sheet',
  '⚠️ 门告警': '⚠️ Gate warning', '项已标黄': 'item(s) highlighted',
  '解析中…': 'Parsing…', '检测到扫描版 PDF（无文本层），启动浏览器端 OCR…': 'Scanned PDF detected (no text layer) — starting in-browser OCR…',
  '扫描版 PDF OCR 未识别出足够文字，请换更清晰的扫描件或改用粘贴文本': 'OCR found too little text in the scanned PDF — use a clearer scan or paste the text',
  '检测到混合型 PDF：第': 'Mixed PDF detected: page', '页为扫描图，启动浏览器端逐页 OCR…': ' is scanned — starting page-by-page OCR…',
  '扫描页 OCR 未识别出文字，请换更清晰的扫描件或改用粘贴文本': 'OCR found no text on the scanned pages — use a clearer scan or paste the text',
  '解析失败：': 'Parsing failed: ', '请先粘贴文本': 'Please paste text first', '提取中…': 'Extracting…', '提取失败：': 'Extraction failed: ',
  '⛔ 数据质量门拦截': '⛔ Data-quality gate: blocked', '⚠️ 数据质量门告警': '⚠️ Data-quality gate: warning', '✅ 数据质量门通过': '✅ Data-quality gate: passed',
  '数据质量门拦截（': 'Data-quality gate blocked (', '数据质量门告警（': 'Data-quality gate warning (',
  '标黄字段请先核实。仍要继续生成吗？': 'Please check the highlighted fields first. Generate anyway?',
  '外观': 'Exterior', 'OCR 引擎加载失败（网络）': 'OCR engine failed to load (network)', '截图 OCR 识别中': 'Screenshot OCR running',
  '截图 OCR 识别中…': 'Screenshot OCR running…', 'PDF 渲染引擎加载异常': 'PDF renderer failed to initialize', 'PDF 渲染引擎加载失败（网络）': 'PDF renderer failed to load (network)',
  '扫描 PDF OCR：第': 'Scanned PDF OCR: page', '页渲染识别中…': ' rendering & recognizing…', '扫描 PDF 共': 'Scanned PDF has',
  '页，仅 OCR 前': 'pages; OCR only the first', '混合 PDF 扫描页 OCR：第': 'Mixed PDF OCR: page',
  'OCR 未识别出足够文字，请换更清晰的截图或改用粘贴文本': 'OCR found too little text — use a clearer screenshot or paste the text',
  '；服务端 OCR 亦不可用：': '; server-side OCR also unavailable: ', '截图处理失败：': 'Screenshot processing failed: ',

  /* ---- key returns & pipeline ---- */
  '任一输入格改动 → 整条链自动重算并闪烁。': 'Change any input → the whole chain recalculates and flashes.',
  '琥珀色': 'Amber', '= 机器算出；': '= computed; ', '描边徽章': 'Outlined badge', '= 你的手工覆盖。留空即自动。': '= your manual override. Leave blank for automatic.',
  '关键回报': 'Key returns', '预测转售价值': 'Projected resale value', '税前净收益': 'Pre-tax net gain', '投资回报率 ROI': 'Return on investment (ROI)',
  '退出 IRR': 'Exit IRR', '股本倍数': 'Equity multiple', '预测净现金流/年': 'Pro forma net cash flow / yr',
  '数据流水线': 'Data pipeline', 'A · 年租金合计': 'A · Total annual rent', '包租口径': 'Master-lease basis',
  'B · 预测 NOI': 'B · Pro forma NOI', 'EGI − 费用': 'EGI − expenses', 'B · Cap 率': 'B · Cap rate', 'NOI ÷ 购买价': 'NOI ÷ purchase price',
  'C · 净现金流': 'C · Net cash flow', 'NOI − 还贷': 'NOI − debt service', '净现金流 ÷ 自有资金': 'Net cash flow ÷ equity',
  'NOI ÷ 年还贷': 'NOI ÷ annual debt service', 'C · 退出 IRR': 'C · Exit IRR', '年持有': '-yr hold',

  /* ---- A rent roll ---- */
  '租金表': 'Rent roll', '每户填': 'For each tenant enter', '面积 / 月租（合同） / 包租年租': 'area / monthly rent (contract) / master-lease annual rent',
  '。年租 = 月租×12；合计自动流入 B 现金流基础租金（历史←合同租金合计，预测←包租租金合计）。':
    '. Annual rent = monthly × 12; totals flow into B cash-flow base rent (historical ← contract total, pro forma ← master-lease total).',
  '月租（合同）': 'Monthly rent (contract)', '月租/SF': 'Monthly rent/SF', '算': 'calc', '年租': 'Annual rent', '年租/SF': 'Annual rent/SF',
  '包租年租': 'Master-lease annual rent', '输入': 'input', '包租/SF': 'Master lease/SF', '月 CAM': 'Monthly CAM', '月停车费': 'Monthly parking',
  '＋ 加租户': '+ Add tenant', '空置面积 SF': 'Vacant area SF', '可出租总面积 SF': 'Total leasable area SF', '出租率': 'Occupancy',
  '包租年租（预测口径用）': 'Master-lease annual rent (for pro forma)', '月 CAM（模板 T 列）': 'Monthly CAM (template col T)',
  '月停车费（模板 U 列）': 'Monthly parking (template col U)', '月租合计': 'Monthly rent total', '年租合计': 'Annual rent total',
  '→ B 现金流 · 历史基础租金': '→ B cash flow · historical base rent', '包租合计': 'Master-lease total',
  '→ B 现金流 · 预测基础租金': '→ B cash flow · pro forma base rent', 'CAM 年合计': 'CAM annual total',
  '→ B/C 现金流 · CAM 回收（模板 T 列）': '→ B/C cash flow · CAM recovery (template col T)', '停车年合计': 'Parking annual total',
  '→ B/C 现金流 · 停车收入（模板 U 列）': '→ B/C cash flow · parking income (template col U)',
  '自动取自租户表 T/U 列年合计': 'Taken from the rent roll T/U annual totals', '租户表自动': 'From rent roll', '手工输入覆盖租户表': 'Manual input overrides the rent roll',
  '手工': 'Manual', '空=租户表自动': 'blank = from rent roll', '合计': 'Total', '空置': 'Vacant', 'SF / 总': 'SF / total',
  'SF，隐含空置率': 'SF, implied vacancy', '填入两栏空置率': 'Fill both vacancy fields', '空置面积为 0': 'Vacant area is 0',

  /* ---- B cash flow ---- */
  '现金流': 'Cash flow', '基础租金 ← A 租金表；其余为输入。NOI = 有效总收入 − 总费用；NOI 自动流入 C 投资分析。':
    'Base rent ← A rent roll; everything else is input. NOI = EGI − total expenses; NOI flows into C investment analysis.',
  '历史 Historical': 'Historical', '← 合同租金': '← contract rent', '预测 Pro Forma': 'Pro forma', '← 包租租金': '← master-lease rent',
  '服务合同 Service Contracts': 'Service contracts', '公共区域维护 CAM': 'Common-area maintenance (CAM)', '综合管理 G&A': 'General & admin (G&A)',
  '维修保养 R&M': 'Repairs & maintenance (R&M)', '保洁 Janitor': 'Janitorial', '安保 Security': 'Security', '水电 Utilities': 'Utilities',
  '工资 Payroll': 'Payroll', '管理费 Mgmt Fee': 'Management fee', '房产税 Property Tax': 'Property tax', '保险 Insurance': 'Insurance',
  '景观绿化 Landscape': 'Landscaping', '基础租金 Base Rents': 'Base rents', 'CAM 回收': 'CAM recovery', '停车收入': 'Parking income',
  '其他收入': 'Other income', '总潜在收入': 'Potential gross income', '空置/坏账损失 %': 'Vacancy / credit loss %', '空置损失额': 'Vacancy loss',
  '有效总收入 EGI': 'Effective gross income (EGI)', '费用 Expenses': 'Expenses', '总费用': 'Total expenses', '净营业收入 NOI': 'Net operating income (NOI)',
  '→ C 投资分析': '→ C investment analysis', '租户装修 TI': 'Tenant improvements (TI)', '资本性支出 CapEx': 'Capital expenditure (CapEx)',
  '租赁佣金': 'Leasing commissions', '可用于还贷现金流': 'Cash flow available for debt service', '净现金流': 'Net cash flow',

  /* ---- C investment analysis ---- */
  '投资分析': 'Investment analysis', 'NOI ← B 现金流；输入购买与贷款条件，回报自动重算。': 'NOI ← B cash flow; enter purchase and loan terms and returns recalculate.',
  '承保假设': 'Underwriting assumptions', '模板手工口径': 'Template manual basis',
  '模板里 F13/F15/I24 是手填的承保判断，不是公式。留空 = 自动取现金流实时值；手填 = 锁定为你的手工口径。':
    'In the template, F13/F15/I24 are hand-entered underwriting judgments, not formulas. Blank = live cash-flow value; filled = locked to your manual figure.',
  '在手 NOI (F13) $': 'In-place NOI (F13) $', '空=现金流': 'blank = cash flow', '预测 NOI (F15) $': 'Pro forma NOI (F15) $',
  '现金流块在手 NOI (I24) $': 'Cash-flow block in-place NOI (I24) $', '从现金流同步三项': 'Sync all three from cash flow',
  '当前口径：F13': 'Current basis: F13', '手工锁定': 'Manually locked', '现金流实时': 'Live from cash flow',
  '现金流（NOI+其他收入）': 'Cash flow (NOI + other income)', '模板口径': 'Template basis', 'Cap 率': 'Cap rate',
  '← A 租金表 · 合同年租合计': '← A rent roll · contract annual total', '← A 租金表 · 包租年租合计': '← A rent roll · master-lease annual total',
  '物业概况': 'Property overview', '物业名称': 'Property name', '城市': 'City', '州': 'State', '邮编': 'ZIP',
  '县/郡 County': 'County', '可租面积 SF': 'Leasable area SF', '占地（英亩）': 'Land (acres)', '车位数': 'Parking spaces',
  '车位 / 千SF': 'Spaces / 1,000 SF', '建造年份': 'Year built', '翻新年份': 'Year renovated', '楼栋数': 'Buildings', '层数': 'Stories',
  '出租率统计日期': 'Occupancy as of', '如 2026-10-01': 'e.g. 2026-10-01',
  '资金来源与用途': 'Sources & uses', '购买价 $': 'Purchase price $', '(+) 建筑维修 $': '(+) Building repairs $',
  '(+) 资本储备 $': '(+) Capital reserve $', '(+) 贷款费用 $': '(+) Loan fees $', '(+) 交割费用 $': '(+) Closing costs $',
  '总投入': 'Total capitalization', '贷款金额': 'Loan amount', '需自有资金': 'Equity required', '贷款条件': 'Loan terms',
  '还款方式': 'Amortization', '只还利息 IO（模板默认）': 'Interest-only IO (template default)', '等额本息 Amortizing': 'Amortizing',
  '年还贷额': 'Annual debt service', '租金减免/抵免 $': 'Rent concessions / credits $', '租金减免/抵免': 'Rent concessions / credits',
  '回报汇总': 'Returns summary', '预测口径现金回报': 'Pro forma cash-on-cash', '← 预测 NOI': '← pro forma NOI',
  '在手口径现金回报': 'In-place cash-on-cash', '← 历史 NOI': '← historical NOI', '（预测）': '(pro forma)', '（在手）': '(in place)',
  '在手 NOI': 'In-place NOI', '在手 Cap 率': 'In-place cap rate', '预测 NOI': 'Pro forma NOI', '市场 Cap 率（输入）': 'Market cap rate (input)',
  '收购费用': 'Acquisition costs', '退出费用': 'Exit costs', '新增指标': 'Additional metrics', '预测 DSCR': 'Pro forma DSCR', '在手 DSCR': 'In-place DSCR',
  '盈亏平衡出租率': 'Break-even occupancy', '购买单价 /SF': 'Purchase price /SF', '预测租金 /SF': 'Pro forma rent /SF', '费用 /SF': 'Expenses /SF',
  '持有退出分析': 'Hold & exit analysis', '持有年数': 'Hold period (years)', 'NOI 年增长率 %': 'NOI annual growth %', '市场 Cap 率 %': 'Market cap rate %',
  '退出 Cap 率 %': 'Exit cap rate %', '退出费用 %': 'Exit costs %', '模板固定 4%': 'Template fixed at 4%',
  '模板固定 4%，按 Miao 决定锁定': 'Template fixed at 4%, locked per Miao\'s decision',
  '持有期': 'Hold period', '退出售价': 'Exit sale price', '剩余贷款': 'Remaining loan', '退出净得': 'Net exit proceeds',
  'DealDesk-商业核保-': 'DealDesk-commercial-underwriting-',
});
