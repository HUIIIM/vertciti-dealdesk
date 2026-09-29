"""TopHap 数据源适配器：MCP server → DealDesk 字段体系.

[实测 2026-09-28] 浏览器登录态实地扒 https://www.tophap.com/mcp：
- 认证：标准 OAuth（Streamable HTTP），无 API key；beta 期间免费。
- Server URL: https://mcp.tophap.com/api/mcp
- 9 个 tools（照抄实测名）：
    find_property_by_address / search_properties / get_property_detail /
    get_property_insights / get_property_cma / get_building_units /
    search_schools / get_school_detail / lookup_area_boundary
- 核心 enrich 链路：
    find_property_by_address → get_property_detail →
    get_property_insights / get_property_cma → 估值 enrich。

[待验证] 各 tool 的参数键名与返回 payload 结构 —— 首次 OAuth 授权后实测校准。
本模块对参数键做多样式兼容（address/query；property_id/propertyId/id），
返回做防御式映射：缺字段跳过，未知结构不崩。

认证：
  首次：跑 tools/tophap_oauth_setup.py（标准 OAuth + PKCE，localhost 回调；
  用户在已登录 TopHap 的浏览器里点一次 Approve）→ 短期 access token 进 .env，
  refresh_token 只进 Secure Vault，绝不落盘、不打印。
  日常：读 TOPHAP_ACCESS_TOKEN；401 时用 vault 里的 refresh token 换一次，
  换不到就降级（不崩）并提示重新跑授权脚本。

配置（环境变量/.env，.env 已 gitignore；密钥绝不硬编码）：
  TOPHAP_ENABLED=1        功能开关（默认 0=关闭）
  TOPHAP_MCP_URL          默认 https://mcp.tophap.com/api/mcp
  TOPHAP_ACCESS_TOKEN     OAuth access token（短期，授权脚本写入）
  TOPHAP_TOKEN_EXPIRES_AT ISO 时间（可选）
  TOPHAP_TOKEN_ENDPOINT   OAuth token endpoint（授权脚本写入，非敏感）
  TOPHAP_CLIENT_ID        OAuth client_id（授权脚本写入，非敏感）

诚实铁律：每字段带来源(TopHap MCP)＋抓取时间＋可信度；
公共记录类=高，算法估值=中（含区间），算法租金=低。
任何失败（未启用/无 token/401/超时/tool 缺失）返回 ok=False，
由 research_pipeline 降级走原 DDG pipeline，绝不打断 intake。
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

import httpx

from . import research_pipeline as rp

MCP_URL_DEFAULT = "https://mcp.tophap.com/api/mcp"
RPC_TIMEOUT_INIT = 10
RPC_TIMEOUT_CALL = 25
VAULT_TIMEOUT = 10
SOURCE_NAME = "TopHap MCP"

# ---- 实测 tool 名（2026-09-28 照抄 https://www.tophap.com/mcp） ----
TOOL_FIND = "find_property_by_address"
TOOL_SEARCH = "search_properties"
TOOL_DETAIL = "get_property_detail"
TOOL_INSIGHTS = "get_property_insights"
TOOL_CMA = "get_property_cma"
TOOL_UNITS = "get_building_units"
TOOL_SCHOOLS = "search_schools"
TOOL_SCHOOL_DETAIL = "get_school_detail"
TOOL_BOUNDARY = "lookup_area_boundary"

ALL_KNOWN_TOOLS = (TOOL_FIND, TOOL_SEARCH, TOOL_DETAIL, TOOL_INSIGHTS,
                   TOOL_CMA, TOOL_UNITS, TOOL_SCHOOLS, TOOL_SCHOOL_DETAIL,
                   TOOL_BOUNDARY)
CORE_TOOLS = (TOOL_FIND, TOOL_DETAIL, TOOL_INSIGHTS, TOOL_CMA)

# 参数键多样式兼容（[待验证] 授权后以实测校准）
FIND_ARG_STYLES = ("address", "query")
ID_ARG_STYLES = ("property_id", "propertyId", "id")

# 新增字段标签（注册进 research_pipeline.FIELD_LABELS，保持单一标签表）
TOPHAP_FIELD_LABELS = {
    "tophap_value": "TopHap 估值参考",
    "tophap_value_range": "TopHap 估值区间",
    "tophap_comps": "TopHap 可比成交",
    "tophap_schools": "周边学校",
    "last_sale_price": "上次成交价",
    "last_sale_date": "上次成交日期",
    "open_loans": "在押贷款记录",
    "loan_history": "贷款历史",
    "ownership_history": "产权/持有历史",
    "tax_assessed_value": "计税估值",
    "pre_foreclosure": "法拍预警记录",
    "property_type_detail": "物业类型明细",
    "parcel_id": "Parcel 编号",
    "building_units": "楼宇单元数",
}
for _k, _v in TOPHAP_FIELD_LABELS.items():
    rp.FIELD_LABELS.setdefault(_k, _v)


class MCPError(Exception):
    """MCP 调用失败（消息已是中文，可直接展示/记日志）。"""


class MCPAuthError(MCPError):
    """401/403：token 无效或过期，需要（重新）OAuth 授权。"""


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def dotenv_path() -> Path:
    return repo_root() / ".env"


def mcp_url() -> str:
    return os.environ.get("TOPHAP_MCP_URL", MCP_URL_DEFAULT).strip() or MCP_URL_DEFAULT


def is_enabled() -> bool:
    return os.environ.get("TOPHAP_ENABLED", "0").strip() == "1"


def access_token() -> str:
    return os.environ.get("TOPHAP_ACCESS_TOKEN", "").strip()


def is_configured() -> bool:
    return bool(access_token())


# ---------------- Secure Vault（refresh token 专用，绝不落盘） ----------------
# [平台相关·待运行时验证] 经 /opt/hatch/bin/hatch-vault 与平台 Secure Vault 交互。
# 语义是 fail-safe 的：存/读任何失败都返回 False/None，调用方必须中止流程，
# 绝不回退到磁盘文件。这是硬约束，不是可选项。

VAULT_BIN = "/opt/hatch/bin/hatch-vault"
VAULT_REFRESH_NAME = "tophap_refresh_token"


def vault_store_secret(name: str, value: str) -> bool:
    """往 Secure Vault 存一个密钥。成功 True；任何失败 False（调用方中止，不落盘）。"""
    try:
        payload = json.dumps({"name": name, "value": value}).encode()
        p = subprocess.run([VAULT_BIN, "store"], input=payload,
                           capture_output=True, timeout=VAULT_TIMEOUT)
        return p.returncode == 0
    except Exception:
        return False


def vault_read_secret(name: str) -> str | None:
    """从 Secure Vault 读一个密钥。失败/不存在返回 None（内存中短暂持有，不打印不落盘）。"""
    try:
        payload = json.dumps({"name": name}).encode()
        p = subprocess.run([VAULT_BIN, "get"], input=payload,
                           capture_output=True, timeout=VAULT_TIMEOUT)
        if p.returncode != 0:
            return None
        data = json.loads((p.stdout or b"").decode() or "{}")
        v = data.get("value") if isinstance(data, dict) else None
        return v if isinstance(v, str) and v else None
    except Exception:
        return None


def write_dotenv(updates: dict) -> None:
    """更新仓库 .env（gitignored）：原地替换已有键，不存在则追加。只写非长期密钥。"""
    path = dotenv_path()
    lines: list[str] = []
    if path.exists():
        lines = path.read_text().splitlines()
    seen = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k in updates:
                out.append(f"{k}={updates[k]}")
                seen.add(k)
                continue
        out.append(line)
    for k, v in updates.items():
        if k not in seen:
            out.append(f"{k}={v}")
    path.write_text("\n".join(out) + "\n")


# ---------------- JSON-RPC 客户端 ----------------

def _headers() -> dict:
    h = {"Content-Type": "application/json",
         "Accept": "application/json, text/event-stream",
         "User-Agent": rp.UA}
    t = access_token()
    if t:
        h["Authorization"] = f"Bearer {t}"
    return h


def _parse_rpc_response(resp) -> dict:
    """解析 JSON-RPC 响应（兼容纯 JSON 与 SSE 两种回包）。"""
    ctype = (resp.headers.get("content-type") or "").lower()
    msgs: list = []
    if "text/event-stream" in ctype:
        for line in resp.text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload and payload != "[DONE]":
                    try:
                        msgs.append(json.loads(payload))
                    except Exception:
                        pass
    else:
        try:
            data = resp.json()
        except Exception:
            raise MCPError(f"TopHap 返回非 JSON（HTTP {resp.status_code}）")
        msgs = [data] if isinstance(data, dict) else []
    for m in reversed(msgs):
        if isinstance(m, dict) and ("result" in m or "error" in m):
            if m.get("error"):
                err = m["error"]
                msg = err.get("message") if isinstance(err, dict) else str(err)
                raise MCPError(f"TopHap MCP 错误：{msg}")
            return m.get("result") or {}
    raise MCPError("TopHap 返回无法解析（无有效 JSON-RPC 消息）")


def _rpc(method: str, params: dict | None = None, req_id: int = 1,
         timeout: int = RPC_TIMEOUT_CALL) -> dict:
    payload = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        payload["params"] = params
    try:
        resp = httpx.post(mcp_url(), json=payload, headers=_headers(), timeout=timeout)
    except Exception as e:  # noqa: BLE001
        raise MCPError(f"TopHap MCP 连接失败：{str(e)[:120]}")
    if resp.status_code == 401:
        raise MCPAuthError("TopHap 授权失败（401）：access token 无效或过期")
    if resp.status_code == 403:
        raise MCPAuthError("TopHap 拒绝访问（403）：账号权限不足或 beta 名额限制")
    if resp.status_code == 429:
        raise MCPError("TopHap 限流（429）：稍后重试")
    if resp.status_code >= 400:
        raise MCPError(f"TopHap HTTP {resp.status_code}")
    return _parse_rpc_response(resp)


def _notify_initialized() -> None:
    try:
        httpx.post(mcp_url(),
                   json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                   headers=_headers(), timeout=RPC_TIMEOUT_INIT)
    except Exception:
        pass


def discover_tools() -> dict:
    """initialize → tools/list，返回 {tool_name: tool_def}。"""
    _rpc("initialize",
         {"protocolVersion": "2024-11-05", "capabilities": {},
          "clientInfo": {"name": "dealdesk-tophap", "version": "2.0"}},
         req_id=1, timeout=RPC_TIMEOUT_INIT)
    _notify_initialized()
    lst = _rpc("tools/list", {}, req_id=2, timeout=RPC_TIMEOUT_INIT)
    tools = lst.get("tools") or []
    return {t.get("name"): t for t in tools if isinstance(t, dict) and t.get("name")}


def call_tool(name: str, arguments: dict, req_id: int = 3) -> dict:
    """调一个 tool，返回其结构化结果（dict）。文本 content 尝试解析为 JSON。"""
    result = _rpc("tools/call", {"name": name, "arguments": arguments},
                  req_id=req_id, timeout=RPC_TIMEOUT_CALL)
    content = result.get("content") if isinstance(result, dict) else None
    texts = []
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                texts.append(str(part.get("text", "")))
    blob = "\n".join(texts).strip()
    if not blob:
        return result if isinstance(result, dict) else {}
    try:
        parsed = json.loads(blob)
        return parsed if isinstance(parsed, dict) else {"_text": blob}
    except Exception:
        return {"_text": blob}


def _call_with_arg_styles(tool: str, value: str, styles: tuple) -> dict:
    """参数键多样式兼容：逐个试，返回第一个非空结果（[待验证] 授权后校准）。

    401/403 直接上抛（换参数重试没有意义，走 refresh 流程）。"""
    for style in styles:
        try:
            rec = call_tool(tool, {style: value})
        except MCPAuthError:
            raise
        except MCPError:
            continue
        if isinstance(rec, dict) and rec and "_text" not in rec:
            return rec
    return {}


def _extract_property_id(found: dict) -> str | None:
    """从 find_property_by_address 返回里提取 property_id（防御式）。"""
    if not isinstance(found, dict):
        return None
    for key in ("property_id", "propertyId", "id"):
        v = found.get(key)
        if v:
            return str(v)
    inner = found.get("property")
    if isinstance(inner, dict):
        return _extract_property_id(inner)
    cands = found.get("candidates") or found.get("results")
    if isinstance(cands, list) and cands and isinstance(cands[0], dict):
        return _extract_property_id(cands[0])
    return None


# ---------------- token 刷新 ----------------

def try_refresh(log: list | None = None) -> bool:
    """用 Secure Vault 里的 refresh_token 换新的 access token。

    成功：更新环境变量 + .env，返回 True。
    失败：返回 False（调用方降级并提示重新跑授权脚本）。绝不抛异常。"""
    try:
        rt = vault_read_secret(VAULT_REFRESH_NAME)
        token_ep = os.environ.get("TOPHAP_TOKEN_ENDPOINT", "").strip()
        client_id = os.environ.get("TOPHAP_CLIENT_ID", "").strip()
        if not (rt and token_ep and client_id):
            if log is not None:
                rp._log(log, "TopHap", "auth", "refresh 不可用（vault/endpoint/client_id 缺失）")
            return False
        resp = httpx.post(token_ep,
                          data={"grant_type": "refresh_token",
                                "refresh_token": rt,
                                "client_id": client_id},
                          timeout=15)
        data = resp.json() if resp.status_code == 200 else {}
        new_at = data.get("access_token")
        if not new_at:
            if log is not None:
                rp._log(log, "TopHap", "auth",
                        f"refresh 被拒（HTTP {resp.status_code}），需重新授权")
            return False
        updates = {"TOPHAP_ACCESS_TOKEN": new_at}
        exp = data.get("expires_in")
        if exp:
            updates["TOPHAP_TOKEN_EXPIRES_AT"] = str(exp)
        os.environ["TOPHAP_ACCESS_TOKEN"] = new_at
        write_dotenv(updates)
        new_rt = data.get("refresh_token")
        if new_rt:
            vault_store_secret(VAULT_REFRESH_NAME, new_rt)  # rotation，进 vault
        if log is not None:
            rp._log(log, "TopHap", "auth", "access token 已刷新")
        return True
    except Exception as e:  # noqa: BLE001
        if log is not None:
            rp._log(log, "TopHap", "auth", f"refresh 异常：{str(e)[:100]}")
        return False


# ---------------- 记录 → DealDesk 字段 ----------------

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


def _new_field(key, value, display=None, confidence="高", note=""):
    if value is None or value == "" or value == []:
        return None
    return {"key": key, "label": rp.FIELD_LABELS.get(key, key),
            "value": value, "display": display or str(value),
            "source": SOURCE_NAME, "source_url": "",
            "fetched_at": now_str(), "confidence": confidence,
            "seller_claimed": False, "claim_label": "",
            "note": note, "status": "filled"}


def _getter(rec: dict):
    def _get(*names):
        for n in names:
            if isinstance(rec, dict) and rec.get(n) not in (None, ""):
                return rec.get(n)
        return None
    return _get


def _map_detail(rec: dict) -> list[dict]:
    """get_property_detail → 建筑/占地/房型等公共记录字段（可信度=高）。"""
    g = _getter(rec or {})
    out = []
    ptype = g("propertyType", "property_type", "useCode")
    if ptype:
        out.append(_new_field("property_type_detail", str(ptype),
                              note="TopHap 物业档案（公共记录）"))
    parcel = g("parcelId", "parcel_id", "apn")
    if parcel:
        out.append(_new_field("parcel_id", str(parcel),
                              note="TopHap 物业档案（公共记录）"))
    beds = _num(g("bedrooms", "beds"))
    if beds is not None:
        out.append(_new_field("beds", int(beds), note="TopHap 物业档案（公共记录）"))
    baths = _num(g("bathrooms", "baths"))
    if baths is not None:
        out.append(_new_field("baths", baths, note="TopHap 物业档案（公共记录）"))
    sf = _num(g("livingAreaSqft", "building_sf", "buildingAreaSqft", "sqft"))
    if sf is not None:
        out.append(_new_field("building_sf", sf, f"{sf:,.0f} SF",
                              note="TopHap 物业档案（公共记录）"))
    lot = _num(g("lotSizeSqft", "lot_sf", "lotAreaSqft"))
    if lot is not None:
        out.append(_new_field("lot_sf", lot, f"{lot:,.0f} SF",
                              note="TopHap 物业档案（公共记录）"))
    yb = _num(g("yearBuilt", "year_built"))
    if yb is not None:
        out.append(_new_field("year_built", int(yb),
                              note="TopHap 物业档案（公共记录）"))
    units = _num(g("unitCount", "units", "buildingUnits"))
    if units is not None:
        out.append(_new_field("building_units", int(units),
                              note="TopHap 楼宇单元（公共记录）；condo/co-op 适用"))
    return [f for f in out if f]


def _map_insights(rec: dict) -> list[dict]:
    """get_property_insights → 估值/税/成交/贷款/产权等（公共记录=高，算法=中/低）。"""
    g = _getter(rec or {})
    out = []

    est = g("estimatedValue", "valueEstimate", "estimated_value")
    est_v = est_l = est_h = None
    if isinstance(est, dict):
        est_v, est_l, est_h = (_num(est.get("value")), _num(est.get("low")),
                              _num(est.get("high")))
    else:
        est_v = _num(est)
    if est_v is not None:
        out.append(_new_field("tophap_value", est_v, _money(est_v), confidence="中",
                              note="TopHap 算法估值，非成交价；以可比成交校准为准"))
        if est_l is not None and est_h is not None:
            out.append(_new_field("tophap_value_range", [est_l, est_h],
                                  f"{_money(est_l)} - {_money(est_h)}", confidence="中",
                                  note="TopHap 公布的估值置信区间"))

    tax = g("tax", "propertyTax")
    tax_annual = (_num(tax.get("annualAmount")) if isinstance(tax, dict)
                  else _num(g("taxes_annual", "taxAnnual")))
    if tax_annual is not None:
        out.append(_new_field("taxes_annual", tax_annual, f"${tax_annual:,.0f}/年",
                              note="TopHap 税务记录（公共记录）"))
    assessed = (_num(tax.get("assessedValue")) if isinstance(tax, dict)
                else _num(g("assessedValue", "tax_assessed_value")))
    if assessed is not None:
        out.append(_new_field("tax_assessed_value", assessed, _money(assessed),
                              note="TopHap 计税估值（公共记录）"))

    sales = g("salesHistory", "sale_history", "sales") or []
    hist = []
    if isinstance(sales, list):
        for s in sales:
            if not isinstance(s, dict):
                continue
            p = _num(s.get("price"))
            if p is None:
                continue
            hist.append({"date": str(s.get("date", "")),
                         "event": str(s.get("type", "记录")), "price": p})
    if hist:
        out.append(_new_field(
            "price_history", hist,
            "; ".join(f"{h['date']} {h['event']} ${h['price']:,.0f}" for h in hist[:5]),
            note=f"TopHap 成交记录（公共记录），共 {len(hist)} 条"))
        last = hist[0]
        out.append(_new_field("last_sale_price", last["price"], _money(last["price"]),
                              note="TopHap 上次成交记录"))
        if last["date"]:
            out.append(_new_field("last_sale_date", last["date"], last["date"],
                                  note="TopHap 上次成交记录"))

    loans = g("loans", "loanHistory", "mortgages") or []
    if isinstance(loans, list) and loans:
        open_l = [l for l in loans
                  if isinstance(l, dict)
                  and str(l.get("status", "open")).lower() in ("open", "active", "current")]
        if open_l:
            parts = []
            for l in open_l:
                amt = _money(l.get("amount")) or "金额未知"
                rate = l.get("rate")
                rate_s = f" @{rate}%" if rate not in (None, "") else ""
                parts.append(f"{amt}{rate_s}（{l.get('date', '日期未知')}，"
                             f"{l.get('lender', 'lender 未知')}）")
            out.append(_new_field("open_loans", open_l,
                                  f"{len(open_l)} 笔在押：" + "; ".join(parts),
                                  note="TopHap 贷款记录（公共记录）；subject-to 核保需以 title/statement 独立验证"))
        out.append(_new_field("loan_history", loans, f"共 {len(loans)} 条贷款记录",
                              note="TopHap 贷款历史（公共记录）"))

    own = g("ownershipHistory", "ownership_history", "owners") or []
    if isinstance(own, list) and own:
        disp = "; ".join(
            f"{o.get('from', '')}-{o.get('to', '今')} {o.get('owner', '')}".strip()
            for o in own[:4] if isinstance(o, dict))
        out.append(_new_field("ownership_history", own, disp or f"共 {len(own)} 段",
                              note="TopHap 产权历史（公共记录）"))

    pf = g("preForeclosure", "pre_foreclosure", "foreclosureFilings") or []
    if isinstance(pf, list) and pf:
        out.append(_new_field("pre_foreclosure", pf, f"{len(pf)} 条预警记录",
                              note="TopHap 法拍预警（公共记录）；有记录=硬风险信号"))

    rent = g("rentEstimate", "rent_estimate")
    rent_m = _num(rent.get("monthly") if isinstance(rent, dict) else rent)
    if rent_m is not None:
        out.append(_new_field("monthly_rent", rent_m, f"${rent_m:,.0f}/月",
                              confidence="低",
                              note="TopHap 算法租金估算，仅参考；以 1007/实测租金为准"))
    return [f for f in out if f]


def _map_cma(rec: dict) -> list[dict]:
    """get_property_cma → 可比成交列表（可信度=中，recorded sales 口径）。"""
    g = _getter(rec or {})
    comps = g("comparables", "comps", "comparableSales") or []
    rows = []
    if isinstance(comps, list):
        for c in comps:
            if not isinstance(c, dict):
                continue
            price = _num(c.get("price") or c.get("salePrice"))
            if price is None:
                continue
            rows.append({
                "address": str(c.get("address", "")),
                "price": price,
                "date": str(c.get("saleDate") or c.get("date") or ""),
                "beds": _num(c.get("beds")),
                "baths": _num(c.get("baths")),
                "sqft": _num(c.get("sqft") or c.get("livingArea")),
                "distance_mi": _num(c.get("distance") or c.get("distanceMi")),
            })
    if not rows:
        return []
    disp = "; ".join(f"{r['address']} ${_num(r['price']):,.0f}（{r['date']}）"
                     for r in rows[:6])
    f = _new_field("tophap_comps", rows, f"{len(rows)} 套可比成交：" + disp,
                   confidence="中",
                   note="TopHap CMA（recorded sales 口径）；建议在工作台按距离/日期/面积筛选后重跑比较法")
    return [f] if f else []


def _map_schools(items: list) -> list[dict]:
    """search_schools → 周边学校（best-effort，可信度=中）。"""
    rows = []
    for s in items or []:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name", "")).strip()
        if not name:
            continue
        rows.append({
            "name": name,
            "rating": s.get("rating"),
            "distance_mi": _num(s.get("distance") or s.get("distanceMi")),
        })
    if not rows:
        return []
    disp = "; ".join(
        f"{r['name']}" + (f" {r['rating']}分" if r["rating"] not in (None, "") else "")
        for r in rows[:5])
    f = _new_field("tophap_schools", rows, f"{len(rows)} 所学校：" + disp,
                   confidence="中", note="TopHap 学校数据（公共记录）")
    return [f] if f else []


# ---------------- enrich 主链路 ----------------

def _enrich_chain(address: str, log: list) -> tuple[list[dict], str]:
    """find → detail → insights/cma → 字段。返回 (fields, tool 链路描述)。

    单个 tool 缺失/失败只跳过该环节（记日志），不整链崩；
    find 失败则整链无法定位，直接抛 MCPError。"""
    tools = discover_tools()
    missing_core = [t for t in CORE_TOOLS if t not in tools]
    if missing_core:
        rp._log(log, "TopHap", "skipped",
                "tools/list 缺少核心 tool（" + ", ".join(missing_core)
                + "），缺失环节跳过")
    used = []

    found = _call_with_arg_styles(TOOL_FIND, address, FIND_ARG_STYLES)
    pid = _extract_property_id(found)
    if not pid:
        raise MCPError("find_property_by_address 未返回 property_id，无法定位物业")
    used.append(TOOL_FIND)
    rp._log(log, "TopHap", "ok", f"地址定位成功（property_id={pid[:24]}）")

    fields: list[dict] = []
    if TOOL_DETAIL in tools:
        try:
            d = _call_with_arg_styles(TOOL_DETAIL, pid, ID_ARG_STYLES)
            n0 = len(fields)
            fields += _map_detail(d)
            used.append(TOOL_DETAIL)
            rp._log(log, "TopHap", "ok", f"物业档案映射 {len(fields) - n0} 个字段")
        except MCPError as e:
            rp._log(log, "TopHap", "skipped", f"get_property_detail 跳过：{str(e)[:100]}")

    if TOOL_INSIGHTS in tools:
        try:
            ins = _call_with_arg_styles(TOOL_INSIGHTS, pid, ID_ARG_STYLES)
            n0 = len(fields)
            fields += _map_insights(ins)
            used.append(TOOL_INSIGHTS)
            rp._log(log, "TopHap", "ok", f"物业洞察映射 {len(fields) - n0} 个字段")
        except MCPError as e:
            rp._log(log, "TopHap", "skipped", f"get_property_insights 跳过：{str(e)[:100]}")

    if TOOL_CMA in tools:
        try:
            cma = _call_with_arg_styles(TOOL_CMA, pid, ID_ARG_STYLES)
            n0 = len(fields)
            fields += _map_cma(cma)
            used.append(TOOL_CMA)
            rp._log(log, "TopHap", "ok", f"CMA 映射 {len(fields) - n0} 个字段")
        except MCPError as e:
            rp._log(log, "TopHap", "skipped", f"get_property_cma 跳过：{str(e)[:100]}")

    if TOOL_SCHOOLS in tools:  # best-effort，不阻塞主链路
        try:
            s = _call_with_arg_styles(TOOL_SCHOOLS, address, FIND_ARG_STYLES)
            items = s.get("schools") if isinstance(s, dict) else None
            if not isinstance(items, list) and isinstance(s, dict):
                items = s.get("results") or []
            n0 = len(fields)
            fields += _map_schools(items if isinstance(items, list) else [])
            if len(fields) > n0:
                used.append(TOOL_SCHOOLS)
        except MCPError:
            pass

    return fields, " → ".join(used)


def _degraded(log: list, note: str) -> dict:
    rp._log(log, "TopHap", "failed", note + "；已降级走原 pipeline")
    return {"ok": False, "fields": [], "note": note + "；已降级"}


def enrich_address(address: str, log: list | None = None) -> dict:
    """按地址取 TopHap 全记录 → DealDesk 字段。返回 {ok, fields, note, tool_used}。

    失败时 ok=False + 中文 note，调用方负责降级；本函数不抛异常（除程序 bug）。
    401 时自动用 vault refresh token 换一次 access token 后重试一次。"""
    log = log if log is not None else []
    if not is_enabled():
        return {"ok": False, "fields": [],
                "note": "TopHap 未启用（TOPHAP_ENABLED=1 开启）"}
    if not is_configured():
        rp._log(log, "TopHap", "skipped",
                "未配置 TOPHAP_ACCESS_TOKEN：先跑 tools/tophap_oauth_setup.py "
                "完成一次 OAuth 授权（浏览器里点 Approve），已降级走原 pipeline")
        return {"ok": False, "fields": [],
                "note": "未配置授权：跑 tools/tophap_oauth_setup.py 完成一次 OAuth 授权"}
    address = (address or "").strip()
    if not address:
        return {"ok": False, "fields": [], "note": "地址为空"}
    try:
        fields, used = _enrich_chain(address, log)
    except MCPAuthError as e:
        rp._log(log, "TopHap", "auth", f"{e}；尝试 refresh token…")
        if try_refresh(log):
            try:
                fields, used = _enrich_chain(address, log)
            except MCPError as e2:
                return _degraded(log, f"{e2}；refresh 后仍失败，需重新跑授权脚本")
        else:
            return _degraded(log, f"{e}；refresh 不可用，需重新跑 "
                                  "tools/tophap_oauth_setup.py 完成授权")
    except MCPError as e:
        return _degraded(log, str(e))
    rp._log(log, "TopHap", "ok", f"链路 {used}，映射 {len(fields)} 个字段（公共记录口径）")
    return {"ok": True, "fields": fields, "tool_used": used,
            "note": f"TopHap 公共记录 enrich：{len(fields)} 个字段"}


def status() -> dict:
    """数据源状态：开关 / 授权 / 连通性 / tool 面（供前端与授权后验证用）。"""
    st: dict = {"enabled": is_enabled(), "configured": is_configured(),
                "mcp_url": mcp_url(), "reachable": None,
                "tools": [], "core_ready": False, "note": ""}
    if not st["enabled"]:
        st["note"] = "未启用：设置 TOPHAP_ENABLED=1 开启"
        return st
    if not st["configured"]:
        st["note"] = ("未配置：跑 tools/tophap_oauth_setup.py 完成一次 OAuth 授权 "
                      "（浏览器里点 Approve），access token 进 .env，refresh token 进 Secure Vault")
        return st
    try:
        tools = discover_tools()
        st["reachable"] = True
        st["tools"] = sorted(tools.keys())
        missing = [t for t in CORE_TOOLS if t not in tools]
        st["core_ready"] = not missing
        st["note"] = ("MCP 连通；核心链路 tool 齐全"
                      if st["core_ready"]
                      else "MCP 连通，但缺少核心 tool：" + ", ".join(missing))
    except MCPError as e:
        st["reachable"] = False
        st["note"] = str(e)
    return st
