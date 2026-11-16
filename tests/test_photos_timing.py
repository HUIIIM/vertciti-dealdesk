"""轻量取图段位计时日志（research_pipeline.run_photos_pipeline）。

A 栏"外观"小图慢呼无段位日志、归因不可得 —— run_photos_pipeline 须对
搜索段与逐页抓取段逐段计时，任一出口恰落一行结构化日志 photos_timing
（含搜索/逐页 ms 与总 ms），且结果 dict 同步带 timings 可回读对平。
全部用替身，不碰公网。
"""
import logging
import re
import time

from app import research_pipeline as rp
from app.services import cache as cache_mod

ADDR = "236 E 5th St, New York, NY 10003"
ZILLOW = "https://www.zillow.com/homedetails/236-e-5th-st"
REDFIN = "https://www.redfin.com/NY/New-York/236-E-5th-St/home/123"


def _timing_lines(caplog):
    return [r.getMessage() for r in caplog.records
            if r.getMessage().startswith("photos_timing ")]


def _seg_ms(line, slug):
    m = re.search(rf"{slug}_ms=(\d+)", line)
    assert m, f"日志行缺 {slug}_ms：{line}"
    return int(m.group(1))


def _miss_cache(monkeypatch):
    monkeypatch.setattr(cache_mod, "get_cached", lambda addr: None)


def _slow_search(seconds, results):
    def fake_search(query, log, max_results=8):
        time.sleep(seconds)
        return results
    return fake_search


def _slow_fetch(pages):
    """pages: {url: (sleep_seconds, image_url)}；未登记 URL 抓取即测试失败。"""
    def fake_fetch(url, log):
        assert url in pages, f"不应抓取未登记页面：{url}"
        seconds, img = pages[url]
        time.sleep(seconds)
        return {"ok": True, "final_url": url,
                "html": ('<html><head><meta property="og:image" '
                         f'content="{img}"></head></html>')}
    return fake_fetch


def test_photos_timing_slow_call_segments_and_total(monkeypatch, caplog):
    """受控慢呼：日志含搜索/逐页 ms 与总 ms，且与结果 timings 对平；
    非房源站结果不抓取（无对应 fetch 段）。"""
    _miss_cache(monkeypatch)
    monkeypatch.setattr(rp, "ddg_search", _slow_search(0.12, [
        {"title": "z", "url": ZILLOW},
        {"title": "r", "url": REDFIN},
        {"title": "blog", "url": "https://example.com/blog/post"},
    ]))
    monkeypatch.setattr(rp, "fetch_page", _slow_fetch({
        ZILLOW: (0.05, "https://images.example-cdn.com/house-front.jpg"),
        REDFIN: (0.03, "https://images.example-cdn.com/house-side.jpg"),
    }))
    with caplog.at_level(logging.INFO, logger="dealdesk.research_pipeline"):
        result = rp.run_photos_pipeline(ADDR)
    assert result["cached"] is False
    assert len(result["photos"]) == 2
    lines = _timing_lines(caplog)
    assert len(lines) == 1, f"应恰一行 photos_timing，实得 {lines}"
    line = lines[0]
    search_ms = _seg_ms(line, "search")
    fetch1_ms = _seg_ms(line, "fetch1")
    fetch2_ms = _seg_ms(line, "fetch2")
    total_ms = _seg_ms(line, "total")
    assert "fetch3_ms" not in line  # 非房源站未抓，无第三段
    # 慢段耗时如实反映受控睡眠（留调度抖动余量，只断下限量级）
    assert search_ms >= 100
    assert fetch1_ms >= 40
    assert fetch2_ms >= 20
    assert total_ms >= search_ms + fetch1_ms + fetch2_ms
    # 回读对平：结果 timings 与日志逐段一致
    timings = result["timings"]
    assert timings["total_ms"] == total_ms
    assert timings["search_ms"] == search_ms
    assert timings["fetch_ms"] == [fetch1_ms, fetch2_ms]
    assert timings["cache_hit"] is False
    assert "cache_hit=false" in line and "ok=true" in line


def test_photos_timing_cache_hit_logs_without_search(monkeypatch, caplog):
    """缓存命中出口同样恰落一行（cache_hit=true、无搜索/抓取段），且不触发搜索。"""
    cached_photos = [{"url": "https://images.example-cdn.com/cached.jpg"}]
    monkeypatch.setattr(cache_mod, "get_cached", lambda addr: {
        "stale": False,
        "data": {"fields": [{"key": "property_photos", "value": cached_photos}]},
    })

    def _no_search(query, log, max_results=8):  # pragma: no cover - 不应被调用
        raise AssertionError("缓存命中不应再搜索")
    monkeypatch.setattr(rp, "ddg_search", _no_search)
    with caplog.at_level(logging.INFO, logger="dealdesk.research_pipeline"):
        result = rp.run_photos_pipeline(ADDR)
    assert result["cached"] is True
    assert result["photos"] == cached_photos
    lines = _timing_lines(caplog)
    assert len(lines) == 1
    line = lines[0]
    assert "cache_hit=true" in line and "ok=true" in line
    assert _seg_ms(line, "search") == 0
    assert "fetch1_ms" not in line
    assert result["timings"]["fetch_ms"] == []
    assert result["timings"]["cache_hit"] is True


def test_photos_timing_search_failure_still_logs(monkeypatch, caplog):
    """搜索段抛异常同样落一行（ok=false），且 finally 计时保住已耗时段。"""
    _miss_cache(monkeypatch)

    def _boom_search(query, log, max_results=8):
        time.sleep(0.03)
        raise RuntimeError("ddg down")
    monkeypatch.setattr(rp, "ddg_search", _boom_search)
    with caplog.at_level(logging.INFO, logger="dealdesk.research_pipeline"):
        result = rp.run_photos_pipeline(ADDR)
    assert result["photos"] == [] and result["cached"] is False
    lines = _timing_lines(caplog)
    assert len(lines) == 1
    assert "ok=false" in lines[0]
    assert _seg_ms(lines[0], "search") >= 20
    assert result["timings"]["search_ms"] == _seg_ms(lines[0], "search")


def test_photos_timing_empty_address_still_logs(monkeypatch, caplog):
    """空地址出口也恰落一行（全段为 0），归因面无盲区。"""
    with caplog.at_level(logging.INFO, logger="dealdesk.research_pipeline"):
        result = rp.run_photos_pipeline("  ")
    assert result["photos"] == [] and result["cached"] is False
    lines = _timing_lines(caplog)
    assert len(lines) == 1
    assert _seg_ms(lines[0], "search") == 0
    assert result["timings"]["total_ms"] == _seg_ms(lines[0], "total")


def test_photos_timing_reaches_dealdesk_logger_under_prod_config(monkeypatch):
    """生产回归（同第 53 项口径）：configure_logging() 只配置 dealdesk
    logger（handler＋INFO、propagate=False），根 logger 保持默认 WARNING。
    此配置下 photos_timing 行必须经 dealdesk.* 命名空间到达该 handler——
    若走模块 __name__ logger（app.services.research_pipeline），INFO 行
    会被根级别静默丢弃、生产段位归因失效，本用例在彼实现下必挂。"""
    import io

    from app.core.observability import configure_logging

    _miss_cache(monkeypatch)
    monkeypatch.setattr(rp, "ddg_search", _slow_search(0.01, [
        {"title": "z", "url": ZILLOW},
    ]))
    monkeypatch.setattr(rp, "fetch_page", _slow_fetch({
        ZILLOW: (0.01, "https://images.example-cdn.com/house-front.jpg"),
    }))
    dealdesk_log = logging.getLogger("dealdesk")
    saved_handlers, saved_level = dealdesk_log.handlers[:], dealdesk_log.level
    saved_propagate = dealdesk_log.propagate
    stream = io.StringIO()
    try:
        dealdesk_log.handlers = [h for h in saved_handlers
                                 if h.__class__.__name__ != "StreamHandler"]
        configure_logging()  # 幂等：已有 JsonFormatter handler 时不重复挂
        for h in dealdesk_log.handlers:
            if isinstance(h, logging.StreamHandler):
                h.setStream(stream)
        result = rp.run_photos_pipeline(ADDR)
    finally:
        dealdesk_log.handlers, dealdesk_log.level = saved_handlers, saved_level
        dealdesk_log.propagate = saved_propagate
    assert len(result["photos"]) == 1
    out = stream.getvalue()
    assert "photos_timing total_ms=" in out, \
        f"生产配置下计时行未达 dealdesk handler：{out!r}"
    assert "search_ms=" in out and "fetch1_ms=" in out
    assert rp.timing_logger.name == "dealdesk.research_pipeline"
    assert rp.timing_logger.parent is dealdesk_log
