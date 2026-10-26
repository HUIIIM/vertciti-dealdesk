"""robots 成功缓存 TTL 测试.

旧行为：第 20 项修复后失败已不缓存，但 200/404 的确定性结果仍是
进程内永不过期的裸 dict——站点事后修改 robots.txt（如新增
Disallow），长驻进程永远读不到新规则。

新口径：缓存条目带 time.monotonic 时间戳，TTL =
ROBOTS_CACHE_TTL_SECONDS（24h，依据见 app/research_pipeline.py
常量注释）；未过期不重抓、过期重抓；过期后重抓失败不回退旧规则、
不写缓存（第 20 项口径不变）。全部用替身，不碰公网。
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import research_pipeline as rp

V1 = b"User-agent: *\nDisallow: /search\n"
V2 = b"User-agent: *\nDisallow: /search\nDisallow: /new-private/\n"


class _Resp:
    def __init__(self, body=b"", headers=None, status_code=200):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}
        self.encoding = "utf-8"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_bytes(self, chunk_size=65536):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]


class _Seq:
    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = 0

    def __call__(self, *a, **k):
        self.calls += 1
        step = self.steps.pop(0) if self.steps else self.steps
        if isinstance(step, BaseException):
            raise step
        return step


def _install(monkeypatch, seq):
    monkeypatch.setattr(rp.httpx, "stream", seq)
    rp._robots_cache.clear()


def _expire(host):
    fetched_at, rules = rp._robots_cache[host]
    rp._robots_cache[host] = (
        fetched_at - rp.ROBOTS_CACHE_TTL_SECONDS - 1, rules)


def test_ttl_constant_is_24h():
    assert rp.ROBOTS_CACHE_TTL_SECONDS == 24 * 60 * 60


def test_within_ttl_no_refetch(monkeypatch):
    seq = _Seq([_Resp(body=V1), _Resp(body=V2)])
    _install(monkeypatch, seq)
    host = "robots-ttl-fresh.example.com"
    assert rp.robots_disallows(host) == ["/search"]
    assert rp.robots_disallows(host) == ["/search"]
    assert seq.calls == 1


def test_expired_200_refetches_new_rules(monkeypatch):
    seq = _Seq([_Resp(body=V1), _Resp(body=V2)])
    _install(monkeypatch, seq)
    host = "robots-ttl-expire.example.com"
    assert rp.robots_disallows(host) == ["/search"]
    ok, _ = rp.robots_allowed(f"https://{host}/new-private/x")
    assert ok  # 旧规则里没有这条 Disallow
    _expire(host)
    assert rp.robots_disallows(host) == ["/search", "/new-private/"]
    assert seq.calls == 2
    ok, note = rp.robots_allowed(f"https://{host}/new-private/x")
    assert not ok and "/new-private/" in note


def test_expired_404_refetches_and_finds_new_file(monkeypatch):
    seq = _Seq([_Resp(body=b"not found", status_code=404),
                _Resp(body=V1)])
    _install(monkeypatch, seq)
    host = "robots-ttl-404.example.com"
    assert rp.robots_disallows(host) == []
    assert host in rp._robots_cache
    assert rp.robots_disallows(host) == []
    assert seq.calls == 1  # 未过期不重抓
    _expire(host)
    # 站点后来上线了 robots.txt：过期后重抓拿到真实规则
    assert rp.robots_disallows(host) == ["/search"]
    assert seq.calls == 2


def test_refreshed_entry_gets_new_timestamp(monkeypatch):
    seq = _Seq([_Resp(body=V1), _Resp(body=V2), _Resp(body=V1)])
    _install(monkeypatch, seq)
    host = "robots-ttl-refresh.example.com"
    assert rp.robots_disallows(host) == ["/search"]
    _expire(host)
    assert rp.robots_disallows(host) == ["/search", "/new-private/"]
    # 刷新后的条目重新计时：紧接着的调用不再重抓
    assert rp.robots_disallows(host) == ["/search", "/new-private/"]
    assert seq.calls == 2


def test_expired_then_failure_not_cached_no_stale(monkeypatch):
    seq = _Seq([_Resp(body=V1),
                _Resp(body=b"oops", status_code=500),
                _Resp(body=V2)])
    _install(monkeypatch, seq)
    host = "robots-ttl-fail.example.com"
    assert rp.robots_disallows(host) == ["/search"]
    _expire(host)
    # 过期后重抓失败：不回退过期旧规则、不写缓存，本次放行降级
    assert rp.robots_disallows(host) == []
    assert host not in rp._robots_cache
    # 下次调用重试，恢复后拿到新规则
    assert rp.robots_disallows(host) == ["/search", "/new-private/"]
    assert seq.calls == 3


def test_zero_ttl_always_refetches(monkeypatch):
    monkeypatch.setattr(rp, "ROBOTS_CACHE_TTL_SECONDS", 0)
    seq = _Seq([_Resp(body=V1), _Resp(body=V2)])
    _install(monkeypatch, seq)
    host = "robots-ttl-zero.example.com"
    assert rp.robots_disallows(host) == ["/search"]
    assert rp.robots_disallows(host) == ["/search", "/new-private/"]
    assert seq.calls == 2
    # 时间戳确实随条目存入缓存
    fetched_at, _rules = rp._robots_cache[host]
    assert abs(time.monotonic() - fetched_at) < 60
