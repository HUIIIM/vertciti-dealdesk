# SCOPE UPDATE · 2026-09-28 19:30 EDT（Miao 亲定，dealdesk 构建必读）

本文件是对构建任务的口径更新。买盒文件已同步更新到磁盘最新版，
打分引擎必须以 `deal-scout/buyer-box.md`（v2.1）和
`deal-scout/buyer-box-commercial.md`（v1.1）的**当前磁盘版本**为准，
不要用你之前读到的旧阈值。

## 变更清单

1. 住宅线 v2.1：subject-to 首付上限 5%→**8%**（5–8% 为正常区间，不再要求 0–3%）；
   首付评分：≤5% 满分，8% 良好档，10% 及格线。

2. 商业线 v1.1：
   - **office 和酒店正式纳入 in scope**（Miao 点名要看）。
     Office： 在租率 ≥80%、WALT ≥4 年、空置/坏账 ≥12%、
     租金下调 10% 压力测试后 DSCR 仍 ≥1.25、TI/LC 逐项核算；
     纯投机性空置办公不看。
     酒店：RevPAR 取 trailing 12 个月与过去 3 年平均孰低、
     管理费 ≥5% revenue、FF&E reserve ≥4% revenue、
     DSCR ≥1.35、淡季月份现金流覆盖当月 debt service、
     品牌 PIP capex 计入成本、特许经营协议 ≥10 年；
     无经营记录的新建/烂尾酒店不收录。
   - **value-add 明确鼓励**：价格合适或 structure 合适、可接贷款、低首付就做；
     风控门槛沿用（12 个月储备＋TI/LC 预算＋70% 预租进 A 级）。
   - **资金约束是硬约束**（Miao 当前可用资金很少）：
     每笔 deal 必须有一级字段 **cash-to-close** ＝
     现金首付＋交割费用＋交割后储备金＋首年 capex/TI/LC；
     列表页支持按 cash-to-close 升序排列。
     具体硬上限数额待 Miao 确认，先做字段和排序，不硬编码金额。
   - 新增硬否决："只能靠短期高价抛售解套"的结构一票否决
     （持有收租或 refi 必须能独立成立）。
   - subject-to 5–8% 视为健康区间；首付评分：≤5% 满分、8% 良好、20% 及格。

3. UI 保持全中文。其他任务不变。
