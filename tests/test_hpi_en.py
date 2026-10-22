"""Every Chinese string in the embedded HPI data has an EN entry (no half-Chinese EN UI)."""
import re

from fastapi.testclient import TestClient

from app.data import hpi, hpi_en
from app.main import app

CJK = re.compile(r"[一-鿿]")


def _strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from _strings(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from _strings(v)


def test_every_hpi_string_has_en():
    missing = [s for n in ("MARKETS", "PUBLIC_SOURCES", "METHODOLOGY", "FHFA_RELEASE")
               for s in _strings(getattr(hpi, n)) if CJK.search(s) and s not in hpi_en.EN]
    assert missing == []
    assert not any(CJK.search(v) for v in hpi_en.EN.values())


def test_markets_endpoint_en_and_default_zh():
    c = TestClient(app)
    en = c.get("/api/wb/markets?lang=en").json()
    assert not any(CJK.search(s) for s in _strings(en))
    zh = c.get("/api/wb/markets").json()
    assert any(CJK.search(s) for s in _strings(zh))  # default unchanged
    assert en["series"] == zh["series"]  # numbers untouched
