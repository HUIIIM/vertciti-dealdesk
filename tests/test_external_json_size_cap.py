"""外部 JSON API 响应大小上限测试（台账第 25 项，2026-10-24）.

第 23 项曾在 v1 线给四端点加过共享 capped GET helper，但 v2 分层
迁移未把 GET 变体带进 app/services/http_capped.py，四端点回归为
httpx.get + r.json() 整页读入。本项补回：sell_readiness（Socrata
DOB/ECB）、ownership（NY DOS）、providers（RentCast）、geocode
（Census）统一改走 http_capped.get_json_capped（流式 +
MAX_JSON_BYTES 上限，与 MAX_PAGE_BYTES 同值）：超限按各端点既有
诚实降级口径（ok=False + 中文 note / geocode 返回 state=None），
不整页读入内存、不截断残页凑解析。全部用替身，不碰公网。
"""

from __future__ import annotations

import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import geocode, ownership, providers
from app import sell_readiness as sr
from app.services import http_capped
from app.services import research_pipeline as rp


class _Resp:
    def __init__(self, body=b"", headers=None, status_code=200):
        self.status_code = status_code
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.headers = headers or {}
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


def _patch_stream(monkeypatch, resp_or_fn):
    fn = resp_or_fn if callable(resp_or_fn) and not isinstance(resp_or_fn, _Resp) else (lambda *a, **k: resp_or_fn)
    monkeypatch.setattr(http_capped.httpx, "stream", fn)


def _patch_small_cap(monkeypatch, cap=200):
    monkeypatch.setattr(http_capped, "MAX_JSON_BYTES", cap)


# ---------- helper 本体 ----------

def test_json_cap_constant_matches_page_cap():
    assert http_capped.MAX_JSON_BYTES == rp.MAX_PAGE_BYTES == 2_000_000


def test_helper_under_cap_parses_json(monkeypatch):
    _patch_stream(monkeypatch, _Resp(body=[{"a": 1}]))
    out = http_capped.get_json_capped("https://example.test/x")
    assert out == {"status_code": 200, "data": [{"a": 1}],
                   "too_large": False, "json_error": False}


def test_helper_exactly_at_cap_ok(monkeypatch):
    body = json.dumps([{"a": 1}]).encode()
    _patch_stream(monkeypatch, _Resp(body=body))
    out = http_capped.get_json_capped("https://example.test/x", limit=len(body))
    assert out["too_large"] is False
    assert out["data"] == [{"a": 1}]


def test_helper_content_length_precheck_skips_body(monkeypatch):
    _patch_small_cap(monkeypatch, 100)
    body = json.dumps([{"a": 1}]).encode() + b"x" * 500
    resp = _Resp(body=body, headers={"content-length": str(len(body))})
    _patch_stream(monkeypatch, resp)
    out = http_capped.get_json_capped("https://example.test/x")
    assert out["too_large"] is True
    assert resp.iter_called is False  # 预检命中直接停手，不读 body


def test_helper_non_json_flagged(monkeypatch):
    _patch_stream(monkeypatch, _Resp(body=b"<html>nope</html>"))
    out = http_capped.get_json_capped("https://example.test/x")
    assert out["json_error"] is True
    assert out["data"] is None


def test_helper_non_200_status_only(monkeypatch):
    _patch_stream(monkeypatch, _Resp(body=b"err", status_code=503))
    out = http_capped.get_json_capped("https://example.test/x")
    assert out["status_code"] == 503
    assert out["too_large"] is False


# ---------- Socrata DOB / ECB（sell_readiness） ----------

_DOB_ROW = {"house_number": "450", "street": "WEST 44 STREET",
            "violation_type": "WORK WITHOUT PERMIT"}


def test_dob_under_cap_ok(monkeypatch):
    _patch_stream(monkeypatch, _Resp(body=[_DOB_ROW]))
    res = sr.query_dob_violations("450 W 44th St, New York, NY 10036")
    assert res["ok"] is True
    assert len(res["violations"]) == 1


def test_dob_streamed_over_cap_honest_degrade(monkeypatch, caplog):
    _patch_small_cap(monkeypatch, 200)
    body = json.dumps([_DOB_ROW]).encode() + b" " * 1000
    _patch_stream(monkeypatch, _Resp(body=body))
    with caplog.at_level(logging.WARNING, logger=http_capped.logger.name):
        res = sr.query_dob_violations("450 W 44th St, New York, NY 10036")
    assert res["ok"] is False
    assert res["violations"] == []  # 残页就算有命中行也不许用
    assert "响应过大" in res["note"]
    assert any("响应过大" in rec.message for rec in caplog.records)


def test_ecb_over_cap_honest_degrade(monkeypatch):
    _patch_small_cap(monkeypatch, 200)
    body = json.dumps([{"respondent_house_number": "450",
                        "respondent_street": "WEST 44 STREET",
                        "balance_due": "900"}]).encode() + b" " * 1000
    _patch_stream(monkeypatch, _Resp(body=body))
    res = sr.query_ecb_cases("450 W 44th St, New York, NY 10036")
    assert res["ok"] is False
    assert res["cases"] == []
    assert "响应过大" in res["note"]


def test_dob_non_200_unchanged(monkeypatch):
    _patch_stream(monkeypatch, _Resp(body=b"", status_code=500))
    res = sr.query_dob_violations("450 W 44th St, New York, NY 10036")
    assert res["ok"] is False
    assert "HTTP 500" in res["note"]


# ---------- NY DOS（ownership） ----------

_DOS_ROW = {"dos_id": "6628404", "current_entity_name": "JC SPLENDID LLC",
            "entity_type": "DOMESTIC LIMITED LIABILITY COMPANY"}


def test_nydos_over_cap_honest_degrade(monkeypatch):
    _patch_small_cap(monkeypatch, 200)
    body = json.dumps([_DOS_ROW]).encode() + b" " * 1000
    _patch_stream(monkeypatch, _Resp(body=body))
    res = ownership.query_ny_dos("JC SPLENDID LLC")
    assert res["ok"] is False
    assert res["records"] == []
    assert "响应过大" in res["note"]


def test_nydos_content_length_precheck(monkeypatch):
    _patch_small_cap(monkeypatch, 100)
    body = json.dumps([_DOS_ROW]).encode() + b" " * 1000
    resp = _Resp(body=body, headers={"content-length": str(len(body))})
    _patch_stream(monkeypatch, resp)
    res = ownership.query_ny_dos("JC SPLENDID LLC")
    assert res["ok"] is False
    assert "响应过大" in res["note"]
    assert resp.iter_called is False


# ---------- RentCast（providers） ----------

_RENTCAST_REC = [{"propertyType": "Single Family", "bedrooms": 3,
                  "squareFootage": 1800}]


def test_rentcast_under_cap_ok(monkeypatch):
    monkeypatch.setenv("RENTCAST_API_KEY", "test-key")
    _patch_stream(monkeypatch, _Resp(body=_RENTCAST_REC))
    res = providers.RentcastProvider().enrich("450 W 44th St, New York, NY 10036", [])
    assert res["ok"] is True
    assert res["fields"]


def test_rentcast_over_cap_honest_degrade(monkeypatch):
    monkeypatch.setenv("RENTCAST_API_KEY", "test-key")
    _patch_small_cap(monkeypatch, 200)
    body = json.dumps(_RENTCAST_REC).encode() + b" " * 1000
    _patch_stream(monkeypatch, _Resp(body=body))
    res = providers.RentcastProvider().enrich("450 W 44th St, New York, NY 10036", [])
    assert res["ok"] is False
    assert res["fields"] == []
    assert "响应过大" in res["note"]


def test_rentcast_401_unchanged(monkeypatch):
    monkeypatch.setenv("RENTCAST_API_KEY", "bad-key")
    _patch_stream(monkeypatch, _Resp(body=b"", status_code=401))
    res = providers.RentcastProvider().enrich("450 W 44th St, New York, NY 10036", [])
    assert res["ok"] is False
    assert "401" in res["note"]


# ---------- Census（geocode） ----------

_CENSUS_BODY = {"result": {"addressMatches": [{
    "matchedAddress": "450 W 44TH ST, NEW YORK, NY, 10036",
    "addressComponents": {"state": "NY"},
    "coordinates": {"x": -73.99, "y": 40.76}}]}}


def test_census_under_cap_ok(monkeypatch):
    _patch_stream(monkeypatch, _Resp(body=_CENSUS_BODY))
    out = geocode.geocode_state("450 W 44th St, New York, NY 10036")
    assert out["state"] == "NY"
    assert out["lat"] == 40.76


def test_census_over_cap_returns_none(monkeypatch, caplog):
    _patch_small_cap(monkeypatch, 200)
    body = json.dumps(_CENSUS_BODY).encode() + b" " * 1000
    _patch_stream(monkeypatch, _Resp(body=body))
    with caplog.at_level(logging.WARNING, logger=geocode.logger.name):
        out = geocode.geocode_state("450 W 44th St, New York, NY 10036")
    assert out["state"] is None  # 超限按无匹配诚实降级，不拿残页凑州
    assert any("响应过大" in rec.message for rec in caplog.records)
