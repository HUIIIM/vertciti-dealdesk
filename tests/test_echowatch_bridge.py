"""EchoWatch → 市场调查候选证据：未配置/命中/失败三种情况都如实返回，绝不编造."""
import httpx

from app import echowatch_bridge as eb


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_unconfigured_is_honest(monkeypatch):
    monkeypatch.delenv("ECHOWATCH_URL", raising=False)
    monkeypatch.delenv("ECHOWATCH_TOKEN", raising=False)
    out = eb.fetch_evidence("tampa")
    assert out["ok"] is False and out["dims"] == []
    assert "未配置" in out["reason"]


def test_hits_per_dimension(monkeypatch):
    monkeypatch.setenv("ECHOWATCH_URL", "https://ew.test/")
    monkeypatch.setenv("ECHOWATCH_TOKEN", "ew_x")
    seen = []

    def handler(req):
        seen.append(req.url)
        q = req.url.params["q"]
        data = [{"title": f"{q} story", "url": "https://news.test/a", "source": "rss",
                 "published_at": "2026-10-20T08:00:00+00:00"}]
        return httpx.Response(200, json={"data": data, "page": 1, "per_page": 3, "total": 1})

    out = eb.fetch_evidence("tampa", client=_client(handler))
    assert out["ok"] is True
    assert [d["dim"] for d in out["dims"]] == list(eb.DIM_TERMS)
    assert out["dims"][3]["query"] == "Tampa rent"
    assert out["dims"][0]["items"][0]["url"] == "https://news.test/a"
    assert all(u.path == "/api/v1/mentions" and u.params["window"] == "30d" for u in seen)


def test_errors_and_linkless_items(monkeypatch):
    monkeypatch.setenv("ECHOWATCH_URL", "https://ew.test")
    monkeypatch.setenv("ECHOWATCH_TOKEN", "ew_x")

    def handler(req):
        if "jobs" in req.url.params["q"]:
            raise httpx.ConnectError("down")
        if "vacancy" in req.url.params["q"]:
            return httpx.Response(401, json={"error": {"code": "unauthorized"}})
        return httpx.Response(200, json={"data": [{"title": "no link", "url": None}]})

    out = eb.fetch_evidence("us", client=_client(handler))
    by = {d["dim"]: d for d in out["dims"]}
    assert out["ok"] is False and out["reason"] == "EchoWatch 调用失败"
    assert by["employment"]["error"].startswith("EchoWatch 不可达")
    assert by["vacancy"]["error"] == "EchoWatch 返回 HTTP 401"
    assert by["supply"]["items"] == []  # 没链接的提及不能当出处
    assert by["supply"]["query"] == "construction"  # 全美口径不加城市


def test_route(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    monkeypatch.delenv("ECHOWATCH_URL", raising=False)
    r = TestClient(app).get("/api/wb/research/evidence?market_key=phoenix")
    assert r.status_code == 200 and r.json()["ok"] is False
