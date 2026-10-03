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

from . import providers

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
    return {"ok": True, "text": text, "html": r.text,
            "final_url": str(r.url), "note": ""}


def html_to_text(html_doc: str) -> str:
    doc = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html_doc)
    doc = re.sub(r"(?s)<[^>]+>", " ", doc)
    doc = _html.unescape(doc)
    return re.sub(r"\s+", " ", doc).strip()


# ---------------- DuckDuckGo 搜索 ----------------

_OG_IMG_RE = re.compile(
    r'<meta\s+[^>]*?(?:property|name)\s*=\s*["\'](?:og:image|twitter:image)["\']'
    r'[^>]*?content\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_OG_IMG_REV = re.compile(
    r'<meta\s+[^>]*?content\s*=\s*["\']([^"\']+)["\']'
    r'[^>]*?(?:property|name)\s*=\s*["\'](?:og:image|twitter:image)["\']', re.IGNORECASE)
_IMG_SRC_RE = re.compile(
    r'<link\s+[^>]*?rel\s*=\s*["\']image_src["\'][^>]*?'
    r'href\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_JUNK_IMG_RE = re.compile(r'logo|favicon|sprite|/icon|placeholder|blank|pixel|1x1', re.IGNORECASE)
# 只从真正的房源/挂牌站取图：非房源站的 og:image（新闻配图/头像/企业图）一律不要，
# 宁可无图（诚实空态）也不展示"假图"。
_LISTING_HOSTS = (
    "realtor.com", "redfin.com", "zillow.com", "homes.com", "loopnet.com",
    "crexi.com", "apartments.com", "apartmentlist.com", "realtor.ca",
    "compass.com", "coldwellbanker.com", "remax.com", "kw.com", "sothebysrealty.com",
    "century21.com", "bhhs.com", "movoto.com", "trulia.com", "landwatch.com",
    "landandfarm.com", "crelxi", "cityfeet.com", "showcase.com", "cozycozy",
)
# 人像/头像/经纪人照片一律过滤（看着最"假"的来源）
_FACE_IMG_RE = re.compile(r'headshot|agent-|/agents?/|avatar|profile|team-|staff|broker-', re.IGNORECASE)


def _is_listing_host(host: str) -> bool:
    h = (host or "").lower()
    return any(lh in h for lh in _LISTING_HOSTS)


def extract_images(html: str, source_url: str, per_page: int = 3) -> list[dict]:
    """从页面 HTML 提取 og:image 系图片（设计稿 2.2：主图必提 + 同页最多 2 张）。

    只返回 URL（不下载），每张带来源域名 + 抓取时间。TopHap/RentCast/Census
    经实测无图片字段，不从它们挖图；唯一图源是公开网页 og:image。
    """
    if not html or not source_url:
        return []
    host = (urllib.parse.urlparse(source_url).hostname or "").lower()
    seen: set[str] = set()
    out: list[dict] = []

    if not _is_listing_host(host):
        return []  # 非房源站：直接不要图，宁缺毋假
    def _add(url: str, caption: str) -> None:
        if not url or url.startswith("data:"):
            return
        u = urllib.parse.urljoin(source_url, url.strip())
        if not u.startswith(("http://", "https://")):
            return
        if _JUNK_IMG_RE.search(u):
            return
        if _FACE_IMG_RE.search(u):
            return  # 经纪人/人像照不要
        if u in seen:
            return
        seen.add(u)
        out.append({"url": u, "source": f"{host} 页面", "source_url": source_url,
                    "fetched_at": _now(), "caption": caption})

    added_main = False
    for pat in (_OG_IMG_RE, _OG_IMG_REV):  # og:image 主图必提（两种属性顺序）
        for m in pat.finditer(html):
            if len(out) >= per_page:
                break
            if "og:image" in m.group(0).lower() and not added_main:
                _add(m.group(1), "挂牌主图")
                added_main = True
            elif "og:image" not in m.group(0).lower():
                _add(m.group(1), "页面图片")  # twitter:image 算补充
        if len(out) >= per_page:
            break
    for m in _IMG_SRC_RE.finditer(html):  # 同页再补
        if len(out) >= per_page:
            break
        _add(m.group(1), "页面图片")
    return out[:per_page]


def _photos_field(photos: list[dict]) -> dict:
    """property_photos 字段（设计稿 2.3 格式）。"""
    hosts: list[str] = []
    for q in photos:
        h = (urllib.parse.urlparse(q.get("source_url") or "").hostname or "").lower()
        h = h[4:] if h.startswith("www.") else h
        if h and h not in hosts:
            hosts.append(h)
    return {
        "key": "property_photos", "label": "房源照片",
        "value": photos,
        "display": f"{len(photos)} 张（{'、'.join(hosts[:3]) or '未知来源'}）",
        "source": "公开网页", "source_url": "",
        "fetched_at": _now(), "confidence": "中",
        "seller_claimed": True, "claim_label": "平台照片、仅供外观参考",
        "note": "挂牌平台公开图片，可能为精修/旧照，不代表现状；以实地看房为准",
        "status": "filled",
    }


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


# ---------- pipeline 入口 ----------

def run_web_collection(address: str, log: list | None = None) -> dict:
    """公开网页搜集：DDG 搜索 + 抓取 + 字段抽取（含市场新闻字段）。

    供 providers.WebProvider 调用（多数据源链的一环）。
    返回 {"fields": [...], "parsed": {...}, "log": log}。
    失败时 fields 为空 + 日志记录原因，不抛异常。
    """
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
    photos, photo_seen = [], set()
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
        for img in extract_images(page.get("html", ""), page["final_url"]):
            if img["url"] not in photo_seen and len(photos) < 6:
                photo_seen.add(img["url"])
                photos.append(img)
        if "news" in c["url"] or fetches <= 2:
            news.append({"title": c["title"][:120], "url": c["url"]})

    fields = merge_fields(all_fields)
    if photos:
        fields.append(_photos_field(photos))
        _log(log, "提取房源照片", "ok", f"{len(photos)} 张（og:image）")
    if news:
        fields.append({"key": "market_news", "label": "市场新闻/供需信号",
                       "value": news[:6],
                       "display": f"{len(news[:6])} 条相关链接（标题仅供参考）",
                       "source": "DuckDuckGo 搜索", "source_url": "",
                       "fetched_at": _now(), "confidence": "低",
                       "seller_claimed": False, "claim_label": "",
                       "note": "新闻标题不代表事实核实", "status": "filled"})
    return {"fields": fields, "parsed": parsed, "log": log}


def run_address_pipeline(address: str, log: list | None = None) -> dict:
    """纯地址 → 多数据源 fallback 链搜集（TopHap → RentCast → 公开网页 → Census 保底）。

    字段按优先级合并（TopHap > RentCast > 网页 > Census），每个字段自带来源标注；
    全部数据源失败时返回各源中文诊断（diagnostics），不静默空结果。
    """
    log = log if log is not None else []
    parsed = parse_address(address)
    chain = providers.run_chain(parsed.get("full") or address, log)
    fields = chain["fields"]

    keys = {f["key"] for f in fields}
    manual = [{"key": k, "label": FIELD_LABELS[k], "status": "manual_needed",
               "note": "全网未抓到可靠值，需手动补"}
              for k in FIELD_LABELS if k not in keys
              and k not in ("market_news", "price_history", "zestimate")]
    result = {"mode": "address", "address": parsed["full"], "parsed": parsed,
              "fields": fields, "manual_needed": manual, "log": log,
              "fetched_at": _now(),
              "primary_provider": chain["primary_provider"],
              "provider_chain": chain["provider_results"]}
    if not chain["ok"]:
        # 全部数据源失败：中文诊断，不静默
        result["diagnostics"] = chain["diagnostics"]
        _log(log, "地址搜集", "failed", "全部数据源失败：" + chain["diagnostics"])
    return result


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
    seller_photos = extract_images(page.get("html", ""), page["final_url"])
    result = {"mode": "url", "url": page["final_url"], "address": address,
              "seller_fields": seller_fields, "log": log, "fetched_at": _now()}
    if address:
        indep = run_address_pipeline(address, log)
        # 独立源优先；卖方声称保留备注
        merged = merge_fields(indep["fields"] + seller_fields)
        # 照片合并：用户粘贴链接的图优先，去重，最多 6 张（设计稿 2.2）
        indep_photos = []
        for f in indep["fields"]:
            if f.get("key") == "property_photos" and isinstance(f.get("value"), list):
                indep_photos = f["value"]
        combined, cseen = [], set()
        for q in (seller_photos + indep_photos):
            u = q.get("url")
            if u and u not in cseen:
                cseen.add(u)
                combined.append(q)
        merged = [f for f in merged if f.get("key") != "property_photos"]
        if combined:
            merged.append(_photos_field(combined[:6]))
            _log(log, "提取房源照片", "ok",
                 f"{len(combined[:6])} 张（粘贴链接优先）")
        result["fields"] = merged
        result["manual_needed"] = indep["manual_needed"]
        result["independent_note"] = "独立搜集结果优先；卖方口径数字已标注待验证"
    else:
        result["fields"] = seller_fields
        if seller_photos:
            result["fields"] = seller_fields + [_photos_field(seller_photos[:6])]
            _log(log, "提取房源照片", "ok", f"{len(seller_photos[:6])} 张（房源链接页）")
        result["manual_needed"] = [
            {"key": k, "label": FIELD_LABELS[k], "status": "manual_needed",
             "note": "未提取到地址，无法做独立搜集；请手动输入地址"}
            for k in ("building_sf", "taxes_annual", "monthly_rent")]
    return result


def run_photos_pipeline(address: str, log: list | None = None) -> dict:
    """轻量取图：商业页 A 栏"外观"小图专用。

    先查 24h 地址缓存（命中直接返回照片，约 0.7s）；未命中则做一次轻量抓取
    （DDG 搜地址 → 最多抓 3 页 → 只提 og:image），不写缓存、不跑全量字段抽取。
    返回 {"photos": [...], "cached": bool}。
    """
    from . import cache as _cache
    log = log if log is not None else []
    addr = (address or "").strip()
    if not addr:
        return {"photos": [], "cached": False}
    try:
        cached = _cache.get_cached(addr)
    except Exception:  # noqa: BLE001
        cached = None
    if cached and not cached.get("stale"):
        for f in (cached["data"].get("fields") or []):
            if f.get("key") == "property_photos" and isinstance(f.get("value"), list):
                _log(log, "照片缓存", "hit", f"{len(f['value'])} 张")
                return {"photos": f["value"], "cached": True}
    photos, seen = [], set()
    try:
        results = list(ddg_search(f'"{addr}"', log, max_results=8))
        # 房源站优先：先抓挂牌站，非房源站不抓（省配额、杜绝假图）
        results.sort(key=lambda r: 0 if _is_listing_host(
            (urllib.parse.urlparse(r["url"]).hostname or "").lower()) else 1)
        for r in results:
            if len(photos) >= 3:
                break
            host = (urllib.parse.urlparse(r["url"]).hostname or "").lower()
            if any(b in host for b in ("facebook.com", "linkedin.com", "youtube.com")):
                continue
            if not _is_listing_host(host):
                continue  # 非房源站：不抓，宁缺毋假
            page = fetch_page(r["url"], log)
            if not page.get("ok"):
                continue
            for img in extract_images(page.get("html", ""), page["final_url"]):
                if img["url"] not in seen:
                    seen.add(img["url"])
                    photos.append(img)
    except Exception as e:  # noqa: BLE001
        _log(log, "轻量取图", "failed", str(e)[:100])
    _log(log, "轻量取图", "ok" if photos else "empty", f"{len(photos)} 张")
    return {"photos": photos[:6], "cached": False}


def run(mode: str, text: str) -> dict:
    """统一入口：mode = address | url。"""
    text = (text or "").strip()
    if not text:
        return {"error": "输入为空", "fields": [], "manual_needed": [], "log": []}
    if mode == "url" or re.match(r"^https?://", text, re.I):
        return run_url_pipeline(text)
    return run_address_pipeline(text)
