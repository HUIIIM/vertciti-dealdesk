# DealDesk 组动员三件套（D462）

> 落盘时间：2026-10-01 23:35 EDT。24h 办结制（D461）。pipeline 深度≥1，不许空窗。

## ① 当前手头工作清单（按 agent 列）

| Agent | 在做什么 | 预计结果时间 |
|---|---|---|
| 最优解总协调 ab3625ee | 4 件：①TopHap token 自愈（refresh_token 持久化+30min cron+自动推 Vercel）②部署单源（部署前自动 rsync，消灭双目录漂移）③地址缓存 24h（含 stale 降级）④每日冒烟测试 cron | 2026-10-02 24h 内（D461） |
| dealdesk-daily-improvement（cron，每日 08:00 ET） | 按改进台账逐项交付：报告导出（Manny Khoshbin 经典版+增强版）→ 粘贴文本录取 → 截图录取 → 扫描 PDF OCR → 移动端 QA → provider 并行 → token 巡检 | 每日一份交付 |
| 可靠性专队收尾 | 66 项中剩余 P1/P2 验收 + docs/reliability-audit 落盘 | 并入最优解②③验收 |

## ② 未来预想＋升级迭代计划

- **数据源**：RentCast（等董事长绑卡激活）→ ATTOM（付费，待董事长批预算）→ 各郡县 assessor 免费源（主要 metro）
- **智能**：字段冲突时多源交叉验证（TopHap vs RentCast 估值差异>15% 标黄提示）；地址模糊匹配加人工确认
- **体验**：移动端 390px 全流程可用；报告一键 PDF（含 Manny 版式）
- **成本**：缓存 + 并行后，TopHap/RentCast 调用量降 70%+；用量看板

## ③ 下一步 pipeline（当前完成后自动衔接）

1. 最优解 4 件验收 → 2. 每日改进第 1 项（报告导出）→ 3. RentCast 激活（董事长绑卡后）→ 4. provider 并行 + 冲突提示 → 5. 移动端 QA → 6. ATTOM 评估（一键包给董事长批预算）

pipeline 深度：6。无空窗。
