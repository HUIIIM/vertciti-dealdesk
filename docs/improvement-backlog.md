# DealDesk 每日改进台账

> 董事长指令（2026-10-01）："还有更好的改进方案，每天都需要提供改进。"
> 机制：cron `dealdesk-daily-improvement` 每天取最顶部一项，做完→测试→部署→验证→打勾→补下一项。
> 验收标准：每项必须有生产端到端验证证据，无证据=没做完。

## 待做（按优先级）

1. [ ] 报告导出：Manny Khoshbin 经典版 + DealDesk 增强版（含 DSCR/IRR/保本出租率/退出分析），商业页一键导出当前未保存状态
2. [ ] 商业页粘贴文本智能录取：粘贴 OM/flyer 文本 → 自动提取价格/面积/NOI/租户 → 填表（标卖方口径待验证）
3. [ ] 商业页截图/图片录取：上传房源截图 → OCR/视觉提取 → 填表
4. [ ] 扫描版 PDF OCR：图片型 PDF 先 OCR 再走现有提取链路，明确提示"OCR 口径"
5. [ ] 移动端 390px + 平板布局 QA：商业页三栏在小屏不溢出、可操作
6. [ ] Provider 并行调用：TopHap/RentCast/网页并行跑，取最快有效结果（现在串行慢）
7. [ ] 生产 PDF 解析换纯 Python 库（D2）：Vercel 无 poppler → 切 pypdf/pdfplumber 零系统依赖进 requirements.txt，消除"生产永远传不了 PDF"
8. [ ] 误导性数字口径（D3/D4，D460 CEO 已定）：`_div` 零分母 / `_irr` 无解返回 None，前端统一渲染"N/A"（禁显示 0.00/0%）
9. [ ] `monthly_payment` 与 `amort_payment` 百分制/小数制口径统一（埋雷）：审计发现两者利率口径不一致，静默错数风险
10. [ ] `fetch_page` 页面大小上限（大页面内存风险，P0 上传 OOM 同类）：预检 Content-Length/截断读取
11. [ ] RentCast 激活：等董事长绑卡后接入 fallback 链实测（外部阻塞，不占每日名额）

## 已完成

- 2026-10-02：可靠性专队剩余项收尾验收——18 项修复全部确认已部署生产，抽查回归通过。证据：生产 `tax/estimate` 非字符串/inf/空 body → 422/422/200；伪造 PDF 上传 → 400；真实地址（450 W 44th St）→ 27 字段、TopHap MCP 主源；pytest 192 passed（1 deselect pre-existing）；`tophap-token-watch`（30m）+ `dealdesk-smoke-test`（每日）两 cron 均绿。未修复 P2×12 中：地址缓存、token 巡检已由最优解项目落地并生产验证；DDG 限流/fetch_page 上限/pipeline 总耗时上限/robots 异常缓存/merge 备注丢失/日志截断/geocode 超时/discover_tools 重复 initialize/partialMatch 检查/down_pct 歧义，仍在日常迭代池（本次已取 3 项补入待做 7/9/10）
- 2026-10-02：地址结果缓存 24h 落地并生产验证（最优解项目）：生产重复查询 7363ms → 671ms，同 26 字段 TopHap 主源
- 2026-10-02：TopHap token 巡检升级为 30 分钟自愈链路（原每日巡检作废）：refresh_token 落盘 + cron 自动续期 + 同步 Vercel 环境变量 + 触发重部署；生产 token 实时 fresh（08:25 cron 成功），1 小时有效期问题闭环
- 2026-10-02：多数据源 fallback 链（TopHap → RentCast → 网页 → Census），26 字段生产验证通过
- 2026-10-02：税自动填 4 bug（预测字段丢失/badge 误显示/换州不刷新/手改被覆盖/光标乱跳），浏览器端到端验证通过
- 2026-10-02：可靠性审计 66 项中的 18 项（P0 上传 OOM + 17 项 P1/P2）修复并部署
- 2026-10-01：商业 PDF 智能录取上线；地址→自动房产税（50 州静态表 + Census）
- 2026-10-01：报告改版（三张图 + 叙事重写）；v4 深色终端重设计
