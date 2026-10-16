"""fetch_page 页面大小上限测试（台账暂缓项回补，2026-10-16）.

fetch_page 改流式抓取：解码后字节数超过 MAX_PAGE_BYTES 即停手并诚实降级
（too_large），不再无上限整页读进内存；Content-Length 预检命中时不读 body。
全部用替身，不碰公网。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import research_pipeline as rp


class _Resp:
    def __init__(self, body=b"", headers=None, url="https://example.com/listing"):
        self.status_code = 200
        self._body = body
        self.headers = headers or {}
        self.url = url
        self.encoding = "utf-8"
        self.iter_called = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_bytes(self, chunk_size=65536):
        self.iter_called = True
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]


def _patch(monkeypatch, resp):
    monkeypatch.setattr(rp.httpx, "stream", lambda *a, **k: resp)
    monkeypatch.setattr(rp, "_is_public_url", lambda u: (True, ""))
    monkeypatch.setattr(rp, "robots_allowed", lambda u: (True, ""))


def test_under_cap_ok(monkeypatch):
    body = b"<html><body><p>List Price $485,000 Tampa home</p></body></html>"
    resp = _Resp(body=body)
    _patch(monkeypatch, resp)
    log = []
    r = rp.fetch_page("https://example.com/listing", log)
    assert r["ok"] and "485,000" in r["text"]
    assert r["html"].encode() == body
    assert r["final_url"] == "https://example.com/listing"
    assert any(e["status"] == "ok" for e in log)


def test_streamed_body_over_cap_stops(monkeypatch):
    monkeypatch.setattr(rp, "MAX_PAGE_BYTES", 100)
    # 无 Content-Length：靠流式累计字节数触发上限，且不得返回残页文本
    resp = _Resp(body=b"x" * 500)
    _patch(monkeypatch, resp)
    log = []
    r = rp.fetch_page("https://example.com/listing", log)
    assert not r["ok"] and r.get("too_large")
    assert "text" not in r and "html" not in r
    assert "页面过大" in r["note"]
    assert any(e["status"] == "failed" and "页面过大" in e["note"] for e in log)


def test_content_length_precheck_skips_body(monkeypatch):
    monkeypatch.setattr(rp, "MAX_PAGE_BYTES", 100)
    resp = _Resp(body=b"x" * 500, headers={"content-length": "500"})
    _patch(monkeypatch, resp)
    log = []
    r = rp.fetch_page("https://example.com/listing", log)
    assert not r["ok"] and r.get("too_large")
    assert resp.iter_called is False  # 预检命中直接停手，不读 body


def test_exactly_at_cap_ok(monkeypatch):
    monkeypatch.setattr(rp, "MAX_PAGE_BYTES", 64)
    body = b"<p>" + b"a" * 57 + b"</p>"  # 恰好 64 字节，不超限
    assert len(body) == 64
    resp = _Resp(body=body)
    _patch(monkeypatch, resp)
    r = rp.fetch_page("https://example.com/listing", [])
    assert r["ok"]
