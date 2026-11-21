"""RentCast 月度预算帽：计数累加 / 跨月归零 / 达帽跳过 / env 覆盖。

计数落地址缓存同库同表（cache.usage_*，键 usage:rentcast:YYYY-MM，纽约自然月）。
本模块把"当前时刻"钉到远离真实日期的月份（2031 年），并逐测清行，互不串扰。
"""
from __future__ import annotations

from datetime import datetime

import pytest

from app.services import cache, http_capped
from app.services import providers as pv

ADDR = "450 W 44th St, New York, NY 10036"
_REC = [{"propertyType": "Single Family", "bedrooms": 3, "squareFootage": 1800}]
_MONTHS = ("2031-01", "2031-02", "2031-03")


def _ny(y: int, m: int, d: int, hh: int = 12) -> datetime:
    return datetime(y, m, d, hh, tzinfo=pv._RENTCAST_TZ)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    from sqlalchemy import delete

    from app.services.persistence.engine import session_scope
    from app.services.persistence.schema import AddressCache

    keys = [cache.USAGE_KEY_PREFIX + f"rentcast:{m}" for m in _MONTHS]

    def _clear() -> None:
        with session_scope() as sess:
            sess.execute(delete(AddressCache).where(AddressCache.address_hash.in_(keys)))

    monkeypatch.setenv("RENTCAST_API_KEY", "test-key")
    monkeypatch.delenv("RENTCAST_MONTHLY_CAP", raising=False)
    monkeypatch.setattr(pv, "_rentcast_now", lambda: _ny(2031, 1, 15))
    _clear()
    yield
    _clear()


@pytest.fixture
def http_calls(monkeypatch):
    """替身 RentCast HTTP：记录真正发出的请求数。"""
    sent = {"n": 0}

    def fake_get(url, **kw):
        sent["n"] += 1
        return {"status_code": 200, "too_large": False, "json_error": False,
                "data": _REC}
    monkeypatch.setattr(http_capped, "get_json_capped", fake_get)
    return sent


def test_count_accumulates_per_sent_request(http_calls, monkeypatch):
    p = pv.RentcastProvider()
    assert p.enrich(ADDR, [])["ok"] is True
    assert p.enrich(ADDR, [])["ok"] is True
    assert http_calls["n"] == 2
    assert cache.usage_count("rentcast:2031-01") == 2


def test_failed_request_still_counts(monkeypatch):
    def fake_get(url, **kw):
        return {"status_code": 500, "too_large": False, "json_error": False, "data": None}
    monkeypatch.setattr(http_capped, "get_json_capped", fake_get)
    res = pv.RentcastProvider().enrich(ADDR, [])
    assert res["ok"] is False
    assert cache.usage_count("rentcast:2031-01") == 1


def test_empty_address_does_not_count(http_calls):
    pv.RentcastProvider().enrich("  ", [])
    assert http_calls["n"] == 0
    assert cache.usage_count("rentcast:2031-01") == 0


def test_month_rollover_resets(http_calls, monkeypatch):
    monkeypatch.setenv("RENTCAST_MONTHLY_CAP", "1")
    p = pv.RentcastProvider()
    # 纽约 1 月 31 日 23:30（UTC 已是 2 月 1 日）仍算 1 月
    monkeypatch.setattr(pv, "_rentcast_now", lambda: _ny(2031, 1, 31, 23).replace(minute=30))
    assert pv.rentcast_usage_key() == "rentcast:2031-01"
    assert p.enrich(ADDR, [])["ok"] is True
    assert p.available()[0] is False
    monkeypatch.setattr(pv, "_rentcast_now", lambda: _ny(2031, 2, 1, 0))
    assert pv.rentcast_usage_key() == "rentcast:2031-02"
    assert p.available() == (True, "")
    assert p.enrich(ADDR, [])["ok"] is True
    assert cache.usage_count("rentcast:2031-01") == 1
    assert cache.usage_count("rentcast:2031-02") == 1


def test_at_cap_skips_without_request(http_calls, monkeypatch):
    monkeypatch.setattr(pv, "_rentcast_now", lambda: _ny(2031, 3, 10))
    for _ in range(45):
        assert cache.usage_reserve("rentcast:2031-03", 45) is not None
    p = pv.RentcastProvider()
    ok, why = p.available()
    assert ok is False and why == "RentCast 月度预算帽已达（45/月）"
    res = p.enrich(ADDR, [])
    assert res["ok"] is False and res["note"] == "RentCast 月度预算帽已达（45/月）"
    assert http_calls["n"] == 0
    assert cache.usage_count("rentcast:2031-03") == 45
    # 链照常降级：RentCast 记 skipped，后续源继续
    chain = pv.run_chain(ADDR, [], providers=[p])
    assert chain["provider_results"][0]["status"] == "skipped"
    assert chain["provider_results"][0]["note"] == "RentCast 月度预算帽已达（45/月）"


def test_env_override_cap(http_calls, monkeypatch):
    monkeypatch.setenv("RENTCAST_MONTHLY_CAP", "2")
    assert pv.rentcast_monthly_cap() == 2
    p = pv.RentcastProvider()
    assert p.enrich(ADDR, [])["ok"] is True
    assert p.enrich(ADDR, [])["ok"] is True
    res = p.enrich(ADDR, [])
    assert res["ok"] is False and res["note"] == "RentCast 月度预算帽已达（2/月）"
    assert http_calls["n"] == 2
    monkeypatch.setenv("RENTCAST_MONTHLY_CAP", "garbage")
    assert pv.rentcast_monthly_cap() == 45


def test_counter_unreadable_fails_closed(http_calls, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(cache, "usage_count", boom)
    monkeypatch.setattr(cache, "usage_reserve", boom)
    p = pv.RentcastProvider()
    assert p.available()[0] is False
    assert p.enrich(ADDR, [])["ok"] is False
    assert http_calls["n"] == 0
