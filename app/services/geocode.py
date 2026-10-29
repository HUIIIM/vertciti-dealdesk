"""地址 → 州（USPS 缩写），零 key 方案：U.S. Census Bureau Geocoder.

免费、无 key、无需注册。benchmark 用 Public_AR_Census2020。
注意：Census geocoder 对商业地址/新楼盘覆盖不如商用 API，失败时返回 None，
调用方降级为"用户手选州"或"不填"，绝不瞎猜。
"""
from __future__ import annotations

import logging

import httpx  # noqa: F401  （历史 patch 点；GET 已改走 http_capped 流式上限）

from app.services import http_capped

logger = logging.getLogger(__name__)

_CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
_TIMEOUT = 12


def geocode_state(address: str) -> dict:
    """返回 {"state": "NY"|None, "matched_address": str|None, "lat": float|None, "lng": float|None}.

    任何失败（超时/无匹配/格式变化）都返回 state=None，不抛异常。
    """
    out = {"state": None, "matched_address": None, "lat": None, "lng": None}
    if not address or not address.strip():
        return out
    try:
        r = http_capped.get_json_capped(_CENSUS_URL, params={
            "address": address.strip(), "benchmark": "2020", "format": "json",
        }, timeout=_TIMEOUT)
        if r["too_large"]:
            logger.warning(
                "Census geocoder 响应过大（超过 %s 字节上限），已停止读取，"
                "按无匹配降级", http_capped.MAX_JSON_BYTES)
            return out
        if r["status_code"] != 200 or r["json_error"]:
            return out
        data = r["data"] if isinstance(r["data"], dict) else {}
        matches = (data.get("result") or {}).get("addressMatches") or []
        if not matches:
            return out
        m = matches[0]
        comp = m.get("addressComponents") or {}
        coords = m.get("coordinates") or {}
        out["state"] = (comp.get("state") or "").upper() or None
        out["matched_address"] = m.get("matchedAddress")
        out["lng"], out["lat"] = coords.get("x"), coords.get("y")
        return out
    except Exception:
        return out
