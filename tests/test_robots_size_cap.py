"""robots.txt 抓取大小上限测试.

robots_disallows 改走与 fetch_page 同款流式＋上限 helper（_collect_capped，
共用 MAX_PAGE_BYTES 常量）：超限按"无 Disallow 信息"诚实降级（空列表）
并留 warning log，不整页读入内存、不截断残页凑解析。
全部用替身，不碰公网。
"""

from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import research_pipeline as rp


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


def _patch(monkeypatch, resp):
    monkeypatch.setattr(rp.httpx, "stream", lambda *a, **k: resp)
    rp._robots_cache.clear()


def test_robots_under_cap_parses(monkeypatch):
    body = b"User-agent: *\nDisallow: /private/\nDisallow: /tmp\n"
    _patch(monkeypatch, _Resp(body=body))
    d = rp.robots_disallows("robots-ok.example.com")
    assert d == ["/private/", "/tmp"]
    # 降级不得误伤：被禁路径仍拦、公开路径仍放行
    ok, _ = rp.robots_allowed("https://robots-ok.example.com/private/x")
    assert not ok
    ok2, _ = rp.robots_allowed("https://robots-ok.example.com/public/x")
    assert ok2


def test_robots_streamed_over_cap_degrades_to_no_disallow(monkeypatch, caplog):
    monkeypatch.setattr(rp, "MAX_ROBOTS_BYTES", 100)
    # 无 Content-Length：靠流式累计触发上限；残页里就算有 Disallow 也不许用
    body = b"User-agent: *\nDisallow: /private/\n" + b"x" * 500
    resp = _Resp(body=body)
    _patch(monkeypatch, resp)
    with caplog.at_level(logging.WARNING, logger=rp.logger.name):
        d = rp.robots_disallows("robots-big.example.com")
    assert d == []  # 诚实降级：无 Disallow 信息
    assert any("robots.txt 过大" in rec.message for rec in caplog.records)
    # 降级后 robots_allowed 按允许处理（与既有"检查异常按允许"口径一致）
    ok, _ = rp.robots_allowed("https://robots-big.example.com/private/x")
    assert ok


def test_robots_content_length_precheck_skips_body(monkeypatch, caplog):
    monkeypatch.setattr(rp, "MAX_ROBOTS_BYTES", 100)
    body = b"User-agent: *\nDisallow: /private/\n" + b"x" * 500
    resp = _Resp(body=body, headers={"content-length": str(len(body))})
    _patch(monkeypatch, resp)
    with caplog.at_level(logging.WARNING, logger=rp.logger.name):
        d = rp.robots_disallows("robots-clen.example.com")
    assert d == []
    assert resp.iter_called is False  # 预检命中直接停手，不读 body
    assert any("robots.txt 过大" in rec.message for rec in caplog.records)


def test_robots_exactly_at_cap_parses(monkeypatch):
    body = b"User-agent: *\nDisallow: /a\n"
    monkeypatch.setattr(rp, "MAX_ROBOTS_BYTES", len(body))
    _patch(monkeypatch, _Resp(body=body))
    assert rp.robots_disallows("robots-edge.example.com") == ["/a"]


def test_robots_non_200_returns_empty(monkeypatch):
    _patch(monkeypatch, _Resp(body=b"nope", status_code=404))
    assert rp.robots_disallows("robots-404.example.com") == []
