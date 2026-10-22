"""代码审查发现的问题（2026-10-22）逐条回归：每个测试在修复前都会失败。"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.core import hardening, security
from app.domain import uw_commercial
from app.main import app


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DEALDESK_DB", str(tmp_path / "rv.db"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DEALDESK_AUTH", raising=False)
    return TestClient(app)


def H(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


# F3 ---------------------------------------------------------------- 保留用户名不能借内置身份提权
def test_reserved_usernames_rejected(env):
    for name in ("local", "Local", "system", "anonymous"):
        with pytest.raises(ValueError, match="保留"):
            security.add_user(name, "viewer")
    r = env.post("/api/v2/admin/users", json={"username": "local", "role": "viewer"})
    assert r.status_code == 422 and "保留" in r.json()["detail"]


def test_builtin_local_privileges_only_without_auth(env, monkeypatch):
    assert security.builtin_roles() == {"local": "chairman"}
    assert security.is_builtin_local(security.LOCAL)
    assert not security.is_builtin_local(security.Actor("amy", "analyst"))
    monkeypatch.setenv("DEALDESK_AUTH", "on")
    assert security.builtin_roles() == {}  # 认证开启：没有任何名字自带董事长票
    assert not security.is_builtin_local(security.LOCAL)


# F4 ---------------------------------------------------------------- 唯一约束冲突是 409，不是 500
def test_duplicate_username_is_409(env):
    assert env.post("/api/v2/admin/users", json={"username": "amy", "role": "analyst"}).status_code == 201
    r = env.post("/api/v2/admin/users", json={"username": "amy", "role": "viewer"})
    assert r.status_code == 409 and "已存在" in r.json()["detail"]


def test_integrity_error_maps_to_409(env, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    from app.services.v2 import deals

    d = env.post("/api/v2/deals", json={"name": "D", "track": "commercial", "kill_criteria": []}).json()

    def boom(*_a, **_k):
        raise IntegrityError("insert", {}, Exception("uq_deal_versions_deal_no"))
    monkeypatch.setattr(deals, "save_version", boom)
    r = env.post(f"/api/v2/deals/{d['id']}/versions", json={"inputs": uw_commercial.example_39_main()})
    assert r.status_code == 409 and "刷新后重试" in r.json()["detail"] and r.json()["request_id"]


# F1 ---------------------------------------------------------------- 请求体硬上限（含无 Content-Length 的分块上传）
def _run(mw: hardening.BodySizeLimit, chunks: list[bytes], headers: list[tuple[bytes, bytes]]):
    sent: list[dict] = []
    seen = {"bytes": 0}

    async def downstream(scope, receive, send):
        while True:
            m = await receive()
            seen["bytes"] += len(m.get("body", b""))
            if not m.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    mw.app = downstream
    it = iter(chunks)

    async def receive():
        c = next(it, b"")
        return {"type": "http.request", "body": c, "more_body": bool(c)}

    async def send(m):
        sent.append(m)

    asyncio.run(mw({"type": "http", "headers": headers}, receive, send))
    return sent[0]["status"], seen["bytes"]


def test_body_limit_rejects_declared_and_chunked_oversize():
    mw = hardening.BodySizeLimit(None, limit=1000)  # type: ignore[arg-type]
    assert _run(mw, [b"x" * 10], [(b"content-length", b"5000")])[0] == 413  # 声明超限：不读一个字节
    status, read = _run(mw, [b"x" * 600] * 10, [])                        # 分块：边收边计数
    assert status == 413 and read <= 1200
    assert _run(mw, [b"x" * 300, b"x" * 300], [])[0] == 200


def test_body_limit_is_wired_into_app(env, monkeypatch):
    monkeypatch.setattr(hardening, "MAX_BODY_BYTES", 10)
    assert any(m.cls is hardening.BodySizeLimit for m in app.user_middleware)


# F2 ---------------------------------------------------------------- 只读也能调的计算接口：输入数量有上限
def test_scenarios_and_targets_are_capped(env):
    d = env.post("/api/v2/deals", json={"name": "D", "track": "commercial", "kill_criteria": []}).json()
    env.post(f"/api/v2/deals/{d['id']}/versions", json={"inputs": uw_commercial.example_39_main()})
    many = [{"name": f"s{i}", "probability": 1, "changes": []} for i in range(100)]
    assert env.post(f"/api/v2/deals/{d['id']}/scenarios", json={"scenarios": many}).status_code == 422
    tg = [{"metric": "dscr", "min": 1}] * 50
    assert env.post(f"/api/v2/deals/{d['id']}/max-bid", json={"targets": tg}).status_code == 422
    tags = ["t"] * 50
    assert env.post("/api/v2/deals", json={"name": "x", "track": "commercial", "tags": tags}).status_code == 422


# F5 ---------------------------------------------------------------- 代理后的来源 IP
def test_client_ip_trusts_forwarded_for_only_when_configured(monkeypatch):
    monkeypatch.delenv("DEALDESK_TRUST_PROXY", raising=False)
    assert hardening.client_ip("10.0.0.1", "1.2.3.4") == "10.0.0.1"  # 缺省不信（可伪造）
    monkeypatch.setenv("DEALDESK_TRUST_PROXY", "1")
    assert hardening.client_ip("10.0.0.1", "1.2.3.4, 10.0.0.1") == "1.2.3.4"
    assert hardening.client_ip("10.0.0.1", None) == "10.0.0.1"
