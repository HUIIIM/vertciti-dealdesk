"""交易生命周期与关卡：发现 → 初筛 → 承销 → 投委会 → 尽调 → 交割 → 持有；任何阶段可放弃。

每个阶段有进入条件，不满足不能推进；只能逐级前进（不跳级），可回退。
全系统统一状态词：已验证 / 建设中 / 计划中 / 风险。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

STAGES: tuple[tuple[str, str], ...] = (
    ("sourcing", "发现"), ("screening", "初筛"), ("underwriting", "承销"), ("committee", "投委会"),
    ("diligence", "尽调"), ("closing", "交割"), ("holding", "持有"),
)
TERMINAL = ("passed", "已放弃")
STAGE_LABEL = dict(STAGES) | {TERMINAL[0]: TERMINAL[1]}
ORDER = [s for s, _ in STAGES]
STATUS_WORDS = {"verified": "已验证", "building": "建设中", "planned": "计划中", "risk": "风险"}


@dataclass(frozen=True)
class Check:
    key: str
    label: str
    status: str  # verified | building | planned | risk
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "verified"

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "status": self.status,
                "status_label": STATUS_WORDS[self.status], "detail": self.detail, "ok": self.ok}


def _checks_for(target: str, ctx: dict[str, Any]) -> list[Check]:
    c: list[Check] = []
    if target == "screening":
        c.append(Check("basics", "名称、地址、赛道已填", "verified" if ctx.get("has_basics") else "building"))
        c.append(Check("asking", "要价已填", "verified" if ctx.get("asking_price") else "building"))
    elif target == "underwriting":
        kc = ctx.get("kill", {})
        c.append(Check("kill_defined", "淘汰条件已先写好（防止越算越想买）",
                       "verified" if kc.get("defined") else "planned", "建交易时先填“什么情况下放弃”"))
        c.append(Check("version", "至少有一版承销", "verified" if ctx.get("versions", 0) > 0 else "planned"))
    elif target == "committee":
        kc = ctx.get("kill", {})
        if kc.get("triggered"):
            c.append(Check("kill_clear", "淘汰条件未触发", "risk",
                           "已触发：" + "；".join(r["text"] for r in kc["triggered"])))
        elif kc.get("unknown"):
            c.append(Check("kill_clear", "淘汰条件未触发", "building",
                           "指标未算出（未知不等于安全）：" + "；".join(r["text"] for r in kc["unknown"])))
        else:
            c.append(Check("kill_clear", "淘汰条件未触发", "verified" if kc.get("clear") else "planned"))
        kn = ctx.get("key_numbers", {"done": 0, "total": 0, "ok": False})
        c.append(Check("key_numbers", "关键数字已复核且可信度 ≥ 中",
                       "verified" if kn.get("ok") else "building", f"{kn.get('done', 0)}/{kn.get('total', 0)} 已达标"))
        oc = ctx.get("open_conflicts", 0)
        c.append(Check("conflicts", "跨来源矛盾已裁决", "verified" if oc == 0 else "risk", f"未裁决 {oc} 条" if oc else ""))
        st = ctx.get("stale_evidence", 0)
        c.append(Check("freshness", "无过期证据（>30 天停用）", "verified" if st == 0 else "building",
                       f"{st} 条需重拉" if st else ""))
        c.append(Check("redteam", "红队面板已读（当前版本）", "verified" if ctx.get("redteam_read") else "planned"))
    elif target == "diligence":
        cm = ctx.get("committee", {})
        res = cm.get("result")
        c.append(Check("ic_approved", "投委会已通过（当前版本）",
                       "verified" if res == "approved" else ("risk" if res == "rejected" else "planned")))
        c.append(Check("buy_logged", "决策日志已记 BUY（含理由与数字快照）",
                       "verified" if ctx.get("last_verdict") == "BUY" else "planned"))
    elif target == "closing":
        open_dd = ctx.get("open_tasks", {}).get("diligence", 0)
        c.append(Check("dd_tasks", "尽调任务全部完成", "verified" if open_dd == 0 else "building",
                       f"还有 {open_dd} 项" if open_dd else ""))
        pay = ctx.get("payments", {})
        c.append(Check("payment", "交割付款已由董事长批准", "verified" if pay.get("approved", 0) > 0 else "planned"))
        if pay.get("pending", 0):
            c.append(Check("payment_pending", "无待批付款", "building", f"{pay['pending']} 笔待批"))
    elif target == "holding":
        open_cl = ctx.get("open_tasks", {}).get("closing", 0)
        c.append(Check("closing_tasks", "交割任务全部完成", "verified" if open_cl == 0 else "building",
                       f"还有 {open_cl} 项" if open_cl else ""))
    elif target == "passed":
        c.append(Check("pass_logged", "决策日志已记 PASS 理由", "verified" if ctx.get("last_verdict") == "PASS"
                       else "planned", "放弃也要写清为什么，便于复盘"))
    return c


def evaluate(current: str, target: str, ctx: dict[str, Any]) -> dict[str, Any]:
    if target not in STAGE_LABEL:
        raise ValueError(f"未知阶段：{target}")
    if current == TERMINAL[0]:
        return {"allowed": False, "reason": "交易已放弃；如需重启请新建交易或回退到发现阶段", "checks": []}
    if target != TERMINAL[0]:
        ci, ti = ORDER.index(current), ORDER.index(target)
        if ti <= ci:
            return {"allowed": True, "direction": "back", "checks": [], "reason": "回退不设关卡（会记入日志）"}
        if ti != ci + 1:
            return {"allowed": False, "reason": f"不能跳级：下一阶段是「{STAGE_LABEL[ORDER[ci + 1]]}」", "checks": []}
    checks = _checks_for(target, ctx)
    allowed = all(ch.ok for ch in checks)
    return {"allowed": allowed, "direction": "forward", "checks": [ch.as_dict() for ch in checks],
            "reason": "" if allowed else "关卡未通过：" + "；".join(ch.label for ch in checks if not ch.ok)}


def next_stage(current: str) -> str | None:
    if current not in ORDER or current == ORDER[-1]:
        return None
    return ORDER[ORDER.index(current) + 1]
