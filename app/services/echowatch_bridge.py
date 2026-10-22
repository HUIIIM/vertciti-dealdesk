"""EchoWatch → 市场调查：为六个维度拉「候选证据」（带出处的公开提及）。

只读调用 EchoWatch REST API v1（GET /api/v1/mentions，Bearer token，viewer 权限即可），
每个维度用「城市/区域 + 维度关键词」做全文检索，取最新几条提及作为候选。
区域优先用调用方给的 area（v2 按 deal 地址），否则按 market_key 映射城市。

诚实口径：
  - 候选证据不是已核实数据。前端只展示，由人点「采用」才写进该维度的内容/来源。
  - 未配置 ECHOWATCH_URL / ECHOWATCH_TOKEN、网络失败、无命中，都如实返回原因，绝不编造。

配置（环境变量）：
  ECHOWATCH_URL    例如 https://echowatch.example.com
  ECHOWATCH_TOKEN  EchoWatch「设置 → API tokens」里创建的 ew_... 个人令牌
"""

from __future__ import annotations

import os

import httpx

# 维度 → 检索关键词（EchoWatch 采集以英文来源为主，FTS5 词项之间为 AND）
DIM_TERMS = {
    "supply": "construction",
    "demand": "demand",
    "vacancy": "vacancy",
    "rent_trend": "rent",
    "population": "population",
    "employment": "jobs",
}
DIM_LABELS = {"supply": "供给", "demand": "需求", "vacancy": "空置率",
              "rent_trend": "租金趋势", "population": "人口", "employment": "就业"}

# hpi.MARKETS 的 key → 检索用城市名；全美口径不加城市限定
MARKET_CITY = {"us": "", "nyc": "New York", "phoenix": "Phoenix", "tampa": "Tampa",
               "dallas": "Dallas", "atlanta": "Atlanta"}

PER_DIM = 3
TIMEOUT_S = 8.0
WINDOW = "30d"


def _config() -> tuple[str, str]:
    return os.environ.get("ECHOWATCH_URL", "").rstrip("/"), os.environ.get("ECHOWATCH_TOKEN", "")


def _query(market_key: str, dim: str, area: str = "") -> str:
    city = area.strip() or MARKET_CITY.get(market_key, market_key.replace("_", " ").title())
    return f"{city} {DIM_TERMS[dim]}".strip()


def fetch_evidence(market_key: str = "", client: httpx.Client | None = None, area: str = "") -> dict:
    """返回 {"ok", "reason"?, "source", "window", "dims": [{dim, label, query, items|error}]}."""
    base, token = _config()
    if not base or not token:
        return {"ok": False, "reason": "未配置 EchoWatch（需 ECHOWATCH_URL 与 ECHOWATCH_TOKEN）", "dims": []}
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT_S, headers={"Authorization": f"Bearer {token}"})
    dims = []
    try:
        for dim in DIM_TERMS:
            q = _query(market_key, dim, area)
            entry = {"dim": dim, "label": DIM_LABELS[dim], "query": q}
            try:
                r = client.get(f"{base}/api/v1/mentions",
                               params={"q": q, "per_page": PER_DIM, "window": WINDOW})
                if r.status_code != 200:
                    entry["error"] = f"EchoWatch 返回 HTTP {r.status_code}"
                    entry["items"] = []
                else:
                    entry["items"] = [
                        {"title": m.get("title") or "", "url": m.get("url") or "",
                         "source": m.get("source") or "", "published_at": m.get("published_at")}
                        for m in (r.json().get("data") or [])[:PER_DIM]
                        if m.get("url")  # 没有链接的提及不能当出处
                    ]
            except (httpx.HTTPError, ValueError) as e:
                entry["error"] = f"EchoWatch 不可达：{type(e).__name__}"
                entry["items"] = []
            dims.append(entry)
    finally:
        if own:
            client.close()
    ok = any(d["items"] for d in dims)
    out = {"ok": ok, "source": "EchoWatch /api/v1/mentions", "window": WINDOW, "dims": dims}
    if not ok:
        out["reason"] = "EchoWatch 近 30 天没有匹配的提及" if not any("error" in d for d in dims) else "EchoWatch 调用失败"
    return out
