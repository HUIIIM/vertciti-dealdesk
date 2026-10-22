"""投委会计票规则（公开、可复核）。

- 只有“分析”及以上角色能投票（权限层保证）；每人每版一票，可改票（记审计）。
- 董事长一票否决：董事长投反对 → 不通过。
- 通过条件：董事长已投赞成，且赞成票数 ≥ 反对票数。其余情况为待定。
"""
from __future__ import annotations

from typing import Any


def tally(votes: list[dict[str, Any]], roles: dict[str, str]) -> dict[str, Any]:
    counts = {"approve": 0, "reject": 0, "abstain": 0}
    chairman_vote = None
    for v in votes:
        counts[v["vote"]] = counts.get(v["vote"], 0) + 1
        if roles.get(v["voter"]) == "chairman":
            chairman_vote = v["vote"]
    if chairman_vote == "reject":
        result, why = "rejected", "董事长否决"
    elif counts["reject"] > counts["approve"]:
        result, why = "rejected", "反对票多于赞成票"
    elif chairman_vote == "approve":
        result, why = "approved", "董事长赞成且赞成票不少于反对票"
    else:
        result, why = "pending", "待董事长表决"
    return {**counts, "chairman_vote": chairman_vote, "result": result, "why": why, "votes": len(votes)}
