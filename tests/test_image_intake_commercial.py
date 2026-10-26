"""商业截图 OCR intake 测试。

截图 OCR 文本 -> 与 PDF 共用抽取引擎 -> 价格/面积/租金(租户行) 正确提取，
全部标"截图 OCR 提取、卖方材料口径、待独立验证"，附数据质量门。
服务端直传：无 tesseract 时诚实返回 ocr_unavailable_server，绝不假装排队。
"""

from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from PIL import Image

from app import pdf_intake
from app.main import app

client = TestClient(app)

# 模拟一张房源截图经 OCR 得到的文本（字段与真实 OM 截图一致）
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


def _flat(fields):
    return {f["key"]: f for f in fields}


def _png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color=(255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


def test_image_ocr_text_basic_fields():
    d = pdf_intake.run_commercial_image_ocr_text(OCR_TEXT, "listing-shot.png")
    assert not d.get("error"), d
    f = _flat(d["fields"])
    assert f["analysis.purchase_price"]["value"] == 4350000
    assert f["property.net_rentable_sf"]["value"] == 12500
    assert f["analysis.underwritten_noi"]["value"] == 285000
    assert f["analysis.projected_noi"]["value"] == 340000
    assert f["property.address"]["value"] == "1500 Atlantic Ave"
    # 租金：租户行月租金正确提取
    assert len(d["tenants"]) == 2
    assert d["tenants"][0]["monthly_rent"] == 8500
    assert d["tenants"][1]["monthly_rent"] == 7200
    assert d["mode"] == "image"
    assert d["ocr_engine"] == "browser-tesseract"


def test_image_fields_marked_seller_claimed_ocr_source():
    d = pdf_intake.run_commercial_image_ocr_text(OCR_TEXT, "listing-shot.png")
    for fld in d["fields"]:
        assert fld["seller_claimed"] is True, fld["key"]
        assert fld["confidence"] == "卖方口径"
        assert fld["source"] == "截图OCR:listing-shot.png", fld
    assert "截图 OCR" in d["claim_notice"]
    assert "待独立验证" in d["claim_notice"]


def test_image_quality_gate_attached():
    d = pdf_intake.run_commercial_image_ocr_text(OCR_TEXT, "listing-shot.png")
    g = d["quality_gate"]
    assert g is not None
    assert g["status"] in ("pass", "warn", "blocked")


def test_image_contradictory_text_triggers_gate():
    bad = "Asking price $1,000,000. 100,000 SF. In-Place NOI $50,000. cap rate 1.0%."
    d = pdf_intake.run_commercial_image_ocr_text(bad, "bad.png")
    g = d["quality_gate"]
    assert g["status"] in ("warn", "blocked")
    rules = [c["rule"] for c in g.get("fails", []) + g.get("warns", [])]
    assert any("cap" in r for r in rules), rules


def test_image_ocr_text_too_short_returns_error():
    d = pdf_intake.run_commercial_image_ocr_text("hi", "x.png")
    assert d["fields"] == []
    assert d["error_code"] == "ocr_text_too_short"


def test_endpoint_image_text_ok():
    r = client.post("/api/uw-commercial/intake/image-text",
                    json={"text": OCR_TEXT, "filename": "listing-shot.png"})
    assert r.status_code == 200, r.text
    d = r.json()
    f = _flat(d["fields"])
    assert f["analysis.purchase_price"]["value"] == 4350000
    assert d["mode"] == "image"


def test_endpoint_image_text_empty_400():
    r = client.post("/api/uw-commercial/intake/image-text", json={"text": "  "})
    assert r.status_code == 400


def test_endpoint_image_upload_rejects_non_image():
    r = client.post("/api/uw-commercial/intake/image",
                    files={"file": ("x.png", b"not an image at all........",
                                    "image/png")})
    assert r.status_code == 400


def test_endpoint_image_upload_rejects_wrong_ext():
    r = client.post("/api/uw-commercial/intake/image",
                    files={"file": ("x.pdf", _png_bytes(), "image/png")})
    assert r.status_code == 400


def test_endpoint_image_upload_no_server_ocr_is_honest():
    """无服务端 tesseract 时必须 422 明示，不假装 pending 排队；有时则 200。"""
    r = client.post("/api/uw-commercial/intake/image",
                    files={"file": ("shot.png", _png_bytes(), "image/png")})
    if pdf_intake.server_ocr_available():
        assert r.status_code in (200, 422)  # 空白图 OCR 无文本也可 422
    else:
        assert r.status_code == 422, r.text
        assert "OCR" in r.json()["detail"]


def test_server_ocr_unavailable_note():
    if pdf_intake.server_ocr_available():
        return
    text, note = pdf_intake.extract_text_from_image_bytes(_png_bytes())
    assert text == ""
    assert "OCR" in note
