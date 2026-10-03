# DealDesk 竞品学习总研究报告（2026-10-02）

> 董事长指令：找同类公司学习，差漏补缺，把学到的并入改进。
> 方法：5 researcher 并行深研（只读：browser.search + browser.open 页面文本 + G2/Capterra/Reddit/行业媒体第三方评价；未注册、未付费、未留联系方式）。
> 单家深研报告：`docs/competitive/{dealpath,crexi,reonomy,cherre,costar}-2026-10-02.md`

---

## 一、Dealpath（机构级交易管理平台）

**定位**：机构级 CRE 交易管理平台（Blackstone/AEW/Starwood 等 300+ 机构客户）；OM→pipeline→承销→IC 决策→组合管理的"单一事实源"数据库，AI 挂在结构化数据上。

**核心功能**：AI Extract（OM 抽取 90+ 字段）、AI Deal Screening（秒级 tear sheet）、AI Comps（三源推荐+attach/pass）、Dealpath MCP（pipeline 数据进 Claude/Copilot）、Dealpath Connect（私募 listings 网络）。

**可学的 5 条**：
1. **一键 Tear Sheet**：上传 OM/rent roll/T12 后秒级生成单页纸（portfolio fit + 信封背估算 + highlights + next steps）。证据：dealpath.com/ai 原文 *"create a tear sheet in seconds"*。
2. **Comps attach/pass 工作流**：系统推荐 comps（自有库/MSCI RCA/第三方），deal 页一键采用或丢弃，丢弃记排除理由。证据：同上 *"attach or pass with one click"*。
3. **固定字段 schema + 抽取置信度**：90+ 固定字段抽取（非开放问答），每字段带置信度；新文档类型按 schema 扩展。证据：businesswire 2025-10-14（AI Studio 发布）。
4. **Buy-box 自动打分**：deal 进 pipeline 即按机构投资标准打分、标不匹配项、排序。证据：dealpath.com/ai "What's Coming: Dealpath AI Agents"。
5. **DealDesk MCP Server**：把 pipeline/comps/承销结果做成 MCP server，Miao 在任何对话里自然语言查 deal 实时数。证据：同上 *"Dealpath MCP brings your pipeline... into apps like Claude and Copilot"*。

**不适合我们的**：5 用户起售/权限/SSO/审批流、broker listings 交换网络、基金组合管理、Outlook CRM、lender 产品线——全是大机构协作包袱；定价 ~$12k/年起、实施 6-8 周且实施期就计费（被用户骂的最凶点，反面教材：DealDesk intake 必须永远"丢 PDF 就行"）。

## 二、Crexi（CRE 交易撮合 + 数据平台）

**定位**："平价版 CoStar"（G2 4.6/5，127 条；CoStar 3.7/5）：免费 marketplace + 收费 Intelligence（Select $299/月）：153M+ 物业记录、46M+ verified 销售 comps、租赁 comps、贷款与业主数据。

**核心功能**：Sale & Lease Comps 双轨、on-page 估值计算器、unit-level 租金数据（Dwellsy 合作）、saved searches + alerts、loan/maturity 数据、Crexi Create（AI 生成 OM 初稿）。

**可学的 5 条**：
1. **Sale comps 独立模块**：销售 comps 与租赁 comps 并列为一级数据资产（价格/买卖双方/cap rate/financing detail）。DealDesk 商业页 A 只有自建租金表，缺销售 comps 这个估值锚。证据：crexi.com/intelligence/product-overview。
2. **In-context 估值计算器**：listing 页内置计算器就地验证价值/风险/回报。DealDesk 可在 C 页顶部加"快速估值栏"（cap rate/$/SF/GRM 反推三口径价值），纯前端。证据：Crexi CPO Hans Ku 原话 *"in-context verification of value, risk, and investment outcome"*。
3. **来源可信度分层（反面教材转正）**：G2 上被骂最狠的是 comps 掺水（经纪人谎报成交价 $20-40M 级）。DealDesk 用多源 fallback 反打 🟢🟡⚪ 来源+置信度标签——Crexi 洗不掉的原罪正是我们的差异化。证据：G2 "Poor comp data" 条（2024-05-03）。
4. **Buy-box alerts → deal watchlist**：saved searches + 新数据提醒，"Your buy box becomes a standing pipeline"。N=1 反向用法：跟踪中的 deal 每周重跑估值，指标漂移时推送。证据：同上产品页。
5. **债务时间线**：mortgage history/lender/maturity/CMBS 做成独立数据层。买方视角下这是风险项：450 W 44th 的 balloon 就是例子；C 页加债务到期小节。证据：crexi.com/intelligence "Loan & Financing Data"。

**不适合我们的**：marketplace 撮合侧（发 listing/auction/lead 解锁）、OM 生成（卖方物料，方向相反）、CRM/skip tracing 群发拓客、Research AI 自然语言搜索（153M 库的入口，单 deal 台子不需要）、$299/月订阅（违反花钱铁律）。

## 三、Reonomy（物业数据 AI，2021 年被 Altus Group 收购）

**定位**：美国 CRE 物业数据情报平台：54M+ 物业、30M+ owner 联系人，ML 穿透 LLC 找真实决策人，卖点是 off-market 机会。定价约 $400/月/用户；Capterra 4.1/5。

**核心功能**：Ownership 穿透（Reonomy ID 关联）、"Likely to sell" ML 评分、债务雷达（按 maturity 搜索）、owner portfolio 视图、200+ 过滤器、saved search 动态监控。

**可学的 5 条**：
1. **Ownership 穿透树**：SoS 企业档案 + assessor 记录用统一 ID 关联，LLC→真人→联系方式按可靠性分级。DealDesk intake 自动生成"LLC→真人→可信度"树（450 W 44th subject-to 的痛点）。证据：CRE Daily 评测 *"pierce LLC layers to get to the actual property owner"*。
2. **Sell-readiness 信号分（规则版 likely-to-sell）**：持有年限+loan maturity+refinance+portfolio 周转率 → 0-100 规则分，不用 ML。Miao 是买方：这是砍价/terms 谈判第一输入，信号全来自现有 fallback 链，零训练成本。证据：reonomy.com 官网 likely-to-sell 产品页。
3. **债务到期雷达**：maturity date <12 个月变红。balloon 条款=谈判窗口期。证据：CRE Daily "search by maturity date"。
4. **动态搜索 + deal 监控**：labels（watching/in-underwriting/dropped）+ 笔记 + 保存的搜索条件周期重跑。DealDesk 从"一次性核保台"升级为"deal 管道"的最小功能。证据：同上。
5. **反面教训：诚实标注**：Capterra 2 星骂 bounced emails/dead numbers；theBrokerList 建议只当起点。DealDesk 数据层三层标注 verified/inferred/unverified，界面颜色区分——Reonomy 目标 80% 准确就行，N=1 真钱核保标准必须更高。

**不适合我们的**：批量导出+外呼 campaign、企业 API feed、200+ 过滤器 prospecting 漏斗、$400/月、多 seat 协同、AI 补全联系人——全是机构销售团队批量获客工具。

## 四、Cherre（房地产数据平台，2026-07 被 RealPage 收购）

**定位**：房地产数据连接/标准化平台（不是数据卖家）：三路 ingest→标准数据模型→single GraphQL API。目标客户=Brookfield/Nuveen/Starwood 级最大资本配置者；定价不公开。

**核心功能**：Connectors/Submission Portal/Ingress 三路接入、Knowledge Graph（4B+ entities resolved）、schema mapping engine、single GraphQL API、数据质量 UI（observability + validation 规则库）、Egress（Snowflake/BigQuery 增量）。

**可学的 5 条**：
1. **标准数据模型 + schema mapping engine**：先定 canonical deal schema，每个数据源写独立 connector（map 函数），underwriting 只消费标准模型。加源=新增文件不动核保逻辑。证据：cherre.com/products/platform。
2. **轻量 entity resolution**：地址归一化→geocode→APN/parcel 交叉验证，多源记录合并为一条 canonical deal，字段标来源+置信度，对不上 flag 而非静默取第一个。证据：businesswire 收购官宣（identity 问题原文）。
3. **规则驱动 intake 校验层**：validators.py，规则可配（"租金偏离 ±30% → warn""TopHap 与 PDF 单元数不一致 → fail"），fail 清零才能进 underwriting。证据：cherre.com Submission Portal 段落。
4. **Connector 注册表 + 增量刷新**：fallback 链形式化为 connectors/ 目录（声明 coverage/cost/cadence）；deal 重访只刷新易变字段并留 diff 日志。证据：Cherre Egress "one-time initial load followed by incremental updates"。
5. **Per-field provenance + 完备度进报告**：PDF 备忘录加数据完备度表头（"15/18 字段已解析；租金←RentCast 高置信…"）。证据：GlobeSt CEO 访谈 *"we're not looking for black box AI or magic"*。

**不适合我们的**：多租户数据仓库/Snowflake Egress、数据商许可市场、SOC-2 全套、组合实时看板——Inman 原话 *"Cherre might be too much for some brokerages"*，连中型机构都嫌重；N=1 只取设计思想不取架构规模。

## 五、CoStar（comps 重点；LoopNet 为旗下平台）

**定位**：CRE 数据"事实垄断者"：5.2M 条核实 comps、$15T 累计交易额，靠最大研究团队人工核实堆护城河；comps 锁高 tier（$485/月起，BiggerPockets 实证 $1,200/月/人锁 1 年）；G2 仅 3.5/5——"最全但不准+贵"。

**核心功能**：Sale comps 筛选体系（7 tab：Location/Building/Sale/Capital/Tenants/Contacts/Assessment/Demographics；三态 sold/under contract/for sale 并查）、comp 详情"交易故事"（asking vs achieved、Sale Notes、true buyer/seller、Market at Sale）、Analytics 面板（KPI+分布直方图）、Reports 一键模板。

**可学的 5 条**：
1. **Comp 卡片"交易故事"字段结构**：asking vs achieved、time on market、交易类型标签（1031/auction/distressed/未知）、Sale Notes、hold period。$0 做法：类型允许"未知"但强制显示"未知"——CoStar 用户自己骂数据不准（G2 "A LOT of the property information is inaccurate"；appraiser 实证 cap rate 错 200bps），诚实标注是差异化。证据：costar.com "Story Behind the Sale"；introduction-to-sale-comps.pdf。
2. **三态并查 + 排除式筛选**：sold（定价锚）/under contract（动量）/for sale（竞争面）三段式；在售段天然=ask，直接呈现要价-成交价差视角。证据：同上 PDF "Important Filters"。
3. **Market at Sale 时间调整 + Hold Period 警示**：时间调整系数=当年市场中位 $/SF ÷ 交易年中位 $/SF（中位数来自 LoopNet 公开城市页）；<2 年转手标红；权重给调整最少的 comp。证据：LoopNet "SPC +/- Adj = V" 方法论文章。
4. **结果集统计条（纯前端）**：n 条、中位 $/SF、四分位、价格分布直方图、加权平均 cap rate——50 行 JS，零后端成本，性价比最高。证据：PDF Analytics Overview；Brevitas 模板。
5. **Comp grid 一键报告模板**：备忘录加"可比成交"节（grid + 直方图 + reconciliation 一句话结论），复用现有 PDF 链路。证据：G2 "nice pre made report templates"。

**不适合我们的**：人工核实研究员网络（护城河，复制不了也不该复制）、实地判定字段（建筑星级/stacking plan）、非披露州结构性缺失（德州连 CoStar 也没数据——诚实标注"无公开成交价"）、API（企业审批+redistribution 禁止，$0 预算下此路不通）。

---

## 二、Gap 清单（对照 DealDesk 现状）

| # | 缺口 | 现状 | 涉及竞品 |
|---|---|---|---|
| G1 | **Comps 模块完全缺失** | 无销售 comps；只有自建租金表 | Crexi#1、Dealpath#2、CoStar#1-5（三家 converge，最大缺口） |
| G2 | **Tear sheet / 一页纸** | 无；intake 后直接进三栏 | Dealpath#1 |
| G3 | **Intake 数据质量门** | 无校验层；抽取置信度未系统化（lineage 只有血缘无校验） | Dealpath#3、Cherre#3 |
| G4 | **Ownership 穿透** | 只有 TopHap 原始 ownership 字段，无 LLC→真人树 | Reonomy#1 |
| G5 | **卖方动机信号** | 无 sell-readiness；债务只有金额无 maturity flag | Reonomy#2/#3、Crexi#5 |
| G6 | **债务时间线** | C 页无债务到期小节 | Crexi#5 |
| G7 | **Canonical schema + connector 注册表** | provider 链存在但未形式化；字段形状各源不一 | Cherre#1/#4 |
| G8 | **Entity resolution** | fallback"取到即用"，多源冲突静默 | Cherre#2 |
| G9 | **Buy-box 自动打分** | 无；靠人工判断 | Dealpath#4 |
| G10 | **MCP server（被调用）** | 无；只有调外部 MCP | Dealpath#5 |
| G11 | **In-context 估值** | C 页无快速反推栏 | Crexi#2 |
| G12 | **Watchlist / deal 监控** | deal 列表无跟踪语义 | Crexi#4、Reonomy#4 |
| G13 | 来源可信度分层 | 部分有（字段血缘），未产品化到 UI/报告 | Crexi#3 |

## 三、Top 5 并入（价值 × 成本排序）

排序逻辑：Miao 是单人买方，真钱核保 → 独立估值能力（G1）> 决策速度（G2）> 数据可信（G3）> 交易结构穿透（G4）> 谈判信息（G5）。成本全部控制在"纯前端/纯规则/现有数据源"范围内，零新增采购。

1. **Comps 独立模块**（学自 Crexi#1 + CoStar#1-5 + Dealpath#2）：A 页旁新增 Comps 栏——结构化 comps 表（地址/成交价/日期/cap rate/$/SF/距离/来源必填）+ 三态标签（sold/under contract/for sale）+ 顶部统计条（n/中位 $/SF/四分位/分布直方图，纯前端）+ attach/pass（采用进估值依据/丢弃记理由）。验收：450 W 44th 能拉出 ≥3 条 comps（含来源标签），统计条数字与表格一致。
2. **一键 Tear Sheet**（学自 Dealpath#1）：intake 完成后自动生成 deal 一页纸——关键字段（价格/NOI/cap rate/全口径现金需求/月供/DSCR）+ 3 条 highlights + 1 条下一步建议；进 PDF 备忘录封面页。验收：任一已 intake deal 一键生成，Miao 不翻三栏可做 go/no-go。
3. **Intake 数据质量门**（学自 Dealpath#3 + Cherre#3）：固定字段 schema（分 deal 类型版本）+ 每字段来源/页码/置信度 + validators.py 规则层（偏离 warn、不一致 fail），fail 清零才能进 underwriting；低置信标黄。验收：故意喂一份前后矛盾的 OM，fail 项正确拦截并标黄。
4. **Ownership 穿透树**（学自 Reonomy#1）：intake 自动生成 LLC→真人→可信度树（SoS 公开查询 + TopHap ownership + 标注 verified/待验证）；联系方式只走 verified 来源。验收：450 W 44th 显示完整穿透链，任一推断字段带[待验证]。
5. **Sell-readiness 卖方动机分**（学自 Reonomy#2）：0-100 规则分（持有>10年+25、maturity<24mo+30、refinance+15、lien/violation+20、同 zip 销售率↑+10），intake 输出字段，附每项信号来源。验收：3 个已知 deal 打分排序与人工判断一致。

**暂缓（未丢弃，移入 backlog 暂缓区）**：截图/图片录取、扫描版 PDF OCR、移动端 390px QA、Provider 并行、fetch_page 上限——被挤掉的 5 项，待 Top5 消化后按序取回。
**后续迭代候选**（本次未进 Top5）：canonical schema + connector 注册表（Cherre#1，架构重构，排大版本）、entity resolution（Cherre#2）、buy-box 打分（Dealpath#4）、MCP server（Dealpath#5，N=1 主线长期项）、in-context 估值栏（Crexi#2，可并入 comps 二期）、watchlist（Crexi#4/Reonomy#4）、债务时间线（Crexi#5，可并入 tear sheet 二期）。

---

## 四、一句话结论

5 家研究的最大共识：**comps 是 CRE 核保的一等公民而 DealDesk 完全缺失**（三家 converge）；最大反共识机会：**所有竞品都被用户骂数据不准（CoStar cap rate 错 200bps、Crexi 经纪人谎报 $20-40M、Reonomy  dead numbers），而 DealDesk 的 🟢🟡⚪ 诚实材质 + 独立验证铁律正是它们洗不掉的原罪的反面**——学它们的功能骨架，用诚实做差异化，走 N=1 纵深路线。
