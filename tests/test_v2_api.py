"""v2 API 端到端：一笔交易从发现到持有的完整生命周期，每道关卡先验证“拦得住”再放行；
并覆盖矛盾登记、投委会包防篡改、可复现运行、版本对比、审计、比较页。"""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from app.domain import uw_commercial
from app.main import app

INPUTS = uw_commercial.example_39_main()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DEALDESK_DB", str(tmp_path / "v2.db"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DEALDESK_AUTH", raising=False)
    return TestClient(app)


def _deal(c: TestClient, **over) -> dict:
    body = {"name": "39-09 Main St", "track": "commercial", "address": "39-09 Main St, Flushing, NY",
            "asking_price": 42_000_000, "kill_criteria": [{"metric": "dscr", "op": "<", "threshold": 1.0}]}
    body.update(over)
    r = c.post("/api/v2/deals", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _stage(c: TestClient, did: int, target: str, ok: bool = True, **kw) -> dict:
    r = c.post(f"/api/v2/deals/{did}/stage", json={"target": target, **kw})
    assert (r.status_code == 200) is ok, (target, r.status_code, r.text)
    return r.json()


def test_full_lifecycle_with_gates(client):
    c = client
    d = _deal(c)
    did = d["id"]
    assert d["stage"] == "sourcing" and d["stage_label"] == "发现"
    ov = c.get(f"/api/v2/deals/{did}").json()
    assert ov["next_stage"] == "screening" and ov["next_gate"]["allowed"]

    _stage(c, did, "screening")
    blocked = _stage(c, did, "underwriting", ok=False)
    assert {ch["key"]: ch["ok"] for ch in blocked["gate"]["checks"]} == {"kill_defined": True, "version": False}
    _stage(c, did, "committee", ok=False)  # 不能跳级

    v1 = c.post(f"/api/v2/deals/{did}/versions", json={"inputs": INPUTS, "label": "首版：按 OM 口径"}).json()
    assert v1["run_id"].startswith("R") and v1["outputs"]["metrics"]["irr_pct"] == pytest.approx(1.0294497)
    _stage(c, did, "underwriting")

    # 进投委会前：关键数字未复核、红队未读 → 拦截
    gate = c.get(f"/api/v2/deals/{did}/gate", params={"target": "committee"}).json()
    st = {ch["key"]: ch["status"] for ch in gate["checks"]}
    assert not gate["allowed"] and st["key_numbers"] == "building" and st["redteam"] == "planned"

    rt = c.get(f"/api/v2/deals/{did}/redteam").json()
    assert rt["top"][0]["label"] == "租金水平" and not rt["read"]
    for f in rt["key_fields"]:
        r = c.post(f"/api/v2/deals/{did}/evidence", json={
            "field": f, "value": 1, "source": "OM 第 12 页", "method": "pdf", "confidence": "high", "page": 12})
        assert r.status_code == 201, r.text
        assert c.post(f"/api/v2/deals/{did}/review", json={"field": f}).status_code == 200

    # 矛盾：同一字段另一个来源给出不同数值 → 自动开矛盾、关卡标“风险”
    r = c.post(f"/api/v2/deals/{did}/evidence", json={
        "field": "analysis.exit_cap_rate", "value": 1.2, "source": "经纪人电话", "method": "manual",
        "confidence": "medium"}).json()
    assert r["conflict"] and r["conflict"]["diff_pct"] == pytest.approx(16.6666, rel=1e-3)
    c.post(f"/api/v2/deals/{did}/review", json={"field": "analysis.exit_cap_rate"})
    c.post(f"/api/v2/deals/{did}/redteam/read")
    gate = c.get(f"/api/v2/deals/{did}/gate", params={"target": "committee"}).json()
    assert {ch["key"]: ch["status"] for ch in gate["checks"]}["conflicts"] == "risk"
    cid = c.get(f"/api/v2/deals/{did}/conflicts", params={"status": "open"}).json()[0]["id"]
    assert c.post(f"/api/v2/deals/{did}/conflicts/{cid}/resolve", json={"value": 1, "note": ""}).status_code == 422
    assert c.post(f"/api/v2/deals/{did}/conflicts/{cid}/resolve",
                  json={"value": 1, "note": "以 OM 为准，经纪人口头报价未书面确认"}).status_code == 200

    passport = c.get(f"/api/v2/deals/{did}/passport", params={"field": "analysis.exit_cap_rate"}).json()
    assert len(passport["history"]) == 2 and passport["current"]["review_label"] == "人工改写"
    assert passport["conflicts"][0]["status"] == "resolved"

    ov = c.get(f"/api/v2/deals/{did}").json()
    assert ov["verification"]["key_reviewed"] == ov["verification"]["key_total"] > 0
    _stage(c, did, "committee")

    # 投委会：本机用户 = 董事长 → 赞成即通过；生成投委会包并校验原件 / 篡改件
    t = c.post(f"/api/v2/deals/{did}/committee/vote", json={"vote": "approve", "comment": "价格过高，需议价"}).json()
    assert t["tally"]["result"] == "approved"
    pdf = c.get(f"/api/v2/deals/{did}/committee/pack.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF" and pdf.headers["x-run-id"] == v1["run_id"]
    import io  # noqa: PLC0415

    from pypdf import PdfReader  # noqa: PLC0415
    text = "".join(pg.extract_text() or "" for pg in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "反方意见" in text and "不经 AI" in text  # 上会材料自带“最可能怎么失败”
    ok = c.post("/api/v2/committee/verify", files={"file": ("ic.pdf", pdf.content, "application/pdf")}).json()
    assert ok["genuine"] and ok["run_id"] == v1["run_id"]
    bad = c.post("/api/v2/committee/verify", files={"file": ("ic.pdf", pdf.content + b"x", "application/pdf")}).json()
    assert not bad["genuine"]
    xlsx = c.get(f"/api/v2/deals/{did}/committee/pack.xlsx")
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"
    assert len(c.get(f"/api/v2/deals/{did}/committee/packs").json()) == 2

    _stage(c, did, "diligence", ok=False)  # 还没记 BUY 决策
    assert c.post(f"/api/v2/deals/{did}/decisions", json={"verdict": "BUY", "rationale": "短"}).status_code == 422
    dec = c.post(f"/api/v2/deals/{did}/decisions", json={
        "verdict": "BUY", "rationale": "投委会通过；按 3800 万出价、低于反推最高价"}).json()
    assert dec["run_id"] == v1["run_id"] and dec["snapshot"]["metrics"]["dscr"] == pytest.approx(1.1337868)
    _stage(c, did, "diligence")

    task = c.post(f"/api/v2/deals/{did}/tasks", json={"title": "Phase I 环评", "stage": "diligence"}).json()
    blocked = _stage(c, did, "closing", ok=False)
    assert {ch["key"] for ch in blocked["gate"]["checks"] if not ch["ok"]} == {"dd_tasks", "payment"}
    c.patch(f"/api/v2/deals/{did}/tasks/{task['id']}", json={"status": "done"})
    assert c.post(f"/api/v2/deals/{did}/approvals", json={"kind": "payment", "title": "定金"}).status_code == 422
    ap = c.post(f"/api/v2/deals/{did}/approvals", json={"kind": "payment", "title": "定金", "amount": 500_000}).json()
    assert c.post(f"/api/v2/deals/{did}/approvals/{ap['id']}/decide", json={"approve": True}).json()["status"] == "approved"
    assert c.post(f"/api/v2/deals/{did}/approvals/{ap['id']}/decide", json={"approve": True}).status_code == 409
    _stage(c, did, "closing")
    _stage(c, did, "holding")

    # 持有期：录实际数 → 偏差表 + 事后归因（对照 BUY 时冻结的版本）
    for period, noi, occ in (("2027", 1_800_000, 95), ("2028", 1_850_000, 96)):
        assert c.put(f"/api/v2/deals/{did}/actuals", json={"period": period, "noi": noi, "occupancy_pct": occ}).status_code == 200
    h = c.get(f"/api/v2/deals/{did}/holding").json()
    assert h["basis"]["from_buy_decision"] and h["basis"]["run_id"] == v1["run_id"]
    assert h["variance"][0]["noi"]["variance"] == pytest.approx(-200_000)
    assert h["attribution"]["available"] and len(h["attribution"]["steps"]) == 3

    # 可复现：同编号重算分毫不差；版本对比
    vr = c.post(f"/api/v2/runs/{v1['run_id']}/verify").json()
    assert vr["identical"] and vr["same_engine"]
    inp2 = copy.deepcopy(INPUTS)
    inp2["analysis"]["exit_cap_rate"] = 5.5
    v2 = c.post(f"/api/v2/deals/{did}/versions", json={"inputs": inp2, "label": "退出 cap 上调 50bp"}).json()
    diff = c.get(f"/api/v2/deals/{did}/diff", params={"a": v1["id"], "b": v2["id"]}).json()
    assert [r["path"] for r in diff["inputs"]] == ["analysis.exit_cap_rate"]
    assert any(r["path"] == "irr_pct" and r["delta"] < 0 for r in diff["metrics"])

    kinds = [e["kind"] for e in c.get(f"/api/v2/deals/{did}/events").json()]
    for k in ("created", "version_saved", "stage_changed", "conflict_opened", "conflict_resolved", "redteam_read",
              "vote", "committee_pack", "decision", "approval_decided"):
        assert k in kinds, k
    audit = c.get("/api/v2/admin/audit", params={"entity": "deal", "entity_id": str(did)}).json()
    assert {a["action"] for a in audit} >= {"create", "update"} and all(a["actor"] == "local" for a in audit)
    assert c.get("/api/v2/portfolio").json()["count"] == 1


def test_kill_criteria_trip_blocks_committee_and_max_bid(client):
    c = client
    d = _deal(c, kill_criteria=[{"metric": "dscr", "op": "<", "threshold": 1.25},
                                {"metric": "irr_pct", "op": "<", "threshold": 8}])
    did = d["id"]
    c.post(f"/api/v2/deals/{did}/versions", json={"inputs": INPUTS})
    ov = c.get(f"/api/v2/deals/{did}").json()
    assert {r["metric"] for r in ov["kill"]["triggered"]} == {"dscr", "irr_pct"}
    mb = c.post(f"/api/v2/deals/{did}/max-bid", json={"targets": [{"metric": "irr_pct", "min": 8}]}).json()
    assert mb["max_bid"] == pytest.approx(37_979_400) and mb["binding"]["metric"] == "irr_pct"
    memo = c.get(f"/api/v2/deals/{did}/devils-memo").json()
    assert memo["high"] >= 1 and memo["headline"] and memo["run_id"]
    vq = c.get(f"/api/v2/deals/{did}/verify-queue").json()
    assert vq["items"] and vq["items"][0]["swing_bps"] >= vq["items"][-1]["swing_bps"] and vq["metric"] == "irr_pct"
    # 试算出价：在反推出的最高价处，IRR 下限型淘汰条件刚好不再触发
    pc = c.post(f"/api/v2/deals/{did}/price-check", json={"price": mb["max_bid"]}).json()
    assert pc["metrics"]["irr_pct"] >= 8 and "irr_pct" not in {r["metric"] for r in pc["kill"]["triggered"]}
    assert c.post(f"/api/v2/deals/{did}/price-check", json={"price": 0}).status_code == 422
    sc = c.post(f"/api/v2/deals/{did}/scenarios", json={}).json()
    assert sc["loss_probability_pct"] == 25.0
    r = c.post(f"/api/v2/deals/{did}/scenarios", json={"scenarios": [{"name": "x", "probability": 10, "changes": []}]})
    assert r.status_code == 422


def test_validation_and_not_found(client):
    c = client
    assert c.post("/api/v2/deals", json={"name": "x", "track": "hotel"}).status_code == 422
    assert c.post("/api/v2/deals", json={"name": "x", "track": "commercial", "evil": 1}).status_code == 422
    assert c.post("/api/v2/deals", json={"name": "x", "track": "commercial",
                                         "kill_criteria": [{"metric": "nope", "op": "<", "threshold": 1}]}).status_code == 422
    r = c.get("/api/v2/deals/999")
    assert r.status_code == 404 and r.json()["request_id"]
    did = _deal(c)["id"]
    r = c.post(f"/api/v2/deals/{did}/versions", json={"inputs": {"property": "坏数据"}})
    assert r.status_code == 422 and "计算失败" in r.json()["detail"]
    assert c.get(f"/api/v2/deals/{did}/redteam").status_code == 409  # 还没有版本


def test_documents_and_compare(client):
    c = client
    a, b = _deal(c)["id"], _deal(c, name="Deal B")["id"]
    up = c.post(f"/api/v2/deals/{a}/documents", files={"file": ("om.pdf", b"%PDF-1.4 test", "application/pdf")},
                data={"category": "om"})
    assert up.status_code == 201 and len(up.json()["sha256"]) == 64 and "content" not in up.json()
    dl = c.get(f"/api/v2/deals/{a}/documents/{up.json()['id']}")
    assert dl.content == b"%PDF-1.4 test" and dl.headers["x-content-sha256"] == up.json()["sha256"]
    for i in (a, b):
        c.post(f"/api/v2/deals/{i}/versions", json={"inputs": INPUTS})
    cmp_ = c.get("/api/v2/compare", params={"ids": f"{a},{b}"}).json()
    assert len(cmp_["deals"]) == 2
    assert c.get("/api/v2/compare", params={"ids": str(a)}).status_code == 422
    names = [x["name"] for x in c.get("/api/v2/deals", params={"q": "Deal B"}).json()]
    assert names == ["Deal B"]


def test_health_catalog_and_templates(client):
    c = client
    h = c.get("/api/v2/health").json()
    assert h["ok"] and h["db"]["revision"] == "0002" and h["engine_version"].startswith("2.0.0+")
    cat = c.get("/api/v2/catalog").json()
    assert cat["primary_metric"]["commercial"] == "irr_pct" and "rent_level" in str(cat["assumptions"])
    t = c.get("/api/v2/settings/templates", params={"kind": "kill_criteria"}).json()
    assert {x["name"] for x in t} == {"商业默认", "住宅默认"}
    assert c.put("/api/v2/settings/templates", json={"kind": "kill_criteria", "name": "保守",
                                                     "payload": {"criteria": [{"metric": "dscr", "op": "<",
                                                                               "threshold": 1.4}]}}).status_code == 200
    v = c.put("/api/v2/settings/views", json={"name": "只看商业", "config": {"track": "commercial"}}).json()
    assert c.delete(f"/api/v2/settings/views/{v['id']}").status_code == 204
    assert len(c.get("/api/v2/settings/data-sources").json()) == 5


def test_health_does_not_leak_db_error_text(client, monkeypatch):
    """health 不需要登录：数据库报错原文（可能含主机 / 用户名）不能原样回给调用方。"""
    from app.api.v2 import admin

    def boom():
        raise RuntimeError("could not connect to postgresql://dealdesk:s3cret@db.internal:5432/prod")
    monkeypatch.setattr(admin, "ensure_migrated", boom)
    h = client.get("/api/v2/health").json()
    assert h["ok"] is False and h["db"]["error"] == "RuntimeError"
    assert "s3cret" not in str(h) and "db.internal" not in str(h)


@pytest.mark.parametrize("path", ["/", "/index.html", "/d", "/d.html?addr=1", "/workbench.html", "/uw-commercial.html", "/res-legacy.html"])
def test_legacy_pages_redirect_to_v2(client, path):
    """v1 单页界面已下线：旧书签都 307 到 /app/；接口照常可用。"""
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/app/"
    assert client.get("/api/health").json()["ok"] is True
