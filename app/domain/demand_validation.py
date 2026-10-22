"""有效需求验证（W2，黄升《财富创造系统图》深研，2026-10-05 落地）。

DealDesk deal intake 的评估清单补充项：任何 deal 在进估值/结构设计前，
必须先独立验证"有效需求"三要素。缺≠市场，只有有效需求才是市场。

三项独立验证（每项 status = pass / fail / unknown）：
1. 支付能力 ability_to_pay：目标买家/租客付得起吗？
2. 支付意愿 willingness_to_pay：他们愿意为这个状态改变付钱吗？
3. 可触达性 reachability：我们找得到他们吗（渠道存在、可低成本触达）？

任一项 fail 或 unknown → intake 结果标"需求未验证"，不进估值结构设计，
先补验证证据。卖方 flyer 里的需求断言一律标"卖方口径、待独立验证"。
"""

from __future__ import annotations

# 三项验证的检查要点与证据要求（评估清单原文，进 intake 输出）
DEMAND_VALIDATION_ITEMS = [
    {
        "key": "ability_to_pay",
        "label": "支付能力",
        "question": "目标买家/租客付得起吗？",
        "checks": [
            "目标客群收入中位数 vs 目标月租/月供（租金收入比 ≤ 30% 参考线）",
            "该子市场空置率与去化周期（高空置 = 支付能力不足的信号）",
            "同类房源实际成交租金/售价（成交价，不是挂牌价）",
        ],
        "evidence": "Census 收入数据 / RentCast 租金 / MLS 成交记录；证据等级 [实证]/[公开]/[推断]/[未确认]",
    },
    {
        "key": "willingness_to_pay",
        "label": "支付意愿",
        "question": "他们愿意为这个状态改变付钱吗？",
        "checks": [
            "目标客群的真实痛点（状态差 Gap）是什么？房源解决的是真痛点还是伪痛点？",
            "同类产品的入住率/去化速度（愿意付钱的人正在用脚投票）",
            "卖方急售/低于市场类话术的反向验证：真有需求为什么卖不掉？",
        ],
        "evidence": "市场新闻/供需信号字段 / 去化数据 / 实地看房反馈；卖方口径一律标待验证",
    },
    {
        "key": "reachability",
        "label": "可触达性",
        "question": "我们找得到他们吗？",
        "checks": [
            "获客渠道是否真实存在（MLS/租赁平台/本地中介网络）",
            "触达成本是否在预算内（获客成本 vs 单套利润）",
            "该渠道的历史转化证据（同类房源在该渠道的真实成交）",
        ],
        "evidence": "渠道报价 / 历史成交记录；无证据 = unknown，不许按 pass 处理",
    },
]

STATUS_LABELS = {
    "pass": "通过",
    "fail": "未通过",
    "unknown": "待验证",
}

VALID_STATUSES = frozenset(STATUS_LABELS)


def evaluate(results: dict) -> dict:
    """评估有效需求三项验证结果，返回 intake  verdict。

    参数 results: {key: {"status": "pass"|"fail"|"unknown", "evidence_note": str}}
    未提供的 key 视为 unknown。
    任一项 fail 或 unknown -> 需求未验证，不进估值/结构设计。
    """
    items = []
    blockers = []
    for item in DEMAND_VALIDATION_ITEMS:
        key = item["key"]
        given = results.get(key, {}) if isinstance(results, dict) else {}
        status = given.get("status", "unknown")
        if status not in VALID_STATUSES:
            status = "unknown"
        note = given.get("evidence_note", "")
        items.append({"key": key, "label": item["label"], "status": status,
                      "status_label": STATUS_LABELS[status], "evidence_note": note})
        if status != "pass":
            blockers.append(key)
    verified = not blockers
    return {
        "verified": verified,
        "verdict": "需求已验证，可进估值/结构设计" if verified
                   else "需求未验证：先补验证证据，不进估值/结构设计",
        "blockers": blockers,
        "items": items,
    }


def demand_validation_block() -> dict:
    """返回 intake 输出里的有效需求验证清单块。

    初始状态三项均为 unknown（待人工/后续验证补证据），
    由评估人逐项打勾：pass / fail / unknown。
    """
    return {
        "title": "有效需求验证（缺≠市场）",
        "rule": "三项中任一 fail 或 unknown → 需求未验证，不进估值/结构设计",
        "items": [
            {**item, "status": "unknown", "status_label": STATUS_LABELS["unknown"],
             "evidence_note": ""}
            for item in DEMAND_VALIDATION_ITEMS
        ],
    }
