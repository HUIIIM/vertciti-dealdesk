"""全面分析工作台：纯分析逻辑.

与核保打分引擎完全解耦：这里只做测算/估值/预测/市场调查，
不改动 scoring_residential / scoring_commercial 的任何逻辑。
所有估值输出统一标注"估算"，所有预测输出统一标注"情景预测"。
"""

from __future__ import annotations

import csv
import html
import io
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from . import finance
from .data import hpi

ESTIMATE_TAG = "估算"          # 估值类输出统一标注
FORECAST_TAG = "情景预测"      # 预测类输出统一标注
FORECAST_DISCLAIMER = "预测是情景假设，不是承诺。"


# ---------------- 物业财务测算 ----------------

class WbProperty(BaseModel):
    """工作台物业录入（宽松模型：未知字段忽略，便于前端增量扩展）."""
    model_config = ConfigDict(extra="ignore")

    address: str = ""
    prop_type: str = "residential"  # residential | commercial
    building_sf: float = Field(default=0, ge=0)
    units: int = Field(default=1, ge=1)
    asking_price: float = Field(default=0, ge=0)
    down_payment: float = Field(default=0, ge=0)
    loan_balance: float = Field(default=0, ge=0)
    rate: float = Field(default=0, ge=0, description="年利率（百分制）")
    term_years: float = Field(default=30, gt=0)
    monthly_rent: float = Field(default=0, ge=0)
    other_income_monthly: float = Field(default=0, ge=0)
    vacancy_pct: float = Field(default=8, ge=0, le=100)
    taxes_annual: float = Field(default=0, ge=0)
    insurance_annual: float = Field(default=0, ge=0)
    hoa_monthly: float = Field(default=0, ge=0)
    utilities_owner_monthly: float = Field(default=0, ge=0)
    maint_pct: float = Field(default=8, ge=0, le=100)
    capex_pct: float = Field(default=8, ge=0, le=100)
    mgmt_pct: float = Field(default=10, ge=0, le=100)
    closing_costs: float = Field(default=0, ge=0)
    initial_repairs: float = Field(default=0, ge=0)
    reserves_months: float = Field(default=0, ge=0)


def property_metrics(p: WbProperty) -> dict:
    """物业全口径财务测算（月/年度口径统一换算）."""
    gross = p.monthly_rent + p.other_income_monthly
    egi_m = gross * (1 - p.vacancy_pct / 100)
    opex_m = (p.taxes_annual / 12 + p.insurance_annual / 12 + p.hoa_monthly
              + p.utilities_owner_monthly
              + gross * (p.maint_pct + p.capex_pct) / 100
              + egi_m * p.mgmt_pct / 100)
    noi_m = egi_m - opex_m
    noi_a = noi_m * 12
    ds_m = finance.monthly_payment(p.loan_balance, p.rate, p.term_years)
    ds_a = ds_m * 12
    cf_m = noi_m - ds_m
    cf_a = cf_m * 12
    dscr = (noi_a / ds_a) if ds_a > 0 else None
    cap_on_ask = (noi_a / p.asking_price) if p.asking_price > 0 else None
    piti_m = ds_m + p.taxes_annual / 12 + p.insurance_annual / 12 + p.hoa_monthly
    cash_to_close = (p.down_payment + p.closing_costs + p.initial_repairs
                     + piti_m * p.reserves_months)
    coc = (cf_a / cash_to_close) if cash_to_close > 0 else None
    price_per_sf = (p.asking_price / p.building_sf) if p.building_sf > 0 else None
    rent_per_sf_m = (p.monthly_rent / p.building_sf) if p.building_sf > 0 else None
    return {
        "gross_rent_monthly": round(gross, 2),
        "egi_monthly": round(egi_m, 2),
        "opex_monthly": round(opex_m, 2),
        "noi_monthly": round(noi_m, 2),
        "noi_annual": round(noi_a, 2),
        "debt_service_monthly": round(ds_m, 2),
        "debt_service_annual": round(ds_a, 2),
        "cash_flow_monthly": round(cf_m, 2),
        "cash_flow_annual": round(cf_a, 2),
        "dscr": round(dscr, 3) if dscr is not None else None,
        "cap_rate_on_asking": round(cap_on_ask, 4) if cap_on_ask is not None else None,
        "cash_to_close": round(cash_to_close, 2),
        "cash_on_cash": round(coc, 4) if coc is not None else None,
        "price_per_sf": round(price_per_sf, 2) if price_per_sf is not None else None,
        "rent_per_sf_monthly": round(rent_per_sf_m, 3) if rent_per_sf_m is not None else None,
    }


# ---------------- 可比成交 / 挂牌估值 ----------------

class WbComp(BaseModel):
    model_config = ConfigDict(extra="ignore")
    address: str = ""
    status: str = "sold"  # sold | active
    price: float = Field(gt=0)
    sf: float = Field(default=0, ge=0)
    distance_miles: float = Field(default=0, ge=0)
    adjustment_pct: float = Field(default=0, description="调整 %（百分制，可正可负）")
    note: str = ""


def _r2(x):
    return round(x, 2)


def valuate_comps(comps: list[WbComp]) -> dict:
    """比较法估值（估算）：调整价 = 成交价 x (1+调整%)；默认按距离倒数加权."""
    rows = []
    for c in comps:
        adj_price = c.price * (1 + c.adjustment_pct / 100)
        price_sf = (c.price / c.sf) if c.sf > 0 else None
        adj_sf = (adj_price / c.sf) if c.sf > 0 else None
        rows.append({
            "address": c.address, "status": c.status, "price": c.price,
            "sf": c.sf, "distance_miles": c.distance_miles,
            "adjustment_pct": c.adjustment_pct, "note": c.note,
            "price_per_sf": _r2(price_sf) if price_sf else None,
            "adjusted_price": _r2(adj_price),
            "adjusted_price_per_sf": _r2(adj_sf) if adj_sf else None,
        })
    if not rows:
        return {"tag": ESTIMATE_TAG, "count": 0, "rows": [],
                "note": "未录入可比案例，无法做比较法估值"}
    weights = [1 / (1 + r["distance_miles"]) for r in rows]
    wsum = sum(weights)
    est = sum(r["adjusted_price"] * w / wsum for r, w in zip(rows, weights))
    adj_prices = sorted(r["adjusted_price"] for r in rows)
    mid = adj_prices[len(adj_prices) // 2]
    psfs = [r["price_per_sf"] for r in rows if r["price_per_sf"]]
    return {
        "tag": ESTIMATE_TAG,
        "method": "比较法（可比成交/挂牌，距离倒数加权）",
        "count": len(rows),
        "rows": rows,
        "estimate": _r2(est),
        "median_adjusted": _r2(mid),
        "range": [_r2(adj_prices[0]), _r2(adj_prices[-1])],
        "price_per_sf": {
            "min": _r2(min(psfs)), "max": _r2(max(psfs)),
            "avg": _r2(sum(psfs) / len(psfs)),
        } if psfs else None,
        "note": "权重=1/(1+距离英里)；status=sold 为已成交，active 为在售挂牌（仅参考）",
    }


def valuate_income(noi_annual: float, cap_rate_pct: float) -> dict:
    """收益法估值（估算）：价值 = 年NOI / cap rate."""
    if noi_annual is None or cap_rate_pct is None or cap_rate_pct <= 0:
        return {"tag": ESTIMATE_TAG, "value": None,
                "note": "NOI 或 cap rate 无效，无法做收益法估值"}
    return {
        "tag": ESTIMATE_TAG,
        "method": "收益法（NOI / cap rate）",
        "noi_annual": _r2(noi_annual),
        "cap_rate_pct": cap_rate_pct,
        "value": _r2(noi_annual / (cap_rate_pct / 100)),
    }


def reconcile(comp_value: Optional[float], income_value: Optional[float],
              comp_weight: float = 0.5) -> dict:
    """调和估值（估算）：两种方法按权重综合，给出区间."""
    vals = [v for v in (comp_value, income_value) if v]
    if not vals:
        return {"tag": ESTIMATE_TAG, "reconciled": None,
                "note": "两种方法都无有效值，无法调和"}
    w = max(0.0, min(1.0, comp_weight))
    if comp_value and income_value:
        rec = comp_value * w + income_value * (1 - w)
    else:
        rec = vals[0]
    return {
        "tag": ESTIMATE_TAG,
        "comp_value": comp_value, "income_value": income_value,
        "comp_weight": w,
        "reconciled": _r2(rec),
        "range": [_r2(min(vals)), _r2(max(vals))],
        "note": f"调和权重：比较法 {w:.0%} / 收益法 {1-w:.0%}；区间为两种方法的高低值",
    }


# ---------------- 三年情景预测 ----------------

class WbScenario(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = "base"
    label: str = ""
    annual_rate_pct: float = 0.0  # 年化涨幅假设（百分制）
    rent_growth_pct: float = 0.0


def forecast(base_value: float, scenarios: list[WbScenario],
             years: int = 3) -> dict:
    """三年情景预测：每年价值 = 上年 x (1+年涨幅假设)."""
    out = []
    for s in scenarios:
        g = s.annual_rate_pct / 100
        rg = s.rent_growth_pct / 100
        path, rpath = [], []
        v = base_value
        for _ in range(years):
            v = v * (1 + g)
            path.append(_r2(v))
        out.append({
            "name": s.name, "label": s.label or s.name,
            "annual_rate_pct": s.annual_rate_pct,
            "rent_growth_pct": s.rent_growth_pct,
            "value_path": path,
            "total_return_pct": round((path[-1] / base_value - 1) * 100, 2) if base_value else None,
        })
    return {
        "tag": FORECAST_TAG,
        "disclaimer": FORECAST_DISCLAIMER,
        "base_value": _r2(base_value),
        "years": years,
        "scenarios": out,
        "note": "每年价值按复利滚动假设涨幅；租金涨幅假设仅用于现金流情景参考",
    }


# ---------------- 指数序列（用户粘贴 / 嵌入） ----------------

def series_stats(points: list[dict]) -> dict:
    """指数序列统计：最新值、同比、累计、年化（CAGR）。points: [{q, value}]."""
    pts = [p for p in points if p.get("value")]
    if len(pts) < 2:
        return {"count": len(pts), "note": "数据点不足，至少需要 2 个"}
    pts = sorted(pts, key=lambda p: str(p.get("q")))
    first, last = pts[0], pts[-1]
    # 季度序列：4 个点 ≈ 1 年
    per_year = 4 if any("Q" in str(p.get("q", "")) for p in pts) else 1
    n = len(pts) - 1
    cagr = (last["value"] / first["value"]) ** (per_year / n) - 1 if first["value"] else None
    yoy = None
    if len(pts) >= per_year + 1:
        ago = pts[-(per_year + 1)]
        yoy = (last["value"] / ago["value"] - 1) * 100 if ago["value"] else None
    return {
        "count": len(pts),
        "first": first, "latest": last,
        "cumulative_pct": round((last["value"] / first["value"] - 1) * 100, 2),
        "cagr_pct": round(cagr * 100, 2) if cagr is not None else None,
        "yoy_pct": round(yoy, 2) if yoy is not None else None,
        "per_year": per_year,
    }


# ---------------- CSV 解析（周边成交导入） ----------------

COMP_CSV_COLUMNS = ["address", "status", "price", "sf", "distance_miles",
                    "adjustment_pct", "note"]


def parse_comps_csv(text: str) -> dict:
    """解析周边成交 CSV（表头见 COMP_CSV_COLUMNS；price 必填）."""
    reader = csv.DictReader(io.StringIO(text.strip()))
    rows, errors = [], []
    for i, r in enumerate(reader, start=2):
        try:
            price = float(str(r.get("price", "")).replace(",", "").replace("$", ""))
            if price <= 0:
                raise ValueError("price 必须 > 0")
            rows.append({
                "address": (r.get("address") or "").strip(),
                "status": (r.get("status") or "sold").strip().lower(),
                "price": price,
                "sf": float(str(r.get("sf") or 0).replace(",", "") or 0),
                "distance_miles": float(str(r.get("distance_miles") or 0) or 0),
                "adjustment_pct": float(str(r.get("adjustment_pct") or 0) or 0),
                "note": (r.get("note") or "").strip(),
            })
        except Exception as e:  # noqa: BLE001
            errors.append(f"第 {i} 行：{e}")
    return {"rows": rows, "errors": errors,
            "columns": COMP_CSV_COLUMNS,
            "template": ",".join(COMP_CSV_COLUMNS)}


# ---------------- 市场调查 ----------------

class WbResearch(BaseModel):
    model_config = ConfigDict(extra="ignore")
    address: str = ""
    market_key: str = "tampa"  # us | nyc | phoenix | tampa | dallas | atlanta
    # 供需 / 空置 / 租金 / 人口 / 就业：值 + 来源（来源必填才算"已核实"）
    supply_note: str = ""
    supply_source: str = ""
    demand_note: str = ""
    demand_source: str = ""
    vacancy_note: str = ""
    vacancy_source: str = ""
    rent_trend_note: str = ""
    rent_trend_source: str = ""
    population_note: str = ""
    population_source: str = ""
    employment_note: str = ""
    employment_source: str = ""
    extra_notes: str = ""


def research_completeness(r: WbResearch) -> dict:
    dims = [
        ("供给", r.supply_note, r.supply_source),
        ("需求", r.demand_note, r.demand_source),
        ("空置率", r.vacancy_note, r.vacancy_source),
        ("租金趋势", r.rent_trend_note, r.rent_trend_source),
        ("人口", r.population_note, r.population_source),
        ("就业", r.employment_note, r.employment_source),
    ]
    items = [{"dim": d, "filled": bool(n.strip()),
              "sourced": bool(n.strip() and s.strip())} for d, n, s in dims]
    return {
        "items": items,
        "filled": sum(1 for i in items if i["filled"]),
        "sourced": sum(1 for i in items if i["sourced"]),
        "total": len(items),
    }


def research_payload(r: WbResearch, valuation: dict | None = None,
                     forecast_data: dict | None = None) -> dict:
    market = dict(hpi.get_market(r.market_key) or {})
    market["key"] = r.market_key
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "address": r.address,
        "market_key": r.market_key,
        "market": market,
        "methodology": hpi.METHODOLOGY,
        "completeness": research_completeness(r),
        "inputs": {
            "supply": {"note": r.supply_note, "source": r.supply_source},
            "demand": {"note": r.demand_note, "source": r.demand_source},
            "vacancy": {"note": r.vacancy_note, "source": r.vacancy_source},
            "rent_trend": {"note": r.rent_trend_note, "source": r.rent_trend_source},
            "population": {"note": r.population_note, "source": r.population_source},
            "employment": {"note": r.employment_note, "source": r.employment_source},
            "extra": r.extra_notes,
        },
        "valuation": valuation,
        "forecast": forecast_data,
        "public_sources": hpi.PUBLIC_SOURCES,
        "disclaimer": ("本报告数字来自用户录入或标注来源的公开数据；"
                       "未核实项不得作为决策依据。签约/交割前须经持牌本地律师、CPA、title company 审查。"),
    }


def _row(k, v):
    return f"<tr><th>{html.escape(str(k))}</th><td>{v}</td></tr>"


def _money(x):
    return "—" if x is None else f"${x:,.0f}"


def render_research_report(data: dict) -> str:
    """市场调查报告：中文可打印 HTML（浏览器打印另存为 PDF）."""
    m = data.get("market") or {}
    comp = data.get("completeness") or {}
    dims = {"supply": "供给", "demand": "需求", "vacancy": "空置率",
            "rent_trend": "租金趋势", "population": "人口", "employment": "就业"}
    dim_rows = ""
    for key, label in dims.items():
        d = (data.get("inputs") or {}).get(key) or {}
        note = html.escape(d.get("note") or "—")
        src = html.escape(d.get("source") or "未标注来源")
        badge = "✅ 已核实" if (d.get("note") or "").strip() and (d.get("source") or "").strip() else "⚪ 待补充"
        dim_rows += f"<tr><td>{label}</td><td>{note}</td><td>{src}</td><td>{badge}</td></tr>"

    src_rows = "".join(
        f"<tr><td>{html.escape(s['name'])}</td>"
        f"<td><a href=\"{html.escape(s['url'])}\">{html.escape(s['url'])}</a></td>"
        f"<td>{html.escape(s.get('note', ''))}</td></tr>"
        for s in data.get("public_sources", []))

    val = data.get("valuation")
    val_html = "<p>本次未附估值。</p>"
    if val:
        rec = val.get("reconciled") or {}
        val_html = ("<table>"
                    + _row("比较法估算", _money((val.get("comps") or {}).get("estimate")))
                    + _row("收益法估算", _money((val.get("income") or {}).get("value")))
                    + _row("调和估算", _money(rec.get("reconciled")))
                    + _row("估算区间", f"{_money((rec.get('range') or [None, None])[0])} – "
                                       f"{_money((rec.get('range') or [None, None])[1])}")
                    + "</table><p class='meta'>以上均为估算（" + ESTIMATE_TAG + "），非承诺价格。</p>")

    fc = data.get("forecast")
    fc_html = "<p>本次未附预测。</p>"
    if fc:
        heads = "".join(f"<th>第{i+1}年</th>" for i in range(fc.get("years", 3)))
        body = "".join(
            f"<tr><td>{html.escape(s.get('label') or s['name'])}"
            f"（{s['annual_rate_pct']:+.1f}%/年）</td>"
            + "".join(f"<td>{_money(v)}</td>" for v in s["value_path"]) + "</tr>"
            for s in fc.get("scenarios", []))
        fc_html = (f"<table><tr><th>情景</th>{heads}</tr>{body}</table>"
                   f"<p class='warn'>⚠️ {html.escape(fc.get('disclaimer', FORECAST_DISCLAIMER))}"
                   f"{FORECAST_TAG}，不是承诺。</p>")

    series = m.get("series") or []
    if series:
        pts = " → ".join(f"{p['q']} {p['value']}" for p in series)
        yoy = hpi.yoy_from_series(series) or {}
        hpi_html = (f"<p>{html.escape(m.get('geo', ''))} · {html.escape(m.get('units', ''))}</p>"
                    f"<p class='mono'>{html.escape(pts)}</p>"
                    f"<p>最新 {html.escape(str(yoy.get('latest_q', '')))}：{yoy.get('latest', '—')}；"
                    f"同比 {yoy.get('yoy_pct', '—')}%</p>"
                    f"<p class='meta'>来源：{html.escape(m.get('source', ''))}；"
                    f"更新：{html.escape(m.get('vintage', ''))}"
                    + (f"；{html.escape(m.get('series_vintage', ''))}" if m.get("series_vintage") else "")
                    + "</p>")
    else:
        ch = m.get("changes") or {}
        ch_txt = "、".join(f"{k} {v:+.2f}%" for k, v in ch.items()) or "—"
        hpi_html = (f"<p>{html.escape(m.get('geo', ''))}</p>"
                    f"<p>官方发布涨幅：{html.escape(ch_txt)}</p>"
                    f"<p class='meta'>来源：{html.escape(m.get('source', ''))}；"
                    f"更新：{html.escape(m.get('vintage', ''))}。"
                    f"{html.escape(m.get('series_note', ''))}</p>")

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>市场调查报告 - {html.escape(data.get('address') or '未命名')}</title>
<style>
 body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; max-width: 960px; margin: 24px auto; padding: 0 20px; color: #1a1a1a; }}
 h1 {{ font-size: 22px; }} h2 {{ font-size: 17px; border-bottom: 2px solid #222; padding-bottom: 4px; margin-top: 28px; }}
 table {{ width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 14px; }}
 th, td {{ border: 1px solid #ccc; padding: 6px 10px; text-align: left; vertical-align: top; }}
 th {{ background: #f4f4f4; width: 22%; }}
 .meta {{ color: #555; font-size: 13px; }} .mono {{ font-family: monospace; font-size: 13px; }}
 .warn {{ color: #b45309; font-weight: 700; }}
 .disclaimer {{ font-size: 12px; color: #666; border-top: 1px solid #ccc; margin-top: 32px; padding-top: 8px; }}
 @media print {{ .noprint {{ display: none; }} body {{ margin: 0; }} }}
</style></head><body>
<p class="noprint"><button onclick="window.print()">🖨️ 打印 / 另存为 PDF</button></p>
<h1>市场调查报告</h1>
<p class="meta">vertciti 房地产收购部 · 生成时间 {html.escape(data.get('generated_at', ''))}</p>
<h2>调查对象</h2>
<table>
{_row("地址", html.escape(data.get("address") or "—"))}
{_row("覆盖市场", html.escape((m.get("label") or "") + " / " + (m.get("geo") or "")))}
{_row("六维完整度", f"已填 {comp.get('filled', 0)}/{comp.get('total', 0)}，已核实（带来源）{comp.get('sourced', 0)}/{comp.get('total', 0)}")}
</table>
<h2>房价指数（嵌入公开数据）</h2>
{hpi_html}
<p class="meta">{html.escape(data.get("methodology", ""))}</p>
<h2>六维市场调查</h2>
<table><tr><th>维度</th><th>内容</th><th>来源</th><th>状态</th></tr>{dim_rows}</table>
<h2>估值摘要</h2>
{val_html}
<h2>未来三年{FORECAST_TAG}</h2>
{fc_html}
<h2>公开数据源</h2>
<table><tr><th>名称</th><th>链接</th><th>说明</th></tr>{src_rows}</table>
<div class="disclaimer">{html.escape(data.get("disclaimer", ""))}</div>
</body></html>"""


# ---------------- 工作台 → 打分引擎映射 ----------------

def to_scoring_input(prop: WbProperty, track: str) -> dict:
    """把工作台物业输入映射为现有打分模型的输入字段（只做字段映射，不改逻辑）."""
    if track == "commercial":
        return {
            "asset_class": "small_multifamily_5plus" if prop.units >= 5 else "mixed_use",
            "structure": "seller_financing",
            "price": prop.asking_price or 1,
            "closing_costs": prop.closing_costs,
            "down_payment": prop.down_payment,
            "tranches": ([{"balance": prop.loan_balance, "rate": prop.rate,
                           "rate_type": "fixed", "term_years": prop.term_years}]
                         if prop.loan_balance > 0 else []),
            "annual_base_rent": prop.monthly_rent * 12,
            "other_income_annual": prop.other_income_monthly * 12,
            "vacancy_pct": prop.vacancy_pct,
            "tax_annual": prop.taxes_annual,
            "insurance_annual": prop.insurance_annual,
            "mgmt_pct": prop.mgmt_pct,
            "building_sf": prop.building_sf,
            "units": prop.units,
            "reserves_months_ds": prop.reserves_months,
            "capex_y1": prop.initial_repairs,
        }
    return {
        "structure": "subject_to",
        "price": prop.asking_price or 1,
        "down_payment": prop.down_payment,
        "loan_balance": prop.loan_balance,
        "rate": prop.rate,
        "rate_type": "fixed",
        "term_years_remaining": prop.term_years,
        "monthly_rent": prop.monthly_rent,
        "other_income_monthly": prop.other_income_monthly,
        "units": prop.units,
        "rent_source": "estimated",
        "taxes_annual": prop.taxes_annual,
        "insurance_annual": prop.insurance_annual,
        "hoa_monthly": prop.hoa_monthly,
        "utilities_owner_monthly": prop.utilities_owner_monthly,
        "vacancy_pct": prop.vacancy_pct,
        "maint_pct": prop.maint_pct,
        "capex_pct": prop.capex_pct,
        "mgmt_pct": prop.mgmt_pct,
        "closing_costs": prop.closing_costs,
        "initial_repairs": prop.initial_repairs,
        "reserves_months_piti": prop.reserves_months,
    }
