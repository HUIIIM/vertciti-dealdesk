"""取数（老版功能搬进 v2）：从已上传的 PDF 提取字段、按地址 / 房源链接自动搜集、导入老版项目。

提取与搜集只给“候选值”，不直接改承销：每个候选带来源、页码、可信度，并标好它对应的承销输入路径；
用户在工作台逐条采用后才写进草稿，同时登记数字护照（谁、从哪份文件第几页取的）。
卖方材料里的数一律按“卖方口径”低可信度登记，必须另行复核。
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.i18n import T
from app.services import db as legacy_db
from app.services import pdf_intake, research_pipeline
from app.services.persistence.engine import session_scope
from app.services.persistence.schema import Deal, Document
from app.services.v2 import deals
from app.services.v2.errors import InvalidInputError, NotFoundError

JSON = dict[str, Any]

# 老版字段键 → v2 承销输入路径（None = 只作参考，不是承销输入）
_PATHS: dict[str, dict[str, str]] = {
    "residential": {"asking_price": "price", "monthly_rent": "monthly_rent",
                    "taxes_annual": "taxes_annual", "hoa_monthly": "hoa_monthly"},
    "commercial": {"asking_price": "analysis.purchase_price", "address": "property.address",
                   "year_built": "property.year_built", "taxes_annual": "historical.property_tax"},
    # 机构级：沿用商业 PDF 提取，键映射到逐租约引擎的输入；租约表行由前端转成 leases
    "institutional": {"asking_price": "purchase_price", "analysis.purchase_price": "purchase_price",
                      "property.net_rentable_sf": "area_sf", "building_sf": "area_sf"},
}
_CONFIDENCE = {"高": "high", "中": "medium", "high": "high", "medium": "medium"}  # 其余（低 / 卖方口径）→ low
_TEXT_PATHS = {"property.address", "property.city", "property.state", "property.zip", "property.property_type"}
LEGACY_TAG = "v1:{kind}:{pid}"


def _path_for(track: str, key: str) -> str | None:
    if track == "commercial" and "." in key:  # 商业 PDF 提取的键本身就是承销输入路径
        return key
    return _PATHS[track].get(key)


def _adoptable(path: str | None, value: Any) -> bool:
    if path is None:
        return False
    if path in _TEXT_PATHS:
        return isinstance(value, str) and bool(value.strip())
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _candidates(track: str, fields: list[JSON], *, source: str, method: str) -> list[JSON]:
    out = []
    for f in fields:
        key, value = str(f.get("key", "")), f.get("value")
        path = _path_for(track, key)
        conf_label = str(f.get("confidence") or "")
        out.append({
            "key": key, "label": str(f.get("label") or key),
            "path": path if _adoptable(path, value) else None,
            "value": value if isinstance(value, (int, float, str)) and not isinstance(value, bool) else None,
            "display": str(f.get("display") or value or ""),
            "page": f.get("page") if isinstance(f.get("page"), int) else None,
            "source": str(f.get("source") or source)[:300], "source_url": str(f.get("source_url") or ""),
            "confidence": _CONFIDENCE.get(conf_label, "low"), "confidence_label": conf_label,
            "seller_claimed": bool(f.get("seller_claimed")), "note": str(f.get("note") or ""),
            "method": method,
        })
    return out


def _track_of(deal_id: int) -> tuple[str, str]:
    with session_scope() as s:
        d = deals.deal_or_404(s, deal_id)
        return d.track, d.name


# ---------------------------------------------------------------- 从已上传的文件提取
def extract_document(deal_id: int, doc_id: int) -> JSON:
    track, _ = _track_of(deal_id)
    with session_scope() as s:
        doc = s.get(Document, doc_id)
        if doc is None or doc.deal_id != deal_id:
            raise NotFoundError(T("文件 {0} 不存在", doc_id))
        filename, data = doc.filename, bytes(doc.content)
    if not data.startswith(b"%PDF-"):
        raise InvalidInputError(T("目前只能从 PDF 提取字段（图片和扫描件请先 OCR 或手动录入）"))
    fd, path = tempfile.mkstemp(prefix="dd_extract_", suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        run = pdf_intake.run_pdf_upload if track == "residential" else pdf_intake.run_commercial_pdf_upload
        r = run(path, filename)
    finally:
        Path(path).unlink()
    if r.get("needs_ocr"):
        raise InvalidInputError(T("这份 PDF 是扫描件（没有文字层），需要先 OCR；可以手动录入或上传带文字的版本"))
    if r.get("error") and not r.get("fields"):
        raise InvalidInputError(T("提取失败：{0}", str(r["error"])[:200]))
    return {"document_id": doc_id, "filename": filename, "track": track,
            "candidates": _candidates(track, r.get("fields") or [], source=filename, method="pdf"),
            "tenants": [t for t in (r.get("tenants") or []) if isinstance(t, dict)][:40],
            "notice": T("以下全部是卖方材料口径，采用后仍需独立复核")}


# ---------------------------------------------------------------- 按地址 / 链接搜集公开信息
def research(track: str, mode: str, text: str) -> JSON:
    if track not in _PATHS:
        raise InvalidInputError(T("赛道只能是 residential 或 commercial"))
    if mode not in ("address", "url"):
        raise InvalidInputError(T("搜集方式只能是 address（地址）或 url（房源链接）"))
    if not text.strip():
        raise InvalidInputError(T("请输入地址或房源链接"))
    r = research_pipeline.run(mode, text.strip())
    fields = r.get("fields") or []
    address = next((str(f.get("value")) for f in fields if f.get("key") == "address" and f.get("value")), "")
    return {"track": track, "mode": mode, "address": address or (text.strip() if mode == "address" else ""),
            "candidates": _candidates(track, fields, source=T("公开网页"), method="api"),
            "manual_needed": [str(x.get("label") if isinstance(x, dict) else x)
                              for x in (r.get("manual_needed") or [])],
            "error": str(r.get("error") or "")}


# ---------------------------------------------------------------- 导入老版项目
def _imported() -> dict[str, int]:
    with session_scope() as s:
        out: dict[str, int] = {}
        for d in s.scalars(select(Deal).where(Deal.archived.is_(False))).all():
            for t in d.tags or []:
                if isinstance(t, str) and t.startswith("v1:"):
                    out[t] = d.id
        return out


def list_legacy() -> list[JSON]:
    done = _imported()
    rows = [{"kind": "project", "id": p["id"], "track": p["track"], "name": p["name"], "address": p["address"],
             "updated_at": p["updated_at"]} for p in legacy_db.list_projects()]
    rows += [{"kind": "uw", "id": p["id"], "track": "commercial", "name": p["name"],
              "address": str((p["input"].get("property") or {}).get("address") or ""), "updated_at": p["updated_at"]}
             for p in legacy_db.list_uw_projects()]
    for r in rows:
        r["imported_deal_id"] = done.get(LEGACY_TAG.format(kind=r["kind"], pid=r["id"]))
    return sorted(rows, key=lambda r: r["updated_at"] or 0, reverse=True)


def import_legacy(kind: str, pid: int) -> JSON:
    """老版项目 → 新交易 + 第一版承销（输入原样带过来）。同一项目不重复导入。"""
    tag = LEGACY_TAG.format(kind=kind, pid=pid)
    if kind == "project":
        p = legacy_db.get_project(pid)
        track = p["track"] if p else ""
        name, address = (p["name"], p["address"]) if p else ("", "")
    elif kind == "uw":
        p = legacy_db.get_uw_project(pid)
        track, name = "commercial", p["name"] if p else ""
        address = str(((p or {}).get("input", {}).get("property") or {}).get("address") or "")
    else:
        raise InvalidInputError(T("老版项目类型只能是 project 或 uw"))
    if p is None:
        raise NotFoundError(T("老版项目 {0} 不存在", pid))
    if tag in _imported():
        raise InvalidInputError(T("这个老版项目已经导入过了"))
    deal = deals.create_deal(name or T("老版项目 {0}", pid), track, address=address, tags=[tag])
    inputs = {k: v for k, v in (p.get("input") or {}).items() if k not in ("name", "address")}
    try:
        version = deals.save_version(deal["id"], inputs, T("从老版导入"))
    except InvalidInputError as e:  # 输入不全（老版允许存半成品）：交易照建，承销留给用户补
        return {"deal": deal, "version": None, "warning": str(e)}
    return {"deal": deal, "version": version, "warning": ""}
