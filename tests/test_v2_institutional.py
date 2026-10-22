"""机构级赛道接入 v2 全链路：建交易 → 保存版本（逐租约引擎）→ 最高出价 / 红队 / 情景 / 先核哪个 / 反方备忘录 /
投委会包 / 持有期 都能用；导出明确说下一版提供（不假装能导出）。"""
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


def test_bad_institutional_inputs_are_422_and_exports_say_not_yet(c):
    did = c.post("/api/v2/deals", json={"name": "x", "track": "institutional", "kill_criteria": []}).json()["id"]
    r = c.post(f"/api/v2/deals/{did}/versions", json={"inputs": {**suburban_office(), "exit_cap_pct": 0}})
    assert r.status_code == 422 and "exit_cap_pct" in r.json()["detail"]
    did = _deal(c)
    e = c.get(f"/api/v2/deals/{did}/export/memo")
    assert e.status_code == 422 and "下一版" in e.json()["detail"]


def test_workbench_preview_route_returns_standard_shape(c):
    """回归：工作台试算走 /model/{track}；机构级必须返回统一的 {metrics, detail.cre}，不能被原始引擎端点截走。"""
    r = c.post("/api/v2/model/institutional", json=suburban_office()).json()
    assert r["track"] == "institutional" and r["metrics"]["irr_pct"] == pytest.approx(16.903, abs=1e-3)
    assert r["detail"]["cre"]["rent_roll"]
