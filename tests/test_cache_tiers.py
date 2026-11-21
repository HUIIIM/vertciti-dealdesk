"""地址缓存分级 TTL：完整成功 7 天 / 部分或失败 24h，均可 env 覆盖。"""
from __future__ import annotations

import time

import pytest

from app.services import cache

ADDR_FULL = "tier-full 1 Tier Way, Tampa, FL 33602"
ADDR_PART = "tier-part 2 Tier Way, Tampa, FL 33602"


def _f(k: str) -> dict:
    return {"key": k, "value": 1}


FULL = {"ok": True, "primary_provider": "TopHap MCP", "fields": [_f("a")],
        "provider_results": [{"provider": "TopHap MCP", "status": "ok"},
                             {"provider": "RentCast", "status": "ok"}]}
SMOKE = {"ok": True, "primary_provider": "TopHap MCP",
         "fields": [_f(str(i)) for i in range(15)],
         "provider_results": [{"provider": "TopHap MCP", "status": "ok"},
                              {"provider": "RentCast", "status": "skipped"},
                              {"provider": "公开网页", "status": "failed"}]}
# 生产实证形态：TopHap 挂 + RentCast 未配置，仅 Census 1 字段
PARTIAL = {"ok": True, "primary_provider": "Census", "fields": [_f("state_confirmed")],
           "provider_results": [{"provider": "TopHap MCP", "status": "failed"},
                                {"provider": "RentCast", "status": "skipped"},
                                {"provider": "公开网页", "status": "failed"},
                                {"provider": "Census", "status": "ok"}]}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    from sqlalchemy import delete

    from app.services.persistence.engine import session_scope
    from app.services.persistence.schema import AddressCache

    monkeypatch.delenv("DEALDESK_CACHE_TTL_SECONDS", raising=False)
    monkeypatch.delenv("DEALDESK_CACHE_TTL_PARTIAL_SECONDS", raising=False)
    hashes = [cache.address_hash(a) for a in (ADDR_FULL, ADDR_PART)]

    def _clear() -> None:
        with session_scope() as sess:
            sess.execute(delete(AddressCache).where(AddressCache.address_hash.in_(hashes)))
    _clear()
    yield
    _clear()


def _age(address: str, seconds_ago: float) -> None:
    from app.services.persistence.engine import session_scope
    from app.services.persistence.schema import AddressCache
    with session_scope() as sess:
        sess.get(AddressCache, cache.address_hash(address)).fetched_at = time.time() - seconds_ago


def test_completeness_criterion():
    assert cache.is_complete(FULL) is True
    assert cache.is_complete(SMOKE) is True  # 冒烟口径兜住（RentCast 跳过、网页失败）
    assert cache.is_complete(PARTIAL) is False
    assert cache.is_complete({"ok": False, "fields": []}) is False
    assert cache.is_complete(dict(FULL, primary_provider=None)) is False
    assert cache.is_complete({"ok": True, "primary_provider": "x", "fields": [_f("a")]}) is False


def test_default_tiers():
    assert cache.ttl_for(FULL) == 604800
    assert cache.ttl_for(PARTIAL) == 86400


def test_complete_result_fresh_after_24h_stale_after_7d():
    cache.put_cached(ADDR_FULL, FULL)
    _age(ADDR_FULL, 86400 * 2)
    hit = cache.get_cached(ADDR_FULL)
    assert hit["complete"] is True and hit["stale"] is False
    _age(ADDR_FULL, 604800 + 60)
    assert cache.get_cached(ADDR_FULL)["stale"] is True


def test_partial_result_stale_after_24h():
    cache.put_cached(ADDR_PART, PARTIAL)
    _age(ADDR_PART, 3600 * 9.6)  # 生产实证 9.6h：仍在 24h 内
    hit = cache.get_cached(ADDR_PART)
    assert hit["complete"] is False and hit["stale"] is False
    _age(ADDR_PART, 86400 + 60)
    assert cache.get_cached(ADDR_PART)["stale"] is True


def test_env_overrides_both_tiers(monkeypatch):
    monkeypatch.setenv("DEALDESK_CACHE_TTL_SECONDS", "100")
    monkeypatch.setenv("DEALDESK_CACHE_TTL_PARTIAL_SECONDS", "10")
    assert cache.ttl_for(FULL) == 100 and cache.ttl_for(PARTIAL) == 10
    cache.put_cached(ADDR_PART, PARTIAL)
    _age(ADDR_PART, 20)
    assert cache.get_cached(ADDR_PART)["stale"] is True
    monkeypatch.setenv("DEALDESK_CACHE_TTL_PARTIAL_SECONDS", "nope")
    assert cache.ttl_partial_seconds() == 86400


def test_usage_rows_never_served_as_address_cache():
    """用量计数行（usage: 前缀）不会被地址查询命中。"""
    assert cache.usage_reserve("tier-test:x", 5) == 1
    assert not cache.address_hash("tier-test:x").startswith(cache.USAGE_KEY_PREFIX)
    assert cache.get_cached("usage:tier-test:x") is None
    from sqlalchemy import delete

    from app.services.persistence.engine import session_scope
    from app.services.persistence.schema import AddressCache
    with session_scope() as sess:
        sess.execute(delete(AddressCache).where(
            AddressCache.address_hash == cache.USAGE_KEY_PREFIX + "tier-test:x"))
