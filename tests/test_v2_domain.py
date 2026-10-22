"""v2 领域层（纯计算）：路径、淘汰条件、新鲜度、数字护照规则、红队、情景、反推最高出价、
版本对比、生命周期关卡、投委会计票、可复现运行、事后归因。"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

from app.domain import uw_commercial
from app.domain.v2 import (
    committee,
    diffing,
    freshness,
    holding,
    kill_criteria,
    lifecycle,
    max_bid,
    provenance,
    redteam,
    reproducible,
    scenarios,
)
from app.domain.v2.model import ModelInputError, run_model
from app.domain.v2.paths import get_path, set_path, update_path
from test_scoring import base_residential

COM = uw_commercial.example_39_main()
RES = base_residential()


# ---------------------------------------------------------------- 路径
def test_paths_get_set_wildcard_and_copy():
    d = {"a": {"b": 1}, "t": [{"r": 10}, {"r": 20}]}
    assert get_path(d, "a.b") == 1 and get_path(d, "t.1.r") == 20 and get_path(d, "t.*.r") == [10, 20]
    assert get_path(d, "x.y") is None and get_path(d, "t.9.r") is None
    d2 = update_path(d, "t.*.r", lambda v: v * 2)
    assert get_path(d2, "t.*.r") == [20, 40] and get_path(d, "t.*.r") == [10, 20]  # 原对象不变
    assert set_path(d, "n.m", 5)["n"]["m"] == 5


# ---------------------------------------------------------------- 模型
def test_model_units_are_percent_numbers_and_unknown_stays_none():
    m = run_model("commercial", COM)["metrics"]
    assert m["irr_pct"] == pytest.approx(1.029449701669749)  # 0.0103 → 1.03（百分比数）
    assert m["dscr"] == pytest.approx(1.1337868480725626)
    r = run_model("residential", RES)["metrics"]
    assert r["irr_pct"] is None and r["equity_multiple"] is None  # 住宅引擎不算 IRR：未知保持未知
    assert r["coc_pct"] == pytest.approx(67.37)


def test_model_rejects_bad_input_in_chinese():
    with pytest.raises(ModelInputError, match="住宅输入校验失败"):
        run_model("residential", {"price": "abc"})
    with pytest.raises(ModelInputError, match="未知赛道"):
        run_model("hotel", {})


# ---------------------------------------------------------------- 淘汰条件
def test_kill_criteria_triggered_ok_unknown():
    crit = [{"metric": "dscr", "op": "<", "threshold": 1.25}, {"metric": "irr_pct", "op": "<", "threshold": 12},
            {"metric": "ltv_pct", "op": ">", "threshold": 90}]
    ev = kill_criteria.evaluate(crit, {"dscr": 1.13, "irr_pct": None, "ltv_pct": 70})
    states = [r["state"] for r in ev["items"]]
    assert states == ["triggered", "unknown", "ok"]
    assert not ev["clear"] and ev["defined"]
    assert "DSCR低于 1.25× 即放弃" == ev["items"][0]["text"]
    with pytest.raises(ValueError, match="未知指标"):
        kill_criteria.validate([{"metric": "nope", "op": "<", "threshold": 1}])


# ---------------------------------------------------------------- 新鲜度
def test_freshness_14_and_30_day_rule():
    now = datetime(2026, 10, 22, tzinfo=timezone.utc)
    assert freshness.classify(now - timedelta(days=13), now)["state"] == "fresh"
    assert freshness.classify(now - timedelta(days=15), now)["state"] == "review"
    assert freshness.classify(now - timedelta(days=31), now)["state"] == "stale"
    assert freshness.classify(now - timedelta(days=300), now, market_data=False)["state"] == "fresh"
    assert freshness.classify(None, now)["state"] == "unknown"


# ---------------------------------------------------------------- 数字护照规则
def test_conflict_tolerance_and_key_numbers():
    assert not provenance.values_conflict(100.0, 100.4)  # 0.4% 以内视为一致
    assert provenance.values_conflict(100.0, 101.0)
    assert provenance.values_conflict("A", "B")
    st = provenance.key_number_status(["a", "b", "c"], {
        "a": {"confidence": "high", "review_status": "reviewed"},
        "b": {"confidence": "low", "review_status": "reviewed"},
    })
    assert (st["done"], st["total"], st["ok"]) == (1, 3, False)
    reasons = {r["field"]: r["reason"] for r in st["items"]}
    assert "可信度低" in reasons["b"] and "没有来源记录" in reasons["c"]


# ---------------------------------------------------------------- 红队
def test_redteam_ranks_by_swing_and_defines_key_numbers():
    r = redteam.run("commercial", COM)
    swings = [x["swing_bps"] for x in r["top"]]
    assert swings == sorted(swings, reverse=True) and len(r["top"]) == 5
    assert r["top"][0]["key"] == "rent_level"
    assert all(x["swing_bps"] >= 100 for x in r["all"] if x["material"])
    assert "analysis.exit_cap_rate" in r["key_fields"]
    # 当前为 0 的假设（如空置率 0）不扰动，列入 skipped 并说明原因
    assert any(s["key"] == "vacancy" for s in r["skipped"])


# ---------------------------------------------------------------- 情景
def test_scenarios_expected_value_and_loss_probability():
    r = scenarios.run("commercial", COM)
    rows = {x["name"]: x for x in r["scenarios"]}
    exp = sum(x["primary"] * x["probability"] for x in r["scenarios"]) / 100
    assert r["expected"] == pytest.approx(exp)
    assert rows["悲观"]["loss"] is True and r["loss_probability_pct"] == 25.0
    with pytest.raises(ValueError, match="合计须为 100"):
        scenarios.run("commercial", COM, [{"name": "x", "probability": 60, "changes": []}])


# ---------------------------------------------------------------- 反推最高出价
def test_max_bid_is_tight_and_binding_constraint_is_lowest():
    r = max_bid.run("commercial", COM, [{"metric": "irr_pct", "min": 8}, {"metric": "dscr", "min": 1.25}],
                    kill=[{"metric": "dscr", "op": "<", "threshold": 1.2}])
    best = r["max_bid"]
    assert best == min(c["price"] for c in r["constraints"]) and r["binding"]["label"] == "IRR ≥ 8"
    at = run_model("commercial", max_bid.with_price("commercial", COM, best))["metrics"]
    over = run_model("commercial", max_bid.with_price("commercial", COM, best + 2 * max_bid.STEP))["metrics"]
    assert at["irr_pct"] >= 8 > over["irr_pct"]  # 精确到 100 美元：再加价就跌破
    assert r["headroom_pct"] < 0  # 要价 4200 万远高于可出价


def test_max_bid_infeasible_and_requires_asking():
    r = max_bid.run("commercial", COM, [{"metric": "irr_pct", "min": 500}])
    assert r["max_bid"] is None and r["constraints"][0]["status"] in ("infeasible", "unknown")
    with pytest.raises(ValueError, match="先填要价"):
        max_bid.run("residential", {**RES, "price": 0}, [{"metric": "dscr", "min": 1}])


def test_residential_max_bid_keeps_ltv():
    r = max_bid.run("residential", RES, [{"metric": "dscr", "min": 1.3}])
    p = r["max_bid"]
    x = max_bid.with_price("residential", RES, p)
    assert x["loan_balance"] / x["price"] == pytest.approx(RES["loan_balance"] / RES["price"])
    assert run_model("residential", x)["metrics"]["dscr"] >= 1.3


# ---------------------------------------------------------------- 版本对比
def test_diff_versions_reports_paths_and_deltas():
    b = copy.deepcopy(COM)
    b["analysis"]["exit_cap_rate"] = 6
    b["tenants"].append({"suite": "2", "tenant": "New", "sf": 100, "monthly_rent": 1})
    out = diffing.compare_versions({"inputs": COM, "outputs": run_model("commercial", COM)},
                                   {"inputs": b, "outputs": run_model("commercial", b)})
    paths = {r["path"]: r for r in out["inputs"]}
    assert paths["analysis.exit_cap_rate"]["delta"] == 1 and paths["tenants.1"]["kind"] == "added"
    assert any(r["path"] == "irr_pct" for r in out["metrics"])


# ---------------------------------------------------------------- 生命周期
def _ctx(**over):
    base = {"has_basics": True, "asking_price": 1.0, "kill": kill_criteria.evaluate(
        [{"metric": "dscr", "op": "<", "threshold": 1.0}], {"dscr": 1.5}), "versions": 1,
        "key_numbers": {"done": 2, "total": 2, "ok": True}, "open_conflicts": 0, "stale_evidence": 0,
        "redteam_read": True, "committee": {"result": "approved"}, "last_verdict": "BUY", "open_tasks": {},
        "payments": {"approved": 1, "pending": 0}}
    base.update(over)
    return base


def test_gates_no_skip_back_ok_and_committee_conditions():
    assert not lifecycle.evaluate("sourcing", "underwriting", _ctx())["allowed"]  # 不能跳级
    assert lifecycle.evaluate("committee", "screening", _ctx())["direction"] == "back"
    assert lifecycle.evaluate("underwriting", "committee", _ctx())["allowed"]
    bad = lifecycle.evaluate("underwriting", "committee", _ctx(
        kill=kill_criteria.evaluate([{"metric": "dscr", "op": "<", "threshold": 1.25}], {"dscr": 1.1}),
        open_conflicts=2, redteam_read=False))
    status = {c["key"]: c["status"] for c in bad["checks"]}
    assert not bad["allowed"] and status["kill_clear"] == "risk" and status["conflicts"] == "risk"
    assert status["redteam"] == "planned"
    # 淘汰条件指标未知 → 不放行（未知不等于安全）
    unk = lifecycle.evaluate("underwriting", "committee", _ctx(
        kill=kill_criteria.evaluate([{"metric": "irr_pct", "op": "<", "threshold": 12}], {"irr_pct": None})))
    assert not unk["allowed"]
    # 进承销前必须先写淘汰条件
    pre = lifecycle.evaluate("screening", "underwriting", _ctx(kill=kill_criteria.evaluate([], {})))
    assert not pre["allowed"] and pre["checks"][0]["key"] == "kill_defined"


def test_committee_tally_rules():
    roles = {"miao": "chairman", "a1": "analyst", "a2": "analyst"}
    t = committee.tally
    assert t([{"voter": "miao", "vote": "approve"}], roles)["result"] == "approved"
    assert t([{"voter": "miao", "vote": "reject"}, {"voter": "a1", "vote": "approve"},
              {"voter": "a2", "vote": "approve"}], roles)["result"] == "rejected"  # 一票否决
    assert t([{"voter": "miao", "vote": "approve"}, {"voter": "a1", "vote": "reject"},
              {"voter": "a2", "vote": "reject"}], roles)["result"] == "rejected"
    assert t([{"voter": "a1", "vote": "approve"}], roles)["result"] == "pending"


# ---------------------------------------------------------------- 可复现运行
def test_run_id_stable_and_sensitive():
    a = reproducible.run_id("underwrite:commercial", COM)
    assert a == reproducible.run_id("underwrite:commercial", copy.deepcopy(COM))
    b2 = copy.deepcopy(COM)
    b2["analysis"]["rate"] = 6.01
    assert a != reproducible.run_id("underwrite:commercial", b2)
    assert a != reproducible.run_id("underwrite:commercial", COM, version="9.9.9+x")
    assert reproducible.canonical_json({"b": 1, "a": float("nan")}) == '{"a":"NaN","b":1}'


# ---------------------------------------------------------------- 事后归因
def test_attribution_steps_sum_to_total():
    acts = [{"period": "2027", "noi": 1_800_000, "occupancy_pct": 95},
            {"period": "2028", "noi": 1_850_000, "occupancy_pct": 96}]
    r = holding.attribution("commercial", COM, acts)
    assert r["available"] and [s["key"] for s in r["steps"]] == ["vacancy", "noi_level", "noi_growth"]
    assert sum(s["contribution_pct_points"] for s in r["steps"]) == pytest.approx(r["total_pct_points"])
    steps = {s["key"]: s for s in r["steps"]}
    assert steps["vacancy"]["contribution_pct_points"] < 0  # 承销空置 0%，实际平均出租 95.5% → 拉低
    assert steps["noi_growth"]["contribution_pct_points"] > 0  # 实际增长 2.78% > 承销 2%
    # NOI 校准后，测算第 1 年 NOI 恰为实际值
    from app.domain.v2.paths import set_path as _sp
    cal = holding._calibrate_noi("commercial", _sp(COM, "proforma.vacancy_pct", 4.5), 1_800_000)
    assert holding._pro_noi(run_model("commercial", cal)) == pytest.approx(1_800_000, abs=0.01)
    assert r["total_pct_points"] < 0
    v = holding.variance("commercial", run_model("commercial", COM), acts)
    assert v[0]["noi"]["underwritten"] == pytest.approx(2_000_000) and v[0]["noi"]["variance"] == -200_000
    assert not holding.attribution("residential", RES, acts)["available"]


def test_price_check_matches_model_at_asking_and_moves_with_price():
    asking = COM["analysis"]["purchase_price"]
    at = max_bid.price_check("commercial", COM, asking, kill=[{"metric": "irr_pct", "op": "<", "threshold": 12}])
    assert at["metrics"] == run_model("commercial", COM)["metrics"] and at["vs_asking_pct"] == 0
    assert at["kill"]["triggered"]  # 要价下 IRR 8.94% < 12% → 触发
    lower = max_bid.price_check("commercial", COM, asking * 0.8)
    assert lower["metrics"]["irr_pct"] > at["metrics"]["irr_pct"] and lower["vs_asking_pct"] == pytest.approx(-20)
    with pytest.raises(ValueError, match="大于 0"):
        max_bid.price_check("commercial", COM, 0)


def test_price_check_residential_keeps_ltv():
    r = max_bid.price_check("residential", RES, RES["price"] * 0.9)
    expect = run_model("residential", max_bid.with_price("residential", RES, RES["price"] * 0.9))["metrics"]
    assert r["metrics"] == expect


def test_verification_value_ranks_by_measured_swing_and_dedupes():
    from app.domain.v2 import verification_value
    from app.domain.v2.model import primary_value
    rt = redteam.run("commercial", COM)
    ks = provenance.key_number_status(rt["key_fields"], {})  # 一个来源都没有：全部关键数字未达标
    con = {"id": 7, "field": "analysis.exit_cap_rate", "value_a": 5.0, "source_a": "OM", "value_b": 5.75, "source_b": "电话"}
    out = verification_value.rank("commercial", COM, rt, ks, [con])
    first = out["items"][0]
    irr = lambda v: primary_value("commercial", run_model("commercial", set_path(COM, "analysis.exit_cap_rate", v)))  # noqa: E731
    by_field = {x["field"]: x for x in out["items"]}
    c = by_field["analysis.exit_cap_rate"]
    assert c["kind"] == "conflict" and c["swing_bps"] == pytest.approx(abs(irr(5.0) - irr(5.75)) * 100)
    assert [x["field"] for x in out["items"]].count("analysis.exit_cap_rate") == 1   # 矛盾与未复核同字段只算一次
    labels = [x["label"] for x in out["items"]]
    assert len(labels) == len(set(labels))  # 一个假设覆盖多个字段（如各租户租金）也只列一次
    swings = [x["swing_bps"] for x in out["items"] if x["swing_bps"] is not None]
    assert swings == sorted(swings, reverse=True) and first["swing_bps"] == max(swings)
    assert {x["kind"] for x in out["items"]} == {"conflict", "unverified"} and 0 < out["top_share_pct"] <= 100


def test_devils_memo_is_deterministic_and_never_invents():
    from app.domain.v2 import devils_advocate
    kill_def = [{"metric": "irr_pct", "op": "<", "threshold": 12}, {"metric": "dscr", "op": "<", "threshold": 1.25}]
    m = run_model("commercial", COM)["metrics"]
    rt = redteam.run("commercial", COM)
    args = {"kill": kill_criteria.evaluate(kill_def, m), "redteam": rt, "scenarios": scenarios.run("commercial", COM),
            "max_bid": max_bid.run("commercial", COM, [], kill=kill_def),
            "key_numbers": provenance.key_number_status(rt["key_fields"], {}), "queue": None}
    a = devils_advocate.build("commercial", COM, m, args)
    b = devils_advocate.build("commercial", COM, m, args)
    assert a == b  # 同输入同备忘录：可复现
    keys = [p["key"] for p in a["points"]]
    assert {"kill:irr_pct", "price:gap", "swing:top", "verify:gap"} <= set(keys)
    first = next(p for p in a["points"] if p["key"] == "kill:irr_pct")
    assert f"{m['irr_pct']:.2f}%" in first["text"] and a["headline"].startswith(f"{a['high']} 条高危")
    assert first["title"] in a["headline"]  # 头条点名最该先解决的
    assert all(p["severity"] == "high" for p in a["points"][: a["high"]])  # 高危在前
    assert not ({"near:dscr", "dscr:thin"} <= set(keys))  # 同一件事不说两遍
    # 数据不足：不写论点，不拿 0 凑
    empty = devils_advocate.build("commercial", {}, {}, {})
    assert empty["points"] == [] and empty["headline"] is None


def test_passed_deal_can_only_restart_to_sourcing():
    ctx = _ctx()
    back = lifecycle.evaluate("passed", "sourcing", ctx)
    assert back["allowed"] and back["direction"] == "back"  # 重启 = 回退：服务层要求写原因
    for t in ("screening", "committee", "holding", "passed"):
        r = lifecycle.evaluate("passed", t, ctx)
        assert not r["allowed"] and "发现" in r["reason"]
