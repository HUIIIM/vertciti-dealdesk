"""权限分权（董事长 / 分析 / 只读 / 匿名）与可观测（请求编号、未捕获异常上报）。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import observability, security
from app.domain import uw_commercial
from app.main import app


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DEALDESK_DB", str(tmp_path / "sec.db"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DEALDESK_AUTH", "on")
    tokens = {r: security.add_user(f"u_{r}", r) for r in ("chairman", "analyst", "viewer")}
    tokens["analyst2"] = security.add_user("u_analyst2", "analyst")
    return TestClient(app), tokens


def H(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def test_anonymous_gets_401_on_v2_and_token_is_hashed(env):
    c, tok = env
    assert c.get("/api/v2/deals").status_code == 401
    assert c.get("/api/v2/deals", headers=H("dd_wrong")).status_code == 401
    assert c.get("/api/v2/health").status_code == 200  # 健康检查不需登录
    me = c.get("/api/v2/me", headers=H(tok["viewer"])).json()
    assert me["role"] == "viewer" and me["role_label"] == "只读" and "deal.write" not in me["permissions"]
    users = c.get("/api/v2/admin/users", headers=H(tok["chairman"])).json()
    assert all("token" not in u and "token_sha256" not in u for u in users)


def test_role_matrix(env):
    c, tok = env
    body = {"name": "D", "track": "commercial", "address": "1 St", "asking_price": 1,
            "kill_criteria": [{"metric": "dscr", "op": "<", "threshold": 1}]}
    assert c.post("/api/v2/deals", json=body, headers=H(tok["viewer"])).status_code == 403
    r = c.post("/api/v2/deals", json=body, headers=H(tok["analyst"]))
    assert r.status_code == 201 and r.json()["created_by"] == "u_analyst"
    did = r.json()["id"]
    assert c.get(f"/api/v2/deals/{did}", headers=H(tok["viewer"])).status_code == 200
    assert c.delete(f"/api/v2/deals/{did}", headers=H(tok["analyst"])).status_code == 403  # 归档仅董事长
    assert c.get("/api/v2/admin/audit", headers=H(tok["analyst"])).status_code == 403
    assert c.put("/api/v2/settings/templates", headers=H(tok["analyst"]),
                 json={"kind": "market", "name": "m", "payload": {}}).status_code == 403


def test_payment_only_chairman_and_no_self_approval(env):
    c, tok = env
    did = c.post("/api/v2/deals", headers=H(tok["analyst"]), json={
        "name": "P", "track": "commercial", "kill_criteria": []}).json()["id"]
    ap = c.post(f"/api/v2/deals/{did}/approvals", headers=H(tok["analyst"]),
                json={"kind": "payment", "title": "定金", "amount": 1000}).json()
    url = f"/api/v2/deals/{did}/approvals/{ap['id']}/decide"
    assert c.post(url, headers=H(tok["analyst2"]), json={"approve": True}).status_code == 403  # 分析不能批付款
    assert c.post(url, headers=H(tok["viewer"]), json={"approve": True}).status_code == 403
    assert c.post(url, headers=H(tok["chairman"]), json={"approve": True}).json()["decided_by"] == "u_chairman"
    own = c.post(f"/api/v2/deals/{did}/approvals", headers=H(tok["chairman"]),
                 json={"kind": "payment", "title": "尾款", "amount": 9}).json()
    r = c.post(f"/api/v2/deals/{did}/approvals/{own['id']}/decide", headers=H(tok["chairman"]), json={"approve": True})
    assert r.status_code == 409 and "自己" in r.json()["detail"]
    # 一般审批：分析可以发起，只有董事长能决定
    g = c.post(f"/api/v2/deals/{did}/approvals", headers=H(tok["analyst"]),
               json={"kind": "general", "title": "延期"}).json()
    assert c.post(f"/api/v2/deals/{did}/approvals/{g['id']}/decide", headers=H(tok["analyst2"]),
                  json={"approve": True}).status_code == 403


def test_committee_vote_rights_and_veto(env):
    c, tok = env
    did = c.post("/api/v2/deals", headers=H(tok["chairman"]), json={
        "name": "IC", "track": "commercial", "address": "1 St", "asking_price": 1,
        "kill_criteria": [{"metric": "dscr", "op": "<", "threshold": 0.5}]}).json()["id"]
    c.post(f"/api/v2/deals/{did}/versions", headers=H(tok["chairman"]), json={"inputs": uw_commercial.example_39_main()})
    from app.services.persistence.engine import session_scope
    from app.services.persistence.schema import Deal
    with session_scope() as s:  # 直接置于投委会阶段（关卡另有测试）
        s.get(Deal, did).stage = "committee"
    v = f"/api/v2/deals/{did}/committee/vote"
    assert c.post(v, headers=H(tok["viewer"]), json={"vote": "approve"}).status_code == 403
    assert c.post(v, headers=H(tok["analyst"]), json={"vote": "approve"}).json()["tally"]["result"] == "pending"
    t = c.post(v, headers=H(tok["chairman"]), json={"vote": "reject"}).json()["tally"]
    assert t["result"] == "rejected" and t["why"] == "董事长否决"
    t = c.post(v, headers=H(tok["chairman"]), json={"vote": "approve"}).json()  # 改票：每人每版一票
    assert t["tally"]["result"] == "approved" and len(t["votes"]) == 2


def test_v1_protection_is_opt_in(env, monkeypatch):
    c, tok = env
    from test_scoring import base_residential
    body = {"track": "residential", "name": "a", "address": "b", "input": base_residential()}
    assert c.post("/api/projects", json=body).status_code == 200  # 缺省不改变 v1 公开行为
    assert c.post("/api/score", json={"track": "residential", "input": base_residential()}).status_code == 200
    monkeypatch.setenv("DEALDESK_AUTH_PROTECT_V1", "1")
    assert c.post("/api/projects", json=body).status_code == 401
    assert c.post("/api/projects", json=body, headers=H(tok["viewer"])).status_code == 403
    assert c.post("/api/projects", json=body, headers=H(tok["analyst"])).status_code == 200
    assert c.post("/api/score", json={"track": "residential", "input": base_residential()}).status_code == 200
    # SEC-A1（2026-10-26）：flag 同时管 v1 持久化面的读与 wb/research 写——匿名读 401、只读令牌可读
    assert c.get("/api/projects").status_code == 401
    assert c.get("/api/projects", headers=H(tok["viewer"])).status_code == 200
    assert c.get("/api/compare?ids=1").status_code == 401
    assert c.post("/api/wb/research", json={"bogus": True}).status_code == 401


def test_v1_stays_open_in_single_user_mode(tmp_path, monkeypatch):
    # 自 PR #35 吸收（与门语义定版不冲突的增量）：认证关闭（单机模式）时 v1 面保持全开
    monkeypatch.setenv("DEALDESK_DB", str(tmp_path / "local.db"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DEALDESK_AUTH", raising=False)
    from test_scoring import base_residential
    c = TestClient(app)
    assert c.get("/api/projects").status_code == 200
    assert c.post("/api/score", json={"track": "residential", "input": base_residential()}).status_code == 200


def test_request_id_and_unhandled_error_reporting(monkeypatch):
    monkeypatch.delenv("DEALDESK_AUTH", raising=False)
    mini = FastAPI()
    mini.add_middleware(observability.RequestContextMiddleware)

    @mini.get("/api/boom")
    def boom():
        raise RuntimeError("测试用：故意抛错")

    @mini.get("/api/ok")
    def ok():
        return {"ok": True}

    c = TestClient(mini, raise_server_exceptions=False)
    r = c.get("/api/ok", headers={"X-Request-ID": "abc-123"})
    assert r.headers["x-request-id"] == "abc-123"
    r = c.get("/api/ok", headers={"X-Request-ID": "bad id with spaces"})
    assert r.headers["x-request-id"] != "bad id with spaces" and len(r.headers["x-request-id"]) == 32
    before = len(observability.RECENT_ERRORS)
    r = c.get("/api/boom", headers={"X-Request-ID": "trace-1"})
    assert r.status_code == 500 and r.json() == {"detail": "服务器内部错误", "request_id": "trace-1"}
    assert len(observability.RECENT_ERRORS) == min(before + 1, 100)
    err = observability.RECENT_ERRORS[0]
    assert err["request_id"] == "trace-1" and "RuntimeError" in err["error"] and "测试用" in err["trace"]


def test_json_log_format():
    import logging
    rec = logging.LogRecord("dealdesk", logging.INFO, __file__, 1, "hello %s", ("x",), None)
    rec.extra_fields = {"path": "/api/x"}
    import json
    d = json.loads(observability.JsonFormatter().format(rec))
    assert d["msg"] == "hello x" and d["level"] == "INFO" and d["path"] == "/api/x" and "ts" in d


# ---------------------------------------------------------------- HTTP 加固
def test_security_headers_and_strict_csp_on_app():
    c = TestClient(app)
    r = c.get("/api/v2/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" not in r.headers  # v1 页面 CSP 由 vercel.json hash 管
    html = c.get("/app/")
    csp = html.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and "unsafe-inline" not in csp


def test_cookie_token_is_ignored_no_csrf_surface(env):
    c, tok = env
    c.cookies.set("dd_token", tok["chairman"])
    assert c.get("/api/v2/deals").status_code == 401  # 只认 Authorization 头


def test_bad_token_bruteforce_is_throttled(env, monkeypatch):
    from app.core.hardening import AuthThrottle
    monkeypatch.setattr(observability, "AUTH_THROTTLE", AuthThrottle(limit=3, window=60))
    c, tok = env
    for _ in range(3):
        assert c.get("/api/v2/deals", headers=H("dd_guess")).status_code == 401
    r = c.get("/api/v2/deals", headers=H("dd_guess"))
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    # 被封期间连正确令牌也挡（防止撞库者拿到“对了”的信号），没带令牌的请求不计数
    assert c.get("/api/v2/deals", headers=H(tok["viewer"])).status_code == 429
    assert c.get("/api/v2/health").status_code == 200


def test_throttle_window_slides():
    from app.core.hardening import AuthThrottle
    t = AuthThrottle(limit=2, window=10)
    t.fail("ip", now=0)
    t.fail("ip", now=1)
    assert t.blocked("ip", now=2) == pytest.approx(8)
    assert t.blocked("ip", now=10.5) == 0  # 第一次失败滑出窗口
    assert t.blocked("other", now=2) == 0
