"""Condition Adjustment 五档规则（专家规范 §2.10）.

分档（有效楼龄锚定）：Excellent / Good / Average / Fair / Poor
系数量级（经验区间，需本地校准，调整时必须披露依据）：
  相邻一档：3-8%（默认取中点 5.5%）
  跨两档：8-15%（默认取中点 11.5%）
  跨两档以上：按跨两档上限取，并注记"建议分拆依据"
红线：调整依据必填（一句话，如"基于 $45/SF 翻新成本 × 12,000 SF 待翻新面积"）；
      无依据宁可不做，把不确定性放进区间宽度。

语义：把 comp 的价格调整到与标的同成色。
  subject 更好 → comp 价格上调（comp 偏破，加钱补齐）；
  comp 更好 → comp 价格下调。
"""

from __future__ import annotations

TIERS = ("Excellent", "Good", "Average", "Fair", "Poor")

BAND_ADJACENT = (0.03, 0.08)  # 相邻档
BAND_TWO = (0.08, 0.15)       # 跨两档


def tier_index(tier: str) -> int:
    t = str(tier or "").strip().capitalize()
    if t not in TIERS:
        raise ValueError(f"unknown condition tier: {tier!r}（允许 {TIERS}）")
    return TIERS.index(t)


def adjust(subject_tier: str, comp_tier: str, comp_price: float,
           basis: str, rate: float | None = None) -> dict:
    """返回调整结果. rate=None 时取区间中点（公开默认）."""
    si = tier_index(subject_tier)
    ci = tier_index(comp_tier)
    steps = abs(si - ci)
    if steps == 0:
        return {
            "applied": False,
            "subject_tier": TIERS[si],
            "comp_tier": TIERS[ci],
            "steps": 0,
            "rate": 0.0,
            "adjustment": 0.0,
            "adjusted_price": float(comp_price or 0),
            "reason": "同档成色，无需调整",
        }
    if not (basis or "").strip():
        return {
            "applied": False,
            "subject_tier": TIERS[si],
            "comp_tier": TIERS[ci],
            "steps": steps,
            "rate": 0.0,
            "adjustment": 0.0,
            "adjusted_price": float(comp_price or 0),
            "reason": "无调整依据：宁可不做，把不确定性放进区间宽度（专家规范 §2.10 红线）",
        }
    if steps == 1:
        band = BAND_ADJACENT
        band_note = "相邻一档 3-8%"
    elif steps == 2:
        band = BAND_TWO
        band_note = "跨两档 8-15%"
    else:
        band = BAND_TWO
        band_note = f"跨 {steps} 档：按跨两档上限区间取，建议分拆依据"
    r = band[0] + (band[1] - band[0]) / 2 if rate is None else float(rate)
    # 方向：comp 比 subject 差（ci > si）→ comp 价格上调为正
    direction = 1 if ci > si else -1
    amount = direction * r * float(comp_price or 0)
    return {
        "applied": True,
        "subject_tier": TIERS[si],
        "comp_tier": TIERS[ci],
        "steps": steps,
        "band": band_note,
        "rate": round(r, 4),
        "direction": "+" if direction > 0 else "-",
        "adjustment": round(amount, 2),
        "adjusted_price": round(float(comp_price or 0) + amount, 2),
        "basis": (basis or "").strip(),
        "reason": (f"{TIERS[ci]}→{TIERS[si]} 调整 {r * 100:.1f}%（{band_note}），"
                   f"金额 ${amount:+,.0f}"),
    }
