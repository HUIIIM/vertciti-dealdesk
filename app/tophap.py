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

认证（2026-09-29 修订：Secure Vault 按平台设计是 opaque 的，存进的值读不回，
静默刷新此路不通）：
  授权：跑 tools/tophap_oauth_setup.py（标准 OAuth + PKCE，localhost 回调；
  用户在已登录 TopHap 的浏览器里点一次 Approve）→ access token＋绝对过期
  时间戳进 .env（gitignored）。refresh_token 不持久化（无处可安全存放且
  读不回）；access token 过期后重跑脚本即可（约 1 分钟）。
  日常：import 时自动加载仓库 .env（仅 TOPHAP_* 键，不覆盖已有环境变量）；
  401/过期一律降级，不抛异常，note/status 明确提示重跑授权脚本。

配置（环境变量/.env，.env 已 gitignore；密钥绝不硬编码）：
  TOPHAP_ENABLED=1        功能开关（默认 0=关闭）
  TOPHAP_MCP_URL          默认 https://mcp.tophap.com/api/mcp
  TOPHAP_ACCESS_TOKEN     OAuth access token（短期，授权脚本写入）
  TOPHAP_TOKEN_EXPIRES_AT 绝对 epoch 秒（授权脚本写入；status() 据此判过期）
  TOPHAP_TOKEN_ENDPOINT   OAuth token endpoint（授权脚本写入，非敏感）
  TOPHAP_CLIENT_ID        OAuth client_id（授权脚本写入，非敏感）

诚实铁律：每字段带来源(TopHap MCP)＋抓取时间＋可信度；
公共记录类=高，算法估值=中（含区间），算法租金=低。
任何失败（未启用/无 token/token 过期/401/超时/tool 缺失）返回 ok=False，
由 research_pipeline 降级走原 DDG pipeline，绝不打断 intake。
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

import httpx

from . import research_pipeline as rp

MCP_URL_DEFAULT = "https://mcp.tophap.com/api/mcp"
RPC_TIMEOUT_INIT = 10
RPC_TIMEOUT_CALL = 25
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
ID_ARG_STYLES = ("attomId", "property_id", "propertyId", "id")

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


def _load_dotenv() -> None:
    """import 时加载仓库 .env（仅 TOPHAP_* 键；已有环境变量优先，不覆盖）。

    run.sh 不 source .env，这个 loader 保证授权脚本写入的 token 在 API
    进程里可见。零依赖，失败静默（环境变量直传照常工作）。"""
    try:
        path = dotenv_path()
        if not path.exists():
            return
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k.startswith("TOPHAP_") and k not in os.environ:
                os.environ[k] = v
    except Exception:
        pass


_load_dotenv()


def mcp_url() -> str:
    return os.environ.get("TOPHAP_MCP_URL", MCP_URL_DEFAULT).strip() or MCP_URL_DEFAULT


def is_enabled() -> bool:
    return os.environ.get("TOPHAP_ENABLED", "0").strip() == "1"


def access_token() -> str:
    return os.environ.get("TOPHAP_ACCESS_TOKEN", "").strip()


def is_configured() -> bool:
    return bool(access_token())


def write_dotenv(updates: dict) -> None:
    """更新仓库 .env（gitignored）：原地替换已有键，不存在则追加。只写非长期密钥。

    写完强制 chmod 600（token 凭证文件不许组/他人可读）。"""
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
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


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

    401/403 直接上抛（调用方降级并提示重跑授权脚本；不再 refresh）。"""
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
    """从 find_property_by_address 返回里提取物业 ID（防御式）。

    TopHap 真实结构（2026-09-29 实测）：{match: {attomId: 169551792, ...}, alternates: [...]}。
    """
    if not isinstance(found, dict):
        return None
    m = found.get("match")
    if isinstance(m, dict):
        for key in ("attomId", "property_id", "propertyId", "id"):
            v = m.get(key)
            if v:
                return str(v)
    for key in ("attomId", "property_id", "propertyId", "id"):
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
    """get_property_detail → TopHap 物业档案（字段结构 2026-09-29 对 MCP 实测校准）。"""
    g = _getter(rec or {})
    out = []
    ptype = g("propType")
    if ptype:
        pc = g("propClass")
        out.append(_new_field("property_type_detail", str(ptype),
                              note="TopHap 物业档案（公共记录）" + (f"，分类 {pc}" if pc else "")))
    nb = g("neighborhood")
    nb_name = nb.get("name") if isinstance(nb, dict) else nb
    if nb_name:
        out.append(_new_field("neighborhood", str(nb_name), note="TopHap 社区划分"))
    # P0-3 (2026-10-05): 主体一致性校验用——TopHap 模糊命中可能返回异地物业，
    # pull_comps 用 subject_state/subject_city 与输入地址比对，不一致则拒收
    subj_state = g("state", "stateCode", "province", "state_code")
    subj_city = g("city", "town", "municipality", "cityName")
    if not subj_state or not subj_city:
        # 兜底：从完整地址字符串里解析 "…, City, ST …"
        import re as _re
        full_addr = g("address", "fullAddress", "propertyAddress") or ""
        m = _re.search(r",\s*([A-Za-z .'\-]+?),\s*([A-Z]{2})(?:\s+\d{5})?", str(full_addr))
        if m:
            subj_city = subj_city or m.group(1).strip()
            subj_state = subj_state or m.group(2)
    if subj_state:
        out.append(_new_field("subject_state", str(subj_state).upper(),
                              note="TopHap 定位到的物业所在州（主体校验用）"))
    if subj_city:
        out.append(_new_field("subject_city", str(subj_city),
                              note="TopHap 定位到的物业所在城市（主体校验用）"))
    beds = _num(g("beds"))
    if beds is not None:
        out.append(_new_field("beds", int(beds), note="TopHap 物业档案（公共记录）"))
    baths = _num(g("baths"))
    if baths is not None:
        out.append(_new_field("baths", baths, note="TopHap 物业档案（公共记录）"))
    st = _num(g("stories"))
    if st is not None:
        out.append(_new_field("stories", int(st), note="TopHap 物业档案（公共记录）"))
    uc = _num(g("unitCount"))
    if uc is not None:
        out.append(_new_field("building_units", int(uc), note="TopHap 单元数（公共记录）"))
    sf = _num(g("sqft"))
    if sf is not None:
        out.append(_new_field("building_sf", sf, f"{sf:,.0f} SF",
                              note="TopHap 物业档案（公共记录）"))
    lot = _num(g("lotSqft"))
    if lot is not None:
        out.append(_new_field("lot_sf", lot, f"{lot:,.0f} SF",
                              note="TopHap 物业档案（公共记录）"))
    yb = _num(g("yearBuilt"))
    if yb is not None:
        out.append(_new_field("year_built", int(yb), note="TopHap 物业档案（公共记录）"))
    avm = _num(g("avmValue"))
    if avm is not None:
        out.append(_new_field("tophap_value", avm, _money(avm), confidence="中",
                              note="TopHap AVM 算法估值，非成交价；以可比成交校准为准"))
        ahl, ahh = _num(g("avmLow")), _num(g("avmHigh"))
        if ahl is not None and ahh is not None:
            out.append(_new_field("tophap_value_range", [ahl, ahh],
                                  f"{_money(ahl)} - {_money(ahh)}", confidence="中",
                                  note="TopHap AVM 置信区间"))
    tax = _num(g("taxAmount"))
    if tax is not None:
        ty = g("taxYear")
        out.append(_new_field("taxes_annual", tax,
                              f"${tax:,.0f}/年" + (f"（{ty}）" if ty else ""),
                              note="TopHap 税务记录（公共记录）"))
    av = _num(g("assessedValue"))
    if av is not None:
        ay = g("assessedYear")
        out.append(_new_field("tax_assessed_value", av, _money(av),
                              note="TopHap 计税估值（公共记录）" + (f"，{ay} 年" if ay else "")))
    mv = _num(g("marketValue"))
    if mv is not None:
        out.append(_new_field("market_value", mv, _money(mv),
                              note="TopHap 市场价值（公共记录口径）"))
    lsp = _num(g("lastSaleAmount"))
    if lsp is not None:
        out.append(_new_field("last_sale_price", lsp, _money(lsp),
                              note="TopHap 上次成交记录（公共记录）"))
        lsd = g("lastSaleDate")
        if lsd:
            out.append(_new_field("last_sale_date", str(lsd), str(lsd),
                                  note="TopHap 上次成交记录（公共记录）"))
    own = g("ownerName")
    if own:
        flags = []
        if g("companyOwned"):
            flags.append("公司持有")
        if g("absenteeOwner"):
            flags.append("absentee owner")
        out.append(_new_field("owner_name", str(own),
                              note="TopHap 业主记录（公共记录）" + ("；" + "、".join(flags) if flags else "")))
    fz = g("floodFemaZone")
    if fz:
        out.append(_new_field("flood_zone", str(fz), note="TopHap FEMA 洪水区划"))
    rt = _num(g("riskTotal"))
    if rt is not None:
        out.append(_new_field("risk_total", rt, f"综合风险指数 {rt:g}",
                              note="TopHap 风险指数（heat/storm/wildfire/drought/flood 综合）"))
    ltv = _num(g("ltv"))
    if ltv is not None:
        out.append(_new_field("ltv_estimate", ltv, f"LTV 约 {ltv:g}%",
                              confidence="中", note="TopHap 杠杆估算（公共记录推算）"))
    eq = _num(g("equityAvailable"))
    if eq is not None:
        out.append(_new_field("equity_available", eq, _money(eq),
                              note="TopHap 可用净值估算（公共记录推算）"))
    lp = g("loanPositions")
    lp_n = len(lp) if isinstance(lp, list) else _num(lp)
    if lp_n is not None:
        out.append(_new_field("loan_positions", int(lp_n),
                              note="TopHap 在押顺位数（公共记录）；subject-to 核保以 title/statement 独立验证"))
    if g("distressActive"):
        dt = g("distressType") or "distress"
        ad = g("auctionDate") or ""
        out.append(_new_field("distress", True, f"{dt} {ad}".strip(),
                              note="TopHap distress 预警（公共记录）；硬风险信号"))
    rurl = g("pdfReportUrl")
    if rurl:
        out.append(_new_field("tophap_report_url", str(rurl), "TopHap 物业报告 PDF",
                              note="TopHap 生成的物业报告"))
    return [f for f in out if f]


def _map_insights(rec: dict) -> list[dict]:
    """get_property_insights → 成交记录/社区/学校/法拍预警（2026-09-29 对 MCP 实测校准）。"""
    g = _getter(rec or {})
    out = []

    txs = g("transactions") or []
    hist = []
    if isinstance(txs, list):
        for t in txs:
            if not isinstance(t, dict):
                continue
            amt = _num(t.get("amount"))
            if amt is None:
                continue
            hist.append({"date": str(t.get("date", "")),
                         "event": str(t.get("transType", "记录")),
                         "price": amt,
                         "price_per_sqft": _num(t.get("pricePerSqft")),
                         "doc": str(t.get("docNumber", ""))})
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

    comm = g("community")
    if isinstance(comm, dict):
        parts = []
        if comm.get("name"):
            parts.append(str(comm["name"]))
        mhi = _num(comm.get("medianHouseholdIncome"))
        if mhi is not None:
            parts.append(f"家庭收入中位 ${mhi:,.0f}")
        ci = _num(comm.get("crimeIndex"))
        if ci is not None:
            parts.append(f"犯罪指数 {ci:g}")
        if parts:
            out.append(_new_field("tophap_community", comm, "；".join(parts),
                                  confidence="中", note="TopHap 社区统计"))

    dn = g("districtName")
    if dn:
        out.append(_new_field("school_district", str(dn), note="TopHap 学区（公共记录）"))

    sch = g("schools") or []
    rows = []
    if isinstance(sch, list):
        for s in sch:
            if not isinstance(s, dict) or not s.get("name"):
                continue
            rows.append({"name": s["name"], "level": s.get("level"),
                         "rating": s.get("rating"),
                         "distance_mi": _num(s.get("distanceMiles"))})
    if rows:
        disp = "; ".join(
            f"{r['name']}" + (f"（{r['level']}，评级 {r['rating']}）" if r.get("rating") else "")
            for r in rows[:5])
        out.append(_new_field("tophap_schools", rows, f"{len(rows)} 所学校：" + disp,
                              confidence="中", note="TopHap 学校数据（公共记录）"))

    pf = g("preforeclosure") or []
    if isinstance(pf, list) and pf:
        out.append(_new_field("pre_foreclosure", pf, f"{len(pf)} 条预警记录",
                              note="TopHap 法拍预警（公共记录）；有记录=硬风险信号"))
    return [f for f in out if f]


def _map_cma(rec: dict) -> list[dict]:
    """get_property_cma → 可比成交＋年度价格趋势（2026-09-29 对 MCP 实测校准）。"""
    g = _getter(rec or {})
    out = []
    comps = g("comparables") or []
    rows = []
    if isinstance(comps, list):
        for c in comps:
            if not isinstance(c, dict):
                continue
            price = _num(c.get("salePrice"))
            if price is None:
                continue
            addr = str(c.get("address", ""))
            if c.get("city"):
                addr += f", {c.get('city')}"
            rows.append({
                "address": addr,
                "price": price,
                "date": str(c.get("saleDate") or ""),
                "price_per_sqft": _num(c.get("pricePerSqft")),
                "beds": _num(c.get("beds")),
                "baths": _num(c.get("baths")),
                "sqft": _num(c.get("sqft")),
                "year_built": _num(c.get("yearBuilt")),
                "distance_mi": _num(c.get("distanceMiles")),
            })
    if rows:
        disp = "; ".join(f"{r['address']} ${_num(r['price']):,.0f}（{r['date']}）"
                         for r in rows[:6])
        crit = g("criteria") or {}
        note = "TopHap CMA（recorded sales 口径）"
        if isinstance(crit, dict) and crit.get("miles"):
            note += f"；筛选 {crit.get('miles')} 英里内、近 {crit.get('saleDateMonths')} 个月"
        if g("widened"):
            note += "；条件已放宽"
        out.append(_new_field("tophap_comps", rows, f"{len(rows)} 套可比成交：" + disp,
                              confidence="中", note=note))
    trend = g("trend") or []
    trows = []
    if isinstance(trend, list):
        for t in trend:
            if not isinstance(t, dict) or t.get("year") is None:
                continue
            med = _num(t.get("medSalePrice"))
            if med is None:
                continue
            trows.append({"year": t["year"], "med_sale_price": med,
                          "avg_sale_price": _num(t.get("avgSalePrice")),
                          "sale_count": _num(t.get("homeSaleCount"))})
    if trows:
        ta = g("trendArea") or ""
        disp = "；".join(f"{r['year']} 年中位 ${r['med_sale_price']:,.0f}" for r in trows[-5:])
        out.append(_new_field("tophap_market_trend", trows, f"{ta}年度中位价：{disp}",
                              confidence="中", note="TopHap 区域年度成交趋势（recorded sales）"))
    rurl = g("pdfReportUrl")
    if rurl:
        out.append(_new_field("tophap_cma_report_url", str(rurl), "TopHap CMA 报告 PDF",
                              note="TopHap 生成的 CMA 报告"))
    return [f for f in out if f]


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
            "distance_mi": _num(s.get("distanceMiles") or s.get("distance") or s.get("distanceMi")),
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
        raise MCPError("find_property_by_address 未返回 attomId，无法定位物业")
    used.append(TOOL_FIND)
    rp._log(log, "TopHap", "ok", f"地址定位成功（attomId={pid[:24]}）")

    fields: list[dict] = []
    if TOOL_DETAIL in tools:
        try:
            d = _call_with_arg_styles(TOOL_DETAIL, pid, ID_ARG_STYLES)
            n0 = len(fields)
            fields += _map_detail(d)
            used.append(TOOL_DETAIL)
            rp._log(log, "TopHap", "ok", f"物业档案映射 {len(fields) - n0} 个字段")
        except MCPAuthError:
            # 401/403：token 中途过期，整链终止（不吞成"跳过"）
            raise
        except MCPError as e:
            rp._log(log, "TopHap", "skipped", f"get_property_detail 跳过：{str(e)[:100]}")

    if TOOL_INSIGHTS in tools:
        try:
            ins = _call_with_arg_styles(TOOL_INSIGHTS, pid, ID_ARG_STYLES)
            n0 = len(fields)
            fields += _map_insights(ins)
            used.append(TOOL_INSIGHTS)
            rp._log(log, "TopHap", "ok", f"物业洞察映射 {len(fields) - n0} 个字段")
        except MCPAuthError:
            raise
        except MCPError as e:
            rp._log(log, "TopHap", "skipped", f"get_property_insights 跳过：{str(e)[:100]}")

    if TOOL_CMA in tools:
        try:
            cma = _call_with_arg_styles(TOOL_CMA, pid, ID_ARG_STYLES)
            n0 = len(fields)
            fields += _map_cma(cma)
            used.append(TOOL_CMA)
            rp._log(log, "TopHap", "ok", f"CMA 映射 {len(fields) - n0} 个字段")
        except MCPAuthError:
            raise
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
    401/过期 → 直接降级，note 提示重跑授权脚本（不再 refresh：Vault opaque 读不回）。"""
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
    # 过期预检（60 秒缓冲）：过期直接降级，不浪费多次 RPC 才发现 401
    exp = token_expires_at()
    if exp is not None and exp - 60 <= int(time.time()):
        rp._log(log, "TopHap", "skipped",
                "token 已过期（预检）：需重跑 tools/tophap_oauth_setup.py 完成一次 OAuth 授权，已降级")
        return {"ok": False, "fields": [],
                "note": "TopHap token 已过期：需重跑授权脚本（浏览器点 Approve），已降级走原 pipeline"}
    address = (address or "").strip()
    if not address:
        return {"ok": False, "fields": [], "note": "地址为空"}
    try:
        fields, used = _enrich_chain(address, log)
    except MCPAuthError as e:
        return _degraded(log, f"{e}；需重跑 tools/tophap_oauth_setup.py 完成一次 "
                              "OAuth 授权（在已登录 TopHap 的浏览器里点 Approve）")
    except MCPError as e:
        return _degraded(log, str(e))
    rp._log(log, "TopHap", "ok", f"链路 {used}，映射 {len(fields)} 个字段（公共记录口径）")
    return {"ok": True, "fields": fields, "tool_used": used,
            "note": f"TopHap 公共记录 enrich：{len(fields)} 个字段"}


def token_expires_at() -> int | None:
    """TOPHAP_TOKEN_EXPIRES_AT：绝对 epoch 秒；缺失/非法返回 None（视为未知）。"""
    raw = os.environ.get("TOPHAP_TOKEN_EXPIRES_AT", "").strip()
    try:
        v = int(raw)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def is_token_expired() -> bool:
    exp = token_expires_at()
    return exp is not None and exp <= int(time.time())


def token_expires_in_hours() -> float | None:
    """token 剩余有效小时数；无过期时间戳时返回 None（未知）。

    供监控 cron 调用：< 24h 时写警告日志，提醒人工重跑 OAuth 授权。
    注意：不要自动重授权——那需要浏览器里点 Approve，必须人工触发。
    """
    exp = token_expires_at()
    if exp is None:
        return None
    return (exp - int(time.time())) / 3600.0


def token_expiry_report() -> dict:
    """给监控用的结构化报告：剩余小时数 + 状态 + 建议动作（中文）。"""
    hours = token_expires_in_hours()
    if hours is None:
        return {"hours_left": None, "status": "unknown",
                "action": "无 TOPHAP_TOKEN_EXPIRES_AT，无法判断有效期；建议重跑授权脚本"}
    if hours <= 0:
        return {"hours_left": round(hours, 1), "status": "expired",
                "action": "token 已过期：跑 tools/tophap_oauth_setup.py 完成一次 OAuth 授权"}
    if hours < 24:
        return {"hours_left": round(hours, 1), "status": "expiring_soon",
                "action": f"token 将在 {hours:.1f} 小时后过期：尽快重跑授权脚本（需浏览器点 Approve）"}
    return {"hours_left": round(hours, 1), "status": "ok",
            "action": "token 有效，无需操作"}


def status() -> dict:
    """数据源状态：开关 / 授权 / token 过期 / 连通性 / tool 面（供前端与授权后验证用）。"""
    st: dict = {"enabled": is_enabled(), "configured": is_configured(),
                "mcp_url": mcp_url(), "reachable": None,
                "tools": [], "core_ready": False, "token_expired": False, "note": ""}
    if not st["enabled"]:
        st["note"] = "未启用：设置 TOPHAP_ENABLED=1 开启"
        return st
    if not st["configured"]:
        st["note"] = ("未配置：跑 tools/tophap_oauth_setup.py 完成一次 OAuth 授权 "
                      "（浏览器里点 Approve），access token 进 .env")
        return st
    if is_token_expired():
        st["token_expired"] = True
        st["note"] = ("token 过期，需重跑 tools/tophap_oauth_setup.py 完成一次 OAuth 授权 "
                      "（在已登录 TopHap 的浏览器里点 Approve）")
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
    except MCPAuthError as e:
        st["reachable"] = False
        st["note"] = (f"{e}；需重跑 tools/tophap_oauth_setup.py 完成一次 OAuth 授权 "
                      "（在已登录 TopHap 的浏览器里点 Approve）")
    except MCPError as e:
        st["reachable"] = False
        st["note"] = str(e)
    return st
