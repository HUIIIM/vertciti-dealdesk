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

from . import research_pipeline as rp

CLAIM_LABEL = "卖方材料口径、待独立验证"
TALKING_KEYWORDS = ["cap", "noi", "turnkey", "renovat", "cash flow", "appreciation",
                    "below market", "motivated", "as-is", "seller financ",
                    "subject-to", "wrap", "balloon", "upside", "value-add",
                    "拎包", "收益", "回报", "翻新", "急售", "议价"]


def pdftotext_available() -> bool:
    return shutil.which("pdftotext") is not None


def extract_text(pdf_path: str) -> tuple[str, str]:
    """返回 (text, note)。失败时 text 为空、note 说明原因。"""
    if not pdftotext_available():
        return "", "系统缺少 pdftotext（poppler），无法解析 PDF；请手动录入"
    try:
        out = pdf_path + ".txt"
        r = subprocess.run(["pdftotext", "-layout", pdf_path, out],
                           capture_output=True, timeout=60)
        if r.returncode != 0 or not os.path.exists(out):
            return "", f"pdftotext 失败（exit {r.returncode}）：{r.stderr.decode()[:150]}"
        with open(out, encoding="utf-8", errors="ignore") as f:
            text = f.read()
        os.remove(out)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < 50:
            return "", "PDF 提取出的文本过少（可能是扫描件无文本层），请手动录入"
        return text, ""
    except Exception as e:  # noqa: BLE001
        return "", f"PDF 解析异常：{str(e)[:150]}"


def parse_pdf_text(text: str, filename: str) -> dict:
    """从 PDF 文本抽取字段（全部卖方口径）。"""
    at = datetime.now().strftime("%Y-%m-%d %H:%M")
    source = f"PDF:{filename}"

    def F(key, value, display=None, note=""):
        if value is None:
            return None
        return {"key": key, "label": rp.FIELD_LABELS.get(key, key),
                "value": value, "display": display or str(value),
                "source": source, "source_url": "",
                "fetched_at": at, "confidence": "卖方口径",
                "seller_claimed": True, "claim_label": CLAIM_LABEL,
                "note": note, "status": "filled"}

    fields = []
    price = rp._money_near(text, r"(?:price|asking|list price|for sale|\bsale\b|售价|价格)")
    if price:
        fields.append(F("asking_price", price, f"${price:,.0f}"))
    sf_m = re.search(r"([\d,]+)\s*(?:sq\.?\s*ft|sqft|square feet|SF|平方英尺)", text, re.I)
    if sf_m and rp._num(sf_m.group(1)):
        v = rp._num(sf_m.group(1))
        fields.append(F("building_sf", v, f"{v:,.0f} SF"))
    beds_m = re.search(r"(\d+)\s*(?:bd|bed|bedroom|卧)", text, re.I)
    if beds_m:
        fields.append(F("beds", int(beds_m.group(1))))
    baths_m = re.search(r"([\d.]+)\s*(?:ba|bath|bathroom|卫)", text, re.I)
    if baths_m:
        try:
            fields.append(F("baths", float(baths_m.group(1))))
        except Exception:
            pass
    # 租金声称（月租金口径优先）
    rent_m = re.search(r"(?:rent|租金)[^\$]{0,30}\$\s*([\d,]+)", text, re.I)
    if rent_m and rp._num(rent_m.group(1)):
        v = rp._num(rent_m.group(1))
        if v < 100000:  # 过大则疑似年租金/总价，不采
            fields.append(F("monthly_rent", v, f"${v:,.0f}/月", note="卖方声称租金"))
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


def run_pdf_upload(saved_path: str, filename: str) -> dict:
    text, note = extract_text(saved_path)
    if not text:
        return {"mode": "pdf", "filename": filename, "fields": [],
                "error": note, "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
    d = parse_pdf_text(text, filename)
    d["text_chars"] = len(text)
    d["excerpt"] = text[:500]
    return d


def save_upload(file_bytes: bytes, filename: str) -> str:
    """保存上传文件到 /tmp（临时），返回路径。"""
    safe = re.sub(r"[^A-Za-z0-9._\-]", "_", filename)[-80:]
    fd, path = tempfile.mkstemp(prefix="wb_pdf_", suffix="_" + safe, dir="/tmp")
    with os.fdopen(fd, "wb") as f:
        f.write(file_bytes)
    return path
