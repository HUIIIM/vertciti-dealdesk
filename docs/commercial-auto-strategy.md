# 统一智能输入 v2.0（取代商业全自动策略 v1.0）

> 董事长要求：一个网站只有一个搜索框；粘贴商业链接自动进商业核保、住宅链接自动进住宅；不用手动选住宅/商业；只补搜集不到的字段。行业调研结论（NN/g + Arc/Notion/WhatsApp 模式）已融入。

## 一、目标

首页**唯一**智能输入框 → 粘贴即识别意图（chip 明示）→ Enter 确认 → 自动搜集 → 自动路由到对应核保页 → 字段自动填入。
用户只做两件事：① 粘贴/输入后按 Enter；② 补搜集里没有的信息。

## 二、意图检测（三层，确定性优先）

| 层级 | 输入 | 识别结果 | chip 展示 |
|---|---|---|---|
| T1 URL 主机白名单 | loopnet.com / crexi.com / costar.com | 商业房源 | 🏢 商业房源 · host → 将进入商业核保 |
| T1 URL 主机白名单 | zillow.com / redfin.com / realtor.com | 住宅房源 | 🏠 住宅房源 · host → 将进入住宅核保 |
| T1 | 未知主机 URL | 链接（未识别平台） | 🔗 未识别出房源平台 → 按地址搜集 |
| T2 双语命令 | 商业/商业核保/商用/commercial | 命令 | ⚡ 进入商业核保工作台 |
| T2 双语命令 | 住宅/住宅核保/residential | 命令 | ⚡ 住宅核保工作台即本页 |
| T3 | 纯地址 | 地址 | 📍 将按地址搜集（住宅搜集/商业搜集双按钮） |

反模式（已删除）：侧栏第二个搜索框；输入框旁的住宅/商业下拉。IME 拼写中不检测不提交（isComposing + keyCode 229）；全角→半角归一化；Cmd+K 聚焦同一输入框。

## 三、路由规则

```
粘贴/输入 → chip 明示意图（粘贴永不自动执行）
Enter/点击确认
 ├─ 商业房源 → 搜集 → 自动建商业核保项目 → 同标签页跳 /uw-commercial.html?pid=X
 ├─ 住宅房源/地址 → 搜集 → 留在仪表盘（现有流程）
 ├─ 命令"商业" → 直接跳空白商业核保页
 └─ 搜集失败/转入失败 → 留在首页，数据不丢，显示错误+手动选项
```

## 四、字段自动映射（搜集 → 核保输入）

| 搜集字段 | 核保输入 | 说明 |
|---|---|---|
| address | property.name / address / city / state / zip | parsed 拆分 |
| asking_price | analysis.purchase_price | |
| building_sf | property.net_rentable_sf | |
| lot_sf | property.land_acres | ÷43560 |
| year_built | property.year_built | |
| taxes_annual | historical.property_tax + proforma.property_tax | 双场景同步 |

映射不上的（租户、租金、费用明细、融资结构）留空，用户手工补；绝不编数。
所有自动填入的字段用户可改，改一个数全页自动重算。

## 五、商业核保页行为

- 默认空白打开：用户从头输入，所见即所得
- `?pid=` 打开：搜集字段已填入
- "载入模板示例"：仅手动点按钮，不再自动加载
- API 挂掉：按钮/输入/本地计算全部可用（init 先绑按钮，API 后加载且 try/catch）

## 六、计算引擎（已有）

Rent Roll → Cash Flow → Analysis 全链路自动：
合同租金/包销租金、历史与 pro forma NOI、TI/CapEx/租赁佣金、Source & Use、
IO/摊销贷款、cap rate/转售/ROI/CoC、空置/DSCR/保本入住率、每 SF 指标、
持有期/IRR/equity multiple。退出费锁定 4%。

## 七、不做的

- 不在搜集页加跳转按钮（董事长明确否决）
- 不自动猜租户租金等搜集不到的数据（绝不编数）
- 不改住宅流程

## 八、验证门禁

- 真浏览器端到端：选商业→粘贴→搜集→自动跳转→字段填入，全 PASS 才发布
- JS 零报错；API 挂掉时按钮可用；默认空白
