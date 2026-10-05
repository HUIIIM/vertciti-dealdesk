"""Confidence Score 0-100：证据质量分，不是推荐强度.

6 因子权重（专家规范 §2.11）：
  comps 数量与质量 25% / comps 时效 15% / 地理类型匹配 15% /
  NOI 数据质量 20% / cap 证据强度 15% / 三法收敛度 10%

公式公开，UI 必须切开"证据质量"与"推荐强度"两个概念。

输入：
  track: residential | commercial
  comps: 可比成交列表（每项可含 sale_date/price/sf/adjustment_pct/distance_miles/type_match）
  evidence: dict
    - comps_timeliness_months: 平均成交距今月数（缺省则按 sale_date 推算）
    - geo_match: 0-100 地理类型匹配（缺省按 distance/type 估算）
    - noi_evidence: 'audited_ttm' | 'seller_unverified' | 'proforma' | 'none'
    - cap_evidence: 'market_pull' | 'band_of_investment' | 'single_point' | 'none'
    - cap_pull_count: 市场提取成交宗数
    - methods: {'income': (lo, hi), 'sales': (lo, hi), 'cost': (lo, hi)} 或 None
输出：{'score', 'factors': {name: {'score','weight','weighted','note'}}, 'label', 'notes'}
"""

from __future__ import annotations

from datetime import date

WEIGHTS = {
    "comps_nq": 25,   # comps 数量与质量
    "timeliness": 15, # comps 时效
    "geo_match": 15,  # 地理类型匹配
    "noi_q": 20,      # NOI 数据质量
    "cap_e": 15,      # cap 证据强度
    "recon": 10,      # 三法收敛度
}

# P0-9：因子英文代码配中文名（前端直接展示中文，不再裸奔英文代码）
FACTOR_LABELS = {
    "comps_nq": "comps 数量与质量",
    "timeliness": "comps 时效（成交日期新旧）",
    "geo_match": "地理与物业类型匹配度",
    "noi_q": "NOI 数据质量（实数 vs 估算）",
    "cap_e": "cap rate 证据强度",
    "recon": "三法估值收敛度",
}

LABEL_LINE = "证据质量分（0-100），不是推荐强度：它回答'证据有多硬'，不回答'该不该买'。"


def _months_ago(sale_date) -> float | None:
    if not sale_date:
        return None
    try:
        d = date.fromisoformat(str(sale_date)[:10])
        today = date.today()
        return max(0.0, (today - d).days / 30.44)
    except Exception:
        return None


def _score_comps_nq(comps: list) -> tuple[float, str]:
    n = len(comps or [])
    if n >= 5:
        s = 100.0
        note = f"{n} 个高质量 comps"
    elif n >= 3:
        s = 70.0
        note = f"{n} 个 comps（3-4 个）"
    elif n >= 1:
        s = 35.0
        note = f"仅 {n} 个 comps，低于 3 个门槛"
    else:
        return 0.0, "无 comps"
    # gross adjustment 普遍 >25% 再扣
    big = sum(1 for c in comps if abs(float(c.get("adjustment_pct") or 0)) > 25)
    if big and big >= max(1, n // 2):
        s = max(0.0, s - 20.0)
        note += f"；{big} 个 gross adjustment > 25%，扣 20"
    return s, note


def _score_timeliness(comps: list, override: float | None) -> tuple[float, str]:
    if override is not None:
        avg_m = override
    else:
        ms = [m for m in (_months_ago(c.get("sale_date")) for c in (comps or [])) if m is not None]
        avg_m = sum(ms) / len(ms) if ms else None
    if avg_m is None:
        return 30.0, "成交日期缺失，按低分计"
    if avg_m <= 6:
        return 100.0, f"平均 {avg_m:.0f} 个月内成交"
    if avg_m <= 12:
        return 80.0, f"平均 {avg_m:.0f} 个月内成交"
    if avg_m <= 24:
        return 50.0, f"平均 {avg_m:.0f} 个月（>12 个月应做 time 调整）"
    return 20.0, f"平均 {avg_m:.0f} 个月（>24 个月不宜作主要 comp）"


def _score_geo(comps: list, override: float | None) -> tuple[float, str]:
    if override is not None:
        return max(0.0, min(100.0, float(override))), "用户/规则给定匹配度"
    if not comps:
        return 0.0, "无 comps"
    # 距离：市区 ≤1-3 英里满分；类型匹配加成
    ds = [float(c.get("distance_miles") or 0) for c in comps]
    avg_d = sum(ds) / len(ds) if ds else 99
    if avg_d <= 1:
        s = 100.0
    elif avg_d <= 3:
        s = 85.0
    elif avg_d <= 5:
        s = 65.0
    else:
        s = 40.0
    tm = [c.get("type_match") for c in comps]
    if tm and all(t is False for t in tm if t is not None):
        s = max(0.0, s - 25.0)
        return s, f"平均 {avg_d:.1f} 英里；资产类别不匹配扣 25"
    return s, f"平均 {avg_d:.1f} 英里"


def _score_noi_q(evidence: dict) -> tuple[float, str]:
    kind = (evidence or {}).get("noi_evidence", "none")
    table = {
        "audited_ttm": (100.0, "经审计 TTM（银行口径）"),
        "seller_unverified": (60.0, "卖方提供未验证"),
        # Phase 5 第五轮 B5（remote R5）：住宅租金是用户 Zone 7 自填的估算，
        # 从不是"卖方提供"——与 verdict 依据"租金为估算（待与租约/市场核验）"
        # 统一口径。分值与 seller_unverified 同档（60），只改口径表述。
        "user_estimate": (60.0, "租金为估算（待与租约/市场核验）"),
        "proforma": (40.0, "pro forma 预测（强制标注 PF）"),
        "none": (0.0, "无 NOI 数据"),
    }
    return table.get(kind, table["none"])


def _score_cap_e(evidence: dict) -> tuple[float, str]:
    kind = (evidence or {}).get("cap_evidence", "none")
    n = int((evidence or {}).get("cap_pull_count") or 0)
    if kind == "market_pull":
        if n >= 4:
            return 100.0, f"市场提取 ≥4 宗（{n} 宗）"
        return 70.0, f"市场提取仅 {n} 宗（<4）"
    if kind == "band_of_investment":
        return 60.0, "投资带法（无提取证据）"
    if kind == "single_point":
        return 50.0, "第三方单点 cap"
    return 0.0, "无 cap 证据"


def _score_recon(evidence: dict) -> tuple[float, str]:
    methods = (evidence or {}).get("methods")
    if not methods:
        return 40.0, "三法未独立成区间（单法）"
    centers = []
    for v in methods.values():
        if v and len(v) == 2 and v[0] and v[1]:
            centers.append((float(v[0]) + float(v[1])) / 2)
    if len(centers) < 2:
        return 40.0, "有效方法 < 2"
    lo, hi = min(centers), max(centers)
    mid = (lo + hi) / 2
    div = (hi - lo) / mid if mid else 1.0
    if div <= 0.10:
        return 100.0, f"三法收敛（分歧 {div * 100:.0f}%）"
    if div <= 0.25:
        return 70.0, f"三法基本收敛（分歧 {div * 100:.0f}%）"
    if div <= 0.40:
        return 40.0, f"三法分歧大（{div * 100:.0f}%）"
    return 15.0, f"三法严重分歧（{div * 100:.0f}%）"


def compute(track: str, comps: list | None = None, evidence: dict | None = None) -> dict:
    """公开公式：score = Σ(因子分 × 权重) / 100."""
    if track not in ("residential", "commercial"):
        raise ValueError(f"unknown track: {track}")
    ev = evidence or {}
    comps = comps or []
    raw = {
        "comps_nq": _score_comps_nq(comps),
        "timeliness": _score_timeliness(comps, ev.get("comps_timeliness_months")),
        "geo_match": _score_geo(comps, ev.get("geo_match")),
        "noi_q": _score_noi_q(ev),
        "cap_e": _score_cap_e(ev),
        "recon": _score_recon(ev),
    }
    factors = {}
    total = 0.0
    for name, w in WEIGHTS.items():
        s, note = raw[name]
        weighted = s * w / 100
        total += weighted
        factors[name] = {"score": round(s, 1), "weight": w,
                         "weighted": round(weighted, 1), "note": note,
                         "label": FACTOR_LABELS.get(name, name)}
    notes: list[str] = []
    # P1 缺口 5：无 cap 提取证据时 Confidence 天花板 60
    if ev.get("cap_evidence", "none") not in ("market_pull",) and track == "commercial":
        if total > 60:
            notes.append("无 cap 市场提取证据：Confidence 天花板 60（专家规范 P1-5）")
            total = 60.0
    score = round(total, 1)
    if score >= 80:
        label = "高置信（区间可窄）"
    elif score >= 60:
        label = "中等置信"
    elif score >= 40:
        label = "低置信（区间放宽、verdict 倾向 HOLD）"
    else:
        label = "熔断（<40：不给 verdict，转人工评估）"
    return {
        "score": score,
        "label": label,
        "factors": factors,
        "formula": "Σ(因子分 × 权重) / 100；权重：comps 数量质量 25 / 时效 15 / 地理类型匹配 15 / NOI 数据质量 20 / cap 证据强度 15 / 三法收敛度 10",
        "notes": notes,
        "disclaimer": LABEL_LINE,
    }
