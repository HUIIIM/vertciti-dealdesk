"""独立代码审查（第二轮，2026-10-22）发现的问题逐条回归。编号对应审查报告。"""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from app.domain import uw_commercial
from app.domain.v2 import committee, devils_advocate, holding, kill_criteria, max_bid, provenance, scenarios
from app.domain.v2.model import run_model
from app.main import app
from test_scoring import base_residential

COM = uw_commercial.example_39_main()


@pytest.fixture
def c(tmp_path, monkeypatch):
    monkeypatch.setenv("DEALDESK_DB", str(tmp_path / "r2.db"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DEALDESK_AUTH", raising=False)
    return TestClient(app)


def _deal(c, inputs=None, **kw):
    d = c.post("/api/v2/deals", json={"name": "D", "track": "commercial", "kill_criteria": [], **kw}).json()
    if inputs is not None:
        assert c.post(f"/api/v2/deals/{d['id']}/versions", json={"inputs": inputs}).status_code == 201
    return d["id"]


# 1 ---------------------------------------------------------------- 缺数不被情景变动量“补上”
def test_scenario_on_missing_input_is_unknown_not_fabricated():
    inp = copy.deepcopy(COM)
    inp["analysis"].pop("exit_cap_rate", None)
    r = scenarios.run("commercial", inp)
    by = {x["name"]: x for x in r["scenarios"]}
    pess = next(x for x in r["scenarios"] if any(ch.get("add") for ch in x["changes"] if ch.get("assumption") == "exit_cap"))
    assert pess["primary"] is None and pess["note"]  # 此前：退出 cap 被设成 0.75%，IRR 72%
    assert r["expected"] is None  # 任一情景算不出 → 期望值未知
    assert by  # 其余情景照常给出


# 2 ---------------------------------------------------------------- 多位董事长：任一反对即否决，与票序无关
def test_tally_any_chairman_reject_vetoes_regardless_of_order():
    roles = {"a": "chairman", "b": "chairman", "x": "analyst"}
    for votes in ([{"voter": "a", "vote": "reject"}, {"voter": "b", "vote": "approve"}],
                  [{"voter": "b", "vote": "approve"}, {"voter": "a", "vote": "reject"}]):
        t = committee.tally(votes, roles)
        assert t["result"] == "rejected" and t["chairman_vote"] == "reject"
    assert committee.tally([{"voter": "a", "vote": "approve"}, {"voter": "x", "vote": "approve"}], roles)["result"] == "approved"


# 3 ---------------------------------------------------------------- 上限型淘汰条件也约束最高出价
def test_max_bid_respects_upper_bound_kill_criteria():
    kill = [{"metric": "cash_to_close", "op": ">", "threshold": 16_660_000}]
    r = max_bid.run("commercial", COM, [{"metric": "dscr", "min": 0.5}], kill=kill)
    assert r["max_bid"] is not None
    at = max_bid.price_check("commercial", COM, r["max_bid"], kill=kill)
    assert not at["kill"]["triggered"]  # 此前：给出 $95.2M，但该价现金需求 $29.9M 已越线
    over = max_bid.price_check("commercial", COM, r["max_bid"] + 5 * max_bid.STEP, kill=kill)
    assert over["kill"]["triggered"]


# 4 / 5 ---------------------------------------------------------------- 归因：负 NOI 不出复数；月度合成年度
def test_attribution_negative_noi_is_unknown_not_complex():
    acts = [{"period": "2027", "noi": 100_000.0}, {"period": "2028", "noi": 50_000.0}, {"period": "2029", "noi": -1_000.0}]
    a = holding.attribution("commercial", COM, acts)
    g = next(s for s in a["steps"] if s["key"] == "noi_growth")
    assert g["actual"] is None and g["contribution_pct_points"] is None
    assert a["actual_implied"] is None and a["total_pct_points"] is None
    assert all(not isinstance(v, complex) for s in a["steps"] for v in s.values())


def test_monthly_actuals_are_annualized_before_comparison():
    out = run_model("commercial", COM)
    months = [{"period": f"2027-{m:02d}", "noi": 10_000.0, "cash_flow": 1.0, "occupancy_pct": 90.0} for m in range(1, 13)]
    rows = holding.variance("commercial", out, months)
    assert len(rows) == 1 and rows[0]["period"] == "2027" and rows[0]["noi"]["actual"] == 120_000.0
    part = holding.variance("commercial", out, months[:3])
    assert part[0]["noi"]["actual"] is None and part[0]["months"] == 3  # 不足 12 个月：未知，不拿一季当一年


# 7 / 10 / 17 ---------------------------------------------------------------- 坏输入是 422，不是 500
def test_bad_inputs_are_422(c):
    did = _deal(c, COM)
    r = c.post(f"/api/v2/deals/{did}/scenarios", json={"scenarios": [
        {"name": "x", "probability": 100, "changes": [{"path": "tenants.999.monthly_rent", "pct": 5}]}]})
    assert r.status_code == 422
    assert c.post(f"/api/v2/deals/{did}/tasks", json={"title": "t", "assignee": "a" * 200}).status_code == 422
    assert c.patch(f"/api/v2/deals/{did}", json={"name": None}).status_code == 422
    assert c.patch(f"/api/v2/deals/{did}", json={"kill_criteria": None}).status_code == 422  # 此前：静默清空
    assert c.patch(f"/api/v2/deals/{did}", json={"kill_criteria": []}).status_code == 200    # 显式清空仍可
    big = copy.deepcopy(COM)
    big["tenants"] = [copy.deepcopy(COM["tenants"][0]) for _ in range(2001)]
    assert c.post(f"/api/v2/deals/{did}/versions", json={"inputs": big}).status_code == 422


# 8 ---------------------------------------------------------------- 同一投委会包生成两次：复用，不报冲突
def test_same_pack_twice_is_not_a_conflict(c):
    did = _deal(c, COM)
    a = c.get(f"/api/v2/deals/{did}/committee/pack.xlsx")
    b = c.get(f"/api/v2/deals/{did}/committee/pack.xlsx")
    assert a.status_code == b.status_code == 200
    assert len(c.get(f"/api/v2/deals/{did}/committee/packs").json()) == 1 + (a.content != b.content)


# 11 / 12 ---------------------------------------------------------------- 通配路径归到同一假设；金额按 $ 写
def test_verify_queue_maps_indexed_paths_to_assumption():
    from app.domain.v2 import redteam, verification_value
    rt = redteam.run("commercial", COM)
    ks = provenance.key_number_status(rt["key_fields"], {})
    con = {"id": 1, "field": "tenants.0.monthly_rent", "value_a": 80_000, "source_a": "OM", "value_b": 90_000, "source_b": "RR"}
    items = verification_value.rank("commercial", COM, rt, ks, [con])["items"]
    labels = [x["label"] for x in items]
    assert len(labels) == len(set(labels)) and "tenants.0.monthly_rent" not in labels


def test_devils_memo_formats_dollar_metrics():
    m = run_model("residential", base_residential())["metrics"]
    kill = [{"metric": "annual_cash_flow", "op": "<", "threshold": m["annual_cash_flow"] + 5000}]
    memo = devils_advocate.build("residential", base_residential(), m, {"kill": kill_criteria.evaluate(kill, m)})
    text = next(p["text"] for p in memo["points"] if p["key"] == "kill:annual_cash_flow")
    assert "$" in text and "%" not in text


# 14 ---------------------------------------------------------------- 存库与语言无关；用户输入不被翻译
def test_language_never_leaks_into_storage_or_user_text(c):
    en = {"X-DD-Lang": "en"}
    did = _deal(c)
    v = c.post(f"/api/v2/deals/{did}/versions", headers=en, json={"inputs": COM}).json()
    assert v["label"] == "Version 1"
    assert c.get(f"/api/v2/deals/{did}/versions").json()[0]["label"] == "第 1 版"  # 中文用户看到中文默认名
    c.post(f"/api/v2/deals/{did}/tasks", json={"title": "风险"})
    assert c.get(f"/api/v2/deals/{did}/tasks", headers=en).json()[0]["title"] == "风险"  # 用户数据原样


# 15 / 16 ---------------------------------------------------------------- 审计留痕；定案不改；归档冻结
def test_audit_and_settled_records(c):
    did = _deal(c, COM)
    t = c.post(f"/api/v2/deals/{did}/tasks", json={"title": "看租约"}).json()
    c.post(f"/api/v2/deals/{did}/documents", files={"file": ("a.pdf", b"%PDF-1", "application/pdf")})
    c.put("/api/v2/settings/views", json={"name": "我的", "config": {}})
    ents = {a["entity"] for a in c.get("/api/v2/admin/audit").json()}
    assert {"task", "document", "saved_view"} <= ents
    for src, val in (("OM", 5.0), ("RR", 6.0)):
        c.post(f"/api/v2/deals/{did}/evidence", json={"field": "analysis.exit_cap_rate", "value": val, "source": src,
                                                       "method": "pdf", "confidence": "high"})
    cid = c.get(f"/api/v2/deals/{did}/conflicts").json()[0]["id"]
    url = f"/api/v2/deals/{did}/conflicts/{cid}/resolve"
    assert c.post(url, json={"value": 5.0, "note": "按 OM"}).status_code == 200
    assert c.post(url, json={"value": 6.0, "note": "改主意"}).status_code == 409  # 此前：覆盖原裁决
    ap = c.post(f"/api/v2/deals/{did}/approvals", json={"kind": "general", "title": "x"}).json()
    assert c.delete(f"/api/v2/deals/{did}").status_code == 204
    assert c.post(f"/api/v2/deals/{did}/approvals/{ap['id']}/decide", json={"approve": True}).status_code == 404
    assert c.patch(f"/api/v2/deals/{did}/tasks/{t['id']}", json={"status": "done"}).status_code == 404


# 18 ---------------------------------------------------------------- 四眼原则：多人模式下自己录的数不能自己过关
def test_four_eyes_on_key_numbers():
    p = {"confidence": "high", "review_status": "overridden", "created_by": "amy", "reviewed_by": None}
    assert provenance.key_number_status(["f"], {"f": p})["ok"]                      # 单机：一人即全员
    assert not provenance.key_number_status(["f"], {"f": p}, four_eyes=True)["ok"]  # 多人：须他人复核
    assert not provenance.key_number_status(["f"], {"f": {**p, "reviewed_by": "amy"}}, four_eyes=True)["ok"]
    assert provenance.key_number_status(["f"], {"f": {**p, "reviewed_by": "bob"}}, four_eyes=True)["ok"]


def test_kill_criteria_moved_after_model_is_called_out(c):
    did = _deal(c, COM, kill_criteria=[{"metric": "irr_pct", "op": "<", "threshold": 12}])
    c.patch(f"/api/v2/deals/{did}", json={"kill_criteria": [{"metric": "irr_pct", "op": "<", "threshold": 1}]})
    keys = [p["key"] for p in c.get(f"/api/v2/deals/{did}/devils-memo").json()["points"]]
    assert "kill:moved" in keys


# 19 ---------------------------------------------------------------- 红队按运行编号缓存
def test_redteam_is_cached_per_run(c, monkeypatch):
    from app.domain.v2 import redteam
    from app.services.v2 import analysis
    did = _deal(c, COM)
    calls = {"n": 0}
    real = redteam.run

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)
    monkeypatch.setattr(redteam, "run", counting)
    analysis._RT_CACHE.clear()
    for _ in range(3):
        assert c.get(f"/api/v2/deals/{did}").status_code == 200
    assert calls["n"] == 1


# 20 ---------------------------------------------------------------- 中间件报错也跟语言走
def test_middleware_errors_follow_language(monkeypatch):
    from app.core import hardening
    monkeypatch.setattr(hardening, "MAX_BODY_BYTES", 10)
    mw = hardening.BodySizeLimit(None, limit=10)  # type: ignore[arg-type]
    sent: list[dict] = []

    async def send(m):
        sent.append(m)
    import asyncio
    asyncio.run(mw._reject(send, "en"))
    assert b"Request too large" in sent[1]["body"]
