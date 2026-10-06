"""Intake 数据质量门（台账 2026-10-06：Intake 数据质量门，学自 Dealpath/Cherre Top3）。

职责：
1. 固定字段 schema（按 deal 类型版本化）：commercial-v1 / residential-v1，
   每个字段声明类型、口径单位、核保必填、合理区间。
2. 规则层（validators.py）：交叉字段一致性检查。
   - 不一致（fail）：直接拦截，fail 清零前不得进入 underwriting
     （报告/备忘录/Tear Sheet 导出服务端硬拦 422）。
   - 偏离（warn）：允许继续，但前端弹确认并标黄。
3. 每字段来源/页码/置信度：intake 阶段写入，门内汇总成 field_report；
   低置信字段（卖方口径/低）在门面板标黄。

设计原则（诚实红线）：缺数 = 未知，不拦；只有"自相矛盾"才 fail。
"""

from __future__ import annotations

from datetime import datetime

SCHEMA_VERSIONS = {"commercial": "commercial-v1", "residential": "residential-v1"}

# 置信度分级：seller=低（标黄）, web=中, verified=高
CONF_LOW = {"卖方口径", "截图提取", "低", "seller", "low"}
FAIL = "fail"
WARN = "warn"


def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x


# ---------------- 固定字段 schema（按 deal 类型版本化） ----------------
# type: money=美元金额 | number=数值 | pct_decimal=小数口径比率(0.065=6.5%) |
#       int=整数 | str=文本 | year=年份
FIELD_SCHEMA = {
    "commercial": {
        "analysis.purchase_price":   {"type": "money", "label": "购买价格", "required_for_uw": True,
                                      "min": 1000, "max": 50_000_000_000,
                                      "soft_min": 50_000, "soft_max": 5_000_000_000},
        "property.net_rentable_sf":  {"type": "number", "label": "可租面积 SF", "required_for_uw": True,
                                      "min": 100, "max": 200_000_000,
                                      "soft_min": 500, "soft_max": 20_000_000},
        "analysis.underwritten_noi": {"type": "money", "label": "在手 NOI", "required_for_uw": True,
                                      "min": 0, "max": 5_000_000_000,
                                      "soft_min": 0, "soft_max": 500_000_000},
        "analysis.projected_noi":   {"type": "money", "label": "预测 NOI", "required_for_uw": False,
                                      "min": 0, "max": 5_000_000_000},
        "analysis.market_cap_rate":  {"type": "pct_decimal", "label": "Cap Rate（小数口径）",
                                      "required_for_uw": False, "min": 0.0, "max": 0.30,
                                      "soft_min": 0.02, "soft_max": 0.12,
                                      "note": "商业空置率等一律小数口径：0.065=6.5%"},
        "property.year_built":       {"type": "year", "label": "建造年份", "required_for_uw": False,
                                      "min": 1700, "max": 2100},
        "property.address":          {"type": "str", "label": "地址", "required_for_uw": False},
        "property.city":             {"type": "str", "label": "城市", "required_for_uw": False},
        "property.state":            {"type": "str", "label": "州", "required_for_uw": False},
        "property.zip":              {"type": "str", "label": "邮编", "required_for_uw": False},
        "property.property_type":    {"type": "str", "label": "物业类型", "required_for_uw": False},
    },
    "residential": {
        "asking_price":  {"type": "money", "label": "售价/要价", "required_for_uw": True,
                          "min": 1000, "max": 500_000_000,
                          "soft_min": 20_000, "soft_max": 50_000_000},
        "building_sf":   {"type": "number", "label": "建筑面积 SF", "required_for_uw": True,
                          "min": 100, "max": 1_000_000,
                          "soft_min": 200, "soft_max": 100_000},
        "monthly_rent":  {"type": "money", "label": "月租金", "required_for_uw": False,
                          "min": 0, "max": 1_000_000,
                          "soft_min": 100, "soft_max": 100_000},
        "beds":          {"type": "int", "label": "卧室数", "required_for_uw": False,
                          "min": 0, "max": 50},
        "baths":         {"type": "number", "label": "浴室数", "required_for_uw": False,
                          "min": 0, "max": 50},
        "year_built":    {"type": "year", "label": "建造年份", "required_for_uw": False,
                          "min": 1700, "max": 2100},
    },
}


def validate_schema(deal_type: str, flat: dict, strict_unknown: bool = True) -> list[dict]:
    """按 schema 逐字段校验类型/区间。返回 issue 列表。
    strict_unknown=False 时跳过未知字段（供完整 state 过门用：name/land_acres
    等应用字段不在 intake schema 内）。"""
    issues = []
    schema = FIELD_SCHEMA.get(deal_type, {})
    now_year = datetime.now().year
    for key, raw in flat.items():
        spec = schema.get(key)
        if spec is None:
            if strict_unknown:
                issues.append({"rule": "schema.unknown_field", "severity": WARN, "fields": [key],
                               "title": f"未知字段 {key}（schema 外，未参与规则校验）",
                               "detail": "字段不在固定 schema 内，可能为解析误抓或版本漂移"})
            continue
        t = spec["type"]
        if t == "str":
            continue
        v = _f(raw)
        if v is None:
            issues.append({"rule": "schema.type", "severity": FAIL, "fields": [key],
                           "title": f"{spec['label']} 非数值：{raw!r}",
                           "detail": "类型校验失败，无法参与任何计算"})
            continue
        if t == "year":
            if v > now_year:
                issues.append({"rule": "schema.year_future", "severity": FAIL, "fields": [key],
                               "title": f"{spec['label']} {int(v)} 年是未来年份",
                               "detail": "建造年份不可能在未来，卖方材料自相矛盾"})
            elif v < spec["min"]:
                issues.append({"rule": "schema.range", "severity": WARN, "fields": [key],
                               "title": f"{spec['label']} {int(v)} 早于 {spec['min']}，疑似误抓",
                               "detail": ""})
            continue
        if not (spec["min"] <= v <= spec["max"]):
            issues.append({"rule": "schema.range", "severity": FAIL, "fields": [key],
                           "title": f"{spec['label']} {v:,.2f} 超出合理硬区间 "
                                    f"[{spec['min']:,.0f}, {spec['max']:,.0f}]",
                           "detail": "数值在物理上不可能，多为解析误抓或材料矛盾"})
        elif "soft_min" in spec and not (spec["soft_min"] <= v <= spec["soft_max"]):
            issues.append({"rule": "schema.range_soft", "severity": WARN, "fields": [key],
                           "title": f"{spec['label']} {v:,.2f} 偏离常规区间 "
                                    f"[{spec['soft_min']:,.0f}, {spec['soft_max']:,.0f}]，请人工复核",
                           "detail": ""})
    return issues


def _missing_required(deal_type: str, flat: dict) -> list[dict]:
    out = []
    for key, spec in FIELD_SCHEMA.get(deal_type, {}).items():
        if spec.get("required_for_uw") and (key not in flat or flat[key] in (None, "")):
            out.append({"rule": "schema.missing_required", "severity": WARN, "fields": [key],
                        "title": f"核保必填字段缺失：{spec['label']}",
                        "detail": "未知保持未知，不拦路；补上后估值/打分更完整"})
    return out


# ---------------- 交叉一致性规则 ----------------

def _check_cap_consistency(flat: dict) -> list[dict]:
    out = []
    price = _f(flat.get("analysis.purchase_price"))
    noi = _f(flat.get("analysis.underwritten_noi"))
    cap = _f(flat.get("analysis.market_cap_rate"))
    if price and price > 0 and noi is not None and noi > 0 and cap is not None:
        implied = noi / price
        dev = abs(implied - cap)
        msg = (f"材料声称 cap {cap*100:.2f}%，但 要价/在手 NOI 反推为 {implied*100:.2f}%"
               f"（${noi:,.0f} / ${price:,.0f}），偏差 {dev*10000:.0f}bps")
        if dev > 0.03:
            out.append({"rule": "xfield.cap_consistency", "severity": FAIL,
                        "fields": ["analysis.market_cap_rate", "analysis.purchase_price",
                                   "analysis.underwritten_noi"],
                        "title": "Cap rate 自相矛盾（>300bps）", "detail": msg})
        elif dev > 0.01:
            out.append({"rule": "xfield.cap_consistency", "severity": WARN,
                        "fields": ["analysis.market_cap_rate"],
                        "title": "Cap rate 与要价/NOI 偏差超 100bps", "detail": msg})
    return out


def _check_noi_vs_gross_rent(flat: dict, tenants: list) -> list[dict]:
    out = []
    noi = _f(flat.get("analysis.underwritten_noi"))
    if noi is None or not tenants:
        return out
    gross = 0.0
    for t in tenants or []:
        r = _f((t or {}).get("monthly_rent")) or 0
        gross += r * 12
    if gross <= 0:
        return out
    if noi > gross * 1.05:
        out.append({"rule": "xfield.noi_vs_gross_rent", "severity": FAIL,
                    "fields": ["analysis.underwritten_noi"],
                    "title": f"NOI ${noi:,.0f} 超过租约表毛租金年化 ${gross:,.0f}",
                    "detail": "NOI 不可能超过毛租金收入总和（未计空置/运营费），卖方数字自相矛盾"})
    elif noi > gross * 0.90:
        out.append({"rule": "xfield.noi_vs_gross_rent", "severity": WARN,
                    "fields": ["analysis.underwritten_noi"],
                    "title": f"NOI ${noi:,.0f} 达毛租金 ${gross:,.0f} 的 {noi/gross*100:.0f}%",
                    "detail": "费用率异常低（<10%），请复核租金表或 NOI 口径"})
    return out


def _check_rent_roll_sf(flat: dict, tenants: list) -> list[dict]:
    out = []
    rentable = _f(flat.get("property.net_rentable_sf"))
    if rentable is None or rentable <= 0 or not tenants:
        return out
    t_sf = sum((_f((t or {}).get("sf")) or 0) for t in tenants)
    if t_sf <= 0:
        return out
    if t_sf > rentable * 1.05:
        out.append({"rule": "xfield.rent_roll_sf", "severity": FAIL,
                    "fields": ["property.net_rentable_sf"],
                    "title": f"租约表面积 {t_sf:,.0f} SF 超过可租面积 {rentable:,.0f} SF",
                    "detail": "租户面积总和不可能超过整栋可租面积，卖方数字自相矛盾"})
    elif t_sf < rentable * 0.50:
        out.append({"rule": "xfield.rent_roll_sf", "severity": WARN,
                    "fields": ["property.net_rentable_sf"],
                    "title": f"租约表只覆盖 {t_sf/rentable*100:.0f}% 的可租面积",
                    "detail": "可能租约表不全或空置面积未列，请补全"})
    return out


def _check_tenant_rent_psf(tenants: list) -> list[dict]:
    out = []
    for t in tenants or []:
        sf = _f((t or {}).get("sf"))
        r = _f((t or {}).get("monthly_rent"))
        if not sf or sf <= 0 or r is None or r < 0:
            continue
        psf = r / sf
        who = (t.get("tenant") or t.get("suite") or "?")
        if psf < 0.05 or psf > 300:
            out.append({"rule": "xfield.tenant_rent_psf", "severity": FAIL,
                        "fields": [],
                        "title": f"租户 {who} 租金 ${r:,.0f}/月 ÷ {sf:,.0f} SF = ${psf:.2f}/SF/月，物理不可能",
                        "detail": "疑似面积/租金单位错位（月租当成年租或 SF 误抓）"})
        elif psf < 0.20 or psf > 50:
            out.append({"rule": "xfield.tenant_rent_psf", "severity": WARN,
                        "fields": [],
                        "title": f"租户 {who} ${psf:.2f}/SF/月 偏离常规区间",
                        "detail": "请复核该租户租金或面积单位"})
    return out


def _check_projected_vs_inplace(flat: dict) -> list[dict]:
    out = []
    inp = _f(flat.get("analysis.underwritten_noi"))
    proj = _f(flat.get("analysis.projected_noi"))
    if inp is not None and proj is not None and inp > 0:
        if proj < inp:
            out.append({"rule": "xfield.projected_vs_inplace", "severity": WARN,
                        "fields": ["analysis.projected_noi"],
                        "title": f"预测 NOI ${proj:,.0f} 低于在手 NOI ${inp:,.0f}",
                        "detail": "稳定后 NOI 通常不低于在手 NOI，请确认口径（是否扣除了 capex/lease-up）"})
        elif proj > inp * 3:
            out.append({"rule": "xfield.projected_vs_inplace", "severity": WARN,
                        "fields": ["analysis.projected_noi"],
                        "title": f"预测 NOI ${proj:,.0f} 超过在手 {inp:,.0f} 的 3 倍",
                        "detail": "增长假设激进，请复核 pro forma 假设"})
    return out


def _check_price_sf(flat: dict) -> list[dict]:
    out = []
    price = _f(flat.get("analysis.purchase_price"))
    sf = _f(flat.get("property.net_rentable_sf"))
    if price and price > 0 and sf and sf > 0:
        psf = price / sf
        if psf < 1:
            out.append({"rule": "xfield.price_sf", "severity": FAIL,
                        "fields": ["analysis.purchase_price", "property.net_rentable_sf"],
                        "title": f"单价 ${psf:.2f}/SF，物理不可能",
                        "detail": "价格与面积至少其一误抓"})
    return out


def _check_residential(flat: dict) -> list[dict]:
    out = []
    price = _f(flat.get("asking_price"))
    rent = _f(flat.get("monthly_rent"))
    if price and price > 0 and rent and rent > 0:
        gy = rent * 12 / price
        if gy < 0.01 or gy > 0.25:
            out.append({"rule": "xfield.gross_yield", "severity": WARN,
                        "fields": ["asking_price", "monthly_rent"],
                        "title": f"毛租金回报率 {gy*100:.1f}% 偏离常规",
                        "detail": f"年租金 ${rent*12:,.0f} / 要价 ${price:,.0f}，请复核租金或价格口径"})
    beds = _f(flat.get("beds"))
    baths = _f(flat.get("baths"))
    if beds is not None and baths is not None and beds > 0 and baths > beds * 3 + 2:
        out.append({"rule": "xfield.beds_baths", "severity": WARN,
                    "fields": ["beds", "baths"],
                    "title": f"{int(beds)} 卧配 {baths:g} 卫，比例异常",
                    "detail": "可能卧室/浴室其一误抓"})
    return out

# ---------------- 文档内自相矛盾（同一 OM 出现多个不同数值） ----------------

import re as _re


def _money_on_lines(text: str, keyword_pat: str, min_v: float = 1000.0) -> list[tuple[float, str]]:
    """只看含关键词的整行，取行内所有 $金额。返回 [(value, 行证据)]。
    按行扫描（而非字符窗口），避免租约表租金被误认成要价。"""
    out = []
    for ln in text.splitlines():
        if not _re.search(keyword_pat, ln, _re.I):
            continue
        for m in _re.finditer(r"\$\s*([\d,]+(?:\.\d+)?)", ln):
            v = _f(m.group(1).replace(",", ""))
            if v and v >= min_v:
                out.append((v, ln.strip()[:140]))
    return out


def _sf_on_lines(text: str) -> list[tuple[float, str]]:
    """面积矛盾检测：只看带 rentable/building/total 等整栋口径词的行，
    租约表行（Suite 101 ... 6,000 SF）不参与，避免误报。"""
    out = []
    for ln in text.splitlines():
        if not _re.search(r"(?:rentable|nra|building|total|gross|net|可租|建筑面积|总面积)", ln, _re.I):
            continue
        if not _re.search(r"(?:sq\.?\s*ft|sqft|square\s*feet|\bSF\b)(?![A-Za-z])", ln, _re.I):
            continue
        for m in _re.finditer(r"([\d,]+)\s*(?:sq\.?\s*ft|sqft|square\s*feet|\bSF\b)(?![A-Za-z])", ln, _re.I):
            v = _f(m.group(1).replace(",", ""))
            if v and 500 < v < 100_000_000:
                out.append((v, ln.strip()[:140]))
    return out


def _distinct(values: list[tuple[float, str]], tol: float = 0.10) -> list[tuple[float, list[str]]]:
    """按相对容差聚类，返回 [(代表值, [证据])]。"""
    groups: list[list] = []
    for v, ev in values:
        placed = False
        for g in groups:
            if abs(v - g[0]) / max(g[0], 1e-9) <= tol:
                g[1].append(ev)
                placed = True
                break
        if not placed:
            groups.append([v, [ev]])
    return [(g[0], g[1]) for g in groups]


def _emit_dup(out: list, key: str, label: str, vals: list[tuple[float, str]],
              page_of, pages) -> None:
    if len(vals) < 2:
        return
    groups = _distinct(vals)
    if len(groups) < 2:
        return
    vals_sorted = sorted(g[0] for g in groups)
    worst = max(vals_sorted) / max(min(vals_sorted), 1e-9)
    ev = [f"${gv:,.0f}（{evs[0]}）" for gv, evs in groups]
    out.append({"rule": "dup.conflict", "severity": FAIL, "fields": [key],
                "title": f"文档内自相矛盾：{label}出现 {len(groups)} 个不同数值 "
                         f"（最大相差 {worst*100-100:.0f}%）",
                "detail": "；".join(ev[:4]),
                "page": page_of(vals[0][1]) if pages else None})


def dup_conflict_checks(text: str, pages: list[str] | None = None) -> list[dict]:
    """同一文档内同一口径出现多个矛盾数值 → fail。
    NOI 按标签分组（在手/预测/未区分），同组内矛盾才算。"""
    out = []
    if not text or len(text) < 100:
        return out
    page_of = _page_fn(text, pages)
    _emit_dup(out, "analysis.purchase_price", "要价",
              _money_on_lines(text, r"(?:price|asking|list price|offering price|for sale|\bsale\b|售价|价格|要价)"),
              page_of, pages)
    # NOI 按标签分组
    noi_groups: dict[str, list[tuple[float, str]]] = {}
    for ln in text.splitlines():
        low = ln.lower()
        if "noi" not in low:
            continue
        if _re.search(r"in-?place|current|在手|现有", low):
            label = "在手 NOI"
        elif _re.search(r"pro\s*forma|projected|stabilized|预测", low):
            label = "预测 NOI"
        else:
            label = "NOI"
        for m in _re.finditer(r"\$\s*([\d,]+(?:\.\d+)?)", ln):
            v = _f(m.group(1).replace(",", ""))
            if v and v >= 1000:
                noi_groups.setdefault(label, []).append((v, ln.strip()[:140]))
    for label, vals in noi_groups.items():
        _emit_dup(out, "analysis.underwritten_noi", label, vals, page_of, pages)
    _emit_dup(out, "property.net_rentable_sf", "面积", _sf_on_lines(text), page_of, pages)
    return out


def _page_fn(text: str, pages: list[str] | None):
    if not pages:
        return lambda _snippet: None
    bounds = []
    off = 0
    for p in pages:
        bounds.append((off, off + len(p)))
        off += len(p) + 1  # join 用 "\n"

    def page_of_snippet(snippet: str):
        if not snippet:
            return None
        probe = snippet.strip("…")[:40]
        idx = text.find(probe)
        if idx < 0:
            return None
        for i, (a, b) in enumerate(bounds):
            if a <= idx <= b:
                return i + 1
        return None
    return page_of_snippet


# ---------------- 门主入口 ----------------

# 零值视为空（未录入）：money/number/比率/年份填 0 = 没填，不按矛盾拦，
# 由 missing_required 给出 warn。注意 beds 等 int 类型 0 有意义（studio），保留。
ZERO_AS_EMPTY_TYPES = {"money", "number", "pct_decimal", "year"}


def _normalize_flat(deal_type: str, flat: dict) -> dict:
    """扁平字段归一化：去空、零值视为空、小数口径归一。

    口径说明：intake 提取的 market_cap_rate 是小数口径（0.065=6.5%）；
    但商业页 state 里存的是百分比数（6.5=6.5%，见台账第 7 项口径统一待做）。
    这里 >1 即视为百分比数自动折算，避免误拦（台账#7 落地后可删此适配）。
    """
    schema = FIELD_SCHEMA.get(deal_type, {})
    out = {}
    for k, v in flat.items():
        if v is None:
            continue
        if isinstance(v, str) and v.strip() == "":
            continue
        spec = schema.get(k)
        if spec and spec["type"] in ZERO_AS_EMPTY_TYPES:
            n = _f(v)
            if n is None:
                # 非空非数值字符串：保留，让 validate_schema 报 schema.type fail
                if isinstance(v, str) and v.strip() != "":
                    out[k] = v
                continue
            if n == 0:
                continue
            if spec["type"] == "pct_decimal" and n > 1:
                v = n / 100  # 百分比数 → 小数口径
        out[k] = v
    return out


def run_quality_gate(deal_type: str, fields: list[dict] | dict,
                     tenants: list | None = None,
                     raw_text: str = "", pages: list[str] | None = None,
                     strict_unknown: bool = True) -> dict:
    """运行 intake 数据质量门。

    fields: intake 字段列表（每项含 key/value/source/page/confidence）
            或扁平 dict {key: value}。
    返回 gate 报告：status ∈ pass | warn | blocked。
    """
    tenants = tenants or []
    if isinstance(fields, dict):
        flat = {k: v for k, v in fields.items()}
        meta = {k: {} for k in flat}
    else:
        flat, meta = {}, {}
        for f in fields or []:
            k = (f or {}).get("key")
            v = (f or {}).get("value")
            if k:
                flat[k] = v
                meta[k] = f
    flat = _normalize_flat(deal_type, flat)

    checks: list[dict] = []
    checks += validate_schema(deal_type, flat, strict_unknown=strict_unknown)
    checks += _missing_required(deal_type, flat)
    checks += _check_cap_consistency(flat)
    checks += _check_noi_vs_gross_rent(flat, tenants)
    checks += _check_rent_roll_sf(flat, tenants)
    checks += _check_tenant_rent_psf(tenants)
    checks += _check_projected_vs_inplace(flat)
    checks += _check_price_sf(flat)
    if deal_type == "residential":
        checks += _check_residential(flat)
    if raw_text:
        checks += dup_conflict_checks(raw_text, pages)

    fails = [c for c in checks if c["severity"] == FAIL]
    warns = [c for c in checks if c["severity"] == WARN]
    status = "blocked" if fails else ("warn" if warns else "pass")

    # 标黄集合：fail/warn 命中的字段
    flagged = set()
    for c in checks:
        for k in c.get("fields") or []:
            flagged.add(k)
    # field_report：每字段来源/页码/置信度 + 低置信标黄
    field_report = []
    for k, v in flat.items():
        m = meta.get(k, {}) or {}
        conf = str(m.get("confidence") or "")
        low_conf = any(tag in conf for tag in CONF_LOW) or not conf
        field_report.append({
            "key": k, "value": v,
            "label": (FIELD_SCHEMA.get(deal_type, {}).get(k) or {}).get("label", m.get("label") or k),
            "source": m.get("source") or "", "page": m.get("page"),
            "confidence": conf or "未标注",
            "low_confidence": low_conf,
            "flagged": k in flagged,
            "yellow": (k in flagged) or low_conf,
        })

    return {
        "gate": "intake-data-quality",
        "deal_type": deal_type,
        "schema_version": SCHEMA_VERSIONS.get(deal_type, deal_type),
        "status": status,
        "blocked": status == "blocked",
        "fails": fails, "warns": warns,
        "fails_n": len(fails), "warns_n": len(warns),
        "checks_n": len(checks),
        "yellow_fields": sorted(flagged),          # 表单标黄（矛盾/偏离命中的字段）
        "low_confidence_fields": [r["key"] for r in field_report if r["low_confidence"]],
        "field_report": field_report,
        "summary": ("⛔ 门拦截：%d 项自相矛盾，fail 清零后才能进 underwriting"
                    % len(fails)) if fails else (
            "⚠️ %d 项偏离需复核（标黄），可继续但建议先核实" % len(warns) if warns
            else "✅ 数据质量门通过"),
    }


def gate_verdict_for_state(state: dict) -> dict:
    """商业页 state（嵌套）→ 扁平 → 跑门。供报告/Tear Sheet 导出前服务端硬拦。
    state 含应用字段（name/land_acres 等），未知字段不告警（strict_unknown=False）。"""
    flat = {}
    for sec in ("property", "analysis"):
        d = (state or {}).get(sec) or {}
        for k, v in d.items():
            flat[f"{sec}.{k}"] = v
    # 历史/预测场景里的 NOI 口径字段不参与门（门只看 analysis.*）
    return run_quality_gate("commercial", flat, tenants=(state or {}).get("tenants") or [],
                            strict_unknown=False)
