"""地址缓存测试：24h TTL 命中 + 全挂时 stale 兜底。

注意：run_chain 的缓存只在 providers=None（默认链）时生效，注入 providers
的测试路径（test_providers.py 的旧用例）不受影响。这里用 monkeypatch 把
四个 provider 类的方法替换为可计数/可控的 fake，走 providers=None 测缓存。
"""
import time

import pytest

import app.cache as cache
import app.providers as pv
from app.db import _conn


def _field(key, value, source="TopHap MCP"):
    return {"key": key, "label": key, "value": value, "display": str(value),
            "source": source, "source_url": "", "fetched_at": "t",
            "confidence": "高", "seller_claimed": False, "claim_label": "",
            "note": "", "status": "filled"}


@pytest.fixture
def mock_chain(monkeypatch):
    """四源全 mock：TopHap 成功、RentCast 跳过、网页/Census 失败；记录调用数。"""
    calls = {"tophap": 0, "web": 0, "census": 0}
    monkeypatch.setattr(pv.TophapProvider, "available", lambda self: (True, ""))
    def _th_enrich(self, address, log):
        calls["tophap"] += 1
        return {"ok": True, "fields": [_field("beds", 3)],
                "provider": "TopHap MCP", "note": "mock ok"}
    monkeypatch.setattr(pv.TophapProvider, "enrich", _th_enrich)
    monkeypatch.setattr(pv.RentcastProvider, "available",
                        lambda self: (False, "RENTCAST_API_KEY 未设置（mock）"))
    def _web_enrich(self, address, log):
        calls["web"] += 1
        return {"ok": False, "fields": [], "provider": "公开网页",
                "note": "mock fail"}
    monkeypatch.setattr(pv.WebProvider, "enrich", _web_enrich)
    def _cen_enrich(self, address, log):
        calls["census"] += 1
        return {"ok": False, "fields": [], "provider": "Census",
                "note": "mock fail"}
    monkeypatch.setattr(pv.CensusProvider, "enrich", _cen_enrich)
    return calls


@pytest.fixture
def fail_all(monkeypatch):
    """四源全挂（且 mock_chain 的假成功先被覆盖掉）。"""
    for cls in (pv.TophapProvider, pv.WebProvider, pv.CensusProvider):
        monkeypatch.setattr(cls, "available", lambda self: (True, ""))
        monkeypatch.setattr(cls, "enrich",
                            lambda self, address, log:
                            {"ok": False, "fields": [], "provider": "x",
                             "note": "全挂 mock"})
    monkeypatch.setattr(pv.RentcastProvider, "available",
                        lambda self: (False, "RENTCAST_API_KEY 未设置（mock）"))


def _age_row(address, seconds_ago):
    h = cache.address_hash(address)
    with _conn() as conn:
        conn.execute("UPDATE address_cache SET fetched_at=? WHERE address_hash=?",
                     (time.time() - seconds_ago, h))


def test_cache_hit_second_call_skips_providers(mock_chain):
    """同一地址调两次：第二次 cached=True，且 providers 没被再次调用。"""
    addr = "cache-hit 123 Main St, Tampa, FL 33602"
    r1 = pv.run_chain(addr)
    assert r1["ok"] is True
    assert r1["cached"] is False
    assert mock_chain["tophap"] == 1
    assert mock_chain["web"] == 1
    assert mock_chain["census"] == 1

    # 归一化验证：大小写/多余空白视为同一地址
    r2 = pv.run_chain("  CACHE-HIT   123 main st,  Tampa, FL 33602  ")
    assert r2["ok"] is True
    assert r2["cached"] is True
    assert mock_chain["tophap"] == 1  # providers 没被再次调用
    assert mock_chain["web"] == 1
    assert mock_chain["census"] == 1
    by_key = {f["key"]: f for f in r2["fields"]}
    assert by_key["beds"]["value"] == 3
    assert any("命中缓存" in e.get("note", "") for e in r2["log"])


def test_cache_ttl_expiry_refetches(mock_chain):
    """TTL 过期后重新调用：providers 被再次调用，返回新鲜数据（cached=False）。"""
    addr = "cache-ttl 456 Oak Ave, Austin, TX 78701"
    r1 = pv.run_chain(addr)
    assert r1["ok"] is True
    assert mock_chain["tophap"] == 1

    _age_row(addr, cache.CACHE_TTL_SECONDS + 1)  # 把条目推过 TTL
    r2 = pv.run_chain(addr)
    assert r2["ok"] is True
    assert r2["cached"] is False
    assert "stale" not in r2
    assert mock_chain["tophap"] == 2  # 重新走了 provider 链


def test_stale_fallback_when_all_fail(mock_chain, monkeypatch):
    """全挂且有过期缓存：返回旧数据，stale=True，diagnostics 说明可能过期。"""
    addr = "cache-stale 789 Pine Rd, Miami, FL 33101"
    r1 = pv.run_chain(addr)
    assert r1["ok"] is True

    # 第一次成功写入缓存后，再把四源全 mock 成失败
    for cls in (pv.TophapProvider, pv.WebProvider, pv.CensusProvider):
        monkeypatch.setattr(cls, "available", lambda self: (True, ""))
        monkeypatch.setattr(cls, "enrich",
                            lambda self, address, log:
                            {"ok": False, "fields": [], "provider": "x",
                             "note": "全挂 mock"})
    monkeypatch.setattr(pv.RentcastProvider, "available",
                        lambda self: (False, "RENTCAST_API_KEY 未设置（mock）"))

    _age_row(addr, cache.CACHE_TTL_SECONDS + 3600)  # 过期 1 小时
    r2 = pv.run_chain(addr)
    assert r2["ok"] is True  # 兜底成功
    assert r2["stale"] is True
    by_key = {f["key"]: f for f in r2["fields"]}
    assert by_key["beds"]["value"] == 3  # 旧数据
    assert "可能过期" in r2["diagnostics"]


def test_all_fail_no_cache_returns_diagnostics(fail_all):
    """全挂且无缓存：原样返回诊断，ok=False。"""
    r = pv.run_chain("cache-nocache 999 Nowhere Ln, Void, XX 00000")
    assert r["ok"] is False
    assert r["fields"] == []
    assert "stale" not in r
    assert r["cached"] is False
    assert r["diagnostics"]  # 中文诊断非空


def test_use_cache_false_disables(mock_chain):
    """use_cache=False：两次都走 provider 链，且不写缓存。"""
    addr = "cache-off 321 Elm St, Denver, CO 80202"
    r1 = pv.run_chain(addr, use_cache=False)
    r2 = pv.run_chain(addr, use_cache=False)
    assert r1["cached"] is False and r2["cached"] is False
    assert mock_chain["tophap"] == 2
    assert cache.get_cached(addr) is None
