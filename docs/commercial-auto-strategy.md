# 商业核保全自动策略 v1.0

> 董事长要求：单开商业线，全程自动化；能对上的自动填，对不上的才手工补。不打补丁，一次想全。

## 一、目标

从首页粘贴房源链接/地址 → 自动搜集 → 自动识别住宅/商业 → 自动跳到对应核保页 → 字段自动填入 → 计算自动出结果。
用户只做两件事：① 粘贴链接点开始；② 补搜集里没有的信息。

## 二、入口（4 个，全打通）

| 入口 | 行为 |
|---|---|
| 首页搜集框 + 选"商业" | 搜集完自动跳商业核保页 |
| 首页搜集框 + LoopNet 链接 | 自动识别为商业（无视 track 选择），搜集完自动跳商业核保页 |
| 首页搜集框 + 选"住宅" | 走现有住宅流程，留在仪表盘 |
| 侧栏"商业核保" / 首页搜索输"商业" | 打开空白商业核保页，手动录入 |

## 三、自动路由规则

```
搜集完成
 ├─ track == commercial ─→ 建核保项目 → location.href 跳转 /uw-commercial.html?pid=X（同标签页，不被弹窗拦截）
 └─ track == residential ─→ 留在仪表盘（现有流程不变）
搜集失败 ─→ 留在首页显示错误 + 手动录入选项，不跳转，数据不丢
转入建项目失败 ─→ 留在首页显示搜集结果，数据不丢
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

映射不上的（租户、租金、费用明细、融资结构）留空，用户手工补。
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
