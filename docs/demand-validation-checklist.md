# 有效需求验证评估清单（W2，deal intake 前置）

> 模块：`app/demand_validation.py`（`demand_validation_block()` / `evaluate(results)`）
> 规则：任何 deal 在进估值/结构设计前，必须先独立验证有效需求三要素。缺≠市场，只有有效需求才是市场。

## 三项独立验证（每项 status = pass / fail / unknown）

| # | 项 | 问题 | 检查要点 | 证据要求 |
|---|---|---|---|---|
| 1 | 支付能力 ability_to_pay | 目标买家/租客付得起吗？ | 目标客群收入中位数 vs 目标月租/月供（租金收入比 ≤ 30% 参考线）；该子市场空置率与去化周期；同类房源实际成交租金/售价（成交价，非挂牌价） | Census 收入数据 / RentCast 租金 / MLS 成交记录；证据等级 [实证]/[公开]/[推断]/[未确认] |
| 2 | 支付意愿 willingness_to_pay | 他们愿意为这个状态改变付钱吗？ | 目标客群真实痛点（状态差 Gap）；同类产品入住率/去化速度；卖方急售话术反向验证（真有需求为什么卖不掉？） | 市场新闻/供需信号 / 去化数据 / 实地看房反馈；卖方口径一律标"待独立验证" |
| 3 | 可触达性 reachability | 我们找得到他们吗？ | 获客渠道真实存在（MLS/租赁平台/本地中介网络）；触达成本在预算内（获客成本 vs 单套利润）；该渠道历史转化证据 | 渠道报价 / 历史成交记录；无证据 = unknown，不许按 pass 处理 |

## 判定规则

- 三项全 pass → `verified=true`："需求已验证，可进估值/结构设计"
- 任一项 fail 或 unknown → `verified=false`："需求未验证：先补验证证据，不进估值/结构设计"
- 非法 status 值按 unknown 处理（fail-closed）
- 卖方 flyer 里的需求断言一律标"卖方口径、待独立验证"，不许直接采信（deal intake 铁律）

## intake 接入方式（给 DealDesk 组）

```python
from app.demand_validation import evaluate
result = evaluate({
    "ability_to_pay": {"status": "pass", "evidence_note": "..."},
    "willingness_to_pay": {"status": "unknown", "evidence_note": ""},
    "reachability": {"status": "pass", "evidence_note": "..."},
})
# result["verified"] 为 False 时，intake 结果标"需求未验证"，阻断估值/结构设计
```

终验（intake 真实接入＋下个 deal 走完）由 DealDesk 组执行，本组不代终验。
