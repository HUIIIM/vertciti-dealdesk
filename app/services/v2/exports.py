"""导出（老版功能搬进 v2）：投资备忘录 PDF、核保明细 Excel、一页纸 Tear Sheet、经典核保报告。

都按交易的**当前承销版本**现算（与工作台同一引擎、同一输入），不另开一套数；缺数照旧渲染“—”。
商业导出前先过 v1 的数据质量门：输入自相矛盾就拦下（422），不导出一份错的报告。
渲染器沿用 v1（app/services/render），版式与老版导出逐字一致。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.core.i18n import T
from app.domain import uw_commercial, validators
from app.domain.v2.model import ModelInputError, run_model
from app.services.persistence.engine import session_scope
from app.services.render import excel_uw, pdf_report, pdf_uw, tearsheet
from app.services.v2.deals import _event, current_version, deal_or_404
from app.services.v2.errors import InvalidInputError

JSON = dict[str, Any]
PDF = "application/pdf"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# 导出种类 → (允许的赛道, 文件后缀, 媒体类型)
KINDS: dict[str, tuple[tuple[str, ...], str, str]] = {
    "memo": (("residential", "commercial"), "pdf", PDF),
    "model": (("residential", "commercial"), "xlsx", XLSX),
    "tearsheet": (("commercial",), "pdf", PDF),
    "report": (("commercial",), "pdf", PDF),
}
_STRIP = ("name", "address")


def _slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:40]
    return s or "deal"


def _deal_meta(name: str, address: str, inputs: JSON) -> JSON:
    return {"name": name, "address": address, "has_rent_roll": bool(inputs.get("tenants"))}


def _commercial(kind: str, name: str, address: str, inputs: JSON) -> bytes:
    clean = {k: v for k, v in inputs.items() if k not in _STRIP}
    gate = validators.gate_verdict_for_state(clean)
    if gate.get("blocked"):
        raise InvalidInputError(T("数据质量门拦截：{0} 项输入自相矛盾，修正后再导出", gate.get("fails_n", 0)))
    try:
        r = uw_commercial.compute_all(clean)
    except Exception as e:
        raise InvalidInputError(T("商业核保计算失败：{0}", str(e)[:200])) from e
    prop = r.get("property") or {}
    r["property"] = prop
    prop["name"] = prop.get("name") or name  # 没填物业名时用交易名，避免报告上写“未命名物业”
    prop["address"] = prop.get("address") or address
    meta = _deal_meta(name, address, clean)
    if kind == "memo":
        return pdf_uw.build_uw_pdf(r, "enhanced", deal=meta, cover_tearsheet=True)
    if kind == "report":
        return pdf_uw.build_uw_pdf(r, "classic")
    if kind == "tearsheet":
        return tearsheet.build_tearsheet_pdf(r, meta)
    return excel_uw.build_uw_xlsx(r, clean, comps=[], meta={"has_rent_roll": meta["has_rent_roll"]})


def _residential(kind: str, name: str, address: str, inputs: JSON) -> bytes:
    try:
        detail = run_model("residential", inputs)["detail"]
    except ModelInputError as e:
        raise InvalidInputError(str(e)) from e
    score, validated = detail["score"], detail["validated_input"]
    if kind == "model":
        return excel_uw.build_res_xlsx(score, validated, address)
    return pdf_report.build_pdf({"track": "residential", "name": name, "address": address, "input": validated,
                                 "score": score, "verdict": None, "comps": [], "assumptions": None,
                                 "effective_assumptions": None, "verdict_word": None, "veto_count": None,
                                 "valuation_display": None})


def export(deal_id: int, kind: str) -> tuple[str, str, bytes]:
    """→ (文件名, 媒体类型, 内容)。没有承销版本、赛道不支持、质量门不过 → InvalidInputError。"""
    if kind not in KINDS:
        raise InvalidInputError(T("不支持的导出：{0}", kind))
    tracks, ext, media = KINDS[kind]
    with session_scope() as s:
        d = deal_or_404(s, deal_id)
        v = current_version(s, d)
        if v is None:
            raise InvalidInputError(T("还没有承销版本：先在模型页保存一版再导出"))
        if d.track == "institutional":
            raise InvalidInputError(T("机构级交易的导出（带公式的 Excel、机构格式投委会备忘录）在下一版提供"))
        if d.track not in tracks:
            raise InvalidInputError(T("这种导出只适用于商业交易"))
        name, address, track, inputs, version_no = d.name, d.address, d.track, dict(v.inputs or {}), v.version_no
    build = _commercial if track == "commercial" else _residential
    data = build(kind, name, address, inputs)
    with session_scope() as s:
        _event(s, deal_id, "exported", {"kind": kind, "version_no": version_no})
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"dealdesk_{_slug(address or name)}_{kind}_v{version_no}_{stamp}.{ext}", media, data
