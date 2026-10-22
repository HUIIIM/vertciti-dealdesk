"""性质测试（hypothesis）：对任意输入都必须成立的不变量——金标准锁住"已知用例"，这里锁住"规律"。"""

from __future__ import annotations

import math
import random

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.domain import finance, uw_commercial
from app.domain.v2 import committee, diffing, kill_criteria, max_bid, reproducible
from app.domain.v2.model import run_model

principal = st.floats(min_value=1_000, max_value=50_000_000, allow_nan=False)
rate = st.floats(min_value=0, max_value=25, allow_nan=False)
years = st.integers(min_value=1, max_value=40)
json_leaf = st.one_of(st.none(), st.booleans(), st.integers(-10**9, 10**9),
                      st.floats(allow_nan=False, allow_infinity=False), st.text(max_size=8))
json_tree = st.recursive(json_leaf, lambda kids: st.one_of(
    st.lists(kids, max_size=4), st.dictionaries(st.text(max_size=6), kids, max_size=4)), max_leaves=20)


# ---------------------------------------------------------------- 贷款数学
@given(principal, rate, years)
def test_payment_covers_principal_and_rises_with_rate(p, r, n):
    pmt = finance.monthly_payment(p, r, n)
    assert pmt * n * 12 >= p * (1 - 1e-9)  # 总还款不少于本金（利率 ≥ 0）
    assert finance.monthly_payment(p, r + 0.5, n) >= pmt - 1e-9


@given(principal, rate, years, st.data())
def test_balance_starts_at_principal_ends_at_zero_and_never_rises(p, r, n, data):
    assert finance.remaining_balance(p, r, n, 0) == p
    assert finance.remaining_balance(p, r, n, n) == 0
    k = data.draw(st.integers(min_value=0, max_value=n * 12 - 1))
    b1 = finance.remaining_balance(p, r, n, k / 12)
    b2 = finance.remaining_balance(p, r, n, (k + 1) / 12)
    assert -1e-6 * p <= b2 <= b1 + 1e-6 * p


# ---------------------------------------------------------------- 可复现运行
@given(st.dictionaries(st.text(max_size=6), json_tree, max_size=6), st.randoms(use_true_random=False))
def test_canonical_json_ignores_key_order(d, rnd: random.Random):
    items = list(d.items())
    rnd.shuffle(items)
    assert reproducible.canonical_json(dict(items)) == reproducible.canonical_json(d)


@given(json_tree)
def test_run_id_is_deterministic(x):
    assert reproducible.run_id("t", x) == reproducible.run_id("t", x)


# ---------------------------------------------------------------- 版本对比
@given(json_tree)
def test_diff_with_self_is_empty(x):
    assert diffing.deep_diff(x, x) == []


@given(json_tree, json_tree)
def test_diff_empty_iff_equal(a, b):
    assert (diffing.deep_diff(a, b) == []) == (a == b)


# ---------------------------------------------------------------- 投委会计票
votes = st.lists(st.tuples(st.sampled_from(["c", "a1", "a2", "a3", "v1"]),
                           st.sampled_from(["approve", "reject", "abstain"])), max_size=8, unique_by=lambda t: t[0])
ROLES = {"c": "chairman", "a1": "analyst", "a2": "analyst", "a3": "analyst", "v1": "viewer"}


@given(votes)
def test_tally_chairman_veto_and_approval_needs_chairman(vs):
    t = committee.tally([{"voter": u, "vote": v} for u, v in vs], ROLES)
    chair = dict(vs).get("c")
    if chair == "reject":
        assert t["result"] == "rejected"
    if t["result"] == "approved":
        assert chair == "approve" and t["approve"] >= t["reject"]
    assert t["approve"] + t["reject"] + t["abstain"] == t["votes"] == len(vs)


# ---------------------------------------------------------------- 淘汰条件
@given(st.sampled_from(sorted(kill_criteria.OPS)), st.floats(-100, 100), st.one_of(st.none(), st.floats(-100, 100)))
def test_kill_state_is_unknown_only_when_metric_missing(op, th, v):
    r = kill_criteria.evaluate([{"metric": "irr_pct", "op": op, "threshold": th}], {"irr_pct": v})
    state = r["items"][0]["state"]
    assert (state == "unknown") == (v is None)  # 未知保持未知：缺数既不算通过也不算触发
    if v is not None:
        assert (state == "triggered") == kill_criteria.OPS[op](v, th)


# ---------------------------------------------------------------- 反推最高出价（每例跑数十次模型，例数从严）
COM = uw_commercial.example_39_main()
BASE_DSCR = run_model("commercial", COM)["metrics"]["dscr"]


@settings(max_examples=8, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.floats(min_value=0.9, max_value=2.0))
def test_max_bid_meets_target_and_is_tight(target):
    r = max_bid.run("commercial", COM, [{"metric": "dscr", "min": target}])
    best = r["max_bid"]
    if best is None:
        return  # 搜索区间内不可行：已由 status 表明，不编数字
    at = run_model("commercial", max_bid.with_price("commercial", COM, best))["metrics"]["dscr"]
    assert at >= target - 1e-9
    hi = max_bid.with_price("commercial", COM, best + 2 * max_bid.STEP)
    over = run_model("commercial", hi)["metrics"]["dscr"]
    capped = best >= r["constraints"][0].get("search_max", math.inf) - 2 * max_bid.STEP
    assert capped or over < target


@pytest.mark.parametrize("target", [BASE_DSCR * 0.95])
def test_max_bid_above_asking_when_target_below_current(target):
    """目标比现状宽松 → 可出价不低于要价（指标随价格单调递减）。"""
    r = max_bid.run("commercial", COM, [{"metric": "dscr", "min": target}])
    assert r["max_bid"] is not None and r["headroom_pct"] >= 0
