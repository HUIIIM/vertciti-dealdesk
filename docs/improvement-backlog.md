# DealDesk 每日改进台账

> 董事长指令（2026-10-01）："还有更好的改进方案，每天都需要提供改进。"
> 机制：cron `dealdesk-daily-improvement` 每天取最顶部一项，做完→测试→部署→验证→打勾→补下一项。
> 验收标准：每项必须有生产端到端验证证据，无证据=没做完。

## 待做（按优先级）

1. [ ] 商业页粘贴文本智能录取：粘贴 OM/flyer 文本 → 自动提取价格/面积/NOI/租户 → 填表（标卖方口径待验证）
2. [ ] **Ownership 穿透树**（学自 Reonomy，Top4）：intake 自动生成 LLC→真人→可信度树（SoS 公开查询 + TopHap ownership + 标注 verified/待验证）；联系方式只走 verified 来源。验收：450 W 44th 显示完整穿透链，任一推断字段带[待验证]
3. [ ] **Sell-readiness 卖方动机分**（学自 Reonomy，Top5）：0-100 规则分（持有>10年+25、maturity<24mo+30、refinance+15、lien/violation+20、同 zip 销售率↑+10），intake 输出字段，附每项信号来源。验收：3 个已知 deal 打分排序与人工判断一致
4. [ ] 生产 PDF 解析换纯 Python 库（D2）：Vercel 无 poppler → 切 pypdf/pdfplumber 零系统依赖进 requirements.txt，消除"生产永远传不了 PDF"
5. [ ] 误导性数字口径（D3/D4，D460 CEO 已定）：`_div` 零分母 / `_irr` 无解返回 None，前端统一渲染"N/A"（禁显示 0.00/0%）
6. [ ] `monthly_payment` 与 `amort_payment` 百分制/小数制口径统一（埋雷）：审计发现两者利率口径不一致，静默错数风险
7. [ ] 商业页 390px 移动端 QA：新增"一键 Tear Sheet"按钮后 cmd-ctl 在 390px 是否溢出/可操作；商业页三栏在小屏不溢出。验收：真机/真浏览器 390px 逐项目检通过
8. [ ] 商业页截图/图片录取（暂缓项回补）：上传房源截图 → OCR/视觉提取 → 填表（标卖方口径待验证）。验收：上传一张真实房源截图，价格/面积/租金字段正确提取并标待验证
9. [ ] 扫描版 PDF OCR（暂缓项回补）：图片型 PDF 先 OCR 再走现有提取链路，明确提示"OCR 口径"
10. [ ] 门覆盖补齐（2026-10-06 数据质量门二期）：截图 intake 的视觉提取结果同样跑质量门（`image_intake` 输出附 quality_gate）；住宅页（d.html）接入商
    业页同款门面板 + 导出前过门。验收：截图/住宅两路各喂一份矛盾材料，fail 正确拦截并标黄
11. [ ] RentCast 激活：等董事长绑卡后接入 fallback 链实测（外部阻塞，不占每日名额）

## 暂缓（被 Top5 挤掉，未丢弃，消化完按序取回）

- 扫描版 PDF OCR：图片型 PDF 先 OCR 再走现有提取链路，明确提示"OCR 口径"
- （移动端 390px QA 已升为待做第 10 项，含新导出按钮的 cmd-ctl 溢出检查）
- Provider 并行调用：TopHap/RentCast/网页并行跑（缓存已缓解，优先级下降）
- `fetch_page` 页面大小上限（大页面内存风险，P0 上传 OOM 同类）

## 后续迭代候选（竞品研究未进 Top5，排大版本/长期）

- Canonical deal schema + connector 注册表（学自 Cherre，架构重构）
- 轻量 entity resolution：多源字段冲突 flag 而非静默取第一个（学自 Cherre）
- Buy-box 自动打分：Miao"资金很少"硬约束写成可配置 YAML（学自 Dealpath）
- DealDesk MCP Server：pipeline/comps/承销结果暴露给 Miao 自然语言查询（学自 Dealpath，N=1 主线长期项）
- In-context 估值栏：C 页顶部 cap rate/$/SF/GRM 一键反推（学自 Crexi，可并入 comps 二期）
- Deal watchlist：跟踪中 deal 每周重跑估值，漂移推送（学自 Crexi/Reonomy）
- 债务时间线：C 页债务到期小节（学自 Crexi，可并入 tear sheet 二期）

## 已完成

- 2026-10-06：Intake 数据质量门上线（原台账第 1 项，学自 Dealpath/Cherre Top3）。新模块 `app/validators.py`：固定字段 schema（commercial-v1/residential-v1：类型/口径/核保必填/合理区间）＋ 规则层（cap rate 一致性 >300bps fail / NOI 超毛租金 fail / 租约面积超可租面积 fail / 租户租金单价物理不可能 fail / 文档内同一口径多数值矛盾 fail / 偏离 warn），fail 清零前 blocked；`pdf_intake` 按页提取（pdftotext `\x0c` 分页）字段标注来源页码；两 intake 端点响应附 `quality_gate`（field_report：来源/页码/置信度，低置信标黄）；新端点 POST /api/wb/intake/gate；`/api/uw/report` 与 `/api/uw/tearsheet` 服务端硬拦（blocked→422）；商业页门面板（拦截/告警/通过）＋ fail/warn 命中的输入框琥珀描边常驻标黄＋导出前过门（拦截则终止、告警则确认）。附带修复：`tests/test_cache.py` 缺 sys.path 导致全量 pytest 采集失败。证据：pytest 384 passed（20 新，1 deselect pre-existing test_address_pipeline_degradation）＋ 生产 E2E（dpl_2qamFzhczTPoeqPYq9uftfqeUB2B）：/api/wb/intake/gate 矛盾字段 → blocked（2 fail：NOI>毛租金/双要价矛盾，yellow_fields 3 个）；/api/uw/tearsheet 矛盾 state → 422、干净 state → 200 PDF；/api/uw/report 同样 422/200；uw-commercial.html/js 含门面板与标黄代码。限制：生产无 poppler，PDF intake 端点返回"缺少 pdftotext"（台账第 4 项 D2 待解决），故生产 E2E 用 gate 端点＋JSON 字段直调完成。证据文件：goals/vertcity-build-out/hidden_files/dealdesk-improvement-2026-10-06/
- 2026-10-05：一键 Tear Sheet 上线（原台账第 1 项，学自 Dealpath Top2）。新模块 `app/tearsheet.py`：compute_all() 结果 → 一页纸数据（12 个关键指标：价格/NOI/cap/全口径现金需求/月供/DSCR/盈亏平衡/现金回报/IRR/股本倍数）＋ 规则引擎生成恰好 3 条 highlights（危>警>好排序：DSCR<1.0 致命、DSCR<1.25 银行口径警告、盈亏平衡>90% 安全垫薄、cap±100bps 定价信号、现金回报<5%/IRR<8% 偏低）＋ 1 条下一步建议；缺数一律 None → "—"（不印 0.00×/0%）。新端点 POST /api/uw/tearsheet（当前未保存 state 一键生成独立 1 页 PDF）；商业页 cmd-ctl 新增"一键 Tear Sheet"按钮（flex-wrap 已有，390px 无新增溢出风险）；备忘录 PDF（POST /api/memo/pdf 商业线）首插 Tear Sheet 封面页（浅色页配白底，深色正文页不受影响）。证据：pytest 364 passed（10 新，1 deselect pre-existing test_address_pipeline_degradation）＋ 生产 E2E：450 W 44th St（$4.35M）/api/uw/tearsheet 200 → 严格 1 页、文本层含 TEAR SHEET/$4,350,000/DSCR/全口径现金需求/下一步建议；/api/memo/pdf 商业 200 → 3 页且第 1 页为 Tear Sheet 封面；生产 uw-commercial.html/js 含按钮与端点调用。证据文件：goals/vertcity-build-out/hidden_files/dealdesk-improvement-2026-10-05/
- 2026-10-04：Comps 独立模块上线（原台账第 1 项）。A 页新增②可比成交栏：TopHap CMA 一键拉取（新端点 POST /api/wb/comps/pull）+ 结构化表（三态标签 sold/under contract/for sale、成交价/日期/cap rate/$/SF/距离/来源必填）+ 顶部统计条（n/中位 $/SF/Q1/Q3/分布直方图，纯前端）+ attach/pass（丢弃须填理由）；估值/周边汇总只用已采用案例。证据：pytest 212 passed（11 新）+ 生产真浏览器 E2E：450 W 44th St 拉取 10 条 comps（全部来源标签 TopHap CMA · recorded sales），统计条 n=10/中位 $740/Q1 $484/Q3 $1078 与表格独立复算完全一致，丢弃/重新采用联动重算正确。证据文件：goals/vertcity-build-out/hidden_files/dealdesk-improvement-2026-10-04/
- 2026-10-03：商业核保报告导出双版本落地（原台账第 1 项）。经典版=1:1 复刻 Manny Khoshbin 模板三表（PROPERTY OVERVIEW/Analysis/Cash Flow/Rent Roll，全部由引擎实时重算）；增强版=DealDesk 指标（DSCR×2/盈亏平衡出租率/IRR/股本倍数/持有期现金流+退出分析）；新端点 POST /api/uw/report（variant=classic|enhanced），商业页新增"导出经典版 PDF / 导出增强版 PDF"两按钮，一键导出当前未保存 state。附带修复：此前 vercel-deploy/app/pdf_uw.py 是未接线孤儿草稿（无端点无按钮无测试）——本次补齐字体容错（serverless 无字体不崩）、HTML 转义、NaN/None→"--"诚实标注、删死代码。证据：pytest 201 passed（1 deselect pre-existing test_address_pipeline_degradation）+ 9 新用例；生产 dpl_8WQHS4UDrA2hAdKJtcAKdu2hrJBB：真 deal（450 W 44th St, $4.35M）classic 3 页/enhanced 1 页 200+application/pdf，文本层含物业名/金额/DSCR/IRR/盈亏平衡出租率/持有期现金流，非法 variant 400。证据文件：goals/vertcity-build-out/hidden_files/dealdesk-improvement-2026-10-03/
- 2026-10-02：竞品学习 5 家（Dealpath/Crexi/Reonomy/Cherre/CoStar）→ gap 清单 13 项 → Top5 并入本台账。报告：`docs/competitive-study-2026-10-02.md`
- 2026-10-02：可靠性专队剩余项收尾验收——18 项修复全部确认已部署生产，抽查回归通过。证据：生产 `tax/estimate` 非字符串/inf/空 body → 422/422/200；伪造 PDF 上传 → 400；真实地址（450 W 44th St）→ 27 字段、TopHap MCP 主源；pytest 192 passed（1 deselect pre-existing）；`tophap-token-watch`（30m）+ `dealdesk-smoke-test`（每日）两 cron 均绿。未修复 P2×12 中：地址缓存、token 巡检已由最优解项目落地并生产验证；DDG 限流/fetch_page 上限/pipeline 总耗时上限/robots 异常缓存/merge 备注丢失/日志截断/geocode 超时/discover_tools 重复 initialize/partialMatch 检查/down_pct 歧义，仍在日常迭代池（本次已取 3 项补入待做 7/9/10）
- 2026-10-02：地址结果缓存 24h 落地并生产验证（最优解项目）：生产重复查询 7363ms → 671ms，同 26 字段 TopHap 主源
- 2026-10-02：TopHap token 巡检升级为 30 分钟自愈链路（原每日巡检作废）：refresh_token 落盘 + cron 自动续期 + 同步 Vercel 环境变量 + 触发重部署；生产 token 实时 fresh（08:25 cron 成功），1 小时有效期问题闭环
- 2026-10-02：多数据源 fallback 链（TopHap → RentCast → 网页 → Census），26 字段生产验证通过
- 2026-10-02：税自动填 4 bug（预测字段丢失/badge 误显示/换州不刷新/手改被覆盖/光标乱跳），浏览器端到端验证通过
- 2026-10-02：可靠性审计 66 项中的 18 项（P0 上传 OOM + 17 项 P1/P2）修复并部署
- 2026-10-01：商业 PDF 智能录取上线；地址→自动房产税（50 州静态表 + Census）
- 2026-10-01：报告改版（三张图 + 叙事重写）；v4 深色终端重设计
