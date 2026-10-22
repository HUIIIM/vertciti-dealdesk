"""反方备忘录（vertciti 独有）：上投委会之前，系统先写“这笔交易最可能怎么失败”。

别人的 AI 写的是“为什么该买”；这里反着来，而且**不经 AI**：每条论点只由确定性规则从系统已算出的结果拼成
（淘汰条件余量、红队摆动、悲观情景、要价与可出价的差、核对缺口、盈亏平衡出租率、退出与买入 cap），
每个数字都能回到来源——可复现、不会编。数据不足的论点不写，绝不拿“0”凑。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.i18n import T
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


def _fmt_for(unit: str) -> Callable[[float], str]:
    """按指标单位写数：倍数 ×、百分比 %、金额 $（负数带减号）、分数 pts。"""
    if unit == "x":
        return lambda x: f"{x:.2f}×"
    if unit == "pct":
        return lambda x: f"{x:.2f}%"
    if unit == "usd":
        return lambda x: f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"
    return lambda x: f"{x:g} pts" if unit == "pts" else f"{x:g}"


def _kill_points(kill: JSON) -> list[JSON]:
    out = []
    for k in kill.get("items", []):
        v, th = _num(k.get("value")), float(k["threshold"])
        f = _fmt_for(METRICS[k["metric"]].unit)
        if k["state"] == "triggered" and v is not None:
            out.append(_pt(f"kill:{k['metric']}", "high", T("已触发淘汰条件"),
                           T("{0}：当前 {1}，越线 {2}。", k["text"], f(v), f(abs(v - th))), "overview"))
        elif k["state"] == "ok" and v is not None and th != 0 and abs(v - th) / abs(th) <= NEAR_MISS:
            out.append(_pt(f"near:{k['metric']}", "medium", T("离淘汰线很近"),
                           T(
                               "{0}：当前 {1}，只比底线多 {2}，一个假设稍差就会触发。",
                               k["text"], f(v), f(abs(v - th))), "risk"))
    return out


def _price_point(mb: JSON | None) -> list[JSON]:
    if not mb:
        return []
    ask, best, bind = _num(mb.get("asking")), _num(mb.get("max_bid")), mb.get("binding") or {}
    if best is None and bind:
        why = T("「{0}」{1}。", bind.get("label", ""), bind.get("reason", ""))
        return [_pt("price:none", "high", T("任何价格都不满足"), why, "risk")]
    if ask and best is not None and best < ask:
        text = T("要价 ${0:,.0f} 比所有约束允许的最高价 ${1:,.0f} 高 {2:.1f}%；"
                 "卡住价格的是「{3}」。按要价成交等于放弃这条底线。",
                 ask, best, (ask / best - 1) * 100, bind.get("label", ""))
        return [_pt("price:gap", "high", T("要价高过可出价"), text, "risk")]
    return []


def _swing_point(rt: JSON | None) -> list[JSON]:
    top = rt.get("top") if rt else None
    if not rt or not top:
        return []
    r = top[0]
    lo, hi = sorted([r["minus"]["value"], r["plus"]["value"]])
    return [_pt("swing:top", "high" if r["material"] else "medium", T("结论押在一个假设上"),
                T("「{0}」只要错 {1:g}%，{2}就落在 {3:.2f}%–{4:.2f}% 之间（摆动 {5"
                  ":.0f} bp）。这个数从哪来、谁核过，决定了这笔交易。",
                  r["label"], rt["shock_pct"], rt["metric_label"], lo, hi, r["swing_bps"]), "risk")]


def _downside_point(sc: JSON | None) -> list[JSON]:
    if not sc:
        return []
    rows = [r for r in sc.get("scenarios", []) if _num(r.get("primary")) is not None]
    if not rows:
        return []
    worst = min(rows, key=lambda r: r["primary"])
    lp = _num(sc.get("loss_probability_pct"))
    if worst["primary"] < 0 or worst.get("loss"):
        tail = T("，按当前情景概率算，亏损概率 {0:.0f}%", lp) if lp is not None else ""
        return [_pt("downside", "high", T("悲观情景是亏的"),
                    T("「{0}」（概率 {1:.0f}%）{2} {3:.2f}%{4}。",
                      worst["name"], worst["probability"], sc["metric_label"], worst["primary"], tail), "risk")]
    return []


def _verify_points(kn: JSON | None, queue: JSON | None, stale: int) -> list[JSON]:
    out = []
    if kn and kn.get("total") and kn["done"] < kn["total"]:
        first = ((queue or {}).get("items") or [None])[0]
        hint = (T("；最该先核：「{0}」（{1:.0f} bp）", first["label"], first["swing_bps"])
                if first and first.get("swing_bps") else "")
        out.append(_pt("verify:gap", "high" if kn["done"] == 0 else "medium", T("关键数字没核完"),
                       T(
                           "{0} 个关键数字只复核了 {1} 个{2}。没核过的数不该拿去上会。",
                           kn["total"], kn["done"], hint), "files"))
    if stale:
        out.append(_pt("verify:stale", "medium", T("证据过期"), T(
            "{0} 条证据超过 30 天，市场数据可能已变。",
            stale), "files"))
    return out


def _structure_points(track: str, inputs: JSON, metrics: JSON) -> list[JSON]:
    out = []
    be = _num(metrics.get("breakeven_occupancy_pct"))
    if track == "commercial" and be is not None and be >= BREAKEVEN_MED:
        out.append(_pt("breakeven", "high" if be >= BREAKEVEN_HIGH else "medium", T("容错空间小"),
                       T(
                           "出租率跌破 {0:.1f}% 就入不敷出——空置只要超过 {1:.1f}% 就开始亏现金。",
                           be, 100 - be), "model"))
    a = inputs.get("analysis") or {}
    exit_cap, entry = _num(a.get("exit_cap_rate")), _num(metrics.get("cap_rate_pct"))
    if exit_cap is not None and entry is not None and exit_cap < entry:
        out.append(_pt("cap:compress", "medium", T("回报靠估值上升"),
                       T(
                           "退出 Cap Rate {0:.2f}% 低于买入 {1:.2f}%：一部分回报来自假设将来有人出更高的价。",
                           exit_cap, entry), "model"))
    dscr = _num(metrics.get("dscr"))
    if dscr is not None and 1.0 <= dscr < DSCR_THIN:
        out.append(_pt("dscr:thin", "medium", T("偿债余量薄"),
                       T("DSCR {0:.2f}×，只比贷款常见门槛 1.25× 高 {1:.2f}，"
                         "NOI 小幅下滑就可能触发贷款条款。", dscr, max(dscr - 1.25, 0)), "model"))
    return out


def _governance_points(kill_changes: int) -> list[JSON]:
    if not kill_changes:
        return []
    return [_pt("kill:moved", "medium", T("看过模型后改过淘汰条件"),
                T("第一版承销保存后，淘汰条件又被改过 {0} 次（时间线里有改前改后）：确认不是为了让交易过关。",
                  kill_changes), "overview")]


def _headline(points: list[JSON]) -> str | None:
    """一句话摘要（不重复清单原文）：几条高危、几条中危，上会前至少先解决哪几件。"""
    if not points:
        return None
    high = [p for p in points if p["severity"] == "high"]
    head = T("{0} 条高危、{1} 条中危", len(high), len(points) - len(high))
    if not high:
        return T("{0}：没有致命问题，但下面几处会削弱结论。", head)
    must = T("、").join(dict.fromkeys(p["title"] for p in high[:2]))
    return T("{0}；要上会，至少先解决：{1}。", head, must)


def build(track: str, inputs: JSON, metrics: JSON, facts: JSON) -> JSON:
    """facts：系统已算好的结果 {kill, redteam, scenarios, max_bid, key_numbers, queue, stale}；缺哪项就少写哪类论点。"""
    points = [*_kill_points(facts.get("kill") or {}), *_price_point(facts.get("max_bid")),
              *_swing_point(facts.get("redteam")), *_downside_point(facts.get("scenarios")),
              *_verify_points(facts.get("key_numbers"), facts.get("queue"), int(facts.get("stale") or 0)),
              *_structure_points(track, inputs, metrics), *_governance_points(int(facts.get("kill_changes") or 0))]
    if any(p["key"] == "near:dscr" for p in points):  # 同一件事（DSCR 贴近 1.25×）只说一次
        points = [p for p in points if p["key"] != "dscr:thin"]
    order = {"high": 0, "medium": 1}
    points.sort(key=lambda p: order[p["severity"]])  # 稳定排序：同级保持规则顺序
    return {
        "headline": _headline(points),
        "points": points, "high": sum(1 for p in points if p["severity"] == "high"),
        "note": T("本备忘录不经 AI：每条都由固定规则从系统已算出的结果拼成，数字可点开来源核对；数据不足的论点不写。"),
    }

