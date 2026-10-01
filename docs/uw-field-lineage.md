# 商业核保模板字段血缘表

> 来源：Manny Khoshbin Financial Starter Kit（两个 Google Sheets 实例）
> F1 = `1MPD9NnLySmbWtBt0J_AZ0WaWv8zRVQ_4`（39-09 Main St，单租户 Retail）
> F2 = `1iaEjyCM5y9080CMz4igQFjyuuyJFgd9v`（Flushing Vacant Main Street，多租户 Office）
> 审计日期：2026-10-01。`[手]`=手工输入，`[算]`=公式，`[链]`=跨表引用。

## 0. 全局结构

- 3 个可见 sheet，无隐藏 sheet/行（Cash Flow 隐藏 K 列辅助列），无命名范围、无数据验证、无条件格式、无批注。
- 数据流向：`Rent Roll → Cash Flow → Analysis`，但 Analysis 有**手工断点**（见 §3）。

## 1. Rent Roll（租户 → 合同年租 → 包租年租）

列定义（row7 分组头 / row8 子头 / row9 字段）：

| 列 | 分组 | 字段 | 类型 | 公式/说明 |
|----|------|------|------|-----------|
| A | — | Suite/Ref. | [手] | 单元号 |
| B | — | Tenant Name | [手] | 租户名；合计行写 TOTALS-EXISTING TENANTS / VACANT SPACE / TOTAL FOR PROPERTY |
| C | Net | Sq. Ft. | [手] | 面积；0 面积允许（CellTower），除零由公式规避 |
| D | % of Sq. Ft. | Total | [算] | `=C10/$C$14`（F1）/=C10/$C$36（F2）：面积占物业总面积比 |
| E | RENT PER LEASE | Monthly Rent | [手] | 合同月租 |
| F | RENT PER LEASE | Monthly Rent Per/SF | [算] | `=E10/C10`：月租/面积 |
| G | RENT PER LEASE | Annual Rent | [算] | `=E10*12`：合同年租 |
| H | RENT PER LEASE | Rent as % of Total | [算] | `=G10/$G$12`（F1）/=G10/$G$34（F2）：占已租年租比 |
| I | RENT PER LEASE | Rent/SF | [算] | `=G10/C10`：合同年租/面积 |
| J | Est. | Market Rent/SF | [手] | 预估市场租金；两实例均空 |
| K | UNDERWRITTEN RENT ** | Annual Rent | [手]/[链] | 包租年租。F1 手填 2,000,000；F2 `=G10` 链合同年租 |
| L | UNDERWRITTEN RENT ** | Rent as % of Total | [算] | `=IF(K10=0,"--",K10/$K$12)`：零值显示 `--` 保护 |
| M | UNDERWRITTEN RENT ** | Rent/SF | [算] | F1 `=K10/C10`；F2 `=MIN(I10,J10)`（取保守值，J 空时退化为 I）|
| O | Lease | Tenant Since | [手] | 起租日期（序列值）|
| P | Lease | Began | [手]/[链] | F2 `=O10` 链起租 |
| Q | Lease | Ends | [手] | 结束日期（文本 `09/302028` 这种脏数据存在）|
| R | Lease | Term (Yrs.) | [算]/[手] | F2 `=(Q10-P10)/365`；F1 手填 5 |
| S | Lease Type | (FSG, NNN…) | [手] | NNN / Gross / ModGross |
| T | Monthly | CAM | [手] | 两实例均空（有 `=SUM(T10:T32)` 合计公式待用）|
| U | Parking | Income | [手] | 两实例均空（U34 手填 0）|
| V | — | Notes | [手] | 如 "3% increase annually" |

合计行公式：
- `TOTALS-EXISTING TENANTS`：C `=SUM(C10:C32)-C35`（F2 扣减空置行；F1 为手填 17042），
  E `=SUM(E10:E32)`，G `=SUM(G10:G32)`，K `=SUM(K10:K32)`
- `VACANT SPACE`：F2 `C35=SUM(C30,C29,C28)`——**空置面积是点名求和**（把标为 Vacant 的租户行加总），不是总数倒减
- `TOTAL FOR PROPERTY`：C `=C34+C35`，K `=SUM(K34:K35)`

**血缘结论**：Rent Roll 全表除 K 列外都是公式驱动；K（包租年租）是第一个手工判断点。

## 2. Cash Flow（Historical / Pro Forma 双栏）

| 行 | 标签 | 历史栏 B | 预测栏 E | 血缘 |
|----|------|----------|----------|------|
| 9 | Base Rents | [链] `='Rent Roll'!G34` | F1 [手] 2,000,000；F2 [链] `='Rent Roll'!K34` | 历史恒链合同年租；预测 F1 手工、F2 链包租 |
| 10 | CAM Recovery | [手] | [手] | T 列有结构但实例未用 |
| 11 | Parking Income | [手] | [手] | U 列有结构但实例未用 |
| 12 | Other Income | [手] | [手] | F1 299,048（Tax Recovery）|
| 13 | Total Potential Income | [算] `=SUM(B9:B12)` | [算] `=SUM(E9:E12)` | |
| 14 | Less: Vacancy/Collection Loss | [手] | [手] | 两实例均为 0 |
| 15 | Total Effective Gross Income | [算] `=B13-B14` | [算] `=E13-E14` | EGI |
| 18-28 | Expenses（11 行 F1 / 8 行 F2） | [手] | [手]/[算] | **费用行名是实例自定义的**；F2 E23 `=0.03*E15`（管理费=3%×EGI）是该 deal 的手工公式 |
| 29/26 | Total Expenses | [算] `=SUM(B18:B28)` | [算] `=SUM(E18:E28)` | 行号因费用行数而异 |
| 31/28 | Net Operating Income | [算] `=B15-B29` | [算] `=E15-E29` | NOI |
| 33/30 | Tenant Improvements | [手] | [手] | F2 预测 60,000 |
| 34/31 | Capital Expenditures | [手] | [手] | F2 预测 32,800 |
| 35/32 | Leasing Commissions | [手] | [手] | F2 预测 7,200 |
| 36/33 | Cash Flow Avail for Debt Serv. | [算] `=B31-B33-B35-B34` | [算] `=E31-E33-E35-E34` | 注意顺序 B33(TI)→B35(LC)→B34(CapEx) |
| 38/35 | CAP Rate | [算] `=B31/C1` | [算] `=E31/C1` | C1：F1 手填购买价；F2 [链] `=Analysis!C13` |

每行另有 C/F 列（占收入/费用比）和 D/G 列（/购买价每 SF 口径，均除 `Analysis!$F$4`）。

**血缘结论**：Cash Flow 是全公式表，输入只有各收入行和费用行；B9 是唯一跨表链。

## 3. Analysis（手工断点 ★）

### 3.1 Source & Use（B12:C21）

| 格 | 标签 | 类型 | 公式 |
|----|------|------|------|
| C13 | Purchase price | [手] | |
| C14 | (+) Building Repairs | [手] | F2 500,000 |
| C15 | (+) Capital Cost Reserves | [手] | |
| C16 | (+) Lender Fees | [手] | |
| C17 | (+) Closing Costs | [手] | |
| C20 | Financed | [算] | `=-C23`（贷款取负）|
| C21 | Net liquidity needed | [算] | `=SUM(C13:C17)+C20`（总投入−贷款）|
| C23 | Loan bal. | [算] | `=C13*(1-C24)` |
| C24 | % Down | [手] | 0.30 |
| C25 | Rate | [手] | 0.06 / 0.04 |
| C26 | fully amortized or Interest | [手] | "IO"（文本，无公式分支——等额本息是我们的增强）|
| C27 | Annual payments | [算] | `=C23*C25`（IO 口径）|
| C22 | （空）| — | 标签缺失 |

### 3.2 回报（E13:F21）——核心手工断点

| 格 | 标签 | F1 | F2 | 类型 |
|----|------|----|----|------|
| F13 | Underwritten NOI | 1,000,000 [手] | 516,000 [手] | ★手工（≠Cash Flow NOI：F2 现金流 NOI 是 423,972）|
| F14 | Capitalization Rate | `=F13/C13` 2.38% | `=F13/C13` 5.73% | [算] |
| F15 | Projected NOI | 2,000,000 [手] | 616,000 [手] | ★手工（F2 现金流预测 NOI 是 476,819）|
| F16 | Market Cap rate | 0.04 [手] | 0.05 [手] | 输入 |
| F17 | Projected Resale Value | `=F15/F16` 50,000,000 | `=F15/F16` 12,320,000 | [算] |
| F18 | Acquisition fees | `=SUM(C14:C17)` 1,284,000 | `=SUM(C14:C17)` 975,000 | [算]（注意：是 C14:C17 四项之和）|
| F19 | Exit fees (4%) | `=F17*0.04` 2,000,000 | `=F17*0.04` 492,800 | [算]（4% 硬编码在公式里）|
| F20 | Net Gains before taxes | `=F17-(C13+F18+F19)` 4,716,000 | 同式 1,852,200 | [算] |
| F21 | Return on investment | `=F20/C21` 33.97% | `=F20/C21` 50.40% | [算] |

### 3.3 现金流块（E23:I28）

| 格 | 标签 | F1 | F2 | 类型 |
|----|------|----|----|------|
| F23/I23 | Projected Cash Flow | 2,299,048 / 1,299,048 [手] | 空 | ★手工（= Cash Flow EGI，用户手抄）|
| F24 | Projected NOI | 2,000,000 [手] | `=F15` [链] | F1 手工，F2 链 F15 |
| I24 | （在手 NOI）| 1,000,000 [手] | 423,000 [手] | ★手工 |
| F25/I25 | Rent Abatements/credits | 空 | 空 | [手]（两实例未用）|
| F26/I26 | Loan payments | `=C27` [链] | `=C27` [链] | 链贷款年还 |
| F27 | Net Cash flow（预测）| `=F24-F25-F26` 236,000 | `=F24-F25-F26` 364,000 | [算] |
| I27 | Net Cash flow（在手）| `=I24-I26` -764,000 | `=I24-I26` 171,000 | [算] |
| F28 | Cash on Cash（预测）| `=F27/C21` 1.70% | `=F27/C21` 9.90% | [算] |
| I28 | Cash on Cash（在手）| `=I27/C21` -5.50% | `=I27/C21` 4.65% | [算] |

**血缘总结论**：模板是"两段式"——Rent Roll→Cash Flow 全公式联动；
Cash Flow→Analysis 有**四个手工断点**（F13/F15/F23/F24/I23/I24），承保人把判断数字手填进 Analysis，
下游回报全由公式推导。F2 证明手工数可以与 Cash Flow 显著偏离（616K vs 476,819）。

## 4. DealDesk 引擎的对应实现

| 模板行为 | 引擎实现 |
|----------|----------|
| Rent Roll E→F→G→H→I 全公式 | `compute_rent_roll` 逐租户公式复刻；0 面积 `_div` 保护 |
| K 列手工/链式 | `underwritten_annual` 输入，空=回退合同年租（F2 模式）|
| L 列 `--` 保护 | `pct_of_total_uw` 为 0 时前端显示 `--` |
| M 列 F1/K10/C10 vs F2/MIN(I,J) | 引擎用 `uw_per_sf = underwritten/sf`（F1 口径）；J 列市场租金输入已预留 |
| 空置面积点名求和 | `vacant_sf` 独立输入（模板 C35 口径）|
| Cash Flow 双栏公式 | `compute_scenario` 历史/预测各一套；F2 的 8 费用行、`landscape` 已补 |
| F2 E23 管理费 3%×EGI | 该 deal 手工公式；引擎保持手工输入，血缘文档备注 |
| B9 链 Rent Roll | `base_rents` 默认取 `total_annual_lease`（历史），预测取 `total_annual_uw` |
| Analysis 四手工断点 | `underwritten_noi`/`projected_noi`/`inplace_noi_cf` 三输入，空=自动取现金流；`noi_sources` 标记血缘 |
| C26 "IO" 文本无公式分支 | 引擎增强：`amort_type` IO/AMORTIZING 真切换 |
| F19 4% 硬编码 | `exit_fee_pct` 可调，默认 0.04 |

## 5. 待验证 / 诚实标记

- `Cash Flow = NOI + Other Income`（F23 口径）是按 F1 反推的，F2 的 F23 为空无法交叉验证——标记为**单实例反推**。
- J 列（Est. Market Rent/SF）在两实例均空，MIN(I,J) 逻辑未被真实数据检验过。
- F2 的 I24=423,000 与 Cash Flow 历史 NOI 423,972 差 972，原因不明（手工抄写误差？）——标记为**未解释差异**。
- Q 列存在 `09/302028` 这类脏日期；R 列 F1 手填、F2 公式，口径不统一。
