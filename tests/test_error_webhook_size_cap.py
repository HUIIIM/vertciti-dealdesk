"""Error webhook response size cap tests (backlog #28, 2026-10-27).

_report._send previously used httpx.post (non-streaming) to POST an
error summary to DEALDESK_ERROR_WEBHOOK, an environment-configured
external HTTP endpoint. The response body is discarded, but a
non-streaming call still reads the whole body into memory: an
abnormal or hijacked webhook endpoint returning an oversize or
unbounded response could waste memory and hang the daemon reporting
thread, with no Content-Length precheck and no streaming stop.

Now _send goes through the shared http_capped.post_capped streaming
helper, capped at MAX_WEBHOOK_BYTES (= http_capped.MAX_POST_BYTES =
MAX_PAGE_BYTES): oversize stops mid-stream and is treated exactly
like any other reporting failure (one warning log, main flow
unaffected, error still recorded in RECENT_ERRORS). All tests use
fakes; no public network is touched.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
import pytest

from app.core import observability
from app.services import http_capped
from app.services import research_pipeline as rp

_ERR = {"at": "2026-10-27T00:00:00+00:00", "request_id": "rid-1",
        "path": "/api/boom", "method": "GET",
        "error": "RuntimeError: boom", "trace": "tb"}


class _Resp:
    """httpx.stream fake: streaming response context manager."""

    def __init__(self, body=b"", headers=None, status_code=200):
        self.status_code = status_code
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.headers = dict(headers or {})
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


class _SyncThread:
    """threading.Thread fake: runs the target synchronously on start."""

    def __init__(self, target=None, daemon=None):
        self._target = target

    def start(self):
        self._target()


@pytest.fixture()
def webhook(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEALDESK_ERROR_WEBHOOK", "https://hook.test/err")
    monkeypatch.setattr(observability, "threading",
                        SimpleNamespace(Thread=_SyncThread))
    observability.RECENT_ERRORS.clear()
    return monkeypatch


def _patch_stream(monkeypatch, resp_or_fn, capture=None):
    if callable(resp_or_fn) and not isinstance(resp_or_fn, _Resp):
        fn = resp_or_fn
    else:
        def fn(*a, **k):
            if capture is not None:
                capture.update({"args": a, "kwargs": k})
            return resp_or_fn
    monkeypatch.setattr(http_capped.httpx, "stream", fn)


def test_webhook_cap_constant_matches_shared_caps():
    assert observability.MAX_WEBHOOK_BYTES == http_capped.MAX_POST_BYTES
    assert http_capped.MAX_POST_BYTES == rp.MAX_PAGE_BYTES == 2_000_000


def test_under_cap_normal_delivers_payload(webhook, monkeypatch):
    capture: dict = {}
    _patch_stream(monkeypatch, _Resp(body=b"ok"), capture)
    observability._report(dict(_ERR))
    assert observability.RECENT_ERRORS[0]["request_id"] == "rid-1"
    assert capture["args"][0] == "POST"
    assert capture["args"][1] == "https://hook.test/err"
    sent = capture["kwargs"]["json"]
    assert sent == {k: _ERR[k] for k in ("at", "request_id", "path", "method", "error")}
    assert capture["kwargs"]["timeout"] == 5


def test_exactly_at_cap_ok(webhook, monkeypatch, caplog):
    body = b"x" * 64
    monkeypatch.setattr(observability, "MAX_WEBHOOK_BYTES", len(body))
    _patch_stream(monkeypatch, _Resp(body=body))
    with caplog.at_level(logging.WARNING, logger="dealdesk"):
        observability._report(dict(_ERR))
    assert not any("error webhook" in r.message for r in caplog.records)


def test_streamed_over_cap_is_reporting_failure_only(webhook, monkeypatch, caplog):
    monkeypatch.setattr(observability, "MAX_WEBHOOK_BYTES", 100)
    _patch_stream(monkeypatch, _Resp(body=b"x" * 500))
    with caplog.at_level(logging.WARNING, logger="dealdesk"):
        observability._report(dict(_ERR))  # must not raise
    assert observability.RECENT_ERRORS[0]["request_id"] == "rid-1"
    assert any("error webhook 上报失败" in r.message for r in caplog.records)


def test_content_length_precheck_skips_body(webhook, monkeypatch, caplog):
    monkeypatch.setattr(observability, "MAX_WEBHOOK_BYTES", 100)
    body = b"x" * 500
    resp = _Resp(body=body, headers={"content-length": str(len(body))})
    _patch_stream(monkeypatch, resp)
    with caplog.at_level(logging.WARNING, logger="dealdesk"):
        observability._report(dict(_ERR))
    assert resp.iter_called is False  # precheck trips before reading the body
    assert any("error webhook 上报失败" in r.message for r in caplog.records)


def test_endpoint_exception_is_reporting_failure_only(webhook, monkeypatch, caplog):
    def boom(*a, **k):
        raise httpx.ConnectError("down", request=httpx.Request("POST", "https://hook.test/err"))

    _patch_stream(monkeypatch, boom)
    with caplog.at_level(logging.WARNING, logger="dealdesk"):
        observability._report(dict(_ERR))  # must not raise
    assert observability.RECENT_ERRORS[0]["request_id"] == "rid-1"
    assert any("error webhook 上报失败" in r.message for r in caplog.records)


def test_non_200_status_still_counts_as_delivered(webhook, monkeypatch, caplog):
    # Original httpx.post never raised for an HTTP status; that口径 is
    # preserved -- the capped body is read and discarded, status alone
    # does not turn a delivered report into a reporting failure.
    _patch_stream(monkeypatch, _Resp(body=b"err", status_code=500))
    with caplog.at_level(logging.WARNING, logger="dealdesk"):
        observability._report(dict(_ERR))
    assert not any("error webhook" in r.message for r in caplog.records)


def test_no_webhook_configured_never_calls_out(monkeypatch):
    monkeypatch.delenv("DEALDESK_ERROR_WEBHOOK", raising=False)
    monkeypatch.setattr(observability, "threading",
                        SimpleNamespace(Thread=_SyncThread))
    observability.RECENT_ERRORS.clear()

    def forbidden(*a, **k):  # pragma: no cover - must never run
        raise AssertionError("stream called without a configured webhook")

    monkeypatch.setattr(http_capped.httpx, "stream", forbidden)
    observability._report(dict(_ERR))
    assert observability.RECENT_ERRORS[0]["request_id"] == "rid-1"
