"""robots 抓取失败不进长期缓存测试.

旧行为：_robots_rules 对网络异常/非 200 一律把空规则写入 _robots_cache
且进程内永不过期——一次瞬时故障（超时/5xx）会让该 host 在整个进程
生命周期内被当作"robots 无限制"放行，与 404（真无 robots 文件、
放行正确）无法区分。

新口径（二选一取「失败不缓存」，见 _robots_rules docstring）：
- 只有确定性结果进长期缓存：200 解析成功、404 真无文件；
- 失败（网络异常/非 200 非 404/超限降级）只放行本次调用、不缓存，
  同进程下一次调用重新抓取，恢复后即拿到真实规则。
全部用替身，不碰公网。
"""

from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import research_pipeline as rp

GOOD = b"User-agent: *\nDisallow: /search\nDisallow: /private/\n"


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
    """按序返回替身/抛异常的 httpx.stream 替身，并计数调用次数。"""

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


def test_network_exception_not_cached_then_recovers(monkeypatch, caplog):
    seq = _Seq([RuntimeError("timed out"),
                _Resp(body=GOOD)])
    _install(monkeypatch, seq)
    host = "robots-flaky.example.com"
    with caplog.at_level(logging.WARNING, logger=rp.logger.name):
        assert rp.robots_disallows(host) == []  # 本次放行降级
    assert host not in rp._robots_cache  # 失败绝不进长期缓存
    assert any("不缓存" in rec.message for rec in caplog.records)
    # 同进程重试：站点恢复后拿到真实规则
    assert rp.robots_disallows(host) == ["/search", "/private/"]
    assert seq.calls == 2
    ok, note = rp.robots_allowed(f"https://{host}/search?q=x")
    assert not ok and "/search" in note


def test_http_500_not_cached_then_recovers(monkeypatch):
    seq = _Seq([_Resp(body=b"oops", status_code=500),
                _Resp(body=GOOD)])
    _install(monkeypatch, seq)
    host = "robots-500.example.com"
    assert rp.robots_disallows(host) == []
    assert host not in rp._robots_cache
    assert rp.robots_disallows(host) == ["/search", "/private/"]
    assert seq.calls == 2


def test_http_429_not_cached_then_recovers(monkeypatch):
    seq = _Seq([_Resp(body=b"slow down", status_code=429),
                _Resp(body=GOOD)])
    _install(monkeypatch, seq)
    host = "robots-429.example.com"
    assert rp.robots_disallows(host) == []
    assert host not in rp._robots_cache
    assert rp.robots_disallows(host) == ["/search", "/private/"]


def test_404_is_cached_and_stays_allowed(monkeypatch):
    seq = _Seq([_Resp(body=b"not found", status_code=404),
                _Resp(body=GOOD)])
    _install(monkeypatch, seq)
    host = "robots-404cache.example.com"
    assert rp.robots_disallows(host) == []
    assert host in rp._robots_cache  # 404 是确定性结果，可长期缓存
    # 第二次调用走缓存、不再抓取（即便站点后来"出现"了 robots 也不重抓，
    # 与既有进程内缓存口径一致）
    assert rp.robots_disallows(host) == []
    assert seq.calls == 1
    ok, _ = rp.robots_allowed(f"https://{host}/anything")
    assert ok


def test_200_success_is_cached(monkeypatch):
    seq = _Seq([_Resp(body=GOOD),
                _Resp(body=b"User-agent: *\nDisallow: /other/\n")])
    _install(monkeypatch, seq)
    host = "robots-200cache.example.com"
    assert rp.robots_disallows(host) == ["/search", "/private/"]
    assert rp.robots_disallows(host) == ["/search", "/private/"]
    assert seq.calls == 1


def test_too_large_not_cached_then_recovers(monkeypatch):
    monkeypatch.setattr(rp, "MAX_ROBOTS_BYTES", 100)
    big = b"User-agent: *\nDisallow: /private/\n" + b"x" * 500
    seq = _Seq([_Resp(body=big),
                _Resp(body=b"User-agent: *\nDisallow: /a\n")])
    _install(monkeypatch, seq)
    host = "robots-bigcache.example.com"
    assert rp.robots_disallows(host) == []  # 超限诚实降级（第 18 项口径不变）
    assert host not in rp._robots_cache  # 超限是失败结果，不长期缓存
    assert rp.robots_disallows(host) == ["/a"]
    assert seq.calls == 2
