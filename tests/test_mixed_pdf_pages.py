"""混合型 PDF 逐页 OCR 补齐测试。

背景：扫描检测此前是全文阈值——部分页有文本层、部分页是扫描图的
混合 OM 会被当普通 PDF 处理，扫描页字段静默丢失。

覆盖：
1. 逐页检测：inspect_pdf 给出 low_text_pages / is_mixed，纯文本 PDF 不误判。
2. 上传（无服务端 OCR）：文本层页先提取 + needs_ocr_pages 结构化标注，
   不静默、不假装完整。
3. 浏览器逐页 OCR 合并端点：两页关键字段都提取到，字段逐页归属，
   OCR 页字段来源标「扫描页OCR」+ extraction_method=ocr。
4. 服务端逐页 OCR 路径（monkeypatch 引擎）：上传直接闭环合并。
5. 住宅路同构；合并入参缺失/为空诚实报错。
"""

from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter

from app import pdf_intake
from app.main import app

client = TestClient(app)

PAGE1_TEXT_LINES = [
    "1500 Atlantic Ave, Brooklyn, NY 11213",
    "Offering Price: $4,350,000",
    "Mixed-use retail building, 12,500 SF total rentable area",
    "Seller motivated, value-add upside, turnkey opportunity",
]
# 第 2 页（扫描图）经 OCR 应得到的文本：含第 1 页没有的关键字段
PAGE2_OCR_TEXT = (
    "In-Place NOI: $285,000\n"
    "Cap Rate 6.55%\n"
    "Suite 1A  Laundromat  3,200 SF  $8,500\n"
    "Suite 2B  Pizzeria    2,800 SF  $7,200"
)
RES_PAGE2_OCR_TEXT = "Rent $3,200 per month\n3 bed, 2 bath, built 1998"


def _flat(fields):
    return {f["key"]: f for f in fields}


def _mixed_pdf_bytes(page1_lines, img_text="Scanned page - image only") -> bytes:
    """1 页文本层（reportlab）+ 1 页纯图片（PIL）合并的混合 PDF。"""
    from reportlab.pdfgen import canvas
    buf1 = io.BytesIO()
    c = canvas.Canvas(buf1)
    y = 720
    for ln in page1_lines:
        c.drawString(72, y, ln)
        y -= 20
    c.save()
    img = Image.new("RGB", (1240, 1754), color=(255, 255, 255))
    ImageDraw.Draw(img).text((80, 80), img_text)
    buf2 = io.BytesIO()
    img.save(buf2, format="PDF")
    w = PdfWriter()
    for b in (buf1.getvalue(), buf2.getvalue()):
        for pg in PdfReader(io.BytesIO(b)).pages:
            w.add_page(pg)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def test_inspect_detects_mixed_pages(tmp_path):
    p = tmp_path / "mixed.pdf"
    p.write_bytes(_mixed_pdf_bytes(PAGE1_TEXT_LINES))
    info = pdf_intake.inspect_pdf(str(p))
    assert info["page_count"] == 2
    assert info["is_scanned"] is False
    assert info["is_mixed"] is True
    assert info["low_text_pages"] == [2]


def test_inspect_pure_text_not_mixed(tmp_path):
    p = tmp_path / "text.pdf"
    p.write_bytes(_mixed_pdf_bytes(PAGE1_TEXT_LINES)[:0] or
                  _text_only_bytes())
    info = pdf_intake.inspect_pdf(str(p))
    assert info["is_mixed"] is False
    assert info["low_text_pages"] == []


def _text_only_bytes() -> bytes:
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, "1500 Atlantic Ave Offering Price: $4,350,000")
    c.drawString(72, 700, "Mixed-use retail building, 12,500 SF, In-Place NOI: $285,000")
    c.drawString(72, 680, "Cap Rate 6.55% Built 1928 seller motivated turnkey upside")
    c.save()
    return buf.getvalue()


def test_commercial_upload_mixed_flags_needs_ocr_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_intake, "server_ocr_available", lambda: False)
    p = tmp_path / "mixed.pdf"
    p.write_bytes(_mixed_pdf_bytes(PAGE1_TEXT_LINES))
    d = pdf_intake.run_commercial_pdf_upload(str(p), "mixed.pdf")
    assert d["mixed_pdf"] is True
    assert d["partial_extraction"] is True
    assert d["needs_ocr_pages"] == [2]
    assert len(d["page_texts"]) == 2
    flat = _flat(d["fields"])
    # 文本层页字段已提取；扫描页独有字段此时不在（待合并，不假装）
    assert flat["analysis.purchase_price"]["value"] == 4350000
    assert flat["analysis.purchase_price"]["page"] == 1
    assert "analysis.underwritten_noi" not in flat


def test_commercial_merge_endpoint_extracts_both_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_intake, "server_ocr_available", lambda: False)
    p = tmp_path / "mixed.pdf"
    p.write_bytes(_mixed_pdf_bytes(PAGE1_TEXT_LINES))
    d = pdf_intake.run_commercial_pdf_upload(str(p), "mixed.pdf")
    r = client.post("/api/uw-commercial/intake/pdf-ocr-pages", json={
        "filename": "mixed.pdf", "page_texts": d["page_texts"],
        "ocr_pages": {"2": PAGE2_OCR_TEXT}})
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["mixed_pdf"] is True and m["ocr_pages"] == [2]
    flat = _flat(m["fields"])
    # 两页关键字段都提取到
    assert flat["analysis.purchase_price"]["value"] == 4350000
    assert flat["analysis.purchase_price"]["page"] == 1
    noi = flat["analysis.underwritten_noi"]
    assert noi["value"] == 285000
    assert noi["page"] == 2
    # OCR 页字段：来源标 OCR 口径
    assert noi["source"].startswith("扫描页OCR:")
    assert noi["extraction_method"] == "ocr"
    # 文本层页字段不被误标 OCR
    assert flat["analysis.purchase_price"].get("extraction_method") != "ocr"
    assert len(m["tenants"]) == 2  # 扫描页租约表也并入


def test_commercial_upload_mixed_server_ocr_closes_loop(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_intake, "server_ocr_available", lambda: True)
    monkeypatch.setattr(pdf_intake, "extract_text_from_image_bytes",
                        lambda data: (PAGE2_OCR_TEXT, ""))
    p = tmp_path / "mixed.pdf"
    p.write_bytes(_mixed_pdf_bytes(PAGE1_TEXT_LINES))
    d = pdf_intake.run_commercial_pdf_upload(str(p), "mixed.pdf")
    assert d["mixed_pdf"] is True and d["ocr_pages"] == [2]
    assert d["ocr_engine"] == "tesseract-server"
    flat = _flat(d["fields"])
    assert flat["analysis.underwritten_noi"]["value"] == 285000
    assert flat["analysis.underwritten_noi"]["page"] == 2
    assert flat["analysis.underwritten_noi"]["source"].startswith("扫描页OCR:")


def test_residential_mixed_merge(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_intake, "server_ocr_available", lambda: False)
    p = tmp_path / "mixed-res.pdf"
    p.write_bytes(_mixed_pdf_bytes([
        "Charming home at 450 W 44th St, New York, NY 10036",
        "Price: $750,000",
        "2,400 sq ft living space, well maintained, great location",
    ]))
    d = pdf_intake.run_pdf_upload(str(p), "mixed-res.pdf")
    assert d["needs_ocr_pages"] == [2]
    r = client.post("/api/wb/intake/pdf-ocr-pages", json={
        "filename": "mixed-res.pdf", "page_texts": d["page_texts"],
        "ocr_pages": {"2": RES_PAGE2_OCR_TEXT}})
    assert r.status_code == 200, r.text
    m = r.json()
    flat = _flat(m["fields"])
    assert flat["asking_price"]["value"] == 750000
    assert flat["asking_price"]["page"] == 1
    rent = flat["monthly_rent"]
    assert rent["value"] == 3200
    assert rent["page"] == 2
    assert rent["source"].startswith("扫描页OCR:")


def test_merge_endpoint_rejects_empty():
    r = client.post("/api/uw-commercial/intake/pdf-ocr-pages",
                    json={"filename": "x.pdf", "page_texts": [], "ocr_pages": {}})
    assert r.status_code == 400
    r = client.post("/api/wb/intake/pdf-ocr-pages", json={
        "filename": "x.pdf", "page_texts": ["some text page"],
        "ocr_pages": {"1": "   "}})
    assert r.status_code == 422  # 无有效 OCR 页 → 合并未执行
