# DealDesk v2 对标研究与设计依据（2026-10-22）

> 补充 `docs/competitive-study-2026-10-02.md`（那份讲数据平台功能）。本篇讲三件事：
> ① 同行与新一代企业软件的**操作界面**怎么做；② 别人做了、我们没做的；③ 谁都没做、我们来做的。
> 结论直接落进 v2 的后端（§3 新增项）和前端规范（§4）。来源列在文末，多为厂商自述，引用时已标注。

## 1. 一个决定方向的数字

Dealpath《2026 State of AI in CRE Investing》（103 家机构）：97% 已把 AI 接入投资流程，但**只有 51% 认为算上核对后真省了时间，41% 认为反而更慢**，原因是每个输出都要先核对才能用于决策；首要原因是数据碎片化（43%）。机构更信 AI 读文件，不信 AI 估值。

**含义**：下一代承销工具比的不是"算得快"，而是**核对成本**。谁能让投委会不用重新核对就敢用这个数，谁就赢。这恰好是 DealDesk 从 v1 起的立身之本（“每个数字带来源，抓不到绝不编”），v2 要把它做成系统能力，而不是口号。

## 2. 同行在做什么

| 对象 | 界面 / 流程做法 | 我们的判断 |
|---|---|---|
| **Dealpath**（机构交易管理） | 2026-05 发布 Dealpath AI：抽取、AI 可比、秒级初筛、Excel 助手、**MCP**（在 Claude/Copilot/ChatGPT 里查 pipeline）；投委会审批流已有；“AI Agents”（初筛打分、组合感知、承销情景、文件生成）仍是预告 | 学 MCP 与审批流；它的 agent 还没交付，窗口期在 |
| **ARGUS Intelligence**（Altus） | 逐租约现金流、DCF/直接资本化/期限与复归多种估值、40+ 报表；2026 加 **ARGUS Assist** 对话式 agent 层 | 学“假设与结果分屏、逐租约”；它的 UI 仍是桌面时代密度 |
| **AI 原生新玩家**（RealQuant、Primer、Cactus、Apers、Blooma 等） | 共同点：从 OM / 租金表 / T12 抽数填进 Excel 模型，**每个格子引用到原文件第几页**；部分做实时 DCF | 页码级引用已是新基线，我们必须有；但它们多止步于“抽取 + 填表”，不管决策 |
| **验证派**（rets.ai、Leni 的主张） | 每个值链接到文件 / 页 / 原文 / 抽取时间 / 文件版本；高中低可信度 + 人工改写状态；**跨文件矛盾登记**（两个值、差多少、谁裁决）；假设来源登记；不可篡改日志；投委会备忘录显示“自上一版起改了什么、为什么”；源文件与输出做哈希防篡改；按风险分级的复核（高风险双人复核） | 这是投委会真正要的东西，方向与我们一致，我们要做得更彻底 |
| **流水线工具**（Lev、GrowthFactor 等） | 看板 / 列表 / **地图**三视图；阶段关卡；从邮件自动更新状态；投委会就绪报告 | 看板 + 列表必做，地图视图入后续 |

## 3. 别人想到、我们原蓝图没写的（v2 一并做）

1. **跨来源矛盾登记**：同一字段两个来源数值不同时，记录两边的值、差异幅度、采用哪个、谁裁决；未裁决的矛盾黄标，并作为进投委会的关卡之一。
2. **复核状态**：每个数字除了可信度，再带复核状态（待复核 / 已复核 / 人工改写），记录复核人和时间。
3. **假设来源登记**：每条假设标明来源类型：文件抽取、历史数据、市场基准、可比交易、分析师判断。“分析师判断”类且影响大的假设自动列入红队面板。
4. **“自上一版起改了什么”**：投委会包第一页列出与上一版的差异，以及每条改动的理由。
5. **防篡改**：投委会包印上运行编号和内容哈希；系统提供校验接口，拿到一份 PDF 就能验证它是不是原样。
6. **MCP 接口**（后续）：用自然语言在 Claude 里查流水线和单笔交易。v2 先把 OpenAPI 做干净，为 MCP 打底。
7. **界面基本功**：乐观更新（操作后先显示结果，后台再写库，失败回滚）、骨架屏代替转圈、行操作悬停才出现、快捷键提示写在按钮和菜单里、Esc 关闭所有浮层、表头吸顶。

## 4. 谁都没做、vertciti 来做的（在蓝图第 3 节 10 项之上）

1. **用敏感性来定义什么是“关键数字”**。别人的“关键数字”靠人拍脑袋。我们用红队面板的结果来定：凡是变动 ±10% 会让 IRR 移动超过 100 个基点的输入，自动成为“关键数字”。进投委会的关卡就是“所有关键数字都已复核，且可信度 ≥ 中”。这个规则客观、可复现，把核对力气集中在真正影响结论的少数数字上，正面回应上面那个 41%。
2. **核对进度条**：交易页顶部显示“关键数字已复核 x / y、未裁决矛盾 n 条、过期证据 m 条”，让人一眼看出离能上会还差多少。
3. **事后归因复盘**：持有期录入实际数后，系统把实际值逐项代回当时那次运行（同一个运行编号），算出每条假设的偏差各贡献了多少 IRR 偏差。别人只做“实际与承销对比”，我们回答的是“当时错在哪条假设”。下一笔交易的红队面板会引用这些历史偏差。
4. **反推最高出价同时给三条约束线**：同时算满足目标 IRR、满足目标 DSCR、满足淘汰条件的最高价，取其中最低的作为可出价，并写明是哪一条约束卡住了价格。
5. **决策时刻冻结**：每个 BUY / HOLD / PASS 的决策记录都带当时的运行编号和输入哈希。复盘时打开的是当时的数字原样，而不是用今天的模型重新算出来的结果。

## 5. 前端规范（落地版，按 vertciti DNA）

- **色彩**：白底黑字，信号橙 `#FF4713` 只用于品牌强调和焦点框；绿 = 达标或已验证，黄 = 待复核，红 = 触发淘汰或风险。状态一律“颜色 + 图标 + 文字”三者同时出现，色盲用户也能读。深色模式作为长时间建模用的选项，不设为默认。我们不照搬 Linear 的深色加紫色：2026 年这已经是同质化的样子，而且面向的是开发者。
- **字体与数字**：Nunito Sans 加苹方。数字用等宽数字、右对齐、千分位；单位写在表头，不写进单元格；负数同时用括号和红色表示。
- **布局**：间距用 8 点网格。结论卡放在左上（F 型阅读起点）。每屏最多一个主按钮，强调最多三级。
- **密度**：舒适和紧凑两档。紧凑档行高 32px、字号 13px、带斑马纹；舒适档行高 44px、字号 15px。表头和首列冻结，悬停时整行高亮，列宽可拖动并记住。
- **键盘**：⌘K 命令栏（地址、交易名、命令）；J/K 上下移动，Enter 打开，E 编辑，⌘S 保存，? 显示快捷键表，Esc 关闭浮层，G 加字母跳转页面。快捷键提示显示在按钮和菜单上。
- **速度感**：乐观更新，骨架屏，视图切换在 100ms 内完成，尊重系统的“减少动态效果”设置。
- **数字护照**：任何数字都可以点开，看到来源、页码、抽取方式、可信度、复核状态、新鲜度和修改历史。
- **手机端**：以只读为主，重点是结论卡和投委会包；触控目标不小于 44px。

## 来源
- Dealpath AI 发布（2026-05-19）：https://www.joplinglobe.com/region/national_business/dealpath-announces-dealpath-ai-bringing-native-ai-capabilities-to-the-full-investment-lifecycle/article_db86e280-b054-5ce1-b220-6f363a7ebbea.html
- Dealpath AI 页面：https://www.dealpath.com/ai/
- Dealpath 2026 AI 调查：https://www.dealpath.com/resource/21913-2/ ；https://irei.com/news/dealpaths-2026-state-of-ai-in-cre-investing-survey-reveals-near-universal-adoption-yet-limited-impact-to-date/ ；https://www.connectcre.com/stories/institutional-investors-say-data-problem-hinders-ai-use-in-decision-making/
- ARGUS Enterprise：https://www.altusgroup.com/solutions/argus-enterprise/?lang=fr ；Altus 2026 Q1/Q2 业绩：https://www.altusgroup.com/press-releases/altus-group-reports-q1-2026-financial-results-and-quarterly-dividend/ ，https://www.altusgroup.com/press-releases/altus-group-reports-q2-2026-financial-results-and-quarterly-dividend/
- AI 承销工具综述（厂商撰写）：https://www.v7labs.com/blog/best-real-estate-underwriting-software ，https://yieldstack.ai/blog/cre-underwriting-tools-2026 ，https://apers.app/compare/ai-underwriting-commercial-real-estate
- 投委会与审计轨迹：https://rets.ai/blog/the-audit-trail-problem-why-investment-committees-don-t-trust-ai ，https://rets.ai/blog/commercial-real-estate-underwriting-software-how-to-evaluate ，https://leni.co/blog/verifiable-ai-outputs-real-estate ，https://botminds.ai/solutions/investment-memo-ic-pack-generation
- 界面：https://www.925studios.co/blog/linear-design-breakdown-saas-ui-2026 ，https://adminlte.io/blog/fintech-dashboard-design-examples/
- 流水线工具：https://growthfactor.ai/blog-posts/commercial-real-estate-deal-software-guide ，https://lev.com/lp/pipeline
