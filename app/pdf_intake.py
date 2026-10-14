"""PDF intake：房源 flyer / OM / 卖方材料 → 文本提取 → 结构化填表.

铁律：PDF 里所有数字一律标"卖方材料口径、待独立验证"，
绝不直接采信（deal intake 铁律：独立验证先于结构设计）。
文本提取用纯 Python 库 pypdf（零系统依赖，Vercel serverless 可用）；
D2（2026-10-09）：替换原系统 pdftotext（poppler）方案，消除"生产永远传不了 PDF"。
"""

from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime

from pypdf import PdfReader

from . import demand_validation as dv
from . import research_pipeline as rp

CLAIM_LABEL = "卖方材料口径、待独立验证"
# 扫描版 PDF OCR（台账第 3 项，2026-10-14）：无文本层 PDF 的提取结果
# 一律走 OCR 口径标注，与普通文本层提取明确区分，绝不混标。
PDF_OCR_CLAIM_NOTICE = ("以下全部数字为扫描版 PDF OCR 提取、卖方材料口径、待独立验证，"
                        "须独立验证后方可用于估值/打分")
SCANNED_TEXT_THRESHOLD = 50  # 全文字符数低于此值视为无文本层（扫描件）
TALKING_KEYWORDS = ["cap", "noi", "turnkey", "renovat", "cash flow", "appreciation",
                    "below market", "motivated", "as-is", "seller financ",
                    "subject-to", "wrap", "balloon", "upside", "value-add",
                    "拎包", "收益", "回报", "翻新", "急售", "议价"]


def pdftotext_available() -> bool:
    """兼容旧名：pypdf 为硬依赖，恒为 True。新代码请用 pypdf_available()。"""
    return pypdf_available()


def pypdf_available() -> bool:
    return True  # pypdf 在 requirements.txt，为硬依赖


def _normalize_page(raw: str | None) -> str:
    lines = [re.sub(r"[ \t\u00a0]+", " ", ln).strip() for ln in (raw or "").splitlines()]
    return "\n".join(ln for ln in lines if ln)


def extract_text_pages(pdf_path: str) -> tuple[list[str], str]:
    """按页提取：返回 ([page1, page2, ...], note)。pypdf 原生按页，无需 \\x0c 分割。"""
    try:
        reader = PdfReader(pdf_path)
        if reader.is_encrypted:
            return [], "PDF 已加密，无法解析；请解密后上传或手动录入"
        pages = [_normalize_page(pg.extract_text()) for pg in reader.pages]
        if sum(len(p) for p in pages) < 50:
            return [], "PDF 提取出的文本过少（可能是扫描件无文本层），请手动录入"
        return pages, ""
    except Exception as e:  # noqa: BLE001
        return [], f"PDF 解析异常：{str(e)[:150]}"


def extract_text(pdf_path: str) -> tuple[str, str]:
    """返回 (text, note)。失败时 text 为空、note 说明原因。"""
    pages, note = extract_text_pages(pdf_path)
    return "\n".join(pages), note


def inspect_pdf(pdf_path: str) -> dict:
    """扫描件检测（台账第 3 项）：返回页数/文本量/是否扫描件/是否加密。

    与 extract_text_pages 的区别：即使文本过少也保留页数与已提取页，
    供上层决定走 OCR 链路（浏览器端渲染 OCR 或服务端内嵌图 OCR），
    而不是直接报"请手动录入"。
    """
    try:
        reader = PdfReader(pdf_path)
        if reader.is_encrypted:
            return {"pages": [], "page_count": len(reader.pages), "text_chars": 0,
                    "is_scanned": False, "is_encrypted": True,
                    "note": "PDF 已加密，无法解析；请解密后上传或手动录入"}
        pages = [_normalize_page(pg.extract_text()) for pg in reader.pages]
        chars = sum(len(p) for p in pages)
        return {"pages": pages, "page_count": len(pages), "text_chars": chars,
                "is_scanned": chars < SCANNED_TEXT_THRESHOLD,
                "is_encrypted": False, "note": ""}
    except Exception as e:  # noqa: BLE001
        return {"pages": [], "page_count": 0, "text_chars": 0,
                "is_scanned": False, "is_encrypted": False,
                "note": f"PDF 解析异常：{str(e)[:150]}"}


def _money_offset(text: str, value: float) -> int:
    """找 $金额 在文本中的首次偏移（带/不带千分位逗号都试），找不到返回 -1。"""
    iv = int(round(value))
    for pat in (r"\$\s*" + re.escape(f"{iv:,}"), r"\$\s*" + str(iv)):
        m = re.search(pat, text)
        if m:
            return m.start()
    return -1


class _PageMap:
    """字符偏移 → 页码（1-based），供提取字段标注来源页码。"""

    def __init__(self, pages: list[str] | None):
        self.bounds = []
        if pages:
            off = 0
            for p in pages:
                self.bounds.append((off, off + len(p)))
                off += len(p) + 1  # "\n".join

    def page_of(self, offset: int) -> int | None:
        for i, (a, b) in enumerate(self.bounds):
            if a <= offset <= b:
                return i + 1
        return None


def parse_pdf_text(text: str, filename: str, pages: list[str] | None = None,
                   source_label: str | None = None) -> dict:
    """从 PDF 文本抽取字段（全部卖方口径）。pages 可选：用于标注字段来源页码。"""
    at = datetime.now().strftime("%Y-%m-%d %H:%M")
    source = source_label or f"PDF:{filename}"
    pm = _PageMap(pages)

    def F(key, value, display=None, note="", page=None):
        if value is None:
            return None
        d = {"key": key, "label": rp.FIELD_LABELS.get(key, key),
                "value": value, "display": display or str(value),
                "source": source, "source_url": "",
                "fetched_at": at, "confidence": "卖方口径",
                "seller_claimed": True, "claim_label": CLAIM_LABEL,
                "note": note, "status": "filled"}
        if page:
            d["page"] = page
        return d

    fields = []
    price = rp._money_near(text, r"(?:price|asking|list price|for sale|\bsale\b|售价|价格)")
    if price:
        fields.append(F("asking_price", price, f"${price:,.0f}",
                        page=pm.page_of(_money_offset(text, price))))
    sf_m = re.search(r"([\d,]+)\s*(?:sq\.?\s*ft|sqft|square feet|SF|平方英尺)", text, re.I)
    if sf_m and rp._num(sf_m.group(1)):
        v = rp._num(sf_m.group(1))
        fields.append(F("building_sf", v, f"{v:,.0f} SF", page=pm.page_of(sf_m.start())))
    beds_m = re.search(r"(\d+)\s*(?:bd|bed|bedroom|卧)", text, re.I)
    if beds_m:
        fields.append(F("beds", int(beds_m.group(1)), page=pm.page_of(beds_m.start())))
    baths_m = re.search(r"([\d.]+)\s*(?:ba|bath|bathroom|卫)", text, re.I)
    if baths_m:
        try:
            fields.append(F("baths", float(baths_m.group(1)), page=pm.page_of(baths_m.start())))
        except Exception:
            pass
    # 租金声称（月租金口径优先）
    rent_m = re.search(r"(?:rent|租金)[^\$]{0,30}\$\s*([\d,]+)", text, re.I)
    if rent_m and rp._num(rent_m.group(1)):
        v = rp._num(rent_m.group(1))
        if v < 100000:  # 过大则疑似年租金/总价，不采
            fields.append(F("monthly_rent", v, f"${v:,.0f}/月", note="卖方声称租金",
                            page=pm.page_of(rent_m.start())))
    # 卖方话术要点：含 $/%/关键词的行
    points = []
    for line in re.split(r"(?<=[.!?;])\s+|\n", text):
        line = line.strip()
        if 10 < len(line) <= 140 and (
                "$" in line or "%" in line
                or any(k in line.lower() for k in TALKING_KEYWORDS)):
            if line not in points:
                points.append(line)
        if len(points) >= 10:
            break
    if points:
        fields.append({"key": "seller_points", "label": "卖方话术要点",
                       "value": points, "display": f"{len(points)} 条（见明细）",
                       "source": source, "source_url": "", "fetched_at": at,
                       "confidence": "卖方口径", "seller_claimed": True,
                       "claim_label": CLAIM_LABEL,
                       "note": "原文摘录，未核实", "status": "filled"})
    return {"mode": "pdf", "filename": filename, "fields": fields,
            "points": points, "fetched_at": at,
            "claim_notice": f"以下全部数字为{CLAIM_LABEL}，须独立验证后方可用于估值/打分"}



def parse_commercial_pdf_text(text: str, filename: str, pages: list[str] | None = None,
                              source_label: str | None = None) -> dict:
    """商业 OM / flyer → 商业核保字段（全部卖方口径、待验证）。

    pages 可选：用于标注字段来源页码（数据质量门 field_report 用）。
    source_label 可选：覆盖默认来源标注（如"粘贴文本"）。
    """
    at = datetime.now().strftime("%Y-%m-%d %H:%M")
    source = source_label or f"PDF:{filename}"
    pm = _PageMap(pages)

    def F(key, value, display=None, note="", page=None):
        if value is None:
            return None
        d = {"key": key, "label": rp.FIELD_LABELS.get(key, key),
                "value": value, "display": display or str(value),
                "source": source, "source_url": "",
                "fetched_at": at, "confidence": "卖方口径",
                "seller_claimed": True, "claim_label": CLAIM_LABEL,
                "note": note, "status": "filled"}
        if page:
            d["page"] = page
        return d

    fields = []
    # ---- 价格 ----
    price = rp._money_near(text, r"(?:price|asking|list price|for sale|\bsale\b|offering price|售价|价格|要价)")
    if price:
        fields.append(F("analysis.purchase_price", price, f"${price:,.0f}",
                        page=pm.page_of(_money_offset(text, price))))
    # ---- 面积 ----
    sf_m = re.search(r"([\d,]+)[ \t]*(?:sq\.?[ \t]*ft|sqft|square[ \t]*feet|\bSF\b)(?![A-Za-z])", text, re.I)
    if sf_m and rp._num(sf_m.group(1)):
        v = rp._num(sf_m.group(1))
        if 500 < v < 10000000:
            fields.append(F("property.net_rentable_sf", v, f"{v:,.0f} SF",
                            page=pm.page_of(sf_m.start())))
    # ---- NOI ----
    for label, pat in [
        ("analysis.underwritten_noi", r"(?:in-?place\s+NOI|current\s+NOI|在手\s*NOI|现有\s*NOI)[^\$]{0,40}\$\s*([\d,]+)"),
        ("analysis.projected_noi", r"(?:pro\s*forma\s+NOI|projected\s+NOI|stabilized\s+NOI|预测\s*NOI)[^\$]{0,40}\$\s*([\d,]+)"),
    ]:
        m = re.search(pat, text, re.I)
        if m and rp._num(m.group(1)):
            v = rp._num(m.group(1))
            fields.append(F(label, v, f"${v:,.0f}", note="卖方声称",
                            page=pm.page_of(m.start())))
    # 通用 NOI（未标 in-place/pro forma 时）
    if not any(f["key"].endswith("noi") for f in fields):
        m = re.search(r"\bNOI\b[^\$]{0,30}\$\s*([\d,]+)", text, re.I)
        if m and rp._num(m.group(1)):
            v = rp._num(m.group(1))
            fields.append(F("analysis.underwritten_noi", v, f"${v:,.0f}", note="卖方声称，未区分在手/预测",
                            page=pm.page_of(m.start())))
    # ---- Cap Rate ----
    cap_m = re.search(r"(?:cap\s+rate|\bcap\b)[^\d%]{0,20}([\d.]+)\s*%", text, re.I)
    if cap_m:
        try:
            fields.append(F("analysis.market_cap_rate", float(cap_m.group(1)) / 100,
                            f"{cap_m.group(1)}%", note="卖方声称 cap rate",
                            page=pm.page_of(cap_m.start())))
        except Exception:
            pass
    # ---- 年份 ----
    yr_m = re.search(r"(?:built|year built|constructed|建成|建造)[^\d]{0,20}(19\d{2}|20[0-2]\d)", text, re.I)
    if yr_m:
        fields.append(F("property.year_built", yr_m.group(1), page=pm.page_of(yr_m.start())))
    # ---- 地址（首个像地址的行）----
    addr_m = re.search(r"^\s*(\d+\s+[A-Z][A-Za-z0-9.\-]{1,30}(?:[ \t]+(?:St|Street|Ave|Avenue|Blvd|Boulevard|Rd|Road|Dr|Drive|Ln|Lane|Way|Pl|Place)\b)?[^,\n]{0,30})", text, re.M | re.I)
    if addr_m:
        a = addr_m.group(1).strip()
        if len(a) < 80:
            fields.append(F("property.address", a, page=pm.page_of(addr_m.start())))
            # 尝试抓 City, ST ZIP
            csz = re.search(re.escape(a) + r"\s*,?\s*([A-Za-z\s]+),\s*([A-Z]{2})\s*(\d{5})", text)
            if csz:
                fields.append(F("property.city", csz.group(1).strip(), page=pm.page_of(csz.start())))
                fields.append(F("property.state", csz.group(2), page=pm.page_of(csz.start())))
                fields.append(F("property.zip", csz.group(3), page=pm.page_of(csz.start())))
    # ---- 物业类型 ----
    for tkw, tval in [("shopping center", "零售"), ("retail", "零售"), ("office", "办公"),
                      ("industrial", "工业/物流"), ("warehouse", "物流仓储"), ("multifamily", "公寓"),
                      ("mixed-use", "混合用途"), ("hospitality", "酒店")]:
        tm = re.search(r"\b" + tkw + r"\b", text, re.I)
        if tm:
            fields.append(F("property.property_type", tval, note="关键词推断",
                            page=pm.page_of(tm.start())))
            break
    # ---- 租户（租约表行：Suite + 租户名 + SF + 租金）----
    tenants = []
    for m in re.finditer(
        r"(?:Suite|Unit)\s*([A-Za-z0-9\-]+)\s+([A-Za-z0-9\s&.,'\-]{2,40}?)\s+([\d,]+)\s*(?:SF|sq\.?\s*ft)?\s+\$\s*([\d,]+)",
        text):
        try:
            tenants.append({
                "suite": m.group(1).strip(),
                "tenant": m.group(2).strip(),
                "sf": rp._num(m.group(3)),
                "monthly_rent": rp._num(m.group(4)),
                "page": pm.page_of(m.start()),
            })
        except Exception:
            continue
        if len(tenants) >= 40:
            break
    return {"mode": "pdf-commercial", "filename": filename, "fields": fields,
            "tenants": tenants, "fetched_at": at,
            "claim_notice": f"以下全部数字为{CLAIM_LABEL}，须独立验证后方可用于估值/打分"}


def _scanned_needs_ocr(mode: str, filename: str, info: dict,
                       extra: dict | None = None) -> dict:
    """扫描件无文本层时的结构化返回：前端据 needs_ocr 走浏览器端 OCR。

    绝不假装已提取：fields 为空、error 明示原因，并带机器可读标志
    （needs_ocr / error_code），前端渲染页面为图后 OCR 再回传文本。
    """
    d = {"mode": mode, "filename": filename, "fields": [], "tenants": [],
         "error": ("PDF 为扫描件（无文本层，共 "
                   f"{info.get('page_count', 0)} 页、仅提取到 "
                   f"{info.get('text_chars', 0)} 字符），需先 OCR 再提取；"
                   "页面将自动走浏览器端 OCR，或改用粘贴文本/截图"),
         "error_code": "scanned_pdf_needs_ocr",
         "needs_ocr": True, "ocr_required": True, "is_scanned_pdf": True,
         "page_count": info.get("page_count", 0),
         "text_chars": info.get("text_chars", 0),
         "claim_notice": PDF_OCR_CLAIM_NOTICE,
         "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
    if extra:
        d.update(extra)
    return d


def try_server_pdf_ocr(saved_path: str) -> tuple[str, str]:
    """服务端扫描 PDF OCR 尝试：提取内嵌扫描图逐张 OCR（需 tesseract）。

    生产 serverless 无 tesseract 时诚实返回空文本＋原因，由前端浏览器
    端 OCR 接管；绝不编造识别结果。
    """
    if not server_ocr_available():
        return "", "服务端无 OCR 引擎（tesseract 未安装）"
    try:
        reader = PdfReader(saved_path)
    except Exception as e:  # noqa: BLE001
        return "", f"PDF 解析异常：{str(e)[:150]}"
    texts: list[str] = []
    for pg in reader.pages:
        try:
            images = list(pg.images)
        except Exception:  # noqa: BLE001
            images = []
        for img in images:
            try:
                data = img.data
            except Exception:  # noqa: BLE001
                continue
            if not data:
                continue
            t, _note = extract_text_from_image_bytes(data)
            if t:
                texts.append(t)
    joined = "\n".join(texts)
    if len(joined.strip()) < 20:
        return "", "服务端 OCR 未识别出足够文本（内嵌图为空或不清晰）"
    return joined, ""


def run_commercial_pdf_upload(saved_path: str, filename: str) -> dict:
    from . import validators
    info = inspect_pdf(saved_path)
    if info["note"]:
        return {"mode": "pdf-commercial", "filename": filename, "fields": [],
                "tenants": [], "error": info["note"],
                "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
    if info["is_scanned"]:
        # 先试服务端内嵌图 OCR（本地/自托管有 tesseract 时直接闭环）
        ocr_text, _ocr_note = try_server_pdf_ocr(saved_path)
        if ocr_text:
            return run_commercial_pdf_ocr_text(
                ocr_text, filename, engine="tesseract-server")
        return _scanned_needs_ocr("pdf-commercial", filename, info)
    pages = info["pages"]
    text = "\n".join(pages)
    d = parse_commercial_pdf_text(text, filename, pages=pages)
    d["text_chars"] = len(text)
    d["excerpt"] = text[:500]
    d["is_scanned_pdf"] = False
    # 2026-10-06：intake 数据质量门 —— fail 拦截、warn 标黄
    d["quality_gate"] = validators.run_quality_gate(
        "commercial", d["fields"], tenants=d.get("tenants"),
        raw_text=text, pages=pages)
    return d


def run_commercial_pdf_ocr_text(text: str, filename: str = "scanned.pdf",
                                engine: str = "browser-tesseract") -> dict:
    """扫描版 PDF OCR 文本 intake（台账第 3 项，2026-10-14）。

    扫描 PDF 经 OCR（浏览器端 pdf.js 渲染 + Tesseract.js，或服务端
    tesseract 内嵌图）转文本后走与普通 PDF 相同的抽取引擎；来源标
    "扫描PDF OCR:<文件名>"、claim_notice 明示"OCR 口径"，同样跑质量门。
    """
    from . import validators
    text = text or ""
    at = datetime.now().strftime("%Y-%m-%d %H:%M")
    fname = (filename or "scanned.pdf").strip() or "scanned.pdf"
    if len(text.strip()) < 20:
        return {"mode": "pdf-ocr", "filename": fname, "fields": [], "tenants": [],
                "error": "OCR 未识别出足够文本（少于 20 字符），请换更清晰的扫描件或改用粘贴文本",
                "error_code": "ocr_text_too_short",
                "ocr_engine": engine, "is_scanned_pdf": True,
                "fetched_at": at, "claim_notice": PDF_OCR_CLAIM_NOTICE}
    d = parse_commercial_pdf_text(text, fname, pages=None,
                                  source_label=f"扫描PDF OCR:{fname}")
    d["mode"] = "pdf-ocr"
    d["ocr_engine"] = engine
    d["is_scanned_pdf"] = True
    d["extraction_method"] = "ocr"
    d["text_chars"] = len(text)
    d["excerpt"] = text[:500]
    d["claim_notice"] = PDF_OCR_CLAIM_NOTICE
    d["quality_gate"] = validators.run_quality_gate(
        "commercial", d["fields"], tenants=d.get("tenants"), raw_text=text,
        pages=None)
    return d


def run_pdf_ocr_text(text: str, filename: str = "scanned.pdf",
                     engine: str = "browser-tesseract") -> dict:
    """住宅扫描版 PDF OCR 文本 intake（台账第 3 项，住宅路同款）。

    与商业路共用 OCR 口径标注：来源"扫描PDF OCR:<文件名>"、
    claim_notice 明示 OCR 口径，附质量门与需求验证清单。
    """
    from . import validators
    text = text or ""
    at = datetime.now().strftime("%Y-%m-%d %H:%M")
    fname = (filename or "scanned.pdf").strip() or "scanned.pdf"
    if len(text.strip()) < 20:
        return {"mode": "pdf-ocr", "filename": fname, "fields": [],
                "error": "OCR 未识别出足够文本（少于 20 字符），请换更清晰的扫描件或改用粘贴文本",
                "error_code": "ocr_text_too_short",
                "ocr_engine": engine, "is_scanned_pdf": True,
                "fetched_at": at, "claim_notice": PDF_OCR_CLAIM_NOTICE,
                "demand_validation": dv.demand_validation_block()}
    d = parse_pdf_text(text, fname, pages=None,
                       source_label=f"扫描PDF OCR:{fname}")
    d["mode"] = "pdf-ocr"
    d["ocr_engine"] = engine
    d["is_scanned_pdf"] = True
    d["extraction_method"] = "ocr"
    d["text_chars"] = len(text)
    d["excerpt"] = text[:500]
    d["claim_notice"] = PDF_OCR_CLAIM_NOTICE
    d["quality_gate"] = validators.run_quality_gate(
        "residential", d["fields"], raw_text=text, pages=None)
    d["demand_validation"] = dv.demand_validation_block()
    return d


def run_commercial_text_upload(text: str) -> dict:
    """商业粘贴文本 intake（台账 2026-10-07）：粘贴 OM/flyer 文本 → 结构化字段。

    与 PDF intake 共用同一抽取引擎（parse_commercial_pdf_text），抽取逻辑
    完全一致；全部字段标"卖方材料口径、待独立验证"，同样跑数据质量门。
    """
    from . import validators
    text = text or ""
    at = datetime.now().strftime("%Y-%m-%d %H:%M")
    d = parse_commercial_pdf_text(text, "pasted-text.txt", pages=None,
                                  source_label="粘贴文本")
    d["mode"] = "paste"
    d["text_chars"] = len(text)
    d["excerpt"] = text[:500]
    d["claim_notice"] = f"以下全部数字为{CLAIM_LABEL}，须独立验证后方可用于估值/打分"
    # 2026-10-06 数据质量门同样适用：fail 拦截、warn 标黄
    d["quality_gate"] = validators.run_quality_gate(
        "commercial", d["fields"], tenants=d.get("tenants"), raw_text=text,
        pages=None)
    return d


def run_pdf_upload(saved_path: str, filename: str) -> dict:
    from . import validators
    info = inspect_pdf(saved_path)
    if info["note"]:
        return {"mode": "pdf", "filename": filename, "fields": [],
                "error": info["note"],
                "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "demand_validation": dv.demand_validation_block()}
    if info["is_scanned"]:
        ocr_text, _ocr_note = try_server_pdf_ocr(saved_path)
        if ocr_text:
            return run_pdf_ocr_text(ocr_text, filename, engine="tesseract-server")
        return _scanned_needs_ocr(
            "pdf", filename, info,
            extra={"demand_validation": dv.demand_validation_block()})
    pages = info["pages"]
    text = "\n".join(pages)
    d = parse_pdf_text(text, filename, pages=pages)
    d["text_chars"] = len(text)
    d["excerpt"] = text[:500]
    d["is_scanned_pdf"] = False
    # 2026-10-06：intake 数据质量门 —— fail 拦截、warn 标黄
    d["quality_gate"] = validators.run_quality_gate(
        "residential", d["fields"], raw_text=text, pages=pages)
    # W2（2026-10-05）：PDF 卖方材料 intake 同样附有效需求验证清单
    d["demand_validation"] = dv.demand_validation_block()
    return d


IMAGE_CLAIM_NOTICE = ("以下全部数字为截图 OCR 提取、卖方材料口径、待独立验证，"
                      "须独立验证后方可用于估值/打分")


def run_commercial_image_ocr_text(text: str, filename: str = "screenshot.png",
                                  engine: str = "browser-tesseract") -> dict:
    """商业截图 OCR 文本 intake（台账第 2 项，2026-10-13）。

    截图先经 OCR（浏览器端 Tesseract.js，或服务端 tesseract 若可用）转文本，
    再与 PDF/粘贴 intake 共用同一抽取引擎（parse_commercial_pdf_text）。
    全部字段标"卖方材料口径、待独立验证"，来源标"截图OCR:<文件名>"，
    同样跑数据质量门（quality_gate）。
    """
    from . import validators
    text = text or ""
    at = datetime.now().strftime("%Y-%m-%d %H:%M")
    fname = (filename or "screenshot.png").strip() or "screenshot.png"
    if len(text.strip()) < 20:
        return {"mode": "image", "filename": fname, "fields": [], "tenants": [],
                "error": "OCR 未识别出足够文本（少于 20 字符），请换更清晰的截图或改用粘贴文本",
                "error_code": "ocr_text_too_short",
                "ocr_engine": engine, "fetched_at": at,
                "claim_notice": IMAGE_CLAIM_NOTICE}
    d = parse_commercial_pdf_text(text, fname, pages=None,
                                  source_label=f"截图OCR:{fname}")
    d["mode"] = "image"
    d["ocr_engine"] = engine
    d["text_chars"] = len(text)
    d["excerpt"] = text[:500]
    d["claim_notice"] = IMAGE_CLAIM_NOTICE
    d["quality_gate"] = validators.run_quality_gate(
        "commercial", d["fields"], tenants=d.get("tenants"), raw_text=text,
        pages=None)
    return d


def server_ocr_available() -> bool:
    """服务端 OCR 是否可用：tesseract 二进制在 PATH，或 pytesseract 可导入。"""
    import shutil
    if shutil.which("tesseract"):
        return True
    try:
        import pytesseract  # noqa: F401
        return shutil.which("tesseract") is not None
    except Exception:
        return False


def extract_text_from_image_bytes(data: bytes) -> tuple[str, str]:
    """服务端 OCR：图片字节 -> (text, note)。无引擎时 text 为空、note 说明。

    生产（Vercel serverless）无 tesseract 二进制，主路径是浏览器端 OCR；
    本函数只在本地/自托管装有 tesseract 时生效，绝不编造识别结果。
    """
    import io
    import shutil
    import subprocess
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
    except Exception as e:  # noqa: BLE001
        return "", f"文件不是有效的图片：{str(e)[:120]}"
    exe = shutil.which("tesseract")
    if not exe:
        return "", ("服务端无 OCR 引擎（tesseract 未安装）；"
                    "请使用商业页浏览器端 OCR（上传截图自动识别），或改用粘贴文本")
    # tesseract 读 stdin、写 stdout，不落盘
    try:
        proc = subprocess.run([exe, "stdin", "stdout", "-l", "eng"],
                              input=data, capture_output=True, timeout=60)
        text = (proc.stdout or b"").decode("utf-8", errors="replace")
        return _normalize_page(text), "" if text.strip() else "OCR 未识别出文本"
    except Exception as e:  # noqa: BLE001
        return "", f"服务端 OCR 异常：{str(e)[:150]}"


def run_commercial_image_upload(data: bytes, filename: str) -> dict:
    """服务端直传图片 intake：OCR 成功走 OCR 文本链路；无引擎返回明确 error_code。"""
    at = datetime.now().strftime("%Y-%m-%d %H:%M")
    fname = (filename or "screenshot.png").strip() or "screenshot.png"
    text, note = extract_text_from_image_bytes(data)
    if not text:
        return {"mode": "image", "filename": fname, "fields": [], "tenants": [],
                "error": note, "error_code": "ocr_unavailable_server",
                "ocr_engine": "none", "fetched_at": at,
                "claim_notice": IMAGE_CLAIM_NOTICE}
    d = run_commercial_image_ocr_text(text, fname, engine="tesseract-server")
    return d


def save_upload(file_bytes: bytes, filename: str) -> str:
    """保存上传文件到 /tmp（临时），返回路径。"""
    safe = re.sub(r"[^A-Za-z0-9._\-]", "_", filename)[-80:]
    fd, path = tempfile.mkstemp(prefix="wb_pdf_", suffix="_" + safe, dir="/tmp")
    with os.fdopen(fd, "wb") as f:
        f.write(file_bytes)
    return path
