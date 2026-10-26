"""扫描版 PDF OCR intake 测试。

覆盖：
1. 图片型（无文本层）PDF 被检出为扫描件，普通 PDF 端点返回
   needs_ocr / error_code=scanned_pdf_needs_ocr，不再只说"请手动录入"。
2. OCR 文本（商业路）-> 与普通 PDF 共用抽取引擎 -> 价格/面积/NOI/租户
   正确提取，来源标"扫描PDF OCR:<文件名>"、claim_notice 明示 OCR 口径，
   附数据质量门。
3. OCR 文本（住宅路）同样提取并标 OCR 口径，附需求验证清单。
4. 带文本层 PDF 不误判为扫描件，原路径无回归。
5. OCR 文本过短诚实报错 ocr_text_too_short。
"""

from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app import pdf_intake
from app.main import app

client = TestClient(app)

OCR_TEXT = """
1500 Atlantic Ave, Brooklyn, NY 11213
Offering Price: $4,350,000
Mixed-use retail building, 12,500 SF
In-Place NOI: $285,000
Pro Forma NOI: $340,000
Cap Rate 6.55%
Built 1928
Suite 1A  Laundromat  3,200 SF  $8,500
Suite 2B  Pizzeria    2,800 SF  $7,200
Value-add upside. Motivated seller.
"""

RES_OCR_TEXT = """
450 W 44th St, New York, NY 10036
Price: $4,350,000
2,800 sq ft, 4 bed, 3 bath
Rent $6,500 per month claimed by seller, turnkey value-add upside
"""


def _flat(fields):
    return {f["key"]: f for f in fields}


def _scanned_pdf_bytes() -> bytes:
    """生成只有图片、没有文本层的 PDF（模拟扫描件）。"""
    img = Image.new("RGB", (1240, 1754), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((80, 80), "Scanned flyer - image only, no text layer")
    buf = io.BytesIO()
    img.save(buf, format="PDF")
    return buf.getvalue()


def _text_pdf_bytes() -> bytes:
    """生成带文本层的普通 PDF（reportlab）。"""
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, "1500 Atlantic Ave Offering Price: $4,350,000")
    c.drawString(72, 700, "Mixed-use retail building, 12,500 SF, In-Place NOI: $285,000")
    c.drawString(72, 680, "Cap Rate 6.55% Built 1928 seller motivated turnkey upside")
    c.save()
    return buf.getvalue()


def test_inspect_detects_scanned_pdf(tmp_path):
    p = tmp_path / "scan.pdf"
    p.write_bytes(_scanned_pdf_bytes())
    info = pdf_intake.inspect_pdf(str(p))
    assert info["is_scanned"] is True, info
    assert info["page_count"] >= 1
    assert info["text_chars"] < pdf_intake.SCANNED_TEXT_THRESHOLD


def test_inspect_text_pdf_not_scanned(tmp_path):
    p = tmp_path / "text.pdf"
    p.write_bytes(_text_pdf_bytes())
    info = pdf_intake.inspect_pdf(str(p))
    assert info["is_scanned"] is False, info
    assert info["text_chars"] >= pdf_intake.SCANNED_TEXT_THRESHOLD


def test_commercial_upload_scanned_returns_needs_ocr(tmp_path):
    p = tmp_path / "scan.pdf"
    p.write_bytes(_scanned_pdf_bytes())
    if pdf_intake.server_ocr_available():
        return  # 有服务端引擎时直接 OCR 闭环，needs_ocr 路径由端点契约覆盖
    d = pdf_intake.run_commercial_pdf_upload(str(p), "scan.pdf")
    assert d["fields"] == []
    assert d["needs_ocr"] is True
    assert d["error_code"] == "scanned_pdf_needs_ocr"
    assert d["is_scanned_pdf"] is True
    assert "OCR" in d["error"]
    assert "OCR" in d["claim_notice"]


def test_residential_upload_scanned_returns_needs_ocr(tmp_path):
    p = tmp_path / "scan.pdf"
    p.write_bytes(_scanned_pdf_bytes())
    if pdf_intake.server_ocr_available():
        return
    d = pdf_intake.run_pdf_upload(str(p), "scan.pdf")
    assert d["fields"] == []
    assert d["needs_ocr"] is True
    assert d["error_code"] == "scanned_pdf_needs_ocr"
    assert d["demand_validation"] is not None


def test_commercial_pdf_ocr_text_basic_fields():
    d = pdf_intake.run_commercial_pdf_ocr_text(OCR_TEXT, "scan.pdf")
    assert not d.get("error"), d
    f = _flat(d["fields"])
    assert f["analysis.purchase_price"]["value"] == 4350000
    assert f["property.net_rentable_sf"]["value"] == 12500
    assert f["analysis.underwritten_noi"]["value"] == 285000
    assert len(d["tenants"]) == 2
    assert d["mode"] == "pdf-ocr"
    assert d["is_scanned_pdf"] is True
    assert d["extraction_method"] == "ocr"


def test_commercial_pdf_ocr_fields_marked_ocr_source():
    d = pdf_intake.run_commercial_pdf_ocr_text(OCR_TEXT, "scan.pdf")
    for fld in d["fields"]:
        assert fld["seller_claimed"] is True, fld["key"]
        assert fld["source"] == "扫描PDF OCR:scan.pdf", fld
    assert "扫描版 PDF OCR" in d["claim_notice"]
    assert "待独立验证" in d["claim_notice"]
    assert d["quality_gate"]["status"] in ("pass", "warn", "blocked")


def test_residential_pdf_ocr_text_fields():
    d = pdf_intake.run_pdf_ocr_text(RES_OCR_TEXT, "scan.pdf")
    assert not d.get("error"), d
    f = _flat(d["fields"])
    assert f["asking_price"]["value"] == 4350000
    for fld in d["fields"]:
        assert fld["source"] == "扫描PDF OCR:scan.pdf", fld
    assert "扫描版 PDF OCR" in d["claim_notice"]
    assert d["mode"] == "pdf-ocr"
    assert d["demand_validation"] is not None


def test_pdf_ocr_text_too_short_returns_error():
    d = pdf_intake.run_commercial_pdf_ocr_text("hi", "x.pdf")
    assert d["fields"] == []
    assert d["error_code"] == "ocr_text_too_short"
    d2 = pdf_intake.run_pdf_ocr_text("hi", "x.pdf")
    assert d2["error_code"] == "ocr_text_too_short"


def test_endpoint_commercial_pdf_upload_scanned_needs_ocr():
    if pdf_intake.server_ocr_available():
        return
    r = client.post("/api/uw-commercial/intake/pdf",
                    files={"file": ("scan.pdf", _scanned_pdf_bytes(),
                                    "application/pdf")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["needs_ocr"] is True
    assert d["error_code"] == "scanned_pdf_needs_ocr"


def test_endpoint_commercial_pdf_ocr_text_ok():
    r = client.post("/api/uw-commercial/intake/pdf-ocr-text",
                    json={"text": OCR_TEXT, "filename": "scan.pdf"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert _flat(d["fields"])["analysis.purchase_price"]["value"] == 4350000
    assert d["mode"] == "pdf-ocr"


def test_endpoint_residential_pdf_ocr_text_ok():
    r = client.post("/api/wb/intake/pdf-ocr-text",
                    json={"text": RES_OCR_TEXT, "filename": "scan.pdf"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert _flat(d["fields"])["asking_price"]["value"] == 4350000


def test_endpoint_pdf_ocr_text_empty_400():
    r = client.post("/api/uw-commercial/intake/pdf-ocr-text", json={"text": " "})
    assert r.status_code == 400
    r = client.post("/api/wb/intake/pdf-ocr-text", json={"text": " "})
    assert r.status_code == 400


def test_endpoint_text_pdf_upload_not_flagged_scanned():
    r = client.post("/api/uw-commercial/intake/pdf",
                    files={"file": ("text.pdf", _text_pdf_bytes(),
                                    "application/pdf")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert not d.get("needs_ocr"), d
    assert d.get("is_scanned_pdf") is False
    assert _flat(d["fields"])["analysis.purchase_price"]["value"] == 4350000
