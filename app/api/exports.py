"""导出：商业核保 PDF（经典/增强）、Tear Sheet、Excel 模型、住宅备忘录 PDF 与 Excel。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.api.common import (
    _deal_slug,
    _enforce_gate_fields,
    _enforce_quality_gate,
    _MemoReq,
    _ResXlsxReq,
    score_input,
    validate_input,
)
from app.domain import (
    uw_commercial,
)
from app.services.render import excel_uw, pdf_report, pdf_uw

router = APIRouter(tags=["documents"])


@router.post("/api/uw/report")
def uw_report(payload: dict):
    """商业核保报告导出：当前（未保存也行）输入 -> 经典版/增强版 PDF。
    variant: classic（Manny Khoshbin 模板版式）| enhanced（DealDesk 增强版：
    DSCR/IRR/盈亏平衡/持有退出）。
    2026-10-06：先过 intake 数据质量门，fail → 422 拦截。"""
    variant = str(payload.get("variant", "classic") or "classic").lower()
    if variant not in ("classic", "enhanced"):
        raise HTTPException(400, f"unknown variant: {variant!r}")
    data = payload.get("input", payload)
    _enforce_quality_gate(data, "报告导出")
    try:
        r = uw_commercial.compute_all(data)
        pdf_bytes = pdf_uw.build_uw_pdf(r, variant)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"报告生成失败：{str(e)[:200]}")
    name = (r.get("property", {}) or {}).get("name") or "deal"
    slug = "".join(c if c.isalnum() else "-" for c in name)[:30] or "deal"
    safe_ascii = f"DealDesk-uw-{variant}-{slug}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={safe_ascii}"},
    )


@router.post("/api/uw/tearsheet")
def uw_tearsheet(payload: dict):
    """一键 Tear Sheet（台账 2026-10-05）：当前（未保存也行）输入 → 投资一页纸 PDF。

    关键字段（价格/NOI/cap rate/全口径现金需求/月供/DSCR）＋ 3 条 highlights ＋
    1 条下一步建议；缺数项渲染 "—"，不估算。
    2026-10-06：先过 intake 数据质量门，fail → 422 拦截。
    """
    data = payload.get("input", payload)
    _enforce_quality_gate(data, "Tear Sheet")
    try:
        from app.services.render import tearsheet
        r = uw_commercial.compute_all(data)
        deal = {"name": payload.get("name") or (r.get("property", {}) or {}).get("name", ""),
                "address": payload.get("address") or (r.get("property", {}) or {}).get("address", ""),
                "has_rent_roll": bool((data.get("tenants") or []))}
        pdf_bytes = tearsheet.build_tearsheet_pdf(r, deal)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"Tear Sheet 生成失败：{str(e)[:200]}")
    name = deal["name"] or "deal"
    slug = "".join(c if c.isalnum() else "-" for c in name)[:30] or "deal"
    safe_ascii = f"DealDesk-tearsheet-{slug}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={safe_ascii}"},
    )


@router.post("/api/uw/report/xlsx")
def uw_report_xlsx(payload: dict):
    """商业核保明细 Excel：总览/现金流/comps/假设；DSCR/IRR 用原生公式.

    Phase 5 第二轮 item 6：DSCR 分子用银行口径 NOI（前端经 compute-plus 算好传入，
    与网页 KPI 卡 / PDF 同数）；无 rent roll 时传 null，Excel 回退并诚实标注。
    """
    data = payload.get("input", payload)
    comps = payload.get("comps") or []
    # 台账第 4 项：商业 Excel 同样导出前过门（gate_fields 显式送达才拦）
    _enforce_gate_fields(payload.get("gate_fields"),
                         payload.get("gate_deal_type") or "commercial",
                         "Excel 导出")
    try:
        r = uw_commercial.compute_all(data)
        xbytes = excel_uw.build_uw_xlsx(r, data, comps=comps,
                                        meta={"bank_noi": payload.get("bank_noi"),
                                              # Phase 5 第三轮 A3：has_rent_roll 门＋verdict 行
                                              "has_rent_roll": payload.get("has_rent_roll"),
                                              "verdict": payload.get("verdict"),
                                              "verdict_word": payload.get("verdict_word"),
                                              "veto_count": payload.get("veto_count")})
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"报告生成失败：{str(e)[:200]}")
    prop = r.get("property") or {}
    slug = _deal_slug(prop.get("address") or prop.get("name") or "deal")
    stamp = date.today().strftime("%Y%m%d")
    fname = f"dealdesk_{slug}_{stamp}.xlsx"
    from urllib.parse import quote
    return Response(
        content=xbytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f"attachment; filename={fname}; filename*=UTF-8''{quote(fname)}"},
    )


@router.post("/api/memo/pdf")
def memo_pdf(req: _MemoReq):
    """投资备忘录 PDF（不入库）：住宅走 pdf_report 模板，商业走 pdf_uw 增强版.

    P0-8：接到当前 deal 真实数据（verdict/KPI/comps/假设）；商业用 uw_input
    富输入重算，不再导出全零模板。
    """
    from urllib.parse import quote
    # 台账第 4 项：导出前过门（gate_fields 显式送达才拦，blocked → 422）
    _enforce_gate_fields(req.gate_fields,
                         req.gate_deal_type or req.track, "备忘录导出")
    try:
        deal = {"name": req.name, "address": req.address, "verdict": req.verdict,
                "score": req.score, "comps": req.comps,
                "assumptions": req.assumptions,
                # Phase 5 第四轮 B2：PDF"关键假设"栏用此清单（含默认值标注）
                "effective_assumptions": req.effective_assumptions,
                "verdict_word": req.verdict_word, "veto_count": req.veto_count,
                "dscr_trailing": req.dscr_trailing,
                # Phase 5 第五轮 C9：估值结论进备忘录 PDF
                "valuation_display": req.valuation_display,
                # Phase 5 第三轮 A2：服务端兜底——前端没传时按 uw_input 有无租户判定
                "has_rent_roll": req.has_rent_roll}
        if req.track == "commercial":
            uw_in = req.uw_input or req.input
            if not deal["has_rent_roll"]:
                deal["has_rent_roll"] = bool((uw_in or {}).get("tenants"))
            r = uw_commercial.compute_all(uw_in)
            # Phase 5 第四轮 B2/B4：补上只有后端知道的生效假设——持有年数＋退出 cap
            # （来源：用户输入/联动市场cap/默认），PDF"关键假设"栏必须列出
            _eff = list(req.effective_assumptions or [])
            _ex = (r.get("analysis") or {}).get("exit") or {}
            if _ex:
                _eff.append({"key": "hold_years", "label": "持有年数",
                             "value": _ex.get("hold_years"),
                             "display": f"{_ex.get('hold_years')} 年",
                             "is_default": bool(_ex.get("hold_years_is_default"))})
                _src = _ex.get("exit_cap_source") or "默认"
                _eff.append({"key": "exit_cap_rate", "label": "退出 cap",
                             "value": _ex.get("exit_cap_rate"),
                             "display": f"{(_ex.get('exit_cap_rate') or 0) * 100:.2f}%"
                                        + ("" if _src == "用户输入" else f"（{_src}）"),
                             "is_default": _src == "默认"})
            deal["effective_assumptions"] = _eff
            # 富输入带上物业名/地址，避免"未命名物业"
            prop = r.get("property") or {}
            if not prop.get("name") and req.name:
                prop["name"] = req.name
            if not prop.get("address") and req.address:
                prop["address"] = req.address
            pdf_bytes = pdf_uw.build_uw_pdf(r, "enhanced", deal=deal,
                                            cover_tearsheet=True)
        else:
            validated = validate_input("residential", req.input)
            p = {"track": "residential", "name": req.name, "address": req.address,
                 "input": validated,
                 "score": req.score or score_input("residential", validated),
                 "verdict": req.verdict, "comps": req.comps,
                 "assumptions": req.assumptions,
                 # Phase 5 第四轮 B2：PDF"关键假设"栏用此清单（含默认值标注）
                 "effective_assumptions": req.effective_assumptions,
                 "verdict_word": req.verdict_word, "veto_count": req.veto_count,
                 # Phase 5 第五轮 C9：估值结论进备忘录 PDF
                 "valuation_display": req.valuation_display}
            pdf_bytes = pdf_report.build_pdf(p)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"报告生成失败：{str(e)[:200]}")
    slug = _deal_slug(req.address or req.name or "deal")
    fname = f"dealdesk_{slug}_{date.today().strftime('%Y%m%d')}.pdf"
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition":
                 f"attachment; filename={fname}; filename*=UTF-8''{quote(fname)}"},
    )


@router.post("/api/res/report/xlsx")
def res_report_xlsx(req: _ResXlsxReq):
    """住宅核保明细 Excel：总览/现金流/comps/假设."""
    from urllib.parse import quote
    # 台账第 4 项：导出前过门（gate_fields 显式送达才拦，blocked → 422）
    _enforce_gate_fields(req.gate_fields,
                         req.gate_deal_type or "residential", "Excel 导出")
    try:
        xbytes = excel_uw.build_res_xlsx(req.score, req.input, req.address,
                                         req.verdict, req.confidence, req.comps)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"报告生成失败：{str(e)[:200]}")
    slug = _deal_slug(req.address or "deal")
    fname = f"dealdesk_{slug}_{date.today().strftime('%Y%m%d')}.xlsx"
    return Response(
        content=xbytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f"attachment; filename={fname}; filename*=UTF-8''{quote(fname)}"},
    )
