"""intake 段位计时日志（providers.run_chain）。

冒烟首呼超时无段位日志、归因不可得 —— run_chain 须逐 provider 计时，
结束时落一行结构化日志 intake_timing（含逐段 ms 与总 ms），且结果 dict
与 provider_results 同步带 elapsed_ms 可回读对平。
"""
import logging
import re
import time

import app.providers as pv


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
    with caplog.at_level(logging.INFO, logger="dealdesk.providers"):
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
    with caplog.at_level(logging.INFO, logger="dealdesk.providers"):
        chain = pv.run_chain("nowhere", providers=[_Slow("Census", 0.02)],
                             use_cache=False)
    assert chain["ok"] is False
    lines = _timing_lines(caplog)
    assert len(lines) == 1
    assert "ok=false" in lines[0]
    assert _seg_ms(lines[0], "census") >= 10
    assert chain["timings"]["providers"][0]["provider"] == "Census"


def test_intake_timing_reaches_dealdesk_logger_under_prod_config():
    """生产回归（台账第 53 项部署后补验）：configure_logging() 只配置
    dealdesk logger（handler＋INFO、propagate=False），根 logger 保持默认
    WARNING。此配置下 intake_timing 行必须经 dealdesk.* 命名空间到达该
    handler——旧 __name__ logger（app.services.providers）下 INFO 行被根
    级别静默丢弃、生产段位归因失效，本用例在旧实现下必挂。"""
    import io

    from app.core.observability import configure_logging

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
        chain = pv.run_chain("123 Main St, Tampa, FL 33602",
                             providers=[_Slow("TopHap MCP", 0.02,
                                              [_field("beds", 3)])],
                             use_cache=False)
    finally:
        dealdesk_log.handlers, dealdesk_log.level = saved_handlers, saved_level
        dealdesk_log.propagate = saved_propagate
    assert chain["ok"] is True
    out = stream.getvalue()
    assert "intake_timing total_ms=" in out, f"生产配置下计时行未达 dealdesk handler：{out!r}"
    assert "tophap_mcp_ms=" in out
    assert pv.logger.name == "dealdesk.providers"
    assert pv.logger.parent is dealdesk_log


def test_timing_slug_mapping():
    assert pv._timing_slug("TopHap MCP", 0) == "tophap_mcp"
    assert pv._timing_slug("RentCast", 1) == "rentcast"
    assert pv._timing_slug("公开网页", 2) == "web"
    assert pv._timing_slug("Census", 3) == "census"
    assert pv._timing_slug("Some Provider!", 0) == "some_provider"
    assert pv._timing_slug("", 4) == "provider_4"
