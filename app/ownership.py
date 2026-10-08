"""产权穿透树（台账 2026-10-08 第 1 项，学自 Reonomy Top4）。

intake 自动生成 LLC → 真人 → 可信度树：
  L0 标的物业 → L1 契约持有人（TopHap ownerName，公共记录 verified）
            → L2 穿透（NY DOS 公开备案：注册代理人 / CEO·负责人，verified）

铁律（本项验收口径）：
  1. 任一推断字段带 [待验证]（inferred 节点 display 强制后缀，caveats 逐条列明）；
  2. 联系方式只走 verified 来源——contacts 只收公开记录直出的地址，
     无公开来源的电话/邮箱一律不编、不出现；
  3. SoS 查询 best-effort：超时/不可达只记 caveat，不中断整树。

数据源：
  - TopHap MCP get_property_detail（ownerName / companyOwned / absenteeOwner），
    token 过期时降级为"未解析持有人"部分树；
  - NY DOS 公开备案（data.ny.gov Socrata，数据集 n9v6-gdp6 Active Corporations，
    含 LLC：DOS ID / 注册代理人 / CEO 姓名地址 / 送达地址），纯公开记录、无需鉴权。
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime

import httpx


def _sanitize_proxy_env() -> None:
    """与 app/research_pipeline._sanitize_proxy_env 同因：
    httpx 解析 no_proxy 里带方括号的 IPv6（如 [::1]）会抛 InvalidURL。
    进程内清洗 no_proxy（只删方括号条目，代理本身不动），保证出站可用。
    幂等，可重复执行。"""
    for k in ("no_proxy", "NO_PROXY"):
        v = os.environ.get(k, "")
        if "[" in v or "]" in v:
            clean = [part.strip() for part in v.split(",")
                     if "[" not in part and "]" not in part]
            os.environ[k] = ",".join(clean)


_sanitize_proxy_env()

NY_DOS_DATASET = "n9v6-gdp6"  # Active Corporations: Beginning 1800（含 LLC）
NY_DOS_URL = f"https://data.ny.gov/resource/{NY_DOS_DATASET}.json"
NY_DOS_LANDING = "https://data.ny.gov/d/n9v6-gdp6"
SOS_TIMEOUT = 15
NEED_VERIFY = "[待验证]"

# 实体后缀词（含标点变体，正则用）
ENTITY_SUFFIXES = (
    r"LLC|L\.L\.C\.|INC\.?|CORP\.?|CORPORATION|LP|L\.P\.|LLP|PLLC|LTD\.?|"
    r"CO\.?|COMPANY|TRUST|HOLDINGS?|PARTNERS?|PROPERTIES|PROPERTY|REALTY|"
    r"GROUP|CAPITAL|VENTURES?|ENTERPRISES?|ASSOCIATES?|FUND|INVESTMENTS?"
)
_ENTITY_RE = re.compile(rf"\b(?:{ENTITY_SUFFIXES})\b\.?", re.I)

# 通用商业词：穿透人名推断时，剩余 token 命中这些词则不做推断
GENERIC_WORDS = {
    "HOLDING", "HOLDINGS", "PROPERTY", "PROPERTIES", "INVESTMENT", "INVESTMENTS",
    "CAPITAL", "GROUP", "MANAGEMENT", "REALTY", "REAL", "ESTATE", "DEVELOPMENT",
    "DEVELOPERS", "DEVELOPER", "ASSET", "ASSETS", "ENTERPRISE", "ENTERPRISES",
    "VENTURE", "VENTURES", "PARTNER", "PARTNERS", "PARTNERSHIP", "FUND", "FUNDS",
    "TRUST", "ASSOCIATE", "ASSOCIATES", "SERVICE", "SERVICES", "COMPANY",
    "CORPORATION", "CORP", "LLC", "INC", "LTD", "LP", "LLP", "PLLC", "CO",
    "AND", "THE", "OF", "&",
    # 街道类型词：地址衍生命名（如 "123 MAIN STREET LLC"）不是人名
    "STREET", "ST", "AVENUE", "AVE", "ROAD", "RD", "BOULEVARD", "BLVD",
    "LANE", "LN", "DRIVE", "DR", "PLACE", "PL", "COURT", "CT", "WAY",
    "TERRACE", "CIRCLE", "PARKWAY", "HIGHWAY", "PLAZA",
}
_STATE_RE = re.compile(r",\s*([A-Z]{2})\s+\d{5}(?:-\d{4})?\b")
_PERSON_TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z\-']{1,}$")


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def classify_owner_name(name: str) -> tuple[str, str]:
    """持有人名称分类 → (entity|person|unknown, 依据说明)。"""
    n = (name or "").strip()
    if not n:
        return "unknown", "名称为空"
    if _ENTITY_RE.search(n):
        return "entity", "名称含实体后缀（LLC/INC/CORP 等）"
    toks = [t for t in re.split(r"[\s\-,.]+", n) if t]
    if (2 <= len(toks) <= 4 and all(_PERSON_TOKEN_RE.match(t) for t in toks)
            and not any(t.upper() in GENERIC_WORDS for t in toks)):
        return "person", "2-4 个字母 token、无实体后缀/通用商业词，形如自然人名"
    return "unknown", "既无实体后缀也不符合人名形态"


def _norm_name(n: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (n or "").upper())


def _significant_tokens(name: str) -> list[str]:
    """SoS 查询用有效 token：去后缀词/标点，长度≥2 的字母数字 token。"""
    toks = re.findall(r"[A-Z0-9]+", (name or "").upper())
    return [t for t in toks if t not in GENERIC_WORDS and len(t) >= 2]


# 常见姓名 token（拼音姓/常见名/西文常用名）：人名推断的召回门槛。
# 启发式名单，仅用于"疑似人名"形态判断，不作任何身份断言；
# token 须至少命中一个才推断，避免 "GOLDEN GATE" 这类普通词被当成人名。
NAME_TOKENS = {
    # 常见中文姓氏（拼音）
    "CHEN", "WANG", "LI", "ZHANG", "LIU", "HUANG", "ZHAO", "WU", "XU",
    "SUN", "MA", "ZHU", "HU", "GUO", "HE", "LUO", "ZHENG", "LIANG",
    "XIE", "HAN", "TANG", "FENG", "DONG", "XIAO", "CHENG", "CAO",
    "YUAN", "DENG", "JIANG", "CUI", "MIAO", "PENG", "ZENG", "SONG",
    "PAN", "TIAN", "DONG", "REN", "LU", "SU", "WAN", "FAN", "JIN",
    "WEI", "SHEN", "JIANG", "YAO", "JIANG", "CAI", "TAN", "DUAN",
    # 常见中文名字用字（拼音）
    "JIAHUI", "JING", "TAO", "XIN", "YAN", "CHAO", "JIE", "QIANG",
    "JUN", "LONG", "FEI", "YANG", "BIN", "HAO", "KAI", "MIN", "LEI",
    "FANG", "NA", "TING", "YI", "YU", "LIN", "FENG", "PENG",
    # 西文常用名
    "JOHN", "JAMES", "MICHAEL", "DAVID", "ROBERT", "WILLIAM", "RICHARD",
    "THOMAS", "DANIEL", "MATTHEW", "ANTHONY", "MARK", "PAUL", "GEORGE",
    "MARY", "MARIA", "JENNIFER", "LINDA", "ELIZABETH", "SARAH", "EMMA",
    "SOPHIA", "OLIVIA", "AVA", "MIA", "ISABELLA", "SMITH", "JOHNSON",
}


def _person_like_tokens(tokens: list[str]) -> bool:
    return (2 <= len(tokens) <= 3
            and all(t.isalpha() and len(t) >= 2 for t in tokens)
            and not any(t in GENERIC_WORDS for t in tokens)
            and any(t in NAME_TOKENS for t in tokens))


def infer_person_from_entity(entity_name: str) -> str | None:
    """实体名含人名推断：去后缀词后剩余 2-3 个纯字母 token，且至少一个命中
    常见姓名 token → 疑似人名。

    返回 Title-Case 人名；无则返回 None。调用方必须标 [待验证]。"""
    toks = [t for t in re.findall(r"[A-Z0-9]+", (entity_name or "").upper())
            if t not in GENERIC_WORDS]
    # 去掉纯实体后缀残留（如 "LLC" 已在 GENERIC_WORDS）
    toks = [t for t in toks if not t.isdigit()]
    if not _person_like_tokens(toks):
        return None
    return " ".join(t.capitalize() for t in toks)


def _fmt_addr(a1: str = "", a2: str = "", city: str = "",
              state: str = "", zipc: str = "") -> str:
    parts = [str(a1 or "").strip(), str(a2 or "").strip()]
    tail = ", ".join(p for p in (str(city or "").strip(),
                                 str(state or "").strip(),
                                 str(zipc or "").strip()) if p)
    head = " ".join(p for p in parts if p)
    return (head + (", " + tail if tail else "")).strip(" ,") if (head or tail) else ""


def query_ny_dos(entity_name: str, timeout: int = SOS_TIMEOUT) -> dict:
    """查 NY DOS 公开备案（Socrata n9v6-gdp6，无需鉴权）。

    返回 {"ok", "records": [...], "note"}；网络/超时/空结果一律 ok=False + 中文 note，
    不抛异常。record 字段：dos_id / name / entity_type / filed / jurisdiction /
    agent_name / agent_address / ceo_name / ceo_address / process_name / process_address。
    """
    toks = _significant_tokens(entity_name)
    if not toks:
        return {"ok": False, "records": [],
                "note": "实体名无有效查询 token，跳过 NY DOS 查询"}
    like = "%" + "%".join(toks[:3]) + "%"
    params = {
        "$select": ("dos_id,current_entity_name,entity_type,initial_dos_filing_date,"
                    "jurisdiction,registered_agent_name,registered_agent_address_1,"
                    "registered_agent_address_2,registered_agent_city,"
                    "registered_agent_state,registered_agent_zip,"
                    "chairman_name,chairman_address_1,chairman_address_2,"
                    "chairman_city,chairman_state,chairman_zip,"
                    "dos_process_name,dos_process_address_1,dos_process_address_2,"
                    "dos_process_city,dos_process_state,dos_process_zip"),
        "$where": "upper(current_entity_name) like '" + like.replace("'", "''") + "'",
        "$limit": "10",
    }
    try:
        r = httpx.get(NY_DOS_URL, params=params, timeout=timeout,
                      headers={"User-Agent": "dealdesk-ownership/1.0"})
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "records": [],
                "note": f"NY DOS 查询失败（网络/超时）：{str(e)[:100]}"}
    if r.status_code != 200:
        return {"ok": False, "records": [],
                "note": f"NY DOS 返回 HTTP {r.status_code}"}
    try:
        rows = r.json()
    except Exception:
        return {"ok": False, "records": [], "note": "NY DOS 返回非 JSON"}
    if not isinstance(rows, list) or not rows:
        return {"ok": False, "records": [],
                "note": f"NY DOS 未检索到“{entity_name}”（公开备案无此名）"}
    records = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        records.append({
            "dos_id": str(row.get("dos_id") or ""),
            "name": str(row.get("current_entity_name") or ""),
            "entity_type": str(row.get("entity_type") or ""),
            "filed": str(row.get("initial_dos_filing_date") or "")[:10],
            "jurisdiction": str(row.get("jurisdiction") or ""),
            "agent_name": str(row.get("registered_agent_name") or "").strip(),
            "agent_address": _fmt_addr(row.get("registered_agent_address_1"),
                                       row.get("registered_agent_address_2"),
                                       row.get("registered_agent_city"),
                                       row.get("registered_agent_state"),
                                       row.get("registered_agent_zip")),
            "ceo_name": str(row.get("chairman_name") or "").strip(),
            "ceo_address": _fmt_addr(row.get("chairman_address_1"),
                                     row.get("chairman_address_2"),
                                     row.get("chairman_city"),
                                     row.get("chairman_state"),
                                     row.get("chairman_zip")),
            "process_name": str(row.get("dos_process_name") or "").strip(),
            "process_address": _fmt_addr(row.get("dos_process_address_1"),
                                         row.get("dos_process_address_2"),
                                         row.get("dos_process_city"),
                                         row.get("dos_process_state"),
                                         row.get("dos_process_zip")),
        })
    return {"ok": True, "records": records,
            "note": f"NY DOS 命中 {len(records)} 条公开备案"}


def _pick_best_record(records: list[dict], entity_name: str) -> tuple[dict, str, str]:
    """选最匹配的一条备案 → (record, match_kind, note)。

    match_kind: exact（归一化全等）| fuzzy（包含/首条）。"""
    want = _norm_name(entity_name)
    for rec in records:
        if _norm_name(rec.get("name")) == want:
            return rec, "exact", "NY DOS 备案名与持有人名归一化全等"
    for rec in records:
        rn = _norm_name(rec.get("name"))
        if want in rn or rn in want:
            return rec, "fuzzy", f"NY DOS {len(records)} 条命中、无全等名，取包含匹配“{rec.get('name')}”"
    rec = records[0]
    return rec, "fuzzy", f"NY DOS {len(records)} 条命中、无全等/包含匹配，取首条“{rec.get('name')}”"


def _infer_state(address: str) -> str:
    m = _STATE_RE.search(address or "")
    return m.group(1) if m else ""


def _src(source: str, note: str = "", url: str = "") -> dict:
    return {"source": source, "url": url, "fetched_at": now_str(), "note": note}


def _node(nid: str, level: int, ntype: str, name: str, confidence: str,
          relation: str, sources: list[dict], note: str = "") -> dict:
    display = name + (f" {NEED_VERIFY}" if confidence == "inferred" else "")
    return {"id": nid, "level": level, "type": ntype, "name": name,
            "display": display, "confidence": confidence, "relation": relation,
            "sources": sources, "note": note}


def build_tree(address: str, owner_name: str | None = None,
               owner_source: str = "", owner_note: str = "",
               subject_state: str | None = None,
               sos_fetch=None) -> dict:
    """构建产权穿透树（纯函数；sos_fetch 可注入 mock，默认走真实 NY DOS）。

    owner_name 为空 → 只返回 L0 物业节点 + 未解析 caveat（owner_resolved=False）。
    """
    sos_fetch = sos_fetch or query_ny_dos
    state = (subject_state or _infer_state(address or "") or "").upper()
    nodes, edges, contacts, caveats = [], [], [], []

    nodes.append(_node("prop", 0, "property", (address or "").strip(), "verified",
                       "标的物业", [_src("请求地址", "查询起点")],
                       note="穿透起点"))

    owner = (owner_name or "").strip()
    if not owner:
        caveats.append("未解析到契约持有人（TopHap 不可用或无记录）："
                       "可传入 owner_name 手动指定，或 TopHap 恢复后重试")
        return {"ok": True, "address": (address or "").strip(),
                "owner_resolved": False, "nodes": nodes, "edges": edges,
                "contacts": contacts, "caveats": caveats,
                "sos": {"queried": False, "state": state, "hits": 0,
                        "note": "持有人未解析，跳过 SoS 查询"},
                "generated_at": now_str()}

    kind, kind_reason = classify_owner_name(owner)
    owner_verified = owner_source in ("TopHap MCP", "NYC PLUTO 公开记录")
    owner_conf = "verified" if owner_verified else "inferred"
    owner_sources = [_src(owner_source or "人工提供",
                           (owner_note or "契约持有人（公共记录直出）"
                            if owner_verified else "人工提供，未经公开记录交叉验证"))]
    rel = {"entity": "契约持有人（实体）", "person": "契约持有人（自然人）",
           "unknown": "契约持有人（类型未明）"}[kind]
    owner_note_full = kind_reason
    if kind == "person":
        owner_note_full += "；自然人真人身份以姓名为准，深层身份（是否为本人）需人工核验"
        caveats.append(f"持有人为自然人“{owner}”：姓名来自公开记录"
                       f"{NEED_VERIFY}（同名者区分需人工）")
    nodes.append(_node("owner", 1, kind, owner, owner_conf, rel,
                       owner_sources, note=owner_note_full))
    edges.append({"from": "prop", "to": "owner", "relation": "持有"})

    sos_info = {"queried": False, "state": state, "hits": 0, "note": ""}
    if kind == "entity" and state == "NY":
        try:
            res = sos_fetch(owner)
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "records": [],
                   "note": f"NY DOS 查询异常：{str(e)[:100]}"}
        sos_info["queried"] = True
        if not res.get("ok"):
            sos_info["note"] = res.get("note", "NY DOS 查询失败")
            caveats.append(f"{sos_info['note']}：穿透链中断于 L1，"
                           f"需人工查 NY DOS 公开备案 {NEED_VERIFY}")
        else:
            records = res["records"]
            sos_info["hits"] = len(records)
            rec, match_kind, match_note = _pick_best_record(records, owner)
            sos_info["note"] = match_note
            sos_info["dos_id"] = rec.get("dos_id")
            l2_conf = "verified" if match_kind == "exact" else "inferred"
            if match_kind != "exact":
                caveats.append(f"{match_note} {NEED_VERIFY}："
                               "L2 节点基于模糊匹配，需人工确认是否为同一实体")
            # 备案信息回填到 L1 节点
            extra = (f"；NY DOS 备案：{rec['entity_type']}，DOS ID {rec['dos_id']}，"
                     f"成立 {rec['filed'] or '未知'}，辖区 {rec['jurisdiction'] or '未知'}")
            nodes[1]["note"] += extra
            nodes[1]["sources"].append(
                _src("NY DOS 公开备案", f"DOS ID {rec['dos_id']}",
                     url=NY_DOS_LANDING))
            # L2a 注册代理人
            if rec.get("agent_name"):
                ak, ak_reason = classify_owner_name(rec["agent_name"])
                arel = {"person": "注册代理人", "entity": "注册代理机构",
                        "unknown": "注册代理（类型未明）"}[ak]
                nodes.append(_node("sos-agent", 2, ak, rec["agent_name"], l2_conf,
                                   arel, [_src("NY DOS 公开备案",
                                               f"备案实体“{rec['name']}”的注册代理人",
                                               url=NY_DOS_LANDING)],
                                   note=ak_reason))
                edges.append({"from": "owner", "to": "sos-agent",
                              "relation": "注册代理"})
                if rec.get("agent_address"):
                    contacts.append({"kind": "registered_agent_address",
                                     "value": rec["agent_address"],
                                     "confidence": "verified",
                                     "source": "NY DOS 公开备案",
                                     "note": f"“{rec['agent_name']}”备案地址"})
            # L2b CEO/负责人
            if rec.get("ceo_name"):
                ck, ck_reason = classify_owner_name(rec["ceo_name"])
                crel = {"person": "CEO/负责人（备案）", "entity": "负责人实体",
                        "unknown": "负责人（类型未明）"}[ck]
                nodes.append(_node("sos-ceo", 2, ck, rec["ceo_name"], l2_conf,
                                   crel, [_src("NY DOS 公开备案",
                                               f"备案实体“{rec['name']}”的 CEO/负责人",
                                               url=NY_DOS_LANDING)],
                                   note=ck_reason))
                edges.append({"from": "owner", "to": "sos-ceo",
                              "relation": "备案负责人"})
                if rec.get("ceo_address"):
                    contacts.append({"kind": "ceo_address",
                                     "value": rec["ceo_address"],
                                     "confidence": "verified",
                                     "source": "NY DOS 公开备案",
                                     "note": f"“{rec['ceo_name']}”备案地址"})
            # 送达地址 → verified 联系方式
            if rec.get("process_address"):
                contacts.append({"kind": "dos_process_address",
                                 "value": rec["process_address"],
                                 "confidence": "verified",
                                 "source": "NY DOS 公开备案",
                                 "note": f"法律文书送达地址（DOS Process，收件 {rec['process_name'] or '—'}）"})
            # 人名推断（仅线索，强制待验证）
            person_guess = infer_person_from_entity(owner)
            if person_guess:
                nodes.append(_node("inferred-person", 2, "person", person_guess,
                                   "inferred", "疑似实际控制人（名含人名推断）",
                                   [_src("名称形态推断",
                                         "实体名去后缀后剩余疑似人名 token，未经任何公开记录验证")],
                                   note="纯线索：实体名含疑似人名，未经验证，不可作为联系/决策依据"))
                edges.append({"from": "owner", "to": "inferred-person",
                              "relation": "疑似控制"})
                caveats.append(f"实体名“{owner}”含疑似人名“{person_guess}”"
                               f"{NEED_VERIFY}：未经公开记录验证，仅供线索参考")
    elif kind == "entity" and state and state != "NY":
        sos_info["note"] = (f"该州（{state}）SoS 自动查询暂不支持（当前仅 NY）："
                            "需人工核验")
        caveats.append(f"{state} 州 SoS 自动查询暂不支持 {NEED_VERIFY}："
                       "穿透链中断于 L1，需人工查该州 SoS 公开备案")
    elif kind == "entity":
        sos_info["note"] = "州未知，跳过 SoS 查询"
        caveats.append(f"物业所在州未知，跳过 SoS 查询 {NEED_VERIFY}")

    # 联系方式只走 verified 来源：防御性过滤（理论上 contacts 只收 verified）
    contacts = [c for c in contacts if c.get("confidence") == "verified"]
    if kind == "entity" and not contacts and sos_info.get("queried") and sos_info.get("hits"):
        caveats.append("NY DOS 备案未提供可用地址：暂无 verified 联系方式，"
                       "不编造电话/邮箱")

    return {"ok": True, "address": (address or "").strip(),
            "owner_resolved": True, "nodes": nodes, "edges": edges,
            "contacts": contacts, "caveats": caveats, "sos": sos_info,
            "generated_at": now_str()}


def tree_for_address(address: str, owner_name: str | None = None,
                     owner_source: str = "", sos_fetch=None) -> dict:
    """端点编排：owner_name 未给时走 TopHap 解析持有人，再 build_tree。

    TopHap 不可用（未启用/无 token/token 过期/调用失败）→ 返回部分树
    （L0 + 未解析），owner_resolved=False，不抛异常。"""
    address = (address or "").strip()
    if not address:
        return {"ok": False, "address": "", "owner_resolved": False,
                "nodes": [], "edges": [], "contacts": [],
                "caveats": ["地址为空"], "sos": {"queried": False},
                "generated_at": now_str()}
    if owner_name:
        return build_tree(address, owner_name=owner_name,
                          owner_source=owner_source or "人工提供",
                          owner_note="", subject_state=None,
                          sos_fetch=sos_fetch)
    # 走 TopHap 拿 ownerName（延迟 import，避免循环依赖）
    from . import tophap as _tophap
    try:
        en = _tophap.enrich_address(address, log=[])
    except Exception as e:  # noqa: BLE001
        en = {"ok": False, "fields": [], "note": f"TopHap 调用异常：{str(e)[:100]}"}
    owner, state, note = "", "", en.get("note", "")
    if en.get("ok"):
        by_key = {f.get("key"): f for f in en.get("fields", [])
                  if isinstance(f, dict)}
        of = by_key.get("owner_name") or {}
        owner = str(of.get("value") or "")
        st = by_key.get("subject_state") or {}
        state = str(st.get("value") or "")
        flags = []
        if "公司持有" in str(of.get("note") or ""):
            flags.append("公司持有")
        if "absentee" in str(of.get("note") or "").lower():
            flags.append("absentee owner")
        note = ("TopHap 业主记录（公共记录）"
                + ("；" + "、".join(flags) if flags else ""))
    if not owner:
        tree = build_tree(address, owner_name=None,
                          subject_state=state or None, sos_fetch=sos_fetch)
        tree["caveats"].insert(0, f"TopHap 未解析到持有人：{note}")
        return tree
    return build_tree(address, owner_name=owner, owner_source="TopHap MCP",
                      owner_note=note, subject_state=state or None,
                      sos_fetch=sos_fetch)
