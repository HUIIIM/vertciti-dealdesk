"""智能搜集 pipeline：地址/房源链接 → 全网公开信息自动搜集.

诚实铁律（Miao 亲口）：
- 每个自动填入字段必须带：数据来源 + 抓取时间 + 可信度；
- 抓不到就明确说抓不到（需手动补），绝不编数凑数；
- 卖方口径（房源页描述 / PDF 材料）的数字一律标"卖方口径、待验证"，不直接采信；
- 只碰公开页面；robots.txt 禁止的不碰；被反爬拦截立刻停手并记录（降级走手动）。

实现：httpx 直连（标准浏览器 UA）。Zillow/Redfin 类站点大概率 403，
这是预期内的降级路径，不是 bug。
"""

from __future__ import annotations

import html as _html
import ipaddress
import os
import re
import socket
import time
import urllib.parse
from datetime import datetime

import httpx

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
BOT_NAME = "DealDeskBot"
FETCH_TIMEOUT = 15
MAX_FETCHES = 6

BLOCK_MARKERS = ["captcha", "are you a robot", "access denied", "press & hold",
                 "perimeterx", "datadome", "verify you are a human",
                 "attention required", "request blocked", "pardon our interruption",
                 "err_access_denied"]

FIELD_LABELS = {
    "address": "地址", "asking_price": "售价/要价", "building_sf": "建筑面积 SF",
    "beds": "卧室数", "baths": "浴室数", "lot_sf": "占地 SF",
    "year_built": "建造年份", "taxes_annual": "年房产税", "hoa_monthly": "月 HOA",
    "monthly_rent": "月租金（估算）", "zestimate": "平台估值参考",
    "price_history": "价格历史", "market_news": "市场新闻/供需信号",
}
# 填表单映射：pipeline key -> 前端 input id
FORM_MAP = {"address": "p-address", "asking_price": "p-asking",
            "building_sf": "p-sf", "monthly_rent": "p-rent",
            "taxes_annual": "p-tax", "hoa_monthly": "p-hoa"}

def _sanitize_proxy_env() -> None:
    """httpx 解析 no_proxy 里带方括号的 IPv6 会抛 InvalidURL。
    进程内清洗 no_proxy（只删方括号条目，代理本身不动），保证出站抓取可用。"""
    for k in ("no_proxy", "NO_PROXY"):
        v = os.environ.get(k, "")
        if "[" in v or "]" in v:
            clean = [part.strip() for part in v.split(",")
                     if "[" not in part and "]" not in part]
            os.environ[k] = ",".join(clean)


_sanitize_proxy_env()

_robots_cache: dict[str, list[str]] = {}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _log(log: list, step: str, status: str, note: str = ""):
    log.append({"step": step, "status": status, "note": note, "at": _now()})


# ---------------- robots.txt ----------------

def robots_disallows(host: str) -> list[str]:
    """返回该 host 对通用爬虫 Disallow 的路径前缀（缓存）。"""
    if host in _robots_cache:
        return _robots_cache[host]
    disallows: list[str] = []
    try:
        r = httpx.get(f"https://{host}/robots.txt", headers={"User-Agent": UA},
                      timeout=10, follow_redirects=True)
        if r.status_code == 200:
            ua_star, ua_bot = False, False
            for line in r.text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                low = line.lower()
                if low.startswith("user-agent:"):
                    agent = low.split(":", 1)[1].strip()
                    ua_star = agent == "*"
                    ua_bot = BOT_NAME.lower() in agent
                elif low.startswith("disallow:") and (ua_star or ua_bot):
                    path = line.split(":", 1)[1].strip()
                    if path:
                        disallows.append(path)
    except Exception:
        pass
    _robots_cache[host] = disallows
    return disallows


def robots_allowed(url: str) -> tuple[bool, str]:
    try:
        parts = urllib.parse.urlparse(url)
        host = parts.hostname or ""
        for d in robots_disallows(host):
            if parts.path.startswith(d):
                return False, f"robots.txt 禁止抓取该路径（{d}）"
        return True, ""
    except Exception as e:  # noqa: BLE001
        return True, f"robots 检查异常，按允许处理：{e}"


# ---------------- 安全抓取 ----------------

def _is_public_url(url: str) -> tuple[bool, str]:
    """SSRF 防护：只允许公网 http(s) 地址。"""
    try:
        parts = urllib.parse.urlparse(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return False, "非 http(s) 链接"
        infos = socket.getaddrinfo(parts.hostname, None)
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if not ip.is_global:
                return False, f"目标解析到非公网 IP（{ip}），拒绝抓取"
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, f"URL 安全检查失败：{e}"


def fetch_page(url: str, log: list) -> dict:
    """抓取单个公开页面。返回 {ok, text, final_url, status, note}."""
    ok, reason = _is_public_url(url)
    if not ok:
        _log(log, f"抓取 {url[:80]}", "skipped", reason)
        return {"ok": False, "note": reason}
    allowed, rnote = robots_allowed(url)
    if not allowed:
        _log(log, f"抓取 {url[:80]}", "skipped", rnote)
        return {"ok": False, "note": rnote}
    try:
        r = httpx.get(url, headers={"User-Agent": UA,
                                    "Accept-Language": "en-US,en;q=0.9"},
                      timeout=FETCH_TIMEOUT, follow_redirects=True)
    except Exception as e:  # noqa: BLE001
        _log(log, f"抓取 {url[:80]}", "failed", f"网络异常：{str(e)[:120]}")
        return {"ok": False, "note": f"网络异常：{str(e)[:120]}"}
    if r.status_code in (403, 429, 503):
        note = f"HTTP {r.status_code}：站点反爬拦截，已停手（降级走手动录入）"
        _log(log, f"抓取 {url[:80]}", "blocked", note)
        return {"ok": False, "note": note, "blocked": True}
    if r.status_code != 200:
        _log(log, f"抓取 {url[:80]}", "failed", f"HTTP {r.status_code}")
        return {"ok": False, "note": f"HTTP {r.status_code}"}
    text = html_to_text(r.text)
    low = text.lower()
    if any(m in low for m in BLOCK_MARKERS):
        note = "页面返回反爬验证（captcha/验证），已停手（降级走手动录入）"
        _log(log, f"抓取 {url[:80]}", "blocked", note)
        return {"ok": False, "note": note, "blocked": True}
    _log(log, f"抓取 {url[:80]}", "ok", f"HTTP 200，{len(text)} 字符")
    return {"ok": True, "text": text, "final_url": str(r.url), "note": ""}


def html_to_text(html_doc: str) -> str:
    doc = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html_doc)
    doc = re.sub(r"(?s)<[^>]+>", " ", doc)
    doc = _html.unescape(doc)
    return re.sub(r"\s+", " ", doc).strip()


# ---------------- DuckDuckGo 搜索 ----------------

def ddg_unwrap(href: str) -> str:
    """解开 DDG 跳转链接 //duckduckgo.com/l/?uddg=<encoded>&..."""
    if "uddg=" in href:
        m = re.search(r"uddg=([^&]+)", href)
        if m:
            return urllib.parse.unquote(m.group(1))
    if href.startswith("//"):
        return "https:" + href
    return href


def _parse_ddg_links(html_text: str, max_results: int) -> list[dict]:
    """从 DDG 结果页提取外链（lite 与 html 端点通用）。"""
    out, seen = [], set()
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html_text, re.S):
        href = _html.unescape(m.group(1))
        if "duckduckgo.com/y.js" in href or "duckduckgo-help-pages" in href:
            continue  # 广告 / 帮助页
        url = ddg_unwrap(href)
        if not url.startswith("http") or url in seen:
            continue
        title = html_to_text(m.group(2)).strip()
        if len(title) < 3:
            continue
        seen.add(url)
        out.append({"title": title, "url": url})
        if len(out) >= max_results:
            break
    return out


def ddg_search(query: str, log: list, max_results: int = 8) -> list[dict]:
    """DuckDuckGo 搜索（免 key）。lite 端点优先，html 端点兜底。返回 [{title, url}]。"""
    for ep in ("https://lite.duckduckgo.com/lite/",
               "https://html.duckduckgo.com/html/"):
        host = ep.split("/")[2]
        try:
            r = httpx.get(ep, params={"q": query},
                          headers={"User-Agent": UA}, timeout=FETCH_TIMEOUT)
            if r.status_code != 200:
                _log(log, f"搜索({host})：{query[:36]}", "failed",
                     f"HTTP {r.status_code}")
                continue
            out = _parse_ddg_links(r.text, max_results)
            if out:
                _log(log, f"搜索：{query[:36]}", "ok", f"得到 {len(out)} 个结果")
                return out
            _log(log, f"搜索({host})：{query[:36]}", "failed", "无可用结果")
        except Exception as e:  # noqa: BLE001
            _log(log, f"搜索({host})：{query[:36]}", "failed",
                 f"异常：{str(e)[:100]}")
    return []


# ---------------- 地址解析 ----------------

def parse_address(text: str) -> dict:
    """从用户输入解析 street/city/state/zip（尽力而为）。"""
    t = text.strip()
    m = re.match(r"^(.*?),\s*([A-Za-z .'\-]+?),\s*([A-Z]{2})(?:\s+(\d{5}(?:-\d{4})?))?$", t)
    if m:
        return {"street": m.group(1).strip(), "city": m.group(2).strip(),
                "state": m.group(3), "zip": m.group(4) or "",
                "full": t, "parsed": True}
    m2 = re.search(r"([A-Z]{2})\s+(\d{5})", t)
    return {"street": t, "city": "", "state": m2.group(1) if m2 else "",
            "zip": m2.group(2) if m2 else "", "full": t, "parsed": False}


# ---------------- 字段抽取 ----------------

def _num(s: str) -> float | None:
    try:
        return float(s.replace(",", "").replace("$", "").strip())
    except Exception:
        return None


def _money_near(text: str, pattern: str) -> float | None:
    m = re.search(pattern + r"[^\$]{0,60}\$\s*([\d,]+(?:\.\d+)?)", text, re.I)
    return _num(m.group(1)) if m else None


def extract_fields(text: str, source_name: str, source_url: str,
                   seller_claimed: bool = False) -> list[dict]:
    """从页面文本抽取结构化字段。每条带来源/时间/可信度。"""
    at = _now()
    host = (urllib.parse.urlparse(source_url).hostname or "").lower()

    def conf_for(kind: str) -> str:
        if seller_claimed:
            return "卖方口径"
        if kind == "estimate":
            return "低"
        if "assessor" in host or host.endswith(".gov") or "county" in host:
            return "高"
        if any(d in host for d in ("redfin.com", "realtor.com", "zillow.com",
                                   "homes.com", "trulia.com", "compass.com")):
            return "中"
        return "低"

    def F(key, value, display=None, kind="fact", note=""):
        if value is None:
            return None
        return {"key": key, "label": FIELD_LABELS.get(key, key),
                "value": value, "display": display or str(value),
                "source": source_name, "source_url": source_url,
                "fetched_at": at, "confidence": conf_for(kind),
                "seller_claimed": seller_claimed,
                "claim_label": "卖方口径、待验证" if seller_claimed else "",
                "note": note, "status": "filled"}

    fields = []
    price = _money_near(text, r"(?:list price|asking price|price)")
    if price:
        fields.append(F("asking_price", price, f"${price:,.0f}",
                        note="页面价格区附近抓取"))
    beds_m = re.search(r"(\d+)\s*(?:bd|bed|bedroom)", text, re.I)
    if beds_m:
        fields.append(F("beds", int(beds_m.group(1))))
    baths_m = re.search(r"([\d.]+)\s*(?:ba|bath|bathroom)", text, re.I)
    if baths_m:
        try:
            fields.append(F("baths", float(baths_m.group(1))))
        except Exception:
            pass
    sf_m = re.search(r"([\d,]+)\s*(?:sq\.?\s*ft|sqft|square feet)", text, re.I)
    if sf_m and _num(sf_m.group(1)):
        v = _num(sf_m.group(1))
        fields.append(F("building_sf", v, f"{v:,.0f} SF"))
    lot_m = re.search(r"([\d.,]+)\s*acre", text, re.I)
    if lot_m and _num(lot_m.group(1)):
        v = _num(lot_m.group(1)) * 43560
        fields.append(F("lot_sf", round(v), f"{v:,.0f} SF（{lot_m.group(1)} acre 换算）"))
    yb_m = re.search(r"(?:built in|year built)[^\d]{0,10}(19\d{2}|20\d{2})", text, re.I)
    if yb_m:
        fields.append(F("year_built", int(yb_m.group(1))))
    tax = _money_near(text, r"(?:annual tax|property tax|taxes)")
    if tax:
        fields.append(F("taxes_annual", tax, f"${tax:,.0f}/年"))
    hoa = _money_near(text, r"HOA")
    if hoa:
        fields.append(F("hoa_monthly", hoa, f"${hoa:,.0f}/月"))
    rent = _money_near(text, r"(?:rent zestimate|rent estimate)")
    if rent:
        fields.append(F("monthly_rent", rent, f"${rent:,.0f}/月", kind="estimate",
                        note="平台租金估算，仅参考"))
    zest = _money_near(text, r"zestimate")
    if zest:
        fields.append(F("zestimate", zest, f"${zest:,.0f}", kind="estimate",
                        note="平台算法估值，非成交价"))

    # 价格历史：日期 + 事件词 + 价格
    hist = []
    for m in re.finditer(
            r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4})"
            r"[^$]{0,80}?\$([\d,]+)", text, re.I):
        seg = m.group(0)
        ev = ""
        for w in ("sold", "listed", "pending", "delisted", "price change"):
            if w in seg.lower():
                ev = w
                break
        hist.append({"date": m.group(1), "event": ev or "记录",
                     "price": _num(m.group(2))})
        if len(hist) >= 8:
            break
    if hist:
        fields.append(F("price_history", hist,
                        "; ".join(f"{h['date']} {h['event']} ${h['price']:,.0f}"
                                  for h in hist[:5]),
                        note=f"共 {len(hist)} 条"))
    return [f for f in fields if f]


def merge_fields(all_fields: list[dict]) -> list[dict]:
    """同 key 保留可信度最高的；卖方口径备注保留在 note。"""
    rank = {"高": 3, "中": 2, "低": 1, "卖方口径": 0}
    best: dict[str, dict] = {}
    for f in all_fields:
        k = f["key"]
        cur = best.get(k)
        if cur is None or rank.get(f["confidence"], 0) > rank.get(cur["confidence"], 0):
            if cur and cur.get("seller_claimed") and not f.get("seller_claimed"):
                f = dict(f)
                f["note"] = (f.get("note", "") + f"；卖方曾声称 {cur['display']}（待验证）").strip("；")
            best[k] = f
    return list(best.values())


# ---------------- 主流程 ----------------

def _candidate_priority(url: str) -> int:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if any(d in host for d in ("redfin.com", "realtor.com")):
        return 0
    if "zillow.com" in host:
        return 1
    if "assessor" in host or host.endswith(".gov"):
        return 2
    if any(d in host for d in ("homes.com", "trulia.com", "compass.com",
                               "movoto.com", "kw.com")):
        return 3
    return 9


# ---------- TopHap enrich（懒导入：避免 app/tophap.py 与本模块循环 import） ----------

def _tophap_enrich_address(address: str, log: list | None) -> dict:
    try:
        from . import tophap
    except Exception as e:  # noqa: BLE001
        _log(log, "TopHap", "skipped", f"适配器加载失败（已降级）: {str(e)[:120]}")
        return {"ok": False, "fields": [], "note": "TopHap 适配器加载失败，已降级"}
    try:
        return tophap.enrich_address(address, log)
    except Exception as e:  # noqa: BLE001
        _log(log, "TopHap", "failed", f"enrich 内部异常（已降级）: {str(e)[:120]}")
        return {"ok": False, "fields": [], "note": "TopHap enrich 内部异常，已降级"}


def _tophap_summary_field(th: dict) -> dict:
    return {"key": "tophap_enrich_status", "label": "TopHap 数据源状态",
            "value": th.get("tool_used") or "tophap", "display": th.get("note", ""),
            "source": "DealDesk（系统标记）", "source_url": "",
            "fetched_at": _now(), "confidence": "高",
            "seller_claimed": False, "claim_label": "",
            "note": "TopHap 公共记录 enrich 完成；字段级来源/可信度以各自字段为准",
            "status": "filled"}


# ---------- pipeline 入口 ----------

def run_address_pipeline(address: str, log: list | None = None) -> dict:
    """纯地址 → 全网搜集。"""
    log = log if log is not None else []
    parsed = parse_address(address)
    city_state = f"{parsed['city']} {parsed['state']}".strip()
    queries = [
        f'"{parsed["full"]}"',
        f'"{parsed["street"]}" {city_state} county assessor property',
        f'"{parsed["street"]}" {city_state} rent',
    ]
    if city_state:
        queries.append(f"{city_state} housing market news home prices")
    seen, candidates = set(), []
    for q in queries:
        for r in ddg_search(q, log):
            if r["url"] not in seen:
                seen.add(r["url"])
                candidates.append(r)
    candidates.sort(key=lambda r: _candidate_priority(r["url"]))

    all_fields, news = [], []
    fetches = 0
    for c in candidates:
        if fetches >= MAX_FETCHES:
            _log(log, "抓取配额", "skipped", f"已达上限 {MAX_FETCHES} 页，其余结果未抓")
            break
        host = (urllib.parse.urlparse(c["url"]).hostname or "").lower()
        if any(b in host for b in ("facebook.com", "linkedin.com", "youtube.com")):
            continue
        page = fetch_page(c["url"], log)
        if not page.get("ok"):
            continue
        fetches += 1
        src_name = f"{host} 页面"
        all_fields += extract_fields(page["text"], src_name, page["final_url"])
        if "news" in c["url"] or fetches <= 2:
            news.append({"title": c["title"][:120], "url": c["url"]})

    fields = merge_fields(all_fields)
    # TopHap 公共记录 enrich：已授权且可用时并入合并（高/中/低可信度由 merge_fields 原有规则比较）
    th = _tophap_enrich_address(parsed.get("full") or address, log)
    if th["ok"]:
        fields = merge_fields(fields + th["fields"])
        fields.append(_tophap_summary_field(th))
    elif th.get("note"):
        _log(log, "TopHap", "skipped", th["note"])
    # Census 兜底：TopHap 失败时，至少用免费 geocoder 确认州，保证"随便输个地址都有东西"
    if not th["ok"]:
        try:
            from . import geocode as _geocode
            g = _geocode.geocode_state(parsed.get("full") or address)
            if g["state"]:
                at = _now()
                fields.append({
                    "key": "state_confirmed", "label": "州（地理编码确认）",
                    "value": g["state"], "display": g["state"],
                    "source": "U.S. Census Geocoder", "source_url": "",
                    "fetched_at": at, "confidence": "高",
                    "seller_claimed": False, "claim_label": "",
                    "note": f"匹配地址：{g['matched_address'] or '—'}；TopHap 不可用时的兜底",
                    "status": "filled"})
                _log(log, "Census兜底", "ok", f"州={g['state']}（TopHap 失败时的保底）")
            else:
                _log(log, "Census兜底", "failed", "Census 也未匹配到该地址")
        except Exception as e:  # noqa: BLE001
            _log(log, "Census兜底", "failed", f"异常：{str(e)[:100]}")
    if news:
        fields.append({"key": "market_news", "label": "市场新闻/供需信号",
                       "value": news[:6],
                       "display": f"{len(news[:6])} 条相关链接（标题仅供参考）",
                       "source": "DuckDuckGo 搜索", "source_url": "",
                       "fetched_at": _now(), "confidence": "低",
                       "seller_claimed": False, "claim_label": "",
                       "note": "新闻标题不代表事实核实", "status": "filled"})

    keys = {f["key"] for f in fields}
    manual = [{"key": k, "label": FIELD_LABELS[k], "status": "manual_needed",
               "note": "全网未抓到可靠值，需手动补"}
              for k in FIELD_LABELS if k not in keys
              and k not in ("market_news", "price_history", "zestimate")]
    return {"mode": "address", "address": parsed["full"], "parsed": parsed,
            "fields": fields, "manual_needed": manual, "log": log,
            "fetched_at": _now()}


def run_url_pipeline(url: str, log: list | None = None) -> dict:
    """房源链接 → 先提地址+卖方基础信息，再走全网独立搜集。"""
    log = log if log is not None else []
    page = fetch_page(url, log)
    if not page.get("ok"):
        return {"mode": "url", "url": url, "fields": [], "manual_needed": [],
                "log": log, "error": page.get("note", "抓取失败"),
                "fetched_at": _now()}
    host = (urllib.parse.urlparse(page["final_url"]).hostname or "").lower()
    seller_fields = extract_fields(page["text"], f"{host} 房源页",
                                   page["final_url"], seller_claimed=True)
    # 从页面尽量提取地址
    addr_m = re.search(
        r"(\d{2,6}\s+[A-Z0-9][\w\s.'\-]{2,60}?"
        r"(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Boulevard|Blvd|Lane|Ln|Court|Ct|Way|Place|Pl|Terrace|Circle)\b"
        r"[\w\s,.'\-]{0,60}?\d{5})", page["text"])
    address = addr_m.group(1).strip() if addr_m else ""
    _log(log, "提取房源地址", "ok" if address else "failed",
         address or "页面未找到规范地址，请手动输入地址再跑地址模式")
    result = {"mode": "url", "url": page["final_url"], "address": address,
              "seller_fields": seller_fields, "log": log, "fetched_at": _now()}
    if address:
        indep = run_address_pipeline(address, log)
        # 独立源优先；卖方声称保留备注
        merged = merge_fields(indep["fields"] + seller_fields)
        result["fields"] = merged
        result["manual_needed"] = indep["manual_needed"]
        result["independent_note"] = "独立搜集结果优先；卖方口径数字已标注待验证"
    else:
        result["fields"] = seller_fields
        result["manual_needed"] = [
            {"key": k, "label": FIELD_LABELS[k], "status": "manual_needed",
             "note": "未提取到地址，无法做独立搜集；请手动输入地址"}
            for k in ("building_sf", "taxes_annual", "monthly_rent")]
    return result


def run(mode: str, text: str) -> dict:
    """统一入口：mode = address | url。"""
    text = (text or "").strip()
    if not text:
        return {"error": "输入为空", "fields": [], "manual_needed": [], "log": []}
    if mode == "url" or re.match(r"^https?://", text, re.I):
        return run_url_pipeline(text)
    return run_address_pipeline(text)
