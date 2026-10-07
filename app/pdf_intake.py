"""PDF intake：房源 flyer / OM / 卖方材料 → 文本提取 → 结构化填表.

铁律：PDF 里所有数字一律标"卖方材料口径、待独立验证"，
绝不直接采信（deal intake 铁律：独立验证先于结构设计）。
文本提取用系统 pdftotext（poppler）；缺失则明确报错，不静默失败。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime

from . import demand_validation as dv
from . import research_pipeline as rp

CLAIM_LABEL = "卖方材料口径、待独立验证"
TALKING_KEYWORDS = ["cap", "noi", "turnkey", "renovat", "cash flow", "appreciation",
                    "below market", "motivated", "as-is", "seller financ",
                    "subject-to", "wrap", "balloon", "upside", "value-add",
                    "拎包", "收益", "回报", "翻新", "急售", "议价"]


def pdftotext_available() -> bool:
    return shutil.which("pdftotext") is not None


def extract_text_pages(pdf_path: str) -> tuple[list[str], str]:
    """按页提取：返回 ([page1, page2, ...], note)。pdftotext 用 \x0c 分页。"""
    if not pdftotext_available():
        return [], "系统缺少 pdftotext（poppler），无法解析 PDF；请手动录入"
    try:
        out = pdf_path + ".txt"
        r = subprocess.run(["pdftotext", "-layout", pdf_path, out],
                           capture_output=True, timeout=60,
                           stdin=subprocess.DEVNULL)  # 加密 PDF 不等待密码输入
        if r.returncode != 0 or not os.path.exists(out):
            return [], f"pdftotext 失败（exit {r.returncode}）：{r.stderr.decode(errors='ignore')[:150]}"
        with open(out, encoding="utf-8", errors="ignore") as f:
            raw = f.read()
        os.remove(out)
        pages = []
        for pg in raw.split("\x0c"):
            lines = [re.sub(r"[ \t\u00a0]+", " ", ln).strip() for ln in pg.splitlines()]
            pg_text = "\n".join(ln for ln in lines if ln)
            pages.append(pg_text)
        if sum(len(p) for p in pages) < 50:
            return [], "PDF 提取出的文本过少（可能是扫描件无文本层），请手动录入"
        return pages, ""
    except Exception as e:  # noqa: BLE001
        return [], f"PDF 解析异常：{str(e)[:150]}"


def extract_text(pdf_path: str) -> tuple[str, str]:
    """返回 (text, note)。失败时 text 为空、note 说明原因。"""
    pages, note = extract_text_pages(pdf_path)
    return "\n".join(pages), note


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


def parse_pdf_text(text: str, filename: str, pages: list[str] | None = None) -> dict:
    """从 PDF 文本抽取字段（全部卖方口径）。pages 可选：用于标注字段来源页码。"""
    at = datetime.now().strftime("%Y-%m-%d %H:%M")
    source = f"PDF:{filename}"
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


def run_commercial_pdf_upload(saved_path: str, filename: str) -> dict:
    from . import validators
    pages, note = extract_text_pages(saved_path)
    text = "\n".join(pages)
    if not text:
        return {"mode": "pdf-commercial", "filename": filename, "fields": [],
                "tenants": [], "error": note,
                "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
    d = parse_commercial_pdf_text(text, filename, pages=pages)
    d["text_chars"] = len(text)
    d["excerpt"] = text[:500]
    # 2026-10-06：intake 数据质量门 —— fail 拦截、warn 标黄
    d["quality_gate"] = validators.run_quality_gate(
        "commercial", d["fields"], tenants=d.get("tenants"),
        raw_text=text, pages=pages)
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
    pages, note = extract_text_pages(saved_path)
    text = "\n".join(pages)
    if not text:
        return {"mode": "pdf", "filename": filename, "fields": [],
                "error": note, "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "demand_validation": dv.demand_validation_block()}
    d = parse_pdf_text(text, filename, pages=pages)
    d["text_chars"] = len(text)
    d["excerpt"] = text[:500]
    # 2026-10-06：intake 数据质量门 —— fail 拦截、warn 标黄
    d["quality_gate"] = validators.run_quality_gate(
        "residential", d["fields"], raw_text=text, pages=pages)
    # W2（2026-10-05）：PDF 卖方材料 intake 同样附有效需求验证清单
    d["demand_validation"] = dv.demand_validation_block()
    return d


def save_upload(file_bytes: bytes, filename: str) -> str:
    """保存上传文件到 /tmp（临时），返回路径。"""
    safe = re.sub(r"[^A-Za-z0-9._\-]", "_", filename)[-80:]
    fd, path = tempfile.mkstemp(prefix="wb_pdf_", suffix="_" + safe, dir="/tmp")
    with os.fdopen(fd, "wb") as f:
        f.write(file_bytes)
    return path
