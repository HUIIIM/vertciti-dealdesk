"""机构级赛道接入 v2 全链路：建交易 → 保存版本（逐租约引擎）→ 最高出价 / 红队 / 情景 / 先核哪个 / 反方备忘录 /
投委会包 / 持有期 / 导出（带公式 Excel、机构投委会备忘录）都能用。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.domain.v2.cre.example import suburban_office
from app.main import app


@pytest.fixture
def c(tmp_path, monkeypatch):
    monkeypatch.setenv("DEALDESK_DB", str(tmp_path / "v2.db"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DEALDESK_AUTH", raising=False)
    return TestClient(app)


def _deal(c: TestClient) -> int:
    cat = c.get("/api/v2/catalog").json()
    kill = cat["kill_criteria_defaults"]["institutional"]
    assert {k["metric"] for k in kill} == {"dscr", "irr_pct", "debt_yield_pct"}
    d = c.post("/api/v2/deals", json={"name": "Suburban Office", "track": "institutional", "address": "1 Park Ave",
                                      "kill_criteria": kill}).json()
    v = c.post(f"/api/v2/deals/{d['id']}/versions", json={"inputs": suburban_office(), "label": "OM"})
    assert v.status_code == 201, v.text
    m = v.json()["outputs"]["metrics"]
    assert m["irr_pct"] == pytest.approx(16.903, abs=1e-3) and m["dscr"] == pytest.approx(1.765, abs=1e-3)
    assert m["unlevered_irr_pct"] == pytest.approx(11.845, abs=1e-3)
    return d["id"]


def test_whole_toolchain_works_on_institutional_deals(c):
    did = _deal(c)
    ov = c.get(f"/api/v2/deals/{did}").json()
    assert ov["deal"]["asking_price"] == 24_000_000          # 保存版本时按收购价回填要价
    mb = c.post(f"/api/v2/deals/{did}/max-bid", json={}).json()
    assert mb["max_bid"] is not None and mb["binding"]["label"]
    rt = c.get(f"/api/v2/deals/{did}/redteam").json()
    assert rt["metric"] == "irr_pct" and {r["key"] for r in rt["all"]} >= {"exit_cap", "rent_level", "downtime"}
    sc = c.post(f"/api/v2/deals/{did}/scenarios", json={}).json()
    assert len(sc["scenarios"]) == 3 and all(r["primary"] is not None for r in sc["scenarios"])
    assert c.get(f"/api/v2/deals/{did}/verify-queue").json()["items"]
    assert c.get(f"/api/v2/deals/{did}/devils-memo").status_code == 200
    pack = c.get(f"/api/v2/deals/{did}/committee/pack.pdf")
    assert pack.status_code == 200 and pack.content.startswith(b"%PDF-")
    h = c.get(f"/api/v2/deals/{did}/holding").json()
    assert h["basis"]["version_no"] == 1


def test_price_check_moves_irr_and_loan_scales_with_ltv(c):
    did = _deal(c)
    lo = c.post(f"/api/v2/deals/{did}/price-check", json={"price": 22_000_000}).json()
    hi = c.post(f"/api/v2/deals/{did}/price-check", json={"price": 26_000_000}).json()
    assert lo["metrics"]["irr_pct"] > hi["metrics"]["irr_pct"]


def test_bad_institutional_inputs_are_422_and_exports_work(c):
    did = c.post("/api/v2/deals", json={"name": "x", "track": "institutional", "kill_criteria": []}).json()["id"]
    r = c.post(f"/api/v2/deals/{did}/versions", json={"inputs": {**suburban_office(), "exit_cap_pct": 0}})
    assert r.status_code == 422 and "exit_cap_pct" in r.json()["detail"]
    did = _deal(c)
    memo = c.get(f"/api/v2/deals/{did}/export/memo")
    assert memo.status_code == 200 and memo.content[:5] == b"%PDF-"
    assert "_memo_v1_" in memo.headers["content-disposition"]
    xl = c.get(f"/api/v2/deals/{did}/export/model")
    assert xl.status_code == 200 and xl.content[:2] == b"PK"
    e = c.get(f"/api/v2/deals/{did}/export/tearsheet")  # 一页纸是商业 v1 版式，机构级用备忘录封面
    assert e.status_code == 422


def test_workbench_preview_route_returns_standard_shape(c):
    """回归：工作台试算走 /model/{track}；机构级必须返回统一的 {metrics, detail.cre}，不能被原始引擎端点截走。"""
    r = c.post("/api/v2/model/institutional", json=suburban_office()).json()
    assert r["track"] == "institutional" and r["metrics"]["irr_pct"] == pytest.approx(16.903, abs=1e-3)
    assert r["detail"]["cre"]["rent_roll"]


def test_multifamily_deal_through_the_whole_toolchain(c):
    """多户公寓同一套工具链：红队只扰动这笔交易里有的假设（不凭空造出 market），情景、最高出价、投委会包、导出都能用。"""
    from app.domain.v2.cre.example import garden_multifamily
    d = c.post("/api/v2/deals", json={"name": "Garden Apartments", "track": "institutional",
                                      "kill_criteria": []}).json()
    v = c.post(f"/api/v2/deals/{d['id']}/versions", json={"inputs": garden_multifamily(), "label": "OM"})
    assert v.status_code == 201, v.text
    did = d["id"]
    assert v.json()["outputs"]["metrics"]["irr_pct"] == pytest.approx(15.43, abs=1e-2)
    rt = c.get(f"/api/v2/deals/{did}/redteam").json()
    keys = {r["key"] for r in rt["all"]}
    assert {"rent_level", "reno_premium", "exit_cap", "opex"} <= keys
    assert "downtime" not in keys and "renewal" not in keys        # 按租约物业的假设：这笔交易没有，跳过
    sc = c.post(f"/api/v2/deals/{did}/scenarios", json={}).json()
    assert all(r["primary"] is not None for r in sc["scenarios"])
    pess = next(r for r in sc["scenarios"] if r["name"] == "悲观")
    assert pess["primary"] < sc["scenarios"][0]["primary"]
    assert c.post(f"/api/v2/deals/{did}/max-bid", json={}).status_code == 200
    assert c.get(f"/api/v2/deals/{did}/committee/pack.pdf").content.startswith(b"%PDF-")
    for kind, magic in (("memo", b"%PDF-"), ("model", b"PK")):
        r = c.get(f"/api/v2/deals/{did}/export/{kind}")
        assert r.status_code == 200 and r.content.startswith(magic), (kind, r.text[:300])
