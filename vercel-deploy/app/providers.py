"""多数据源 fallback 链：TopHap → RentCast → 公开网页 → Census 保底。

背景：地址 pipeline 曾单吊 TopHap，TopHap 挂（token 过期/401/超时）就全挂。
本模块把四个数据源包成统一接口，按优先级依次尝试、按优先级合并字段。

统一接口（BaseProvider）：
    available() -> (bool, reason_str)   # False 时链跳过该源并记中文原因
    enrich(address, log) -> {"ok", "fields", "provider", "note"}

字段格式与 research_pipeline 一致：
    {key, label, value, display, source, source_url, fetched_at,
     confidence, seller_claimed, claim_label, note, status}
每个字段自带 source / fetched_at / confidence（诚实铁律）。

合并规则（run_chain）：
- 按 TopHap > RentCast > 公开网页 > Census 的顺序尝试
- 不可用的源跳过（记中文原因），单个源抛异常不影响其他源
- 同名字段：先到的（高优先级）胜出，低优先级只补没有的 key
- 第一个返回有效数据的记为 primary_provider（"胜出"）
- 全部失败：ok=False + 各源中文诊断，不静默空结果

循环 import 说明：
- research_pipeline 在模块顶层 import 本模块；
- 本模块对 research_pipeline / tophap 一律懒导入（方法内 import），
  顶层只 import 无循环的 geocode（geocode 只依赖 httpx）。
  因此 research_pipeline → providers → geocode 无环。
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

import httpx

from . import cache as _cache
from . import geocode

# ---------------- RentCast ----------------
RENTCAST_URL = "https://api.rentcast.io/v1/properties"
RENTCAST_TIMEOUT = 20
RENTCAST_SOURCE = "RentCast"

# RentCast 新增字段的中文标签（懒注册进 research_pipeline.FIELD_LABELS）
RENTCAST_FIELD_LABELS = {
    "county": "县",
    "zoning": "用途分区",
    "owner_name": "业主姓名",
    "stories": "楼层数",
    "neighborhood": "社区",
}
_labels_registered = False


def _load_rentcast_key_from_dotenv() -> None:
    """仓库 .env 里读 RENTCAST_API_KEY（仅该键；已有环境变量优先，不覆盖）。

    与 tophap.py 的 _load_dotenv 同模式：run.sh 不 source .env，这个 loader
    保证本地 .env 写入的 key 在 API 进程里可见。Vercel 生产走环境变量。
    """
    if os.environ.get("RENTCAST_API_KEY"):
        return
    try:
        path = Path(__file__).resolve().parent.parent / ".env"
        if not path.exists():
            return
        for line in path.read_text().splitlines():
            line = line.strip()
            if line.startswith("RENTCAST_API_KEY="):
                v = line.split("=", 1)[1].strip().strip('"').strip("'")
                if v:
                    os.environ["RENTCAST_API_KEY"] = v
                return
    except Exception:
        pass


_load_rentcast_key_from_dotenv()


def rentcast_api_key() -> str:
    return os.environ.get("RENTCAST_API_KEY", "").strip()


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _field_labels() -> dict:
    global _labels_registered
    from . import research_pipeline as rp
    if not _labels_registered:
        for _k, _v in RENTCAST_FIELD_LABELS.items():
            rp.FIELD_LABELS.setdefault(_k, _v)
        _labels_registered = True
    return rp.FIELD_LABELS


def _num(x):
    try:
        if x is None or x == "":
            return None
        return float(str(x).replace(",", "").replace("$", "").strip())
    except Exception:
        return None


def _money(v) -> str | None:
    n = _num(v)
    return f"${n:,.0f}" if n is not None else None


def _log_provider(log: list, step: str, status: str, note: str = ""):
    log.append({"step": step, "status": status, "note": note, "at": _now_str()})


# ---------------- Provider 基类 ----------------

class BaseProvider:
    """数据源基类。子类实现 available() 与 enrich()。"""

    name = "Base"
    priority = 99

    def available(self) -> tuple[bool, str]:
        """(是否可用, 不可用时的中文原因)。"""
        return True, ""

    def enrich(self, address: str, log: list) -> dict:
        """-> {"ok", "fields", "provider", "note"}；可抛异常（链会接住）。"""
        raise NotImplementedError


# ---------------- TopHap ----------------

def _tophap_summary_field(th: dict) -> dict:
    """TopHap 状态标记字段（沿用旧 pipeline 的 tophap_enrich_status，前端/测试识别用）。"""
    return {"key": "tophap_enrich_status", "label": "TopHap 数据源状态",
            "value": th.get("tool_used") or "tophap", "display": th.get("note", ""),
            "source": "DealDesk（系统标记）", "source_url": "",
            "fetched_at": _now_str(), "confidence": "高",
            "seller_claimed": False, "claim_label": "",
            "note": "TopHap 公共记录 enrich 完成；字段级来源/可信度以各自字段为准",
            "status": "filled"}


class TophapProvider(BaseProvider):
    """TopHap MCP：公共记录 enrich（最高优先级）。复用 app/tophap.py。"""

    name = "TopHap MCP"
    priority = 0

    def available(self) -> tuple[bool, str]:
        from . import tophap
        if not tophap.is_enabled():
            return False, "TopHap 未启用（TOPHAP_ENABLED=1 开启）"
        if not tophap.is_configured():
            return False, "TopHap 未配置授权（需跑 tools/tophap_oauth_setup.py 完成一次 OAuth 授权）"
        if tophap.is_token_expired():
            return False, "TopHap token 已过期（需重跑授权脚本完成一次 OAuth 授权）"
        return True, ""

    def enrich(self, address: str, log: list) -> dict:
        from . import tophap
        try:
            res = tophap.enrich_address(address, log)
        except Exception as e:  # noqa: BLE001
            _log_provider(log, self.name, "failed",
                          f"enrich 内部异常（已跳过）: {str(e)[:120]}")
            return {"ok": False, "fields": [], "provider": self.name,
                    "note": "TopHap enrich 内部异常，已跳过"}
        out = {"ok": bool(res.get("ok")),
               "fields": list(res.get("fields") or []),
               "provider": self.name,
               "note": res.get("note", "")}
        if out["ok"]:
            out["fields"].append(_tophap_summary_field(res))
        return out

# ---------------- RentCast ----------------

def _map_rentcast(rec: dict) -> list[dict]:
    """RentCast property record → DealDesk 字段（防御式：缺字段跳过）。

    结构依据 https://developers.rentcast.io/reference/property-data-schema：
    propertyType/bedrooms/bathrooms/squareFootage/lotSize/yearBuilt/assessorID/
    lastSalePrice/lastSaleDate/taxAssessments{YYYY:{value}}/propertyTaxes{YYYY:{total}}/
    history{date:{event,price}}/features{unitCount,floorCount}/hoa{fee}/
    county/zoning/owner.names
    """
    if not isinstance(rec, dict):
        return []
    labels = _field_labels()
    out = []

    def add(key, value, display=None, confidence="高", note=""):
        if value is None or value == "" or value == []:
            return
        out.append({"key": key, "label": labels.get(key, key),
                    "value": value, "display": display or str(value),
                    "source": RENTCAST_SOURCE, "source_url": "",
                    "fetched_at": _now_str(), "confidence": confidence,
                    "seller_claimed": False, "claim_label": "",
                    "note": note, "status": "filled"})

    def get(*names, d=rec):
        for n in names:
            v = d.get(n) if isinstance(d, dict) else None
            if v not in (None, ""):
                return v
        return None

    ptype = get("propertyType")
    if ptype:
        add("property_type_detail", str(ptype), note="RentCast 物业类型（county 公共记录）")
    feats = rec.get("features") if isinstance(rec.get("features"), dict) else {}
    uc = _num(feats.get("unitCount"))
    if uc is not None:
        add("building_units", int(uc), note="RentCast 单元数（公共记录）")
    fc = _num(feats.get("floorCount"))
    if fc is not None:
        add("stories", int(fc), note="RentCast 楼层数（公共记录）")
    beds = _num(get("bedrooms"))
    if beds is not None:
        add("beds", int(beds), note="RentCast（公共记录）")
    baths = _num(get("bathrooms"))
    if baths is not None:
        add("baths", baths, note="RentCast（公共记录）")
    sf = _num(get("squareFootage"))
    if sf is not None:
        add("building_sf", sf, f"{sf:,.0f} SF", note="RentCast（公共记录）")
    lot = _num(get("lotSize"))
    if lot is not None:
        add("lot_sf", lot, f"{lot:,.0f} SF", note="RentCast（公共记录）")
    yb = _num(get("yearBuilt"))
    if yb is not None:
        add("year_built", int(yb), note="RentCast（公共记录）")
    apn = get("assessorID")
    if apn:
        add("parcel_id", str(apn), note="RentCast 地块编号（公共记录）")
    county = get("county")
    if county:
        add("county", str(county), note="RentCast（公共记录）")
    zoning = get("zoning")
    if zoning:
        add("zoning", str(zoning), note="RentCast 用途分区（公共记录）")
    owner = rec.get("owner") if isinstance(rec.get("owner"), dict) else {}
    names = owner.get("names")
    if isinstance(names, list) and names and names[0]:
        add("owner_name", str(names[0]), note="RentCast 业主记录（公共记录）")
    hoa = rec.get("hoa") if isinstance(rec.get("hoa"), dict) else {}
    hoa_fee = _num(hoa.get("fee"))
    if hoa_fee is not None:
        add("hoa_monthly", hoa_fee, f"${hoa_fee:,.0f}/月",
            note="RentCast HOA（公共记录）")
    # 税务评估 / 年房产税：取最新年份
    ta = rec.get("taxAssessments")
    if isinstance(ta, dict) and ta:
        yr = max(ta.keys())
        entry = ta[yr] if isinstance(ta[yr], dict) else {}
        av = _num(entry.get("value"))
        if av is not None:
            add("tax_assessed_value", av, _money(av),
                note=f"RentCast 计税估值（{yr}，公共记录）")
    pt = rec.get("propertyTaxes")
    if isinstance(pt, dict) and pt:
        yr = max(pt.keys())
        entry = pt[yr] if isinstance(pt[yr], dict) else {}
        tx = _num(entry.get("total"))
        if tx is not None:
            add("taxes_annual", tx, f"${tx:,.0f}/年",
                note=f"RentCast 年房产税（{yr}，公共记录）")
    lsp = _num(get("lastSalePrice"))
    if lsp is not None:
        add("last_sale_price", lsp, _money(lsp),
            note="RentCast 上次成交价（公共记录；non-disclosure 州可能缺失）")
        lsd = get("lastSaleDate")
        if lsd:
            add("last_sale_date", str(lsd)[:10], str(lsd)[:10],
                note="RentCast 上次成交日期")
    hist = rec.get("history")
    if isinstance(hist, dict) and hist:
        rows = []
        for dstr in sorted(hist.keys(), reverse=True):
            h = hist[dstr]
            if not isinstance(h, dict):
                continue
            price = _num(h.get("price"))
            if price is None:
                continue
            rows.append({"date": str(h.get("date", dstr))[:10],
                         "event": str(h.get("event", "Sale")),
                         "price": price})
            if len(rows) >= 8:
                break
        if rows:
            add("price_history", rows,
                "; ".join(f"{r['date']} {r['event']} ${r['price']:,.0f}"
                          for r in rows[:5]),
                note=f"RentCast 成交历史（公共记录），共 {len(rows)} 条")
    return out


class RentcastProvider(BaseProvider):
    """RentCast API：物业公共记录（第二优先级）。key 走 RENTCAST_API_KEY。

    无 key 时 available() 返回 False，链跳过并记日志，不报错。
    """

    name = "RentCast"
    priority = 1

    def available(self) -> tuple[bool, str]:
        if not rentcast_api_key():
            return False, "RentCast 未配置（RENTCAST_API_KEY 未设置，已跳过）"
        return True, ""

    def enrich(self, address: str, log: list) -> dict:
        key = rentcast_api_key()
        address = (address or "").strip()
        if not address:
            return {"ok": False, "fields": [], "provider": self.name,
                    "note": "地址为空"}
        try:
            r = httpx.get(RENTCAST_URL,
                          params={"address": address, "limit": 1},
                          headers={"X-Api-Key": key,
                                   "Accept": "application/json",
                                   "User-Agent": "DealDeskBot/2.0"},
                          timeout=RENTCAST_TIMEOUT)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "fields": [], "provider": self.name,
                    "note": f"RentCast 连接失败：{str(e)[:120]}"}
        if r.status_code == 401:
            return {"ok": False, "fields": [], "provider": self.name,
                    "note": "RentCast API key 无效（401），请检查 RENTCAST_API_KEY"}
        if r.status_code == 429:
            return {"ok": False, "fields": [], "provider": self.name,
                    "note": "RentCast 限流（429），稍后重试"}
        if r.status_code != 200:
            return {"ok": False, "fields": [], "provider": self.name,
                    "note": f"RentCast HTTP {r.status_code}"}
        try:
            data = r.json()
        except Exception:
            return {"ok": False, "fields": [], "provider": self.name,
                    "note": "RentCast 返回非 JSON"}
        rec = data[0] if isinstance(data, list) and data else None
        if not isinstance(rec, dict):
            return {"ok": False, "fields": [], "provider": self.name,
                    "note": "RentCast 未找到该地址的物业记录"}
        fields = _map_rentcast(rec)
        if not fields:
            return {"ok": False, "fields": [], "provider": self.name,
                    "note": "RentCast 有记录但无可用字段"}
        _log_provider(log, self.name, "ok", f"物业记录映射 {len(fields)} 个字段")
        return {"ok": True, "fields": fields, "provider": self.name,
                "note": f"RentCast 物业记录：{len(fields)} 个字段（county 公共记录）"}


# ---------------- 公开网页 ----------------

class WebProvider(BaseProvider):
    """公开网页搜集（DDG 搜索 + 抓取 + 抽取）。复用 research_pipeline.run_web_collection。"""

    name = "公开网页"
    priority = 2

    def enrich(self, address: str, log: list) -> dict:
        from . import research_pipeline as rp
        res = rp.run_web_collection(address, log)
        fields = res.get("fields") or []
        if not fields:
            return {"ok": False, "fields": [], "provider": self.name,
                    "note": "公开网页未抓到有效字段（搜索无结果或站点反爬拦截）"}
        return {"ok": True, "fields": fields, "provider": self.name,
                "note": f"公开网页搜集：{len(fields)} 个字段"}


# ---------------- Census 保底 ----------------

class CensusProvider(BaseProvider):
    """Census 地理编码保底：任何地址至少返回州。复用 app/geocode.py。"""

    name = "Census"
    priority = 3

    def enrich(self, address: str, log: list) -> dict:
        try:
            g = geocode.geocode_state(address)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "fields": [], "provider": self.name,
                    "note": f"Census 异常：{str(e)[:100]}"}
        if not g.get("state"):
            _log_provider(log, self.name, "failed", "Census 未匹配到该地址")
            return {"ok": False, "fields": [], "provider": self.name,
                    "note": "Census 未匹配到该地址"}
        f = {"key": "state_confirmed", "label": "州（地理编码确认）",
             "value": g["state"], "display": g["state"],
             "source": "U.S. Census Geocoder", "source_url": "",
             "fetched_at": _now_str(), "confidence": "高",
             "seller_claimed": False, "claim_label": "",
             "note": f"匹配地址：{g.get('matched_address') or '—'}；上游数据源不可用时的保底",
             "status": "filled"}
        _log_provider(log, self.name, "ok",
                      f"州={g['state']}（上游数据源不可用时的保底）")
        return {"ok": True, "fields": [f], "provider": self.name,
                "note": f"Census 保底：州={g['state']}"}

# ---------------- 链 ----------------

PROVIDER_ORDER = (TophapProvider, RentcastProvider, WebProvider, CensusProvider)


def run_chain(address: str, log: list | None = None,
              providers: list | None = None,
              use_cache: bool = True) -> dict:
    """多数据源 fallback 链。

    按 TopHap → RentCast → 公开网页 → Census 顺序尝试：
    - 不可用的源跳过（记中文原因），单个源抛异常不影响其他源
    - 同名字段：先到的（高优先级）胜出，低优先级只补没有的 key
    - 第一个返回有效数据的记为 primary_provider（"胜出"）
    - 全部失败：ok=False + 各源中文诊断，不静默空结果

    缓存（use_cache=True 且 providers 为默认链时生效）：
    - 入口命中未过期缓存 → 直接返回缓存数据（注入 "cached": True），不调任何源
    - 链成功（ok=True）→ 写入缓存后返回（"cached": False）
    - 全挂时有缓存（过期也行）→ 返回缓存数据（"stale": True，
      diagnostics 追加说明），无缓存则原样返回诊断

    返回 {"ok", "fields", "primary_provider", "provider_results",
          "diagnostics", "log", "cached", "stale"?}。
    providers 参数供测试注入；默认按 PROVIDER_ORDER 实例化。
    """
    log = log if log is not None else []
    cache_enabled = use_cache and providers is None
    cached = _cache.get_cached(address) if cache_enabled else None

    if cache_enabled and cached is not None and not cached["stale"]:
        # 命中未过期缓存：直接返回，不调任何 provider
        data = cached["data"]
        age_h = (time.time() - cached["fetched_at"]) / 3600
        data["cached"] = True
        data.pop("stale", None)
        _log_provider(log, "地址缓存", "hit", f"命中缓存（{age_h:.1f} 小时前）")
        data["log"] = log
        return data

    if providers is None:
        providers = [c() for c in PROVIDER_ORDER]
    merged: dict[str, dict] = {}
    results: list[dict] = []
    primary: str | None = None

    for p in providers:
        try:
            ok_avail, why = p.available()
        except Exception as e:  # noqa: BLE001
            ok_avail, why = False, f"可用性检查异常：{str(e)[:100]}"
        if not ok_avail:
            results.append({"provider": p.name, "status": "skipped",
                            "note": why or "不可用"})
            _log_provider(log, p.name, "skipped", why or "不可用")
            continue
        try:
            res = p.enrich(address, log)
        except Exception as e:  # noqa: BLE001
            note = f"{p.name} 内部异常（已跳过）：{str(e)[:150]}"
            results.append({"provider": p.name, "status": "failed",
                            "note": note})
            _log_provider(log, p.name, "failed", note)
            continue
        fields = res.get("fields") if isinstance(res, dict) else None
        if not (isinstance(res, dict) and res.get("ok")) or not fields:
            note = (res.get("note") if isinstance(res, dict) else "") or "未返回有效数据"
            results.append({"provider": p.name, "status": "failed",
                            "note": note})
            _log_provider(log, p.name, "failed", note)
            continue
        if primary is None:
            primary = p.name
        added = 0
        for f in fields:
            if isinstance(f, dict) and f.get("key") and f["key"] not in merged:
                merged[f["key"]] = f
                added += 1
        note = res.get("note") or f"{len(fields)} 个字段"
        results.append({"provider": p.name, "status": "ok",
                        "note": f"{note}；合并 {added} 个新字段",
                        "fields_total": len(fields), "fields_added": added})
        _log_provider(log, p.name, "ok", f"{note}；合并 {added} 个新字段")

    fields = list(merged.values())
    if not fields:
        diag = "；".join(f"{r['provider']}：{r['note']}" for r in results)
        _log_provider(log, "数据源链", "failed", "全部数据源失败：" + diag)
        if cache_enabled and cached is not None:
            # 全挂兜底：返回缓存数据（过期也行），标记 stale
            data = cached["data"]
            age_h = (time.time() - cached["fetched_at"]) / 3600
            stale_note = f"各源失败，返回 {age_h:.1f} 小时前的缓存数据，可能过期"
            data["stale"] = True
            data["diagnostics"] = ((data.get("diagnostics") or "") + "；" + stale_note).lstrip("；")
            _log_provider(log, "地址缓存", "stale", stale_note)
            data["log"] = log
            return data
        return {"ok": False, "fields": [], "primary_provider": None,
                "provider_results": results, "diagnostics": diag, "log": log,
                "cached": False}
    result = {"ok": True, "fields": fields, "primary_provider": primary,
              "provider_results": results, "diagnostics": "", "log": log,
              "cached": False}
    if cache_enabled:
        _cache.put_cached(address, result)
    return result


def token_watch_hint() -> str:
    """TopHap token 监控提示（供 cron/运维调用）：剩余不足 24h 或未知/过期时返回中文警告，否则空串。"""
    try:
        from . import tophap
        rep = tophap.token_expiry_report()
        if rep.get("status") in ("expired", "expiring_soon", "unknown"):
            return f"TopHap token 状态【{rep['status']}】：{rep['action']}"
    except Exception:
        pass
    return ""


if __name__ == "__main__":
    import json
    import sys

    addr = sys.argv[1] if len(sys.argv) > 1 else "450 West 44th Street, New York, NY 10036"
    _log: list = []
    _t0 = time.time()
    _res = run_chain(addr, _log)
    print(json.dumps({
        "ok": _res["ok"],
        "primary_provider": _res["primary_provider"],
        "fields": len(_res["fields"]),
        "diagnostics": _res["diagnostics"],
        "elapsed_s": round(time.time() - _t0, 1),
    }, ensure_ascii=False, indent=2))
    for _f in _res["fields"][:12]:
        print(f"  - {_f['key']}: {_f['display'][:60]} [{_f['source']}]")
