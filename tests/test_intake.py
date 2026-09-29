"""智能搜集 intake 测试：抽取 / robots / 反爬降级 / PDF（全部用 fixture，不碰公网）."""

from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from app import pdf_intake, research_pipeline as rp
from app.main import app

client = TestClient(app)

LISTING_TEXT = """
123 Main St, Tampa, FL 33602 | Redfin
List Price $485,000
3 bd 2 ba 1,500 sqft lot 0.25 acre Built in 1998
Annual Tax $4,200 HOA $150
Rent Zestimate $2,900/mo
Price History: Jan 5, 2020 Sold $320,000; Mar 12, 2024 Listed $495,000
Beautiful renovated kitchen, turnkey rental, great cash flow 7% cap.
"""


def test_parse_address():
    p = rp.parse_address("123 Main St, Tampa, FL 33602")
    assert p["parsed"] and p["city"] == "Tampa" and p["state"] == "FL" and p["zip"] == "33602"
    p2 = rp.parse_address("just some text")
    assert not p2["parsed"]


def test_html_to_text():
    t = rp.html_to_text("<html><head><style>x{}</style></head><body><p>Hello <b>World</b></p><script>bad()</script></body></html>")
    assert t == "Hello World"


def test_ddg_unwrap():
    u = rp.ddg_unwrap("//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa&rut=xx")
    assert u == "https://example.com/a"
    assert rp.ddg_unwrap("https://example.com/b") == "https://example.com/b"


def test_robots_parse(monkeypatch):
    class R:
        status_code = 200
        text = "User-agent: *\nDisallow: /private/\nDisallow: /tmp\n"
    monkeypatch.setattr(rp.httpx, "get", lambda *a, **k: R())
    rp._robots_cache.clear()
    d = rp.robots_disallows("example.com")
    assert "/private/" in d
    ok, note = rp.robots_allowed("https://example.com/private/x")
    assert not ok and "robots" in note
    ok2, _ = rp.robots_allowed("https://example.com/public/x")
    assert ok2


def test_fetch_blocked_status(monkeypatch):
    class R:
        status_code = 403
    monkeypatch.setattr(rp.httpx, "get", lambda *a, **k: R())
    monkeypatch.setattr(rp, "_is_public_url", lambda u: (True, ""))
    monkeypatch.setattr(rp, "robots_allowed", lambda u: (True, ""))
    log = []
    r = rp.fetch_page("https://www.zillow.com/homedetails/x", log)
    assert not r["ok"] and r.get("blocked")
    assert any(e["status"] == "blocked" for e in log)


def test_fetch_captcha_text(monkeypatch):
    class R:
        status_code = 200
        text = "<html><body>Please verify you are a human, captcha required</body></html>"
        url = "https://example.com/"
    monkeypatch.setattr(rp.httpx, "get", lambda *a, **k: R())
    monkeypatch.setattr(rp, "_is_public_url", lambda u: (True, ""))
    monkeypatch.setattr(rp, "robots_allowed", lambda u: (True, ""))
    log = []
    r = rp.fetch_page("https://example.com/", log)
    assert not r["ok"] and r.get("blocked")


def test_ssrf_guard(monkeypatch):
    ok, _ = rp._is_public_url("http://127.0.0.1/admin")
    assert not ok
    ok2, _ = rp._is_public_url("ftp://example.com/x")
    assert not ok2
    # 沙盒 DNS 会劫持，这里 monkeypatch getaddrinfo 测逻辑本身
    import socket as _socket
    monkeypatch.setattr(_socket, "getaddrinfo",
                        lambda *a, **k: [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "",
                                          ("93.184.216.34", 0))])
    ok3, _ = rp._is_public_url("https://example.com/listing/1")
    assert ok3
    monkeypatch.setattr(_socket, "getaddrinfo",
                        lambda *a, **k: [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "",
                                          ("10.0.0.5", 0))])
    ok4, note4 = rp._is_public_url("https://example.com/listing/1")
    assert not ok4 and "非公网" in note4


def test_extract_fields_listing():
    fs = rp.extract_fields(LISTING_TEXT, "redfin.com 页面", "https://www.redfin.com/x/1")
    by_key = {f["key"]: f for f in fs}
    assert by_key["asking_price"]["value"] == 485000
    assert by_key["beds"]["value"] == 3
    assert by_key["baths"]["value"] == 2
    assert by_key["building_sf"]["value"] == 1500
    assert by_key["lot_sf"]["value"] == pytest.approx(0.25 * 43560)
    assert by_key["year_built"]["value"] == 1998
    assert by_key["taxes_annual"]["value"] == 4200
    assert by_key["hoa_monthly"]["value"] == 150
    assert by_key["monthly_rent"]["value"] == 2900
    assert by_key["monthly_rent"]["confidence"] == "低"  # 估算
    assert by_key["asking_price"]["confidence"] == "中"  # redfin factual
    assert len(by_key["price_history"]["value"]) == 2
    for f in fs:
        assert f["source"] and f["fetched_at"] and f["status"] == "filled"


def test_extract_fields_seller_claimed():
    fs = rp.extract_fields(LISTING_TEXT, "zillow 房源页", "https://www.zillow.com/x", seller_claimed=True)
    assert all(f["seller_claimed"] and f["claim_label"] == "卖方口径、待验证" for f in fs)


def test_merge_prefers_higher_confidence():
    lo = {"key": "asking_price", "label": "售价", "value": 1, "display": "1",
          "source": "x", "source_url": "", "fetched_at": "t", "confidence": "低",
          "seller_claimed": False, "claim_label": "", "note": "", "status": "filled"}
    hi = dict(lo, value=2, display="2", confidence="高")
    merged = rp.merge_fields([lo, hi])
    assert merged[0]["value"] == 2


def test_address_pipeline_degradation(monkeypatch):
    # 搜索有结果，但全部被反爬拦 → 字段全部 manual_needed，日志记录 blocked
    monkeypatch.setattr(rp, "ddg_search", lambda q, log, max_results=8: [
        {"title": "123 Main St", "url": "https://www.zillow.com/homedetails/1"},
        {"title": "assessor", "url": "https://assessor.example.gov/p/1"}])
    def fake_fetch(url, log):
        rp._log(log, f"抓取 {url[:40]}", "blocked", "HTTP 403：站点反爬拦截，已停手")
        return {"ok": False, "note": "blocked", "blocked": True}
    monkeypatch.setattr(rp, "fetch_page", fake_fetch)
    d = rp.run_address_pipeline("123 Main St, Tampa, FL 33602")
    assert d["fields"] == []
    assert len(d["manual_needed"]) > 0
    assert all(m["status"] == "manual_needed" and "手动" in m["note"] for m in d["manual_needed"])
    assert any(e["status"] == "blocked" for e in d["log"])


def test_url_pipeline_seller_labeling(monkeypatch):
    html = ("<html><body>456 Oak Ave, Dallas, TX 75201 List Price $620,000 "
            "4 bd 3 ba 2,200 sqft</body></html>")
    def fake_fetch(url, log):
        return {"ok": True, "text": rp.html_to_text(html), "final_url": url, "note": ""}
    monkeypatch.setattr(rp, "fetch_page", fake_fetch)
    indep_fields = [{"key": "building_sf", "label": "建筑面积 SF", "value": 2100,
                     "display": "2100 SF", "source": "county", "source_url": "",
                     "fetched_at": "t", "confidence": "高", "seller_claimed": False,
                     "claim_label": "", "note": "", "status": "filled"}]
    monkeypatch.setattr(rp, "run_address_pipeline",
                        lambda addr, log: {"fields": indep_fields, "manual_needed": [], "log": log})
    d = rp.run_url_pipeline("https://www.example-listing.com/456-oak")
    assert d["address"].startswith("456 Oak Ave")
    by_key = {f["key"]: f for f in d["fields"]}
    # 独立源优先
    assert by_key["building_sf"]["value"] == 2100
    # 卖方声称保留标注
    assert by_key["asking_price"]["seller_claimed"]
    assert by_key["asking_price"]["claim_label"] == "卖方口径、待验证"


# ---------------- PDF ----------------

PDF_TEXT = ("FOR SALE $750,000 3,200 SF 4 bd 3 ba Rent $4,500/mo "
            "Cap rate 6.5%! Turnkey renovated duplex, strong cash flow, "
            "below market, motivated seller. Call now.")


def test_parse_pdf_text_all_seller_claimed():
    d = pdf_intake.parse_pdf_text(PDF_TEXT, "flyer.pdf")
    assert d["fields"], "应提取出字段"
    assert all(f["seller_claimed"] and f["claim_label"] == "卖方材料口径、待独立验证"
               for f in d["fields"])
    by_key = {f["key"]: f for f in d["fields"]}
    assert by_key["asking_price"]["value"] == 750000
    assert by_key["building_sf"]["value"] == 3200
    assert by_key["monthly_rent"]["value"] == 4500
    assert any("话术要点" in f["label"] for f in d["fields"])
    assert "待独立验证" in d["claim_notice"]


def _minimal_pdf_bytes() -> bytes:
    """手工拼一个最小合法单页 PDF（含一行文本），供 pdftotext 实测。"""
    content = (b"BT /F1 18 Tf 72 720 Td (Price $485000 3bd 2ba 1500 sqft "
               b"Rent $2900/mo Beautiful renovated Tampa duplex for sale now) Tj ET")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(pdf))
        pdf += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(pdf)
    pdf += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        pdf += f"{off:010d} 00000 n \n".encode()
    pdf += (f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n").encode()
    return pdf


@pytest.mark.skipif(not pdf_intake.pdftotext_available(), reason="无 pdftotext")
def test_pdf_end_to_end_text_extraction(tmp_path):
    p = tmp_path / "t.pdf"
    p.write_bytes(_minimal_pdf_bytes())
    text, note = pdf_intake.extract_text(str(p))
    assert text and "485000" in text.replace(",", ""), note
    d = pdf_intake.parse_pdf_text(text, "t.pdf")
    by_key = {f["key"]: f for f in d["fields"]}
    assert by_key["asking_price"]["value"] == 485000
    assert by_key["monthly_rent"]["value"] == 2900


# ---------------- API ----------------

def test_intake_run_empty():
    r = client.post("/api/wb/intake/run", json={"mode": "address", "text": ""})
    assert r.status_code == 200
    assert r.json()["error"] == "输入为空"


def test_intake_run_bad_mode():
    r = client.post("/api/wb/intake/run", json={"mode": "nope", "text": "x"})
    assert r.status_code == 400


def test_intake_pdf_rejects_non_pdf():
    r = client.post("/api/wb/intake/pdf", files={"file": ("a.txt", io.BytesIO(b"hello"), "text/plain")})
    assert r.status_code == 400


def test_intake_pdf_garbage_graceful():
    # 假 PDF：pdftotext 失败 → 返回 error 字段而非崩溃
    r = client.post("/api/wb/intake/pdf",
                    files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 garbage" * 20), "application/pdf")})
    assert r.status_code == 200
    assert "error" in r.json()


@pytest.mark.skipif(not pdf_intake.pdftotext_available(), reason="无 pdftotext")
def test_intake_pdf_endpoint_ok():
    r = client.post("/api/wb/intake/pdf",
                    files={"file": ("t.pdf", io.BytesIO(_minimal_pdf_bytes()), "application/pdf")})
    assert r.status_code == 200
    d = r.json()
    assert not d.get("error"), d.get("error")
    by_key = {f["key"]: f for f in d["fields"]}
    assert by_key["asking_price"]["value"] == 485000


# ---------------- 截图 intake ----------------
from app import image_intake  # noqa: E402

PNG_1x1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)
JPG_MIN = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 300


def _tmp_pending(monkeypatch, tmp_path):
    monkeypatch.setattr(image_intake, "PENDING_DIR", str(tmp_path / "pending"))


def test_image_upload_ok(monkeypatch, tmp_path):
    _tmp_pending(monkeypatch, tmp_path)
    r = client.post("/api/wb/intake/image",
                    files={"file": ("shot.png", io.BytesIO(PNG_1x1), "image/png")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "pending" and len(d["task_id"]) == 32


def test_image_reject_ext(monkeypatch, tmp_path):
    _tmp_pending(monkeypatch, tmp_path)
    r = client.post("/api/wb/intake/image",
                    files={"file": ("a.txt", io.BytesIO(b"x" * 500), "text/plain")})
    assert r.status_code == 400


def test_image_reject_bad_magic(monkeypatch, tmp_path):
    _tmp_pending(monkeypatch, tmp_path)
    r = client.post("/api/wb/intake/image",
                    files={"file": ("fake.png", io.BytesIO(b"not an image" * 50), "image/png")})
    assert r.status_code == 400


def test_image_reject_too_big(monkeypatch, tmp_path):
    _tmp_pending(monkeypatch, tmp_path)
    big = JPG_MIN + b"\x00" * (15 * 1024 * 1024)
    r = client.post("/api/wb/intake/image",
                    files={"file": ("big.jpg", io.BytesIO(big), "image/jpeg")})
    assert r.status_code == 400


def test_pending_and_extracted_flow(monkeypatch, tmp_path):
    _tmp_pending(monkeypatch, tmp_path)
    r = client.post("/api/wb/intake/image",
                    files={"file": ("shot.jpg", io.BytesIO(JPG_MIN), "image/jpeg")})
    tid = r.json()["task_id"]
    # 404 before extraction
    r2 = client.get(f"/api/wb/intake/extracted/{tid}")
    assert r2.status_code == 404
    # 非法 task_id 防穿越
    r3 = client.get("/api/wb/intake/extracted/..%2f..%2fetc")
    assert r3.status_code in (400, 404)
    # 模拟 watcher 写回
    import json as _json
    ep = os.path.join(image_intake.PENDING_DIR, tid, "extracted.json")
    with open(ep, "w", encoding="utf-8") as f:
        _json.dump({"mode": "screenshot", "filename": "shot.jpg",
                    "fields": [{"key": "asking_price", "label": "挂牌价", "value": 485000,
                                "display": "$485,000", "source": "screenshot",
                                "fetched_at": "2026-09-29 01:00", "confidence": "中",
                                "seller_claimed": True, "claim_label": "截图提取",
                                "note": "待验证", "status": "filled"}],
                    "fetched_at": "2026-09-29 01:00",
                    "claim_notice": "截图提取、待验证"}, f)
    r4 = client.get(f"/api/wb/intake/extracted/{tid}")
    assert r4.status_code == 200
    assert r4.json()["fields"][0]["value"] == 485000
    r5 = client.get("/api/wb/intake/pending")
    assert r5.status_code == 200
    tasks = r5.json()["tasks"]
    assert any(t["task_id"] == tid and t["status"] == "done" for t in tasks)
