"""反方备忘录（vertciti 独有）：上投委会之前，系统先写“这笔交易最可能怎么失败”。

别人的 AI 写的是“为什么该买”；这里反着来，而且**不经 AI**：每条论点只由确定性规则从系统已算出的结果拼成
（淘汰条件余量、红队摆动、悲观情景、要价与可出价的差、核对缺口、盈亏平衡出租率、退出与买入 cap），
每个数字都能回到来源——可复现、不会编。数据不足的论点不写，绝不拿“0”凑。
"""
from __future__ import annotations

from typing import Any

from app.domain.v2.model import METRICS

JSON = dict[str, Any]
NEAR_MISS = 0.10          # 离淘汰线 10% 以内算“擦边”
BREAKEVEN_HIGH = 85.0     # 盈亏平衡出租率 ≥ 85%：容错极低
BREAKEVEN_MED = 75.0
DSCR_THIN = 1.35          # 贷款常见门槛 1.25×，余量 < 0.10 算薄


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _pt(key: str, severity: str, title: str, text: str, tab: str) -> JSON:
    return {"key": key, "severity": severity, "title": title, "text": text, "tab": tab}


def _kill_points(kill: JSON) -> list[JSON]:
    out = []
    for k in kill.get("items", []):
        v, th = _num(k.get("value")), float(k["threshold"])
        unit = METRICS[k["metric"]].unit
        f = (lambda x: f"{x:.2f}×") if unit == "x" else (lambda x: f"{x:.2f}%")
        if k["state"] == "triggered" and v is not None:
            out.append(_pt(f"kill:{k['metric']}", "high", "已触发淘汰条件",
                           f"{k['text']}：当前 {f(v)}，越线 {f(abs(v - th))}。", "overview"))
        elif k["state"] == "ok" and v is not None and th != 0 and abs(v - th) / abs(th) <= NEAR_MISS:
            out.append(_pt(f"near:{k['metric']}", "medium", "离淘汰线很近",
                           f"{k['text']}：当前 {f(v)}，只比底线多 {f(abs(v - th))}，一个假设稍差就会触发。", "risk"))
    return out


def _price_point(mb: JSON | None) -> list[JSON]:
    if not mb:
        return []
    ask, best, bind = _num(mb.get("asking")), _num(mb.get("max_bid")), mb.get("binding") or {}
    if best is None and bind:
        why = f"「{bind.get('label', '')}」{bind.get('reason', '')}。"
        return [_pt("price:none", "high", "任何价格都不满足", why, "risk")]
    if ask and best is not None and best < ask:
        return [_pt("price:gap", "high", "要价高过可出价",
                    f"要价 ${ask:,.0f} 比所有约束允许的最高价 ${best:,.0f} 高 {(ask / best - 1) * 100:.1f}%；"
                    f"卡住价格的是「{bind.get('label', '')}」。按要价成交等于放弃这条底线。", "risk")]
    return []


def _swing_point(rt: JSON | None) -> list[JSON]:
    top = rt.get("top") if rt else None
    if not rt or not top:
        return []
    r = top[0]
    lo, hi = sorted([r["minus"]["value"], r["plus"]["value"]])
    return [_pt("swing:top", "high" if r["material"] else "medium", "结论押在一个假设上",
                f"「{r['label']}」只要错 {rt['shock_pct']:g}%，{rt['metric_label']}就落在 {lo:.2f}%–{hi:.2f}% 之间"
                f"（摆动 {r['swing_bps']:.0f} bp）。这个数从哪来、谁核过，决定了这笔交易。", "risk")]


def _downside_point(sc: JSON | None) -> list[JSON]:
    if not sc:
        return []
    rows = [r for r in sc.get("scenarios", []) if _num(r.get("primary")) is not None]
    if not rows:
        return []
    worst = min(rows, key=lambda r: r["primary"])
    lp = _num(sc.get("loss_probability_pct"))
    if worst["primary"] < 0 or worst.get("loss"):
        tail = f"，按当前情景概率算，亏损概率 {lp:.0f}%" if lp is not None else ""
        return [_pt("downside", "high", "悲观情景是亏的",
                    f"「{worst['name']}」（概率 {worst['probability']:.0f}%）"
                    f"{sc['metric_label']} {worst['primary']:.2f}%{tail}。", "risk")]
    return []


def _verify_points(kn: JSON | None, queue: JSON | None, stale: int) -> list[JSON]:
    out = []
    if kn and kn.get("total") and kn["done"] < kn["total"]:
        first = ((queue or {}).get("items") or [None])[0]
        hint = (f"；最该先核：「{first['label']}」（{first['swing_bps']:.0f} bp）"
                if first and first.get("swing_bps") else "")
        out.append(_pt("verify:gap", "high" if kn["done"] == 0 else "medium", "关键数字没核完",
                       f"{kn['total']} 个关键数字只复核了 {kn['done']} 个{hint}。没核过的数不该拿去上会。", "files"))
    if stale:
        out.append(_pt("verify:stale", "medium", "证据过期", f"{stale} 条证据超过 30 天，市场数据可能已变。", "files"))
    return out


def _structure_points(track: str, inputs: JSON, metrics: JSON) -> list[JSON]:
    out = []
    be = _num(metrics.get("breakeven_occupancy_pct"))
    if track == "commercial" and be is not None and be >= BREAKEVEN_MED:
        out.append(_pt("breakeven", "high" if be >= BREAKEVEN_HIGH else "medium", "容错空间小",
                       f"出租率跌破 {be:.1f}% 就入不敷出——空置只要超过 {100 - be:.1f}% 就开始亏现金。", "model"))
    a = inputs.get("analysis") or {}
    exit_cap, entry = _num(a.get("exit_cap_rate")), _num(metrics.get("cap_rate_pct"))
    if exit_cap is not None and entry is not None and exit_cap < entry:
        out.append(_pt("cap:compress", "medium", "回报靠估值上升",
                       f"退出 Cap Rate {exit_cap:.2f}% 低于买入 {entry:.2f}%："
                       "一部分回报来自假设将来有人出更高的价。", "model"))
    dscr = _num(metrics.get("dscr"))
    if dscr is not None and 1.0 <= dscr < DSCR_THIN:
        out.append(_pt("dscr:thin", "medium", "偿债余量薄",
                       f"DSCR {dscr:.2f}×，只比贷款常见门槛 1.25× 高 {max(dscr - 1.25, 0):.2f}，"
                       "NOI 小幅下滑就可能触发贷款条款。", "model"))
    return out


def _headline(points: list[JSON]) -> str | None:
    """一句话摘要（不重复清单原文）：几条高危、几条中危，上会前至少先解决哪几件。"""
    if not points:
        return None
    high = [p for p in points if p["severity"] == "high"]
    head = f"{len(high)} 条高危、{len(points) - len(high)} 条中危"
    if not high:
        return f"{head}：没有致命问题，但下面几处会削弱结论。"
    must = "、".join(dict.fromkeys(p["title"] for p in high[:2]))
    return f"{head}；要上会，至少先解决：{must}。"


def build(track: str, inputs: JSON, metrics: JSON, facts: JSON) -> JSON:
    """facts：系统已算好的结果 {kill, redteam, scenarios, max_bid, key_numbers, queue, stale}；缺哪项就少写哪类论点。"""
    points = [*_kill_points(facts.get("kill") or {}), *_price_point(facts.get("max_bid")),
              *_swing_point(facts.get("redteam")), *_downside_point(facts.get("scenarios")),
              *_verify_points(facts.get("key_numbers"), facts.get("queue"), int(facts.get("stale") or 0)),
              *_structure_points(track, inputs, metrics)]
    if any(p["key"] == "near:dscr" for p in points):  # 同一件事（DSCR 贴近 1.25×）只说一次
        points = [p for p in points if p["key"] != "dscr:thin"]
    order = {"high": 0, "medium": 1}
    points.sort(key=lambda p: order[p["severity"]])  # 稳定排序：同级保持规则顺序
    return {
        "headline": _headline(points),
        "points": points, "high": sum(1 for p in points if p["severity"] == "high"),
        "note": "本备忘录不经 AI：每条都由固定规则从系统已算出的结果拼成，数字可点开来源核对；数据不足的论点不写。",
    }

