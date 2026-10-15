"""intake 域路由（台账第 14 项 routers 拆分样板，2026-10-15）。

首批迁入：混合型 PDF 逐页 OCR 合并端点（住宅＋商业，第 15 项所建，
2026-10-15 自 app/main.py 逐字迁入，行为不变——tests/test_mixed_pdf_pages.py
＋ tests/test_routers_smoke.py 守）。后续 intake 新端点直接写本模块。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import pdf_intake

router = APIRouter(tags=["intake"])


@router.post("/api/wb/intake/pdf-ocr-pages")
def wb_intake_pdf_ocr_pages(payload: dict):
    """住宅混合型 PDF 逐页 OCR 合并（台账第 15 项，2026-10-15）。

    混合 PDF 上传返回 needs_ocr_pages + page_texts（文本层逐页文本）；
    浏览器只 OCR 低文本页后把 {page_texts, ocr_pages} 发到这里合并，
    字段逐页归属、OCR 页字段标「扫描页OCR」来源。"""
    page_texts = (payload or {}).get("page_texts") or []
    ocr_pages = (payload or {}).get("ocr_pages") or {}
    filename = str((payload or {}).get("filename") or "mixed.pdf")
    if not isinstance(page_texts, list) or not page_texts:
        raise HTTPException(400, "缺少 page_texts（文本层逐页文本），请重新上传 PDF")
    if not isinstance(ocr_pages, dict) or not ocr_pages:
        raise HTTPException(400, "缺少 ocr_pages（逐页 OCR 文本）")
    if sum(len(str(p or "")) for p in page_texts) > 500_000:
        raise HTTPException(400, "文本过长（上限约 500KB）")
    try:
        d = pdf_intake.run_residential_pdf_ocr_pages(
            page_texts, ocr_pages, filename, layout=(payload or {}).get("layout"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"合并失败：{str(e)[:200]}")
    if d.get("error"):
        raise HTTPException(422, d["error"])
    return d


@router.post("/api/uw-commercial/intake/pdf-ocr-pages")
def uw_commercial_intake_pdf_ocr_pages(payload: dict):
    """商业混合型 PDF 逐页 OCR 合并（台账第 15 项，2026-10-15）。

    混合 PDF 上传返回 needs_ocr_pages + page_texts（文本层逐页文本）；
    浏览器只 OCR 低文本页后把 {page_texts, ocr_pages} 发到这里合并，
    字段逐页归属、OCR 页字段标「扫描页OCR」来源。"""
    page_texts = (payload or {}).get("page_texts") or []
    ocr_pages = (payload or {}).get("ocr_pages") or {}
    filename = str((payload or {}).get("filename") or "mixed.pdf")
    if not isinstance(page_texts, list) or not page_texts:
        raise HTTPException(400, "缺少 page_texts（文本层逐页文本），请重新上传 PDF")
    if not isinstance(ocr_pages, dict) or not ocr_pages:
        raise HTTPException(400, "缺少 ocr_pages（逐页 OCR 文本）")
    if sum(len(str(p or "")) for p in page_texts) > 500_000:
        raise HTTPException(400, "文本过长（上限约 500KB）")
    try:
        d = pdf_intake.run_commercial_pdf_ocr_pages(
            page_texts, ocr_pages, filename, layout=(payload or {}).get("layout"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"合并失败：{str(e)[:200]}")
    if d.get("error"):
        raise HTTPException(422, d["error"])
    return d
