"""ddg_search 搜索响应大小上限测试.

ddg_search 改走与 fetch_page/robots 同款流式＋上限 helper（_collect_capped，
上限 MAX_SEARCH_BYTES = MAX_PAGE_BYTES）：超限按该端点失败诚实降级
（转下一端点/空结果＋log 留痕），不整页读入内存、不截断残页凑解析。
全部用替身，不碰公网。
"""

from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import research_pipeline as rp


def _links_html(url="https://example.com/listing-1", title="Example Listing One"):
    return f'<html><body><a href="{url}">{title}</a></body></html>'.encode()


class _Resp:
    def __init__(self, body=b"", headers=None, status_code=200):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}
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


class _Seq:
    """按端点 URL 返回不同替身的 httpx.stream 替身，并记录调用顺序。"""

    def __init__(self, by_host):
        self.by_host = by_host
        self.calls = []

    def __call__(self, method, url, **kwargs):
        self.calls.append(url)
        host = url.split("/")[2]
        resp = self.by_host[host]
        if isinstance(resp, Exception):
            raise resp
        return resp


def test_ddg_under_cap_parses_links(monkeypatch):
    lite = _Resp(body=_links_html())
    html_ep = _Resp(body=b"should not be used")
    seq = _Seq({"lite.duckduckgo.com": lite, "html.duckduckgo.com": html_ep})
    monkeypatch.setattr(rp.httpx, "stream", seq)
    log = []
    out = rp.ddg_search("450 W 44th St", log)
    assert out == [{"title": "Example Listing One",
                    "url": "https://example.com/listing-1"}]
    assert seq.calls == ["https://lite.duckduckgo.com/lite/"]
    assert any(e["status"] == "ok" for e in log)


def test_ddg_streamed_over_cap_falls_back_to_next_endpoint(monkeypatch, caplog):
    monkeypatch.setattr(rp, "MAX_SEARCH_BYTES", 100)
    # lite 无 Content-Length：流式累计触发上限；残页头部就算有可用链接也不许用
    lite_body = _links_html("https://bad.example/partial", "Partial Should Not Parse") + b"x" * 500
    lite = _Resp(body=lite_body)
    html_ep = _Resp(body=_links_html("https://example.com/good", "Good Fallback Result"))
    seq = _Seq({"lite.duckduckgo.com": lite, "html.duckduckgo.com": html_ep})
    monkeypatch.setattr(rp.httpx, "stream", seq)
    log = []
    with caplog.at_level(logging.WARNING, logger=rp.logger.name):
        out = rp.ddg_search("450 W 44th St", log)
    assert out == [{"title": "Good Fallback Result",
                    "url": "https://example.com/good"}]
    assert len(seq.calls) == 2
    assert any(e["status"] == "failed" and "搜索响应过大" in e["note"] for e in log)
    assert any("ddg_search 响应过大" in rec.message for rec in caplog.records)


def test_ddg_content_length_precheck_skips_body(monkeypatch):
    monkeypatch.setattr(rp, "MAX_SEARCH_BYTES", 100)
    body = _links_html() + b"x" * 500
    lite = _Resp(body=body, headers={"content-length": str(len(body))})
    html_ep = _Resp(body=_links_html("https://example.com/good2", "Second Endpoint Win"))
    seq = _Seq({"lite.duckduckgo.com": lite, "html.duckduckgo.com": html_ep})
    monkeypatch.setattr(rp.httpx, "stream", seq)
    out = rp.ddg_search("q", [])
    assert lite.iter_called is False  # 预检命中直接停手，不读 body
    assert out[0]["url"] == "https://example.com/good2"


def test_ddg_both_endpoints_over_cap_returns_empty(monkeypatch):
    monkeypatch.setattr(rp, "MAX_SEARCH_BYTES", 50)
    lite = _Resp(body=_links_html() + b"x" * 500)
    html_ep = _Resp(body=_links_html() + b"y" * 500)
    seq = _Seq({"lite.duckduckgo.com": lite, "html.duckduckgo.com": html_ep})
    monkeypatch.setattr(rp.httpx, "stream", seq)
    log = []
    out = rp.ddg_search("q", log)
    assert out == []  # 两端点都超限：诚实空结果，不拿残页凑数
    assert sum(1 for e in log if "搜索响应过大" in e["note"]) == 2


def test_ddg_exactly_at_cap_ok(monkeypatch):
    body = _links_html()
    monkeypatch.setattr(rp, "MAX_SEARCH_BYTES", len(body))
    seq = _Seq({"lite.duckduckgo.com": _Resp(body=body),
                "html.duckduckgo.com": _Resp(body=b"unused")})
    monkeypatch.setattr(rp.httpx, "stream", seq)
    out = rp.ddg_search("q", [])
    assert len(out) == 1


def test_ddg_non_200_falls_back(monkeypatch):
    seq = _Seq({"lite.duckduckgo.com": _Resp(body=b"", status_code=503),
                "html.duckduckgo.com": _Resp(body=_links_html())})
    monkeypatch.setattr(rp.httpx, "stream", seq)
    log = []
    out = rp.ddg_search("q", log)
    assert len(out) == 1
    assert any(e["status"] == "failed" and "HTTP 503" in e["note"] for e in log)


def test_ddg_search_cap_constant_matches_page_cap():
    assert rp.MAX_SEARCH_BYTES == rp.MAX_PAGE_BYTES == 2_000_000
