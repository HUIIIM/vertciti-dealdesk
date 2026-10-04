# DealDesk GitHub 冷启动与引流打法手册

> 版本：v1.0 · 2026-10-01 · 只调研不执行（不碰仓库设置、不发帖）
> 适用对象：vertciti-dealdesk（房地产交易核保终端，中文，Python/FastAPI）
> 董事长要求："深度学到底 GitHub 里面是怎么玩的、怎么样能把它玩转"

---

## 0. 先说结论：DealDesk 的 GitHub 打法一句话

**小众垂直工具不靠 Trending 爆发，靠"精准人群 × 可试用 × 持续内容"滚雪球。**
房地产核保这个垂类在 GitHub 上几乎没有中文竞品——这是优势（搜索词竞争极低），
也是劣势（自然流量池小，必须自己把第一波人运进来）。
所以打法是：**站内把"被发现"做到满分（topics/描述/README/SEO），站外把第一波
200 个精准用户亲手推进来（X/LinkedIn/Reddit/HN 分批），中间用"一键可试用的
在线 demo"接住所有流量。**

---

## 1. GitHub 发现机制到底怎么工作

### 1.1 Search（站内搜索）排名因素

GitHub 不公开排名公式，但多个独立实测复盘结论一致：

- **排名 ≈ 人气排序**。进入候选集靠文本匹配（仓库名、描述、topics、README 全文索引），
  排第几主要看 stars/forks（实测中 forks 权重甚至高于 stars）。
  文本匹配只决定"进不进池子"，人气决定"在池子里排第几"。
- **仓库名是最强的文本信号**。名字里含关键词 = 所需人气门槛直接降好几倍。
  `vertciti-dealdesk` 里 "dealdesk" 本身就是关键词，这是天然优势；
  但要注意：搜 "real estate underwriting" 的人，名字里没有这些词，
  就要靠描述和 topics 补。
- **README 前 200 词权重最高**。关键词要出现在开头，而不是埋在文档底部。
- **窄词竞争极低**："real estate underwriting 中文工具"这种查询几乎没有竞品，
  小几十个 star 就能排第一；"real estate"这种大词则完全不用想（前面全是几千 star 的老项目）。
- 实操含义：**选 2-4 个"用户真会搜、且我们赢得了"的窄词**（见 3.1），
  而不是去卷大词。

来源：kholodilin/repo-growth-monitor 的实测复盘
（https://github.com/kholodilin/repo-growth-monitor/blob/HEAD/docs/github-search-ranking.md）；
repoboost-hq/github-search-ranking（https://github.com/repoboost-hq/github-search-ranking）

### 1.2 Topics（话题标签）的作用与选词

- Topics 是 GitHub 的**官方分类机制**：可搜索、可订阅（`github.com/topics/<topic>`），
  是"被发现"的主入口之一。每个仓库最多 20 个（docs.github.com 官方文档）。
- 规则：全小写、连字符分隔、50 字符以内。**少于 5 个 topics 会缺席带过滤的搜索**。
- 选词三层结构：**领域词**（用户是谁）+ **技术词**（用什么做的）+ **场景词**（解决什么问题）。
  不要堆 20 个凑数——前 10 个精准比 20 个泛泛有用。
- DealDesk 的 10 个 topics 见 3.1。

来源：docs.github.com "Classifying your repository with topics"；
elamcb 的 SEO 实操指南

### 1.3 Trending（趋势榜）算法与上榜条件

- Trending **不看总 star 数，看 star 增速（velocity）**：过去 24h / 7d / 30d
  新增了多少 star。500 star 的仓库一天涨 80 个，可以排到 5 万 star 一天涨 20 个的前面。
- 经验阈值（多方复盘交叉验证）：
  - 全语言日榜：单日约 80-150+ star；
  - 按语言分榜（如 Python）：单日约 30-60 star 就有机会；
  - 周榜：7 天约 300-500 star。
- 反作弊：新注册（<48h）、零公开活动的账号点的 star 会被降权甚至丢弃；
  **不要买 star、不要搞点赞群**——被识别出来直接失去资格，且损害账号信誉。
- 对 DealDesk 的现实判断：**首发日冲 Python 语言分榜是可争取的目标**
  （30-60 star/天，靠精准渠道分批导流可达）；全语言日榜当期盼，不当计划。
  Trending 是结果不是入口——先有"有用+可试+有人推"，榜单自然来。

来源：gingiris-1031/growth-tools 的 AFFiNE 28 次上榜复盘
（https://github.com/gingiris-1031/growth-tools/blob/HEAD/_posts/2026-04-06-how-to-get-on-github-trending.md）；
chama-x/quiv 的算法机制拆解；
sylin-org/ghostlight 的出版路径研究（核心结论：Trending 榜单是"已经发生的结果的播报"，不是入口）

### 1.4 Social preview（社交分享卡片）图

- 仓库链接被分享到 X/LinkedIn/Slack/Discord 时展开的卡片图。
  **没设置 = 只显示头像+一堵文字墙，点击率直接打折。**
- 官方规格：PNG/JPG/GIF，<1MB，推荐 **1280×640**（2:1），最小 640×320。
  上传路径：Settings → General → Social preview → Edit。
  注意：只有公开仓库的卡片能对外分享；各平台缓存 24-48h，换图后用各平台的
  卡片调试工具强制刷新。
- **四边各留 40pt 安全区**：不同平台裁剪方式不一样，字和 logo 不要贴边。
- DealDesk 的文案与设计见 3.3。

来源：docs.github.com "Customizing your repository's social media preview"

### 1.5 README 首屏的信息架构

高转化 README 的首屏（不滚动看到的部分）固定有 5 件套：

1. **一句话定位**（这是什么、给谁用）——3 秒内让人判断"与我有关/无关"；
2. **视觉证明**：demo GIF 或截图。**这是 star 转化率最高的单个元素**；
3. **徽章行**：CI 通过、license、stars（shields.io）——建立"这是正经项目"的第一印象；
4. **30 秒 quickstart**：可复制粘贴、一行能跑起来的命令；
5. **在线 demo 链接**：点开即用，不用克隆。

反模式：首屏只有大标题+一段愿景散文，没有图、没有跑起来的路径——
访客 10 秒内流失。**DealDesk 当前 README 正好缺 2/3/5（见 3.2），这是公开前必须补的。**

### 1.6 Releases / Changelog

- GitHub Releases 是"项目还活着"的官方信号：有规律的 release = 维护者在乎。
- 首个公开 release 建议 **v1.0.0**（semver；项目已可用、有 159 个测试，不是 demo）。
  Release notes 写法：Highlights（3 条人话）→ Features 列表 → 已知限制/诚实声明 →
  致谢。不要写成 git log 粘贴。
- 之后保持节奏：小步快发比憋大招好，每次 release 都是一次"提醒老用户回来看看"的机会。

### 1.7 Discussions vs Issues 的分工

官方默契（GitHub 社区共识）：

| 用 Issues | 用 Discussions |
|---|---|
| 明确的 bug | "这个怎么用"类问题（Q&A） |
| 可执行的 feature request | 想法 brainstorm（Ideas，成形后再转 issue） |
| 有验收标准的工作项 | 版本公告、路线图（Announcements，维护者发） |
| | 用户晒自己的用法（Show and Tell） |
| | 闲聊（General） |

一句话：**Issues 是工作台（可关闭、可指派），Discussions 是广场（聊完不一定有结论）。**
问题进了 Issues 会污染工作流、抬高 issue 数——这是开 Discussions 的核心原因。
Discussions 是 opt-in 功能，要在 Settings 里手动打开。

来源：GitHub 社区实践文档（bee-ai-labs/bee 的 DISCUSSIONS.md 等多方一致）

### 1.8 Star 增长飞轮

```
有用（解决真问题）→ 可试用（30 秒跑起来）→ 有人晒（用户自发分享）
    → 被收录（awesome-list/ newsletter/博客）→ 更多人发现 → 更多 star
    → 搜索排名上升 → 更多人发现 → …
```

关键洞察：**飞轮的第一推动力永远是"第一波精准用户"，不是 GitHub 站内流量。**
站内流量（搜索/Trending）是飞轮转起来之后的放大器。冷启动阶段 100% 的精力
应该放在"把第一波人亲手推进来"。

### 1.9 Awesome-list 收录路径

- awesome-list 是开发者圈的"人工精选目录"，被收录 = 长期、精准的自然流量。
- 路径：找到对口的 list（如 awesome-python、awesome-real-estate、awesome-selfhosted、
  awesome-finance）→ 按该 list 的 CONTRIBUTING 规则提 PR（一般是 fork → 在 README
  对应分类下加一行 `[名字](链接) - 一句话描述.` → 提 PR）。
- 门槛现实：多数 list 要求项目有一定 star 数和活跃度，**这是 T+30 之后的事**，
  不是首发日动作。但可以提前列好目标 list 清单（见 3.x 附表）。

来源：sindresorhus/awesome 的 PR 模板与各 list 的 CONTRIBUTING（jaywcjlove/awesome-mac 等）

---

## 2. 小众垂直工具的冷启动打法

### 2.1 前 100 star 从哪来（具体渠道，按优先级）

DealDesk 是中文房地产核保工具——受众 = **懂中文的房产投资人 + 爱折腾的开发者**。
这个交集小但精准，100 star 全部来自"亲手推进来"，不要指望自然流量。

| 优先级 | 渠道 | 打法 | 预期 |
|---|---|---|---|
| P0 | 创始人 X（@Miaojiahuii） | build in public 连载：公开前 7 天每天一条（倒计时+截图/GIF），公开当天发 launch 帖 | 创始人的现有粉丝是最热的流量 |
| P0 | LinkedIn（Jiahui Miao） | 中英双语：3GPP 标准人"下场做房地产核保工具"的反差叙事 + demo 截图 | 金融圈/创业圈精准人群 |
| P1 | Reddit r/selfhosted | 标题突出 self-hosted + SQLite 本地（"数据不出本机"是杀手特性） | 该 sub 对"本地优先"工具极友好 |
| P1 | Reddit r/opensource | 开源+MIT+中文特色 | 开源原教旨人群 |
| P1 | Reddit r/realestateinvesting | **不要发广告帖**：发"build in public"复盘帖——"我做了个免费核保工具，帮我测了 3 个 deal，这是我的方法论"，把工具当副产品带出来 | 房产投资人最集中的英文社区，直接用户 |
| P2 | Hacker News（Show HN） | 标题如 `Show HN: DealDesk – open-source real estate underwriting workbench (Chinese)`；正文讲技术取舍（为什么 SQLite/为什么保守口径/敏感性引擎怎么实现），**不要营销腔**；周二至周四美东上午 8-10 点发；发完 1 小时内必须在评论区答疑 | 高风险高回报：上首页=一天几千 star，上不去=零；**严禁拉票/互赞**，会被封 |
| P2 | 小红书/即刻（中文） | 中文受众主阵地：demo 录屏 + "创始人自用工具开源"叙事 | 中文房产投资人 |
| P3 | Product Hunt | **见 2.4 结论：暂缓**，等有 200+ star 和在线 demo 跑顺之后再上，当第二波弹药 |
| P3 | Dev.to / Hashnode | 长文：一篇"为什么房产核保需要保守口径引擎"的技术文， evergreen 搜索流量 | 长尾 SEO |

红线：**永远不要买 star、不要建互赞群、不要让朋友批量注册小号点 star**——
GitHub 反作弊会降权，HN 会封号。慢就是快。

### 2.2 内容钩子（让人愿意点开/转发的东西）

按转化率排序：

1. **Demo GIF（15-30 秒）**：录屏"粘贴一个房源链接 → 自动搜集 → 打分 → 出报告"全流程。
   这是整个冷启动**唯一不可替代**的资产。没有 GIF，README 转化率砍半。
2. **对比评测**："Excel 手算 vs DealDesk"——同一笔 deal，人工 2 小时 vs 工具 3 分钟，
   数字说话。房产投资人看得懂。
3. **Build in public 连载**：公开前 7 天，每天一条"今天修了什么/为什么这样设计"。
   观众参与了建造过程，公开当天会来捧场——这是第一波 star 的主要来源。
4. **方法论钩子**："保守口径""绝不编数""卖方口径待验证"——这是 DealDesk 与所有
   房源网站估值工具的**价值观差异**，写成短文会自然传播。
5. **PDF 备忘录样品**：一页纸的 A4 投资筛选备忘录截图——"这就是你能打印出来
   带去见律师的东西"，具象、可晒。

### 2.3 时间节奏（与第 5 章倒计时衔接）

- T-7 → T-1：build in public 连载（X/LinkedIn/小红书），每天一条，攒期待；
- T-0 当天：GitHub 公开 → X launch 帖 → LinkedIn → Reddit（分时段发，每帖都要能回评论）；
- T+1：Show HN（单独一天，创始人全天在评论区）；
- T+7：复盘帖（数据+学到的东西），第二波传播；
- T+30：开始投 awesome-list PR。

**不要同一天全渠道齐发**——每个渠道都需要创始人亲自回评论，一天只能打一场仗。

### 2.4 Product Hunt：上还是不上？

调研结论（多方 2026 年复盘交叉）：

- Product Hunt 对**有在线 demo、有故事、有现成受众**的产品是一次有效的流量脉冲；
  对"只有一个 repo"的项目效果很差。
- 链接是 nofollow（不直接带来 SEO），价值 = 当天流量 + 被 newsletter/榜单收录的二次传播。
- **给 DealDesk 的建议：暂缓。** 等满足三个条件再上：① 在线 demo 稳定跑顺；
  ② GitHub 200+ star（有社会证明）；③ 准备好英文 landing 文案和 demo 视频。
  PH 当第二波弹药，而不是首发渠道。**（D460/D505：智囊团快审→CEO 终裁，见第 6 章；不再等董事长拍板）**

来源：yerdaulet-damir/awesome-solo-ai 的 2026 发射渠道复盘；
dealpatrol/repofuse 的 Developer SaaS Growth Brief；
mxcorpin 的 Ossium vs Product Hunt 对比

---

## 3. DealDesk 具体执行清单

### 3.1 Topics：选这 10 个

（按"领域词 → 技术词 → 场景词"三层，每行附理由）

| # | Topic | 理由 |
|---|---|---|
| 1 | `real-estate` | 领域大词，必须有 |
| 2 | `real-estate-investing` | 精准用户会搜的词 |
| 3 | `proptech` | 行业黑话，投资人/从业者常用 |
| 4 | `underwriting` | 功能关键词，英文用户搜得到 |
| 5 | `financial-modeling` | 宽一层的金融建模人群 |
| 6 | `investment-analysis` | 同上，扩大候选池 |
| 7 | `fastapi` | 技术栈词，Python 开发者发现入口 |
| 8 | `python` | 语言分榜（Trending 按语言）的入场券 |
| 9 | `self-hosted` | r/selfhosted 人群的搜索词；"数据不出本机"是差异点 |
| 10 | `mcp` | TopHap MCP 集成是技术亮点，MCP 生态人群 |

操作：仓库 About 右侧齿轮 → Topics 逐个添加 → Save。
（GitHub 上限 20 个，先上这 10 个精准的，跑一个月看搜索来源再补。）

### 3.2 README 缺口（对照 1.5 的 5 件套逐项）

| # | 5 件套 | 现状 | 要补什么 |
|---|---|---|---|
| 1 | 一句话定位 | 有（"Miao 的房地产运营工具"） | OK，但建议首屏再加一句英文副标题，方便英文访客 3 秒判断 |
| 2 | 视觉证明 | **缺** | 补：demo GIF（15-30 秒全流程录屏）放最上；再加 2 张截图（仪表盘、PDF 备忘录样品）。素材：`your_files/dealdesk-preview/` 下已有截图可用 |
| 3 | 徽章行 | **缺** | 补 shields.io：CI passing、MIT license、GitHub stars 三个徽章 |
| 4 | 30 秒 quickstart | 有但弱 | 现在只有本地 `./run.sh`；补：① 在线 demo 链接（一点即用）；② Codespace 一键徽章（`Open in GitHub Codespaces`）；③ Docker 一行命令（如果加了 Dockerfile 的话） |
| 5 | 在线 demo | **缺** | vercel-deploy/ 已就绪，部署后把链接放在 README 最上 |

其他缺口：

- **测试数写错了**：README 写 "137 个用例"，实际已 159 个。公开前改掉（小错最伤信任）。
- **"诚实约定"保留并前移**：这是 DealDesk 与 Zillow/Redfin 估值工具最大的价值观差异，
  建议从当前位置往上提，紧跟"这是什么"。
- **缺 Roadmap**：加一节"路线图"（下一步做什么），让人知道项目活着、往哪走。
- **缺 FAQ**：3-5 个真问题（"和 Excel 比优势在哪？""数据准吗？""支持美国以外的房产吗？"）。
- **缺对比表**：DealDesk vs 纯 Excel vs 房源网站估值，一张小表讲清定位。
- **[待 GC 会签确认；D460/D505 后不再经董事长]** README 现有一句"vertciti 正在为 AI agent 构建采购与协作基础设施"——
  "采购基础设施"表述与 D313 之后 N=1 主线（已撤销 AI 代采购线）有张力，
  建议改为 N=1 纯口径（如"vertciti 只做一件事：运营创始人的人生；DealDesk 是这套
  人生操作系统里负责房地产的部分"），改法待批。

### 3.3 Social preview 图：规格与文案

- 规格：**1280×640 PNG，<1MB**，深色底（贴合产品深色终端气质），四边留 40pt 安全区。
- 文案（三行，不要多）：
  - 主标题：`DealDesk · 房地产交易核保台`
  - 副标题：`创始人自用的中文 deal 筛选工作流：录入 → 打分 → 敏感性分析 → 报告`
  - 角落小字：`Open Source · MIT`
- 设计：左文右图——右侧放一张仪表盘截图的暗角剪影（`v2-dashboard-1440.png` 可裁），
  左侧文字。Teal（#2dd4bf）只做一处强调（参考公司设计纪律）。
- 上传：Settings → General → Social preview → Upload。换图后用 X Card Validator /
  LinkedIn Post Inspector 强制刷新缓存。
- 建议把源文件（SVG 或生成脚本）也进仓库 `.github/assets/`，以后改图走 PR。

### 3.4 首个 Release：v1.0.0

- 版本号：**v1.0.0**（项目可用、有 159 测试、已有真实用户（创始人），不是 demo）。
- Release notes 写法（不要粘贴 git log）：

```markdown
## Highlights
- 中文房地产核保工作流开源：录入 → 打分 → 敏感性分析 → 对比 → 报告，一条龙
- 一键生成 A4 投资筛选备忘录 PDF，可打印带去见律师
- 全自动商业核保：搜集完成自动转入打分（Manny Khoshbin 模板方法论）

## 功能
- 住宅/商业双轨打分引擎（A/B/C/不收录四档 + 硬否决项红色置顶）
- 租金 ±10%、利率 ±2% 五档敏感性分析
- 最多 3 项目并排对比；全面分析工作台（估值/可比成交/市场调查）
- 智能搜集：地址 / 房源链接 / PDF（flyer、OM）三选一自动搜集

## 诚实声明
筛选辅助工具，不构成投资建议。抓不到的字段标"需手动补"，卖方口径数字一律
标"卖方口径、待验证"。签约/交割/报税前请经持牌律师、CPA、title company 审查。

## 试用
在线 demo：<链接> · 本地运行：./run.sh
```

- 操作：GitHub → Releases → Draft a new release → tag `v1.0.0` → 标题 `v1.0.0` →
  粘贴 notes → Publish release。

### 3.5 Discussions 开哪几个分类

在 Settings 里启用 Discussions 后，建这 5 个分类（用默认模板即可）：

| 分类 | 用途 |
|---|---|
| 📣 Announcements | 只维护者发：版本发布、路线图、安全公告 |
| 🙏 Q&A | "这个怎么装/怎么用"——可标记正确答案，攒成知识库 |
| 💡 Ideas | 功能 brainstorm，成形后转 Issues |
| 🙌 Show and Tell | 用户晒自己用 DealDesk 算的 deal（脱敏版）——**这是社区最有价值的内容** |
| 💬 General | 其他闲聊 |

分工铁律（写进 README 社区一节）：**有明确 bug/可执行需求 → Issues；
其他一切 → Discussions。**

### 3.6 CONTRIBUTING 还缺什么

现有 CONTRIBUTING 已有：流程、开发环境、代码规范、诚实铁律——底子不错。缺：

1. **Issue 模板**：`.github/ISSUE_TEMPLATE/bug_report.yml` 和 `feature_request.yml`
   （结构化表单，降低无效 issue）；
2. **PR 模板**：`.github/pull_request_template.md`（改了什么/为什么/测试怎么验）；
3. **行为准则**：`CODE_OF_CONDUCT.md`（Contributor Covenant 标准版，复制即可）——
   公开项目标配，没有会显得不专业；
4. **安全政策**：`SECURITY.md`（漏洞私下报告邮箱/方式，不走公开 issue）；
5. **`good first issue` 标签习惯**：留 2-3 个标注好的新手任务，贡献者漏斗的入口；
6. **Discussion-first 规则**：大的功能想法先去 Discussions 聊，成形再开 issue（防无效 PR）。

---

## 4. 引流与转化的衔接：GitHub → Telegram → vertciti 主线

### 4.1 漏斗设计

```
GitHub 访客
  → 在线 demo 点开即用（零安装门槛）————— README 最上、social preview、置顶
  → 跑通一次 → "这个好用" ——————————————— demo 里埋"在 Telegram 群晒你的第一笔测算"
  → Telegram 群（用户群） ———————————————— 群公告置顶：新人先看 #新人必读（3 篇精华）
  → 群内运营：每周一次"deal 复盘"（脱敏）、每月一次创始人 AMA
  → vertciti 主线 ——————————————————————— 群公告 + README About vertciti：
     "vertciti 只做一件事：运营创始人的人生。DealDesk 是这套人生操作系统
      里负责房地产的部分。" + vertciti.com 链接 + 创始人 X
```

### 4.2 每个环节的转化动作（具体、可执行）

- **README → demo**：首屏 3 个入口（徽章下大按钮"在线试用"、quickstart、截图下文字链），
  目标：访客 → demo 点击率。
- **demo → Telegram**：demo 页页脚加一行"算出有意思的 deal？来 Telegram 群晒一下（脱敏）"，
  带群链接。目标：demo 用户 → 加群。
- **Telegram → 主线**：群公告只放两样东西——DealDesk 精华帖 + vertciti 一句话介绍。
  **不要在群里卖任何东西**（D9 变体：群是社区，不是销售漏斗的骚扰位）。
- **X/LinkedIn → GitHub**：每条 launch 内容只带一个链接（GitHub 仓库），
  不要同时给 demo 链接分散——让 GitHub 当唯一落地页，README 再分发到 demo。

### 4.3 N=1 口径红线（全程高压线）

- 对外叙事永远是：**"创始人自用的房地产运营工具，开源出来给大家用"**。
- 禁词（README、release notes、Discussions 公告、所有对外帖子一律零出现）：
  `AI 代采购` / `AI Data Go` / `data-go` / `商城` / `marketplace` /
  `agent commerce` / `procurement concierge` / `AI 伴侣` / `自动运营` / `供应商拓展`。
- 灰区（需 GC/董事长单批）：README 现有"为 AI agent 构建采购与协作基础设施"一句（见 3.2）。
- 房地产是董事长副业升级后的基本盘（D325），DealDesk 讲"算 deal 的工具"完全合规，
  不碰任何已撤销业务线叙事即可。

---

## 5. 倒计时发布流程（T-7 / T-3 / T-1 / T-0）

> 董事长要求："公开之前要有一个倒计时的流程，公司团队要走审批流程，如果都过了才能公开。"
> 下面是 GitHub 侧的操作清单，每一步写清"点什么、发什么、检查什么"。

### T-7｜封版（Freeze）

**目标**：main 分支进入只修 bug 状态，公开物料冻结。

GitHub 操作清单：
- [ ] Settings → Branches → 给 `main` 加 branch protection：Require a pull request
      before merging + Require status checks to pass（选 CI workflow）。
- [ ] 把 3.2/3.3/3.6 的 README、social preview 源文件、CONTRIBUTING 补件全部合进 main。
- [ ] 打 tag `v1.0.0-rc1`（先不 publish release，只推 tag 供内部验证）。
- [ ] 检查：Actions 全绿；repo Insights → Traffic 确认无异常（私有期应接近零）。

内容动作：X/LinkedIn/小红书开始 build in public 倒计时连载 Day 7（"7 天后开源"）。

### T-3｜预热（Warm-up）

**目标**：所有"被发现"的物料就位，外部只看到预告、看不到代码。

GitHub 操作清单：
- [ ] About 设置：Description 一句话（`创始人自用的中文房地产核保工具：录入→打分→敏感性分析→报告 | Open source MIT`，
  160 字符内）→ Website 填在线 demo 链接 → Topics 加 3.1 的 10 个 → Save。
- [ ] Settings → General → Social preview 上传 1280×640 图（3.3）。
- [ ] Settings 启用 Discussions，建 3.5 的 5 个分类；发第一条 📣 Announcements：
  "DealDesk 将于 3 天后开源，欢迎先 star 占位"（配 demo GIF）。
- [ ] Issues 启用模板（bug_report / feature_request）；PR 模板、CODE_OF_CONDUCT、
  SECURITY.md 合并。
- [ ] 检查：在隐私模式下打开仓库页，确认 About、topics、social preview 显示正常；
  用 X Card Validator / LinkedIn Post Inspector 预览卡片（注意此时仓库仍是私有，
  卡片只自己可见——这是正常的）。

内容动作：倒计时 Day 3 帖（demo GIF 全网发一遍）；给 10 个可能转发的朋友私发预告
（**是"告知"不是"求转发"，不搞互赞**）。

### T-1｜公司团队审批（Go / No-Go）

**目标**：按下董事长说的"公司团队走审批流程"，全过才公开。

审批表（逐项签字，不过就延期）：

| # | 审批项 | 负责人 | 通过标准 |
|---|---|---|---|
| 1 | 代码门禁 | CTO | pytest 全过、CI 全绿、无已知 P0 bug |
| 2 | 敏感扫描 | 安全 | gitleaks/密钥无残留、.env/私钥无入仓 |
| 3 | N=1 口径 | GC | README/release notes/About 全文禁词零命中（4.3 清单） |
| 4 | 内容门禁 | CPO | README 5 件套齐（3.2）、demo GIF 可播、social preview 正常 |
| 5 | 法务 | GC | LICENSE=MIT（待 GC 终定）、ATTRIBUTION 完整、免责声明就位 |
| 6 | CEO 终裁 | CEO | 四闸＋GC 会签全过即发（D460/D508：不再经董事长） |

任一不过 → 公开延期，T-0 顺延。**这是铁律，不许"差不多就发"。**

### T-0｜公开（Launch Day）

**目标**：仓库翻公开，流量按顺序进来，每一波都有人接。

GitHub 操作清单（按顺序，30 分钟内做完）：
1. [ ] Settings → General → Danger Zone → **Change visibility → Make public**
      （确认弹窗输入仓库名）。
2. [ ] Releases → Draft a new release → tag `v1.0.0` → 粘贴 3.4 的 notes → Publish。
3. [ ] Discussions → 📣 Announcements 发公开帖（中英双语，带 demo GIF + 在线 demo 链接）。
4. [ ] 检查：公开模式下打开仓库页（About/topics/README/徽章/discussions tab 全正常）；
      手机上点一遍在线 demo 确认可打开。

流量顺序（**分开时段，创始人每波都要回评论**）：
- 上午：X launch 帖 → LinkedIn 双语帖；
- 下午：r/selfhosted → r/opensource（错开 3 小时）；
- 晚上：r/realestateinvesting（build in public 复盘帖形态）；
- T+1 单独一天：Show HN（创始人全天在评论区）。

T+7：发复盘帖（star 数、流量来源、学到的东西）——第二波传播 + 长期信任资产。

---

## 6. 待定事项（D460/D508：智囊团快审→CEO 终裁，不再经董事长）

1. **Product Hunt 上不上**：建议暂缓（见 2.4），等 200+ star + demo 跑顺后当第二波弹药。决断（CEO）：上 / 不上 / 以后再议。
2. **Telegram 群名**：候选：`DealDesk 用户交流群` / `DealDesk 中文核保群` / `vertciti · DealDesk`。决断（CEO）一个（群建好后群名难改）。
3. **Discord 要不要**：README 写了"Discord 社区：即将上线"。建议第一阶段只做 Telegram（中文用户主阵地）+ GitHub Discussions（开发者），Discord 暂缓——三个群运营不过来等于三个死群。决断（CEO）：做 / 暂缓。
4. **Release 版本号**：建议 v1.0.0（见 3.4）。备选 v0.1.0（更保守）。决断（CEO）一个。
5. **README 那句"采购基础设施"**：改 N=1 纯口径还是保留？（见 3.2 灰区）拍板改法。
6. **英文 Issue/PR 接不接**：仓库是中文项目，来了英文 issue 是回英文还是请对方用中文？建议：回英文（开源礼仪），代码注释保持中英双语关键处。拍板。
7. **在线 demo 方案**：Vercel 公开部署（推荐，长期稳定）vs Codespace preview（临时）。拍板。
8. **Awesome-list 目标清单**：建议 T+30 投：awesome-python、awesome-selfhosted、awesome-finance、awesome-real-estate（若有）。拍板是否列入计划。

---

## 资料来源

- GitHub Trending 算法与阈值：gingiris-1031/growth-tools《How to Get on GitHub Trending》
  （https://github.com/gingiris-1031/growth-tools/blob/HEAD/_posts/2026-04-06-how-to-get-on-github-trending.md）；
  chama-x/quiv《Trending Algorithm Mechanics》
- GitHub Search 排名实测：kholodilin/repo-growth-monitor
  （https://github.com/kholodilin/repo-growth-monitor/blob/HEAD/docs/github-search-ranking.md）；
  repoboost-hq/github-search-ranking
- Topics 官方文档：docs.github.com《Classifying your repository with topics》；
  上限 20 个（官方）
- Social preview 官方文档：docs.github.com《Customizing your repository's social media preview》
  （1280×640 推荐，<1MB）
- Show HN 实操：nirholas/visualize-web3-realtime《Hacker News Launch Strategy》；
  muvon/octomind-tap 的 trend-hackernews / social-hackernews skill（含 HN 官方规则引用：
  禁止拉票、禁止互赞）；
  portalfnd/clawtrlautonomous 的 show-hn-draft skill（周二至周四美东 8-10 点经验窗口）
- Discussions vs Issues：bee-ai-labs/bee《DISCUSSIONS.md》；
  community-access/git-going-with-github；GitHub Resources
  （"Discussions are for discussing things. Issues are for cataloguing the work."）
- Awesome-list 收录：sindresorhus/awesome 的 PR 模板要求；jaywcjlove/awesome-mac、
  osmlab/awesome-openstreetmap 的 CONTRIBUTING
- Product Hunt 2026 复盘：yerdaulet-damir/awesome-solo-ai《where-to-launch.md》；
  dealpatrol/repofuse《DEVELOPER_SAAS_GROWTH.md》；
  mxcorpin《Ossium vs Product Hunt》；nextbigtool.com《Product Hunt Alternatives 2026》
- 冷启动节奏参考：pritam-patil/github-trending-without-ai《LAUNCH.md》
  （Day1 HN → Day2-3 Reddit → Day4-5 Dev.to）；
  sylin-org/ghostlight《publication-paths-2026-07》
  （"Trending 是结果的播报，不是入口"）
- 开源社区战略（内部）：2026-09-29 董事长 standing directive——公开门禁
  （CI 全过＋真机实证＋敏感扫描＋N=1 筛查＋GC 口径＋README/品牌配套）
