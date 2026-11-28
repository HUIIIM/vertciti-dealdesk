"""HTML 解析与图片提取（自 research_pipeline 拆分，TN-GATE T1 整改）。

纯函数层：HTML 转纯文本、挂牌站点判定、页面图片提取与 photos 字段组装。
不依赖 research_pipeline 的任何状态，可独立测试；research_pipeline
以 re-export 保持原有公开面（rp.html_to_text 等）不变。
"""

from __future__ import annotations

import html as _html
import re
import urllib.parse
from datetime import datetime
from typing import Any


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


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


def extract_images(html: str, source_url: str, per_page: int = 3) -> list[dict[str, Any]]:
    """从页面 HTML 提取 og:image 系图片（设计稿 2.2：主图必提 + 同页最多 2 张）。

    只返回 URL（不下载），每张带来源域名 + 抓取时间。TopHap/RentCast/Census
    经实测无图片字段，不从它们挖图；唯一图源是公开网页 og:image。
    """
    if not html or not source_url:
        return []
    host = (urllib.parse.urlparse(source_url).hostname or "").lower()
    seen: set[str] = set()
    out: list[dict[str, Any]] = []

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


def _photos_field(photos: list[dict[str, Any]]) -> dict[str, Any]:
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
