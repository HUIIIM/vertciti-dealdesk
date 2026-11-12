"""台账第 53/54 项：intake 段位计时日志（providers.run_chain）。

冒烟首呼超时无段位日志、归因不可得 —— run_chain 须逐 provider 计时，
结束时落一行结构化日志 intake_timing（含逐段 ms 与总 ms），且结果 dict
与 provider_results 同步带 elapsed_ms 可回读对平。
第 54 项：url 模式前置抓取段（fetch_page＋提取地址）以 url_fetch 段并入
同一行；抓取失败/无地址两路不进链时也须恰落一行，结果 dict 带 timings。
"""
import logging
import re
import time

import app.providers as pv
from app import research_pipeline as rp


def _field(key, value, source="Test"):
    return {"key": key, "label": key, "value": value, "display": str(value),
            "source": source, "source_url": "", "fetched_at": "t",
            "confidence": "高", "seller_claimed": False, "claim_label": "",
            "note": "", "status": "filled"}


class _Slow:
    """受控慢 provider：enrich 睡固定时长，模拟冷路径慢呼。"""

    def __init__(self, name, seconds, fields=None):
        self.name = name
        self._seconds = seconds
        self._fields = fields or []

    def available(self):
        return True, ""

    def enrich(self, address, log):
        time.sleep(self._seconds)
        if not self._fields:
            return {"ok": False, "fields": [], "provider": self.name,
                    "note": "慢呼无数据"}
        return {"ok": True, "fields": self._fields, "provider": self.name,
                "note": "slow ok"}


class _Skipped:
    name = "RentCast"

    def available(self):
        return False, "未配置"

    def enrich(self, address, log):  # pragma: no cover - 不应被调用
        raise AssertionError("skipped provider 不应 enrich")


def _timing_lines(caplog):
    return [r.getMessage() for r in caplog.records
            if r.getMessage().startswith("intake_timing ")]


def _seg_ms(line, slug):
    m = re.search(rf"{slug}_ms=(\d+)", line)
    assert m, f"日志行缺 {slug}_ms：{line}"
    return int(m.group(1))


def test_intake_timing_slow_call_segments_and_total(caplog):
    """受控慢呼：日志含逐段 ms 与总 ms，且与结果 timings/provider_results 对平。"""
    providers = [
        _Slow("TopHap MCP", 0.06, [_field("beds", 3, "TopHap MCP")]),
        _Skipped(),
        _Slow("公开网页", 0.03, [_field("baths", 2, "公开网页")]),
        _Slow("Census", 0.0),
    ]
    with caplog.at_level(logging.INFO, logger="app.services.providers"):
        chain = pv.run_chain("123 Main St, Tampa, FL 33602",
                             providers=providers, use_cache=False)
    assert chain["ok"] is True
    lines = _timing_lines(caplog)
    assert len(lines) == 1, f"应恰一行 intake_timing，实得 {lines}"
    line = lines[0]
    tophap_ms = _seg_ms(line, "tophap_mcp")
    web_ms = _seg_ms(line, "web")
    census_ms = _seg_ms(line, "census")
    rentcast_ms = _seg_ms(line, "rentcast")
    total_ms = _seg_ms(line, "total")
    # 慢段耗时如实反映受控睡眠（留调度抖动余量，只断下限量级）
    assert tophap_ms >= 50
    assert web_ms >= 20
    assert census_ms >= 0
    assert rentcast_ms >= 0  # skipped 段也在册（available 即返回）
    assert total_ms >= tophap_ms
    # 回读对平：结果 timings 与日志逐段一致
    timings = chain["timings"]
    assert timings["total_ms"] == total_ms
    by_provider = {t["provider"]: t["elapsed_ms"] for t in timings["providers"]}
    assert by_provider["TopHap MCP"] == tophap_ms
    assert by_provider["公开网页"] == web_ms
    assert by_provider["Census"] == census_ms
    assert by_provider["RentCast"] == rentcast_ms
    # provider_results 每条带 elapsed_ms 且与 timings 一致
    for r in chain["provider_results"]:
        assert r["elapsed_ms"] == by_provider[r["provider"]]
    statuses = {r["provider"]: r["status"] for r in chain["provider_results"]}
    assert statuses["RentCast"] == "skipped"
    assert "cache_hit=false" in line and "ok=true" in line


def test_intake_timing_all_fail_still_logs(caplog):
    """全挂路径同样落一行（ok=false），超时/失败事件可归因。"""
    with caplog.at_level(logging.INFO, logger="app.services.providers"):
        chain = pv.run_chain("nowhere", providers=[_Slow("Census", 0.02)],
                             use_cache=False)
    assert chain["ok"] is False
    lines = _timing_lines(caplog)
    assert len(lines) == 1
    assert "ok=false" in lines[0]
    assert _seg_ms(lines[0], "census") >= 10
    assert chain["timings"]["providers"][0]["provider"] == "Census"


def test_timing_slug_mapping():
    assert pv._timing_slug("TopHap MCP", 0) == "tophap_mcp"
    assert pv._timing_slug("RentCast", 1) == "rentcast"
    assert pv._timing_slug("公开网页", 2) == "web"
    assert pv._timing_slug("Census", 3) == "census"
    assert pv._timing_slug("url_fetch", 0) == "url_fetch"
    assert pv._timing_slug("Some Provider!", 0) == "some_provider"
    assert pv._timing_slug("", 4) == "provider_4"


# ---------------- 台账第 54 项：url 模式前置抓取段计时 ----------------


def test_run_chain_pre_timings_merged_into_line_and_total(caplog):
    """pre_timings 并入同一行：url_fetch 段逐字对平、total 含前置耗时。"""
    pre = [{"provider": "url_fetch", "elapsed_ms": 200}]
    with caplog.at_level(logging.INFO, logger="app.services.providers"):
        chain = pv.run_chain(
            "123 Main St, Tampa, FL 33602",
            providers=[_Slow("Census", 0.0, [_field("state", "FL")])],
            use_cache=False, pre_timings=pre)
    assert chain["ok"] is True
    lines = _timing_lines(caplog)
    assert len(lines) == 1, f"应恰一行 intake_timing，实得 {lines}"
    assert _seg_ms(lines[0], "url_fetch") == 200
    assert _seg_ms(lines[0], "total") >= 200
    assert chain["timings"]["providers"][0] == {
        "provider": "url_fetch", "elapsed_ms": 200}
    assert chain["timings"]["total_ms"] == _seg_ms(lines[0], "total")
    # 前置段不冒充 provider 结果
    assert [r["provider"] for r in chain["provider_results"]] == ["Census"]


def test_url_timing_slow_fetch_segments_and_total(caplog, monkeypatch):
    """受控慢呼（url 模式）：一行含 url_fetch＋provider 段＋总 ms、回读对平。"""
    def slow_fetch(url, log):
        time.sleep(0.12)
        return {"ok": True,
                "text": ("123 Main St, Tampa, FL 33602 List Price $485,000 "
                         "3 bd 2 ba 1,500 sqft"),
                "html": "", "final_url": url, "note": ""}

    monkeypatch.setattr(rp, "fetch_page", slow_fetch)
    real_run_chain = pv.run_chain

    def chain_with_slow_provider(address, log=None, **kwargs):
        return real_run_chain(
            address, log,
            providers=[_Slow("TopHap MCP", 0.05,
                             [_field("beds", 3, "TopHap MCP")])],
            use_cache=False, **kwargs)

    monkeypatch.setattr(pv, "run_chain", chain_with_slow_provider)
    with caplog.at_level(logging.INFO, logger="app.services.providers"):
        d = rp.run_url_pipeline("https://example-listing.com/123-main")
    assert d["mode"] == "url"
    assert d["address"].startswith("123 Main St")
    lines = _timing_lines(caplog)
    assert len(lines) == 1, f"url 模式应恰一行 intake_timing，实得 {lines}"
    line = lines[0]
    url_fetch_ms = _seg_ms(line, "url_fetch")
    tophap_ms = _seg_ms(line, "tophap_mcp")
    total_ms = _seg_ms(line, "total")
    assert url_fetch_ms >= 90
    assert tophap_ms >= 40
    assert total_ms >= url_fetch_ms
    assert "ok=true" in line
    timings = d["timings"]
    assert timings["total_ms"] == total_ms
    by_provider = {t["provider"]: t["elapsed_ms"]
                   for t in timings["providers"]}
    assert by_provider["url_fetch"] == url_fetch_ms
    assert by_provider["TopHap MCP"] == tophap_ms


def test_url_timing_fetch_fail_still_logs(caplog, monkeypatch):
    """抓取失败路不进链，仍落一行（url_fetch 段＋ok=false）。"""
    def slow_fail_fetch(url, log):
        time.sleep(0.03)
        return {"ok": False, "note": "抓取失败（测试）"}

    monkeypatch.setattr(rp, "fetch_page", slow_fail_fetch)
    with caplog.at_level(logging.INFO, logger="app.services.providers"):
        d = rp.run_url_pipeline("https://example-listing.com/x")
    assert d["error"] == "抓取失败（测试）"
    lines = _timing_lines(caplog)
    assert len(lines) == 1
    assert _seg_ms(lines[0], "url_fetch") >= 20
    assert "ok=false" in lines[0]
    assert d["timings"]["providers"] == [
        {"provider": "url_fetch",
         "elapsed_ms": _seg_ms(lines[0], "url_fetch")}]
    assert d["timings"]["total_ms"] == _seg_ms(lines[0], "total")


def test_url_timing_no_address_still_logs(caplog, monkeypatch):
    """无地址路不进链，仍落一行（url_fetch 段＋ok=false）。"""
    def slow_fetch_no_addr(url, log):
        time.sleep(0.03)
        return {"ok": True, "text": "Beautiful turnkey home, call now!",
                "html": "", "final_url": url, "note": ""}

    monkeypatch.setattr(rp, "fetch_page", slow_fetch_no_addr)
    with caplog.at_level(logging.INFO, logger="app.services.providers"):
        d = rp.run_url_pipeline("https://example-listing.com/y")
    assert d["address"] == ""
    assert d["manual_needed"]
    lines = _timing_lines(caplog)
    assert len(lines) == 1
    assert _seg_ms(lines[0], "url_fetch") >= 20
    assert "ok=false" in lines[0]
    assert d["timings"]["total_ms"] == _seg_ms(lines[0], "total")
