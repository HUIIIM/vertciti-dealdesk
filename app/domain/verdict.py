"""Verdict 三档引擎（纯函数，规则公开可审计）.

住宅：值得买 / 再看看 / 别碰
商业：BUY / HOLD / PASS

四规则（spec v2 Zone 1 + 专家规范 §5）：
  R1 缺口降级：关键数据缺口（rent roll / T-12 / 真实贷款条件 / 费用明细）未补时
      自动保守降一档（BUY→HOLD / 值得买→再看看），写明原因
      （展示文案"缺关键数据，结论降一档"，Phase 5 第三轮 D12 去黑话）。
  R2 熔断：Confidence < 40 → 不给三档，给"数据不足，需人工评估"。
  R3 仲裁：要价 > 估值区间上界 → 最高 HOLD / 再看看；
      三法分歧 > 25% 上限 HOLD / 再看看、> 40% 转人工复核（需人工复核）。
  R4 用途限制文案（商业）固定小字。

本模块只做映射与规则叠加，不改任何 score/valuate 引擎逻辑。
"""

from __future__ import annotations

RES_TIERS = ("值得买", "再看看", "别碰")
COM_TIERS = ("BUY", "HOLD", "PASS")

# B1-06：唯一 verdict 口径表（前后端同源，单点定义）。
# code 为机读 canonical；zh 为中文展示；cls 为前端样式类。
# 全站统一双语渲染："值得买 · BUY"。旧 divergent 口径（住宅纯中文／商业纯英文）作废。
VERDICT_TAXONOMY = (
    {"code": "BUY", "zh": "值得买", "cls": "v-buy"},
    {"code": "HOLD", "zh": "再看看", "cls": "v-hold"},
    {"code": "PASS", "zh": "别碰", "cls": "v-pass"},
    {"code": "VETO", "zh": "一票否决", "cls": "v-veto"},
)
# 后端各 track 的词（含历史词"否决"）→ canonical code
VERDICT_WORD2CODE = {
    "值得买": "BUY", "再看看": "HOLD", "别碰": "PASS",
    "否决": "VETO", "一票否决": "VETO",
    "BUY": "BUY", "HOLD": "HOLD", "PASS": "PASS", "VETO": "VETO",
}


def verdict_display(word: str) -> str:
    """B1-06：统一双语渲染。verdict_display("值得买") → "值得买 · BUY" """
    code = VERDICT_WORD2CODE.get(word, word)
    zh = next((t["zh"] for t in VERDICT_TAXONOMY if t["code"] == code), word)
    return f"{zh} · {code}" if code in ("BUY", "HOLD", "PASS", "VETO") else word

RES_USAGE = "筛选辅助工具，不构成投资建议。"
COM_USAGE = ("投资筛选用，非 USPAP 合规评估报告，不能用于贷款/诉讼；"
             "未实地勘察、未审阅租约原件。")

# EN 界面（2026-10-16，PH launch 阻塞项）：lang="en" 时叙事文案走英文模板；
# 默认 zh 行为逐字不变（零回归）。verdict 档位词本身不动（B1-06 双语渲染在前端）。
RES_USAGE_EN = "Screening aid only — not investment advice."
COM_USAGE_EN = ("For investment screening only; not a USPAP-compliant appraisal, "
                "not for lending or litigation use; no site inspection performed; "
                "original leases not reviewed.")


def _usage(track: str, lang: str) -> str:
    if lang == "en":
        return RES_USAGE_EN if track == "residential" else COM_USAGE_EN
    return RES_USAGE if track == "residential" else COM_USAGE


def _tiers(track: str):
    if track == "residential":
        return RES_TIERS
    if track == "commercial":
        return COM_TIERS
    raise ValueError(f"unknown track: {track}")


def _downgrade(tier: str, tiers) -> str:
    """保守降一档：值得买→再看看→别碰；BUY→HOLD→PASS."""
    i = tiers.index(tier)
    return tiers[min(i + 1, len(tiers) - 1)]


def _cap(tier: str, max_tier: str, tiers) -> str:
    """上限封顶：结论不能比 max_tier 更乐观."""
    if tiers.index(tier) < tiers.index(max_tier):
        return max_tier
    return tier


def _price_arb_reason(ev: dict, ask: float, vhi: float, lang: str = "zh") -> str:
    """价格仲裁理由文案（Phase 5 第三轮 item 7/R4：术语统一）.

    单点估值（value_lo == value_hi）时只说"单点"，不许说"估值区间上界".
    """
    vlo = (ev or {}).get("value_lo")
    if lang == "en":
        if vlo and vlo == vhi:
            return f"Price check: asking ${ask:,.0f} is above the valuation ${vhi:,.0f} (single point)"
        return f"Price check: asking ${ask:,.0f} is above the top of the valuation range ${vhi:,.0f}"
    if vlo and vlo == vhi:
        return f"价格仲裁：要价 ${ask:,.0f} 高于估值 ${vhi:,.0f}（单点）"
    return f"价格仲裁：要价 ${ask:,.0f} 高于估值区间上界 ${vhi:,.0f}"


def _base_from_score(track: str, score: dict, lang: str = "zh") -> tuple[str, list[str]]:
    """score(grade/total/vetoes) → 基础档位.

    一票否决（vetoes 非空）→ 最保守档；否则按 total 分数映射
    （与 buyer-box A/B/C/<50 口径同向：>=80 / 65-79 / 50-64 / <50）。
    """
    tiers = _tiers(track)
    vetoes = (score or {}).get("vetoes") or []
    reasons: list[str] = []
    if vetoes:
        if lang == "en":
            reasons.append("Veto: " + "; ".join(
                v.get("message", v.get("code", "?")) for v in vetoes[:2]))
        else:
            reasons.append("一票否决：" + "；".join(
                v.get("message", v.get("code", "?")) for v in vetoes[:2]))
        return tiers[-1], reasons
    total = (score or {}).get("total")
    if total is None:
        reasons.append("No deal score — conservative treatment" if lang == "en"
                       else "缺 deal 评分，保守处理")
        return tiers[-1], reasons
    if total >= 80:
        return tiers[0], reasons
    if total >= 65:
        return tiers[1], reasons
    if total >= 50:
        # 50-64：偏保守的一档（对应 buyer-box C 档，仍属可谈）
        return tiers[1], reasons
    reasons.append(f"Deal score {total:.0f} < 50 (PASS line)" if lang == "en"
                   else f"deal 评分 {total:.0f} < 50（别碰线）")
    return tiers[-1], reasons


def _one_liner_res(score: dict, verdict: str, lang: str = "zh") -> str:
    """住宅一句话原因模板（spec §7 文案）。"""
    m = (score or {}).get("metrics") or {}
    cf = m.get("cash_flow_monthly")
    dscr = m.get("dscr")
    if verdict == "值得买" and cf is not None:
        return (f"Monthly cash flow ${cf:,.0f} — rent covers the mortgage, with room to spare"
                if lang == "en" else f"月现金流 ${cf:,.0f}，租金能覆盖月供还有剩")
    if verdict == "别碰":
        # Phase 5 第三轮 A1（remote R1）：住宅无租金数据时 DSCR 回退为 0.0，
        # 不许印"DSCR 只有 0.00"——0.00 是缺数不是实数
        if dscr is None or dscr == 0:
            return ("No rent data — DSCR cannot be underwritten (data pending)"
                    if lang == "en" else "缺租金数据，DSCR 无法核保（待补数据）")
        if dscr < 1.0:
            return (f"DSCR is only {dscr:.2f} — bank financing is unlikely"
                    if lang == "en" else f"DSCR 只有 {dscr:.2f}，银行大概率不批贷")
        return "Hard veto — see the veto items" if lang == "en" else "硬伤否决：见一票否决项"
    # 再看看：优先讲价格，其次讲现金流
    price = (score or {}).get("price")
    comp_med = (score or {}).get("comp_median_price")
    if price and comp_med and comp_med > 0:
        over = (price - comp_med) / comp_med
        if over > 0.03:
            return (f"Priced {over * 100:.0f}% above the comps median — not worth it unless the price comes down"
                    if lang == "en" else f"价格比 comps 中位高 {over * 100:.0f}%，除非砍价否则不划算")
    if cf is not None:
        return (f"Monthly cash flow ${cf:,.0f}, but gaps/risks still need verification"
                if lang == "en" else f"月现金流 ${cf:,.0f}，但有缺口/风险待核验")
    return ("Gaps in the data or terms — close them before talking offer"
            if lang == "en" else "数据或条件有缺口，先补齐再谈出价")


def _one_liner_com(score: dict, verdict: str, reasons: list[str],
                   evidence: dict | None = None, lang: str = "zh") -> str:
    """商业一句话原因：风险—缓释对子（专家规范 §3.2）.

    P0-4：DSCR 数字必须与 KPI 卡（compute-plus trailing DSCR）为同一个数；
    前端经 evidence.dscr_display 传入，缺失时回退 score 口径。
    """
    m = (score or {}).get("metrics") or {}
    ev = evidence or {}
    dscr = ev.get("dscr_display")
    if dscr is None:
        dscr = m.get("dscr")
    if verdict == "BUY":
        return ("Price, cash flow and leverage all check out — proceed to due diligence"
                if lang == "en" else "价格/现金流/杠杆三项达标，可推进尽调")
    # Phase 5 第三轮 A1：无 rent roll 时 DSCR 根本没数——score 口径回退的 0.0
    # 不许套"DSCR 0.00 < 1.0（生死线）"模板
    if not ev.get("has_rent_roll") and (dscr is None or dscr == 0):
        return ("No rent roll — DSCR cannot be underwritten (data pending)"
                if lang == "en" else "无 rent roll，DSCR 无法核保（待接数据）")
    if verdict == "PASS":
        if dscr is not None and dscr < 1.0:
            return (f"DSCR {dscr:.2f} < 1.0 (the survival line) — you would be feeding this property"
                    if lang == "en" else f"DSCR {dscr:.2f} < 1.0（生死线），贴钱持有")
        return ("Risk is beyond the acceptable range — walk away"
                if lang == "en" else "风险超出可接受范围，建议放弃")
    for r in reasons:
        if lang == "en":
            if "downgraded" in r:
                return "Unverified leases/expenses — the verdict was conservatively downgraded"
            if "Asking price above the valuation range" in r:
                return "Asking price is above the valuation range — negotiate price first"
            if "Divergence check" in r:
                return "The valuation approaches diverge too much — manual review needed"
        elif "降一档" in r or "降级" in r:
            return "因租约/费用未核验，结论已保守降级"
        elif "价格高于估值区间" in r:
            return "价格高于估值区间，先谈价"
        elif "分歧" in r:
            return "三法估值分歧过大，需人工复核"
    if dscr is not None and dscr < 1.2:
        return (f"DSCR {dscr:.2f} is below the bank floor of 1.20 — conditional watch"
                if lang == "en" else f"DSCR {dscr:.2f} 低于银行底线 1.20，观察条件")
    return ("Promising but conditional — close the gaps before talking offer"
            if lang == "en" else "有看点但有条件，先补缺口再谈出价")


def residential_verdict(score: dict, confidence: int, evidence: dict | None = None, lang: str = "zh") -> dict:
    ev = evidence or {}
    base, reasons = _base_from_score("residential", score, lang)
    tier = base
    # Phase 5 第五轮 D11（xiaobai）：comps 拉取抖动致 verdict 在"数据不足（熔断）"↔
    # "别碰"之间翻转——拉取失败时必须显式标注，不许静默熔断。verdict 词本身不动（红线）。
    _pull_fail = ((["Data pull failed — the verdict may change after a retry"] if lang == "en"
                   else ["数据拉取失败，重试后结论可能变化"])
                  if ev.get("comps_pull_failed") else [])
    # R2 熔断
    if confidence is not None and confidence < 40:
        return {
            "track": "residential",
            "verdict": "Insufficient data — manual review required" if lang == "en" else "数据不足，需人工评估",
            "circuit_broken": True,
            "base": base,
            "confidence": confidence,
            "reasons": reasons + _pull_fail + [
                f"Circuit breaker: Confidence {confidence}/100 < 40" if lang == "en"
                else f"置信度熔断：Confidence {confidence}/100 < 40"],
            "one_liner": "Too little evidence for a reliable verdict — add comps, price and rent data first" if lang == "en" else "证据太少，给不出靠谱结论——先补 comps/价格/租金数据",
            "usage": _usage("residential", lang),
        }
    reasons_out = list(reasons) + _pull_fail
    # R1 P0 缺口降级 → 人话（Phase 5 第三轮 D12）：小白看不懂"P0"，
    # 展示文案为"缺关键数据，结论降一档"
    p0 = ev.get("p0_gaps") or []
    if p0:
        tier = _downgrade(tier, RES_TIERS)
        reasons_out.append(("Key data missing — verdict downgraded one notch: " + ", ".join(p0[:3]))
                           if lang == "en"
                           else ("缺关键数据，结论降一档：" + "、".join(p0[:3])))
    # R3 仲裁：价格（Phase 5 第三轮 item 7：单点估值时不许说"区间上界"）
    ask = ev.get("ask_price")
    vhi = ev.get("value_hi")
    if ask and vhi and ask > vhi:
        tier = _cap(tier, "再看看", RES_TIERS)
        reasons_out.append(_price_arb_reason(ev, ask, vhi, lang))
    # R3 仲裁：分歧
    div = ev.get("divergence_pct")
    if div is not None:
        if div > 40:
            return {
                "track": "residential",
                "verdict": "Manual review required" if lang == "en" else "需人工复核",
                "circuit_broken": True,
                "base": base,
                "confidence": confidence,
                "reasons": reasons_out + [
                    f"Divergence check: {div:.0f}% divergence (> 40%) — routed to manual review" if lang == "en"
                    else f"三法分歧仲裁：分歧 {div:.0f}% > 40%，转人工"],
                "one_liner": "The valuation approaches disagree — no machine verdict" if lang == "en" else "各路估值打架，机器不给结论",
                "usage": _usage("residential", lang),
            }
        if div > 25:
            tier = _cap(tier, "再看看", RES_TIERS)
            reasons_out.append(f"Divergence check: {div:.0f}% divergence (> 25%) — capped at HOLD" if lang == "en"
                               else f"三法分歧仲裁：分歧 {div:.0f}% > 25%，上限再看看")
    return {
        "track": "residential",
        "verdict": tier,
        "circuit_broken": False,
        "base": base,
        "confidence": confidence,
        "reasons": reasons_out,
        "one_liner": _one_liner_res(score, tier, lang),
        "usage": _usage("residential", lang),
    }


def commercial_verdict(score: dict, confidence: int, evidence: dict | None = None, lang: str = "zh") -> dict:
    ev = evidence or {}
    base, reasons = _base_from_score("commercial", score, lang)
    tier = base
    # Phase 5 第五轮 D11（xiaobai）：同 residential_verdict——拉取失败显式标注
    _pull_fail = ((["Data pull failed — the verdict may change after a retry"] if lang == "en"
                   else ["数据拉取失败，重试后结论可能变化"])
                  if ev.get("comps_pull_failed") else [])
    if confidence is not None and confidence < 40:
        return {
            "track": "commercial",
            "verdict": "Insufficient data — manual review required" if lang == "en" else "数据不足，需人工评估",
            "circuit_broken": True,
            "base": base,
            "confidence": confidence,
            "reasons": reasons + _pull_fail + [
                f"Circuit breaker: Confidence {confidence}/100 < 40" if lang == "en"
                else f"置信度熔断：Confidence {confidence}/100 < 40"],
            "one_liner": "Too little evidence for a reliable verdict — add the rent roll, T-12 and loan terms first" if lang == "en" else "证据太少，给不出靠谱结论——先补 rent roll/T-12/贷款条件",
            "usage": _usage("commercial", lang),
        }
    reasons_out = list(reasons) + _pull_fail
    # R1 P0 缺口降级 → 人话（Phase 5 第三轮 D12）：小白看不懂"P0"，
    # 展示文案为"缺关键数据，结论降一档"
    p0 = ev.get("p0_gaps") or []
    if p0:
        tier = _downgrade(tier, COM_TIERS)
        reasons_out.append(("Key data missing — verdict downgraded one notch: " + ", ".join(p0[:3]))
                           if lang == "en"
                           else ("缺关键数据，结论降一档：" + "、".join(p0[:3])))
    ask = ev.get("ask_price")
    vhi = ev.get("value_hi")
    if ask and vhi and ask > vhi:
        tier = _cap(tier, "HOLD", COM_TIERS)
        reasons_out.append(_price_arb_reason(ev, ask, vhi, lang))
    div = ev.get("divergence_pct")
    if div is not None:
        if div > 40:
            return {
                "track": "commercial",
                "verdict": "Manual review required" if lang == "en" else "需人工复核",
                "circuit_broken": True,
                "base": base,
                "confidence": confidence,
                "reasons": reasons_out + [
                    f"Divergence check: {div:.0f}% divergence (> 40%) — routed to manual review" if lang == "en"
                    else f"三法分歧仲裁：分歧 {div:.0f}% > 40%，转人工复核"],
                "one_liner": "Income and Sales approaches diverge too much — no machine verdict" if lang == "en" else "Income 与 Sales 法分歧过大，机器不给结论",
                "usage": _usage("commercial", lang),
            }
        if div > 25:
            tier = _cap(tier, "HOLD", COM_TIERS)
            reasons_out.append(f"Divergence check: {div:.0f}% divergence (> 25%) — capped at HOLD" if lang == "en"
                               else f"三法分歧仲裁：分歧 {div:.0f}% > 25%，上限 HOLD")
    return {
        "track": "commercial",
        "verdict": tier,
        "circuit_broken": False,
        "base": base,
        "confidence": confidence,
        "reasons": reasons_out,
        "one_liner": _one_liner_com(score, tier, reasons_out, ev, lang),
        "usage": _usage("commercial", lang),
    }


def verdict(track: str, score: dict, confidence: int, evidence: dict | None = None,
            lang: str = "zh") -> dict:
    """统一入口."""
    if track == "residential":
        return residential_verdict(score, confidence, evidence, lang)
    if track == "commercial":
        return commercial_verdict(score, confidence, evidence, lang)
    raise ValueError(f"unknown track: {track}")
