"""卖方动机分 Sell-readiness Score（台账 2026-10-09 第 3 项，学自 Reonomy Top5）。

0-100 规则分，5 个信号，每项附来源：
  持有>10年 +25 ｜ 贷款到期<24个月 +30 ｜ 24个月内再融资 +15 ｜
  留置权/违规压力 +20 ｜ 区域成交热度上升 +10

铁律（本项验收口径）：
  1. 未知数据保持未知：无数据源的信号记 status="unavailable"，0 分，
     不虚构、不凑分；available_points 明确写出"基于多少分的可用信号"；
  2. 每项信号附来源（TopHap 公共记录 / NYC DOB 公开违规 / 人工覆盖）；
  3. DOB 查询 best-effort（超时/不可达只记 caveat），仅纽约市可用，
     非 NYC 地址该信号记 unavailable；
  4. ECB 未关闭罚金暂未纳入（后续项），caveat 明示。

数据源：
  - TopHap MCP get_property_detail（last_sale_date / distress / pre_foreclosure）
  - TopHap MCP get_property_cma（trend[].homeSaleCount 年度成交数，区域热度代理指标）
  - NYC Open Data DOB Violations（data.cityofnewyork.us，数据集 3h2n-5cm9，
    公开记录、无需鉴权）：house_number + street 匹配，open 判定 =
    无 disposition_date 且 category 非 DISMISSED/RESOLVED/CLOSED。
"""

from __future__ import annotations

import os
import re
import time
from datetime import date, datetime

import httpx


def _sanitize_proxy_env() -> None:
    """与 app/ownership._sanitize_proxy_env 同因：
    httpx 解析 no_proxy 里带方括号的 IPv6（如 [::1]）会抛 InvalidURL。"""
    for k in ("no_proxy", "NO_PROXY"):
        v = os.environ.get(k, "")
        if "[" in v or "]" in v:
            clean = [part.strip() for part in v.split(",")
                     if "[" not in part and "]" not in part]
            os.environ[k] = ",".join(clean)


_sanitize_proxy_env()

DOB_DATASET = "3h2n-5cm9"  # DOB Violations（Active and historical）
DOB_URL = f"https://data.cityofnewyork.us/resource/{DOB_DATASET}.json"
DOB_TIMEOUT = 15
NEED_VERIFY = "[待验证]"

SIGNALS = (
    {"id": "holding_years", "label": "长期持有", "points": 25,
     "rule": "上次成交距今 > 10 年"},
    {"id": "mortgage_maturity", "label": "贷款到期临近", "points": 30,
     "rule": "贷款到期 < 24 个月"},
    {"id": "refinance", "label": "近期再融资", "points": 15,
     "rule": "24 个月内有再融资记录"},
    {"id": "lien_violation", "label": "留置权/违规压力", "points": 20,
     "rule": "活跃法拍/留置权预警，或 NYC DOB 有未关闭违规"},
    {"id": "zip_sales_trend", "label": "区域成交热度上升", "points": 10,
     "rule": "TopHap CMA 区域最近完整年度成交数 ≥ 前一年 +10%"},
)
_POINTS = {s["id"]: s["points"] for s in SIGNALS}
_LABELS = {s["id"]: s["label"] for s in SIGNALS}
_RULES = {s["id"]: s["rule"] for s in SIGNALS}

TIER_HIGH, TIER_MID = 70, 40


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def tier_of(score: int) -> str:
    if score >= TIER_HIGH:
        return "高"
    if score >= TIER_MID:
        return "中"
    return "低"


# ---------------- 纯规则层（可单测，now 可注入） ----------------

def _parse_date(s: str | None) -> date | None:
    """解析 YYYY-MM-DD / YYYYMMDD / MM/DD/YYYY；失败返回 None。"""
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def holding_years(last_sale_date: str | None, today: date | None = None) -> float | None:
    """上次成交距今年数；日期不可解析/缺失 → None（未知）。"""
    d = _parse_date(last_sale_date)
    if d is None:
        return None
    today = today or date.today()
    return (today - d).days / 365.25


def sales_trend_hit(trend: list[dict] | None) -> tuple[bool | None, str]:
    """区域成交热度：最近完整年度 sale_count ≥ 前一年 +10%。

    返回 (hit|None, 说明)；数据不足 → (None, 原因)。"""
    rows = [t for t in (trend or []) if isinstance(t, dict)]
    clean = []
    for t in rows:
        y = t.get("year")
        c = t.get("sale_count")
        try:
            y, c = int(y), int(c)
        except (TypeError, ValueError):
            continue
        clean.append((y, c))
    clean.sort()
    if len(clean) < 2:
        return None, "TopHap CMA 未返回 ≥2 年的年度成交数，无法判断趋势"
    (y0, c0), (y1, c1) = clean[-2], clean[-1]
    if c0 <= 0:
        return None, f"{y0} 年成交数为 0，无法计算同比"
    pct = (c1 - c0) / c0
    return (pct >= 0.10,
            f"{y0} 年 {c0} 套 → {y1} 年 {c1} 套（{pct:+.0%}）")


_OPEN_NEG = ("DISMISS", "RESOLV", "CLOS", "WITHDRAW")


def dob_open_count(violations: list[dict] | None) -> tuple[int | None, int]:
    """DOB 违规：返回 (未关闭数|None, 总数)。violations 为 None → 无数据。"""
    if violations is None:
        return None, 0
    open_n = 0
    for v in violations:
        if not isinstance(v, dict):
            continue
        cat = str(v.get("violation_category") or "").upper()
        disp = str(v.get("disposition_date") or "").strip()
        if disp or any(k in cat for k in _OPEN_NEG):
            continue
        open_n += 1
    return open_n, len(violations)


def score(data: dict, today: date | None = None) -> dict:
    """纯函数打分。data 键：
      last_sale_date, distress(bool), pre_foreclosure(list|None),
      dob_violations(list|None, None=未查询), market_trend(list|None),
      loan_maturity_months(None=无数据), refinance_24mo(None=无数据)。

    任一推断/代理指标在 note 中明示；无数据信号 status="unavailable"。"""
    data = data or {}
    signals, caveats = [], []
    total = 0

    # 1. 长期持有
    yrs = holding_years(data.get("last_sale_date"), today)
    if yrs is None:
        signals.append(_sig("holding_years", "unavailable", 0,
                             "上次成交日期未知",
                             "TopHap last_sale_date（公共记录）",
                             "无成交日期数据，该信号不计分"))
    else:
        hit = yrs > 10
        total += _POINTS["holding_years"] if hit else 0
        signals.append(_sig("holding_years", "hit" if hit else "miss",
                             _POINTS["holding_years"] if hit else 0,
                             f"持有约 {yrs:.1f} 年",
                             "TopHap last_sale_date（公共记录）",
                             "" if hit else "持有 ≤ 10 年"))

    # 2. 贷款到期临近（数据源未接入：诚实记 unavailable）
    signals.append(_sig("mortgage_maturity", "unavailable", 0, "未知",
                         "（数据源未接入）",
                         "TopHap 未返回贷款到期日；需接入贷款明细数据源后启用"))
    caveats.append("贷款到期信号暂无数据：TopHap 未映射 loan 成熟期字段，"
                   "该项 30 分当前不计入，待贷款明细数据源接入后启用")

    # 3. 近期再融资（数据源未接入）
    signals.append(_sig("refinance", "unavailable", 0, "未知",
                         "（数据源未接入）",
                         "TopHap 未返回再融资事件；需接入贷款历史数据源后启用"))
    caveats.append("再融资信号暂无数据：TopHap 未映射 refinance 事件，"
                   "该项 15 分当前不计入，待贷款历史数据源接入后启用")

    # 4. 留置权/违规压力
    distress = bool(data.get("distress"))
    pf = data.get("pre_foreclosure")
    pf_n = len(pf) if isinstance(pf, list) else 0
    dob = data.get("dob_violations")
    if dob is None:
        dob_note, open_n, dob_total = "未查询（非 NYC 或查询失败）", None, 0
    else:
        open_n, dob_total = dob_open_count(dob)
        dob_note = (f"DOB 违规 {dob_total} 条，其中未关闭 {open_n} 条"
                    if dob_total else "DOB 公开记录无违规")
    parts = []
    if distress:
        parts.append("TopHap distress 预警")
    if pf_n:
        parts.append(f"TopHap 法拍预警 {pf_n} 条")
    if open_n:
        parts.append(f"DOB 未关闭违规 {open_n} 条")
    if dob is None:
        status, earned = ("hit" if (distress or pf_n) else "miss",
                          _POINTS["lien_violation"] if (distress or pf_n) else 0)
        caveats.append("DOB 违规未纳入本次打分（非纽约市地址或查询失败）："
                       "留置权信号仅基于 TopHap distress/法拍预警")
    else:
        status = "hit" if (distress or pf_n or open_n) else "miss"
        earned = _POINTS["lien_violation"] if status == "hit" else 0
    total += earned
    value = "；".join(parts) if parts else ("无压力信号" if dob is not None else "TopHap 无压力信号")
    signals.append(_sig("lien_violation", status, earned, value,
                         "TopHap distress/法拍预警（公共记录）＋ NYC DOB 公开违规",
                         dob_note))

    # 5. 区域成交热度上升
    hit, note = sales_trend_hit(data.get("market_trend"))
    if hit is None:
        signals.append(_sig("zip_sales_trend", "unavailable", 0, "未知",
                             "TopHap CMA 年度成交趋势（公共记录）", note))
    else:
        total += _POINTS["zip_sales_trend"] if hit else 0
        signals.append(_sig(
            "zip_sales_trend", "hit" if hit else "miss",
            _POINTS["zip_sales_trend"] if hit else 0, note,
            "TopHap CMA 年度成交趋势（公共记录）",
            "代理指标：CMA 覆盖区域年度成交数同比，非 zip 精确口径"))

    available = sum(s["points"] for s in signals if s["status"] != "unavailable")
    return {"ok": True, "score": total, "max_score": 100,
            "available_points": available,
            "tier": tier_of(total),
            "tier_note": (f"动机{tier_of(total)}（{total}/100；"
                          f"可用信号 {available}/100 分）"),
            "signals": signals, "caveats": caveats,
            "generated_at": now_str()}


def _sig(sid: str, status: str, earned: int, value: str,
         source: str, note: str) -> dict:
    return {"id": sid, "label": _LABELS[sid], "rule": _RULES[sid],
            "points": _POINTS[sid], "earned": earned, "status": status,
            "value": value, "source": source, "note": note}


# ---------------- 数据层 ----------------

_STREET_EXPAND = {
    "ST": "STREET", "AVE": "AVENUE", "AV": "AVENUE", "BLVD": "BOULEVARD",
    "RD": "ROAD", "DR": "DRIVE", "LN": "LANE", "PL": "PLACE", "CT": "COURT",
    "PKWY": "PARKWAY", "HWY": "HIGHWAY", "TER": "TERRACE",
    "N": "NORTH", "S": "SOUTH", "E": "EAST", "W": "WEST",
}
_ORD_RE = re.compile(r"^(\d+)(ST|ND|RD|TH)$")


def parse_house_street(address: str) -> tuple[str, list[str]]:
    """地址 → (门牌号, 街道 token 列表·归一化)。

    "450 W 44th St, New York, NY 10036" → ("450", ["WEST", "44", "STREET"])。
    失败返回 ("", [])。"""
    head = (address or "").split(",")[0].strip().upper()
    head = re.sub(r"[.,]", " ", head)
    toks = head.split()
    if not toks or not re.fullmatch(r"\d+[A-Z]?", toks[0]):
        return "", []
    num = re.sub(r"[A-Z]$", "", toks[0])
    out = []
    for t in toks[1:]:
        t = _STREET_EXPAND.get(t, t)
        m = _ORD_RE.match(t)
        if m:
            t = m.group(1)
        out.append(t)
    return num, out


def _street_match(ds_street: str, want_tokens: list[str]) -> bool:
    ds = set(re.sub(r"[^A-Z0-9 ]", " ", (ds_street or "").upper()).split())
    return all(t in ds for t in want_tokens)


def query_dob_violations(address: str, timeout: int = DOB_TIMEOUT) -> dict:
    """查 NYC DOB 公开违规（Socrata 3h2n-5cm9，无需鉴权）。

    返回 {"ok", "violations": [...], "note"}；网络/超时/空结果一律 ok=False +
    中文 note，不抛异常。violation 字段：bin / violation_type /
    violation_category / issue_date / disposition_date / house_number / street。
    仅纽约市：调用方负责先判定州为 NY。"""
    num, toks = parse_house_street(address)
    if not num or not toks:
        return {"ok": False, "violations": [],
                "note": "地址无法解析出门牌号/街道，跳过 DOB 查询"}
    # 门牌号精确匹配 + 街道客户端过滤（Socrata LIKE 在大表上易超时且易误配）
    params = {
        "$select": ("bin,house_number,street,violation_type,violation_category,"
                    "issue_date,disposition_date,disposition_comments"),
        "$where": f"house_number='{num}'",
        "$limit": "500",
    }
    t0 = time.time()
    try:
        r = httpx.get(DOB_URL, params=params, timeout=timeout,
                      headers={"User-Agent": "dealdesk-sell-readiness/1.0"})
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "violations": [],
                "note": f"DOB 查询失败（网络/超时）：{str(e)[:100]}"}
    if r.status_code != 200:
        return {"ok": False, "violations": [],
                "note": f"DOB 返回 HTTP {r.status_code}"}
    try:
        rows = r.json()
    except Exception:
        return {"ok": False, "violations": [], "note": "DOB 返回非 JSON"}
    if not isinstance(rows, list):
        return {"ok": False, "violations": [], "note": "DOB 返回格式异常"}
    hits = [v for v in rows if isinstance(v, dict)
            and str(v.get("house_number") or "").strip() == num
            and _street_match(str(v.get("street") or ""), toks)]
    note = (f"DOB 公开记录 {len(hits)} 条（门牌 {num}＋街道匹配，"
            f"查询 {time.time() - t0:.1f}s）")
    return {"ok": True, "violations": hits, "note": note}


_STATE_RE = re.compile(r",\s*([A-Z]{2})\s+\d{5}(?:-\d{4})?\b")


def _infer_state(address: str) -> str:
    m = _STATE_RE.search(address or "")
    return m.group(1) if m else ""


def score_for_address(address: str, tophap_fetch=None,
                      dob_fetch=None) -> dict:
    """端点编排：TopHap 取 last_sale_date/distress/法拍预警/CMA 趋势
    （best-effort，不可用则对应信号 unavailable）；NY 地址自动查 DOB 违规。

    tophap_fetch / dob_fetch 可注入 mock；默认走真实数据源。
    任一数据源失败只降级对应信号，不抛异常。"""
    address = (address or "").strip()
    if not address:
        return {"ok": False, "address": "", "score": 0,
                "caveats": ["地址为空"], "generated_at": now_str()}

    data: dict = {"dob_violations": None}  # None = 未查询（非 NYC/失败时保持）
    caveats: list[str] = []
    state = _infer_state(address).upper()

    # TopHap（延迟 import，避免循环依赖）
    if tophap_fetch is None:
        def tophap_fetch(addr):  # noqa: ANN001, ANN202
            from . import tophap as _tophap
            try:
                return _tophap.enrich_address(addr, log=[])
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "fields": [],
                        "note": f"TopHap 调用异常：{str(e)[:100]}"}
    en = tophap_fetch(address)
    if en.get("ok"):
        by_key = {f.get("key"): f for f in en.get("fields", [])
                  if isinstance(f, dict)}
        lsd = by_key.get("last_sale_date") or {}
        data["last_sale_date"] = str(lsd.get("value") or "") or None
        ds = by_key.get("distress") or {}
        data["distress"] = bool(ds.get("value"))
        pf = by_key.get("pre_foreclosure") or {}
        data["pre_foreclosure"] = (pf.get("value")
                                   if isinstance(pf.get("value"), list) else [])
        mt = by_key.get("tophap_market_trend") or {}
        data["market_trend"] = (mt.get("value")
                                if isinstance(mt.get("value"), list) else None)
    else:
        caveats.append(f"TopHap 不可用（{en.get('note', '未知原因')[:80]}）："
                       "持有年限/法拍预警/区域热度三项信号记无数据")

    # DOB（仅 NY；best-effort）
    if dob_fetch is None:
        dob_fetch = query_dob_violations
    if state == "NY" or state == "":
        try:
            res = dob_fetch(address)
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "violations": [],
                   "note": f"DOB 查询异常：{str(e)[:100]}"}
        if res.get("ok"):
            data["dob_violations"] = res["violations"]
            caveats.append(res.get("note", ""))
        else:
            caveats.append(f"{res.get('note', 'DOB 查询失败')}："
                           "违规信号仅基于 TopHap")
    else:
        caveats.append(f"DOB 违规仅支持纽约市（该地址州={state}）："
                       "违规信号仅基于 TopHap")
    # ECB 未关闭罚金暂未纳入：明示
    caveats.append("ECB 未关闭罚金暂未纳入本分（后续项）："
                   "留置权压力可能被低估")

    out = score(data)
    out["address"] = address
    out["caveats"] = caveats + out["caveats"]
    return out
