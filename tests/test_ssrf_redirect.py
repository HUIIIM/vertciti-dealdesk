"""SSRF：公网页面 302 到内网 / 云元数据地址必须被拦（CodeQL py/full-ssrf）。

httpx 自动跟跳转时只有第一跳过了公网检查；现在每一跳都重新检查。
"""
from __future__ import annotations

from app.services import research_pipeline as rp

PUBLIC = "https://93.184.216.34/listing"  # 公网 IP 字面量：不依赖 DNS


class _Resp:
    def __init__(self, status: int, url: str, location: str | None = None, body: bytes = b"") -> None:
        self.status_code, self.url, self._body, self.encoding = status, url, body, "utf-8"
        self.headers = {"location": location} if location else {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_bytes(self, chunk_size=65536):
        yield self._body


def _serve(monkeypatch, responses: dict[str, _Resp]) -> list[str]:
    hit: list[str] = []

    def stream(method, url, **kw):
        assert kw.get("follow_redirects") is False, "不许让 httpx 自动跟跳转"
        hit.append(url)
        return responses[url]
    monkeypatch.setattr(rp.httpx, "stream", stream)
    monkeypatch.setattr(rp, "robots_allowed", lambda url: (True, ""))
    return hit


def test_redirect_to_metadata_ip_is_blocked(monkeypatch):
    meta = "http://169.254.169.254/latest/meta-data/"
    hit = _serve(monkeypatch, {PUBLIC: _Resp(302, PUBLIC, meta)})
    out = rp.fetch_page(PUBLIC, [])
    assert out["ok"] is False and "跳转被拦" in out["note"]
    assert meta not in hit  # 内网地址一次都没请求


def test_redirect_to_public_page_is_followed(monkeypatch):
    nxt = "https://93.184.216.35/final"
    hit = _serve(monkeypatch, {PUBLIC: _Resp(301, PUBLIC, "https://93.184.216.35/final"),
                               nxt: _Resp(200, nxt, body=b"<html><body>3 bed 2 bath</body></html>")})
    out = rp.fetch_page(PUBLIC, [])
    assert out["ok"] is True and out["final_url"] == nxt and "3 bed" in out["text"]
    assert hit == [PUBLIC, nxt]


def test_redirect_loop_stops(monkeypatch):
    _serve(monkeypatch, {PUBLIC: _Resp(302, PUBLIC, PUBLIC)})
    out = rp.fetch_page(PUBLIC, [])
    assert out["ok"] is False and "跳转次数过多" in out["note"]


def test_robots_redirect_to_private_is_not_requested(monkeypatch):
    hit: list[str] = []

    def stream(method, url, **kw):
        hit.append(url)
        return _Resp(302, url, "http://10.0.0.5/robots.txt")
    monkeypatch.setattr(rp.httpx, "stream", stream)
    rp._robots_cache.clear()
    assert rp.robots_disallows("93.184.216.34") == []  # 拦下后按“无规则”且不缓存
    assert hit == ["https://93.184.216.34/robots.txt"]
    assert "93.184.216.34" not in rp._robots_cache


def test_parse_address_long_input_is_fast_and_unparsed():
    import time
    t0 = time.perf_counter()
    out = rp.parse_address("," * 50_000 + "x")
    assert time.perf_counter() - t0 < 0.5 and out["parsed"] is False
    assert rp.parse_address("39-09 Main St, Flushing, NY 11354")["parsed"] is True
