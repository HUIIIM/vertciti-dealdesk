"""EchoWatch evidence bridge response size cap tests (backlog #27, 2026-10-26).

fetch_evidence previously used an injected/self-built httpx.Client.get
plus r.json(), reading the whole GET /api/v1/mentions response into
memory (six dimensions, one call each). per_page=3 limits item count,
not bytes; ECHOWATCH_URL is an environment-configured external HTTP
endpoint, so an abnormal or hijacked endpoint could return an oversize
response with no Content-Length precheck and no streaming stop.

Now fetch_evidence streams via client.stream plus the shared
http_capped.collect_capped helper, capped at MAX_EVIDENCE_BYTES
(= http_capped.MAX_JSON_BYTES = MAX_PAGE_BYTES): oversize degrades
honestly per dimension (error + items=[] and the overall reason stays
truthful), with no whole-body read and no truncated parsing. The
client-injection test seam is preserved. All tests use MockTransport;
no public network is touched.
"""

from __future__ import annotations

import json
import logging

import httpx

from app.services import echowatch_bridge as eb
from app.services import http_capped
from app.services import research_pipeline as rp


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _configured(monkeypatch):
    monkeypatch.setenv("ECHOWATCH_URL", "https://ew.test")
    monkeypatch.setenv("ECHOWATCH_TOKEN", "ew_x")


def test_evidence_cap_constant_matches_shared_caps():
    assert eb.MAX_EVIDENCE_BYTES == http_capped.MAX_JSON_BYTES == rp.MAX_PAGE_BYTES == 2_000_000


def test_under_cap_normal_still_parses(monkeypatch):
    _configured(monkeypatch)

    def handler(req):
        data = [{"title": "story", "url": "https://news.test/a", "source": "rss",
                 "published_at": "2026-10-20T08:00:00+00:00"}]
        return httpx.Response(200, json={"data": data})

    out = eb.fetch_evidence("tampa", client=_client(handler))
    assert out["ok"] is True
    assert out["dims"][0]["items"][0]["url"] == "https://news.test/a"
    assert all("error" not in d for d in out["dims"])


def test_exactly_at_cap_ok(monkeypatch):
    _configured(monkeypatch)
    payload = {"data": [{"title": "t", "url": "https://news.test/a"}]}
    monkeypatch.setattr(eb, "MAX_EVIDENCE_BYTES", len(json.dumps(payload).encode()))

    def handler(req):
        return httpx.Response(200, json=payload)

    out = eb.fetch_evidence("tampa", client=_client(handler))
    assert out["ok"] is True
    assert out["dims"][0]["items"][0]["title"] == "t"


def test_streamed_over_cap_honest_degrade(monkeypatch, caplog):
    _configured(monkeypatch)
    monkeypatch.setattr(eb, "MAX_EVIDENCE_BYTES", 100)
    big = json.dumps({"data": [{"title": "t", "url": "https://news.test/a"}]}).encode() + b" " * 500

    def handler(req):
        # ByteStream sends no Content-Length: the cap must trip mid-stream.
        return httpx.Response(200, stream=httpx.ByteStream(big))

    with caplog.at_level(logging.WARNING, logger=eb.logger.name):
        out = eb.fetch_evidence("tampa", client=_client(handler))
    assert out["ok"] is False
    assert out["reason"] == "EchoWatch 调用失败"
    assert all(d["items"] == [] for d in out["dims"])
    assert all("响应过大" in d["error"] for d in out["dims"])
    assert any("响应过大" in rec.message for rec in caplog.records)


def test_content_length_precheck_honest_degrade(monkeypatch):
    _configured(monkeypatch)
    monkeypatch.setattr(eb, "MAX_EVIDENCE_BYTES", 100)
    big = json.dumps({"data": [{"title": "t", "url": "https://news.test/a"}]}).encode() + b" " * 500

    def handler(req):
        return httpx.Response(200, content=big)

    out = eb.fetch_evidence("tampa", client=_client(handler))
    assert out["ok"] is False
    assert all("响应过大" in d["error"] for d in out["dims"])


def test_non_200_unchanged(monkeypatch):
    _configured(monkeypatch)

    def handler(req):
        return httpx.Response(503, json={"error": {"code": "down"}})

    out = eb.fetch_evidence("tampa", client=_client(handler))
    assert out["ok"] is False
    assert all(d["error"] == "EchoWatch 返回 HTTP 503" for d in out["dims"])
    assert all(d["items"] == [] for d in out["dims"])


def test_non_json_still_honest_error(monkeypatch):
    _configured(monkeypatch)

    def handler(req):
        return httpx.Response(200, content=b"<html>not json</html>")

    out = eb.fetch_evidence("tampa", client=_client(handler))
    assert out["ok"] is False
    assert out["reason"] == "EchoWatch 调用失败"
    assert all(d["items"] == [] for d in out["dims"])
    assert all("error" in d for d in out["dims"])


def test_one_dim_over_cap_other_dims_still_return(monkeypatch):
    _configured(monkeypatch)
    monkeypatch.setattr(eb, "MAX_EVIDENCE_BYTES", 200)
    big = b'{"data": []}' + b" " * 500

    def handler(req):
        if "vacancy" in req.url.params["q"]:
            return httpx.Response(200, stream=httpx.ByteStream(big))
        data = [{"title": "story", "url": "https://news.test/a"}]
        return httpx.Response(200, json={"data": data})

    out = eb.fetch_evidence("tampa", client=_client(handler))
    by = {d["dim"]: d for d in out["dims"]}
    assert out["ok"] is True
    assert by["vacancy"]["items"] == []
    assert "响应过大" in by["vacancy"]["error"]
    assert by["supply"]["items"][0]["url"] == "https://news.test/a"
