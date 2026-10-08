"""产权穿透树（台账 2026-10-08 第 1 项，学自 Reonomy Top4）测试。

覆盖：名称分类 / NY DOS 查询（mock）/ 建树全链路 / 降级路径 /
待验证标注 / 联系方式只走 verified / 端点编排。
"""
import pytest

from app import ownership


# ---------- 名称分类 ----------

@pytest.mark.parametrize("name,expected", [
    ("JC SPLENDID LLC", "entity"),
    ("Acme Holdings Inc.", "entity"),
    ("123 Main Street Corp", "entity"),
    ("Smith Family Trust", "entity"),
    ("ABC Partners LP", "entity"),
    ("John Smith", "person"),
    ("JING CHEN", "person"),
    ("Maria Garcia Lopez", "person"),
    ("C T CORPORATION SYSTEM", "entity"),
    ("", "unknown"),
    ("12345", "unknown"),
])
def test_classify_owner_name(name, expected):
    kind, reason = ownership.classify_owner_name(name)
    assert kind == expected, f"{name!r} → {kind} ({reason})"


def test_infer_person_from_entity():
    assert ownership.infer_person_from_entity("CHEN WEI HOLDINGS LLC") == "Chen Wei"
    assert ownership.infer_person_from_entity("MIAO JIAHUI LLC") == "Miao Jiahui"
    # 通用商业词 / 数字 → 不推断
    assert ownership.infer_person_from_entity("MANHATTAN PROPERTY GROUP LLC") is None
    assert ownership.infer_person_from_entity("123 MAIN STREET HOLDINGS LLC") is None
    assert ownership.infer_person_from_entity("GOLDEN GATE CAPITAL LLC") is None


# ---------- NY DOS 查询（mock httpx） ----------

_DOS_ROW = {
    "dos_id": "6628404",
    "current_entity_name": "JC SPLENDID LLC",
    "entity_type": "DOMESTIC LIMITED LIABILITY COMPANY",
    "initial_dos_filing_date": "2022-10-31T00:00:00.000",
    "jurisdiction": "New York",
    "registered_agent_name": "jing chen",
    "registered_agent_address_1": "9 percheron lane",
    "registered_agent_address_2": "",
    "registered_agent_city": "ROSLYN HEIGHTS",
    "registered_agent_state": "NEW YORK",
    "registered_agent_zip": "11577",
    "chairman_name": "",
    "chairman_address_1": "",
    "chairman_address_2": "",
    "chairman_city": "",
    "chairman_state": "",
    "chairman_zip": "",
    "dos_process_name": "JC SPLENDID LLC",
    "dos_process_address_1": "450 w 44th street",
    "dos_process_address_2": "",
    "dos_process_city": "NEW YORK",
    "dos_process_state": "NY",
    "dos_process_zip": "10036",
}


class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _mock_dos(monkeypatch, rows):
    def _fake_get(url, params=None, timeout=None, headers=None):
        assert "data.ny.gov" in url
        return _FakeResp(200, rows)
    monkeypatch.setattr(ownership.httpx, "get", _fake_get)


def test_query_ny_dos_ok(monkeypatch):
    _mock_dos(monkeypatch, [_DOS_ROW])
    res = ownership.query_ny_dos("JC SPLENDID LLC")
    assert res["ok"] is True
    rec = res["records"][0]
    assert rec["dos_id"] == "6628404"
    assert rec["agent_name"] == "jing chen"
    assert "ROSLYN HEIGHTS" in rec["agent_address"]
    assert "450 w 44th street" in rec["process_address"]


def test_query_ny_dos_empty(monkeypatch):
    _mock_dos(monkeypatch, [])
    res = ownership.query_ny_dos("NONEXISTENT XYZ LLC")
    assert res["ok"] is False
    assert "未检索到" in res["note"]


def test_query_ny_dos_http_error(monkeypatch):
    monkeypatch.setattr(ownership.httpx, "get",
                        lambda *a, **k: _FakeResp(500, []))
    res = ownership.query_ny_dos("JC SPLENDID LLC")
    assert res["ok"] is False
    assert "HTTP 500" in res["note"]


def test_query_ny_dos_network_fail(monkeypatch):
    def _boom(*a, **k):
        raise ConnectionError("dns fail")
    monkeypatch.setattr(ownership.httpx, "get", _boom)
    res = ownership.query_ny_dos("JC SPLENDID LLC")
    assert res["ok"] is False
    assert "网络/超时" in res["note"]


# ---------- 建树 ----------

def _dos_fetch_ok(entity_name):
    return {"ok": True, "records": [{
        "dos_id": "6628404", "name": "JC SPLENDID LLC",
        "entity_type": "DOMESTIC LIMITED LIABILITY COMPANY",
        "filed": "2022-10-31", "jurisdiction": "New York",
        "agent_name": "jing chen",
        "agent_address": "9 percheron lane, ROSLYN HEIGHTS, NEW YORK, 11577",
        "ceo_name": "", "ceo_address": "",
        "process_name": "JC SPLENDID LLC",
        "process_address": "450 w 44th street, NEW YORK, NY, 10036",
    }], "note": "NY DOS 命中 1 条公开备案"}


_ADDR = "450 W 44th St, New York, NY 10036"


def test_build_tree_full_chain():
    t = ownership.build_tree(_ADDR, owner_name="JC SPLENDID LLC",
                             owner_source="NYC PLUTO 公开记录",
                             sos_fetch=_dos_fetch_ok)
    assert t["ok"] and t["owner_resolved"]
    by_id = {n["id"]: n for n in t["nodes"]}
    # L0/L1/L2 齐全
    assert by_id["prop"]["level"] == 0
    assert by_id["owner"]["level"] == 1 and by_id["owner"]["type"] == "entity"
    assert by_id["owner"]["confidence"] == "verified"
    assert "6628404" in by_id["owner"]["note"]  # DOS ID 回填
    agent = by_id["sos-agent"]
    assert agent["level"] == 2 and agent["type"] == "person"
    assert agent["confidence"] == "verified"
    assert agent["relation"] == "注册代理人"
    # 边
    rels = {(e["from"], e["to"]) for e in t["edges"]}
    assert ("prop", "owner") in rels and ("owner", "sos-agent") in rels
    # 联系方式：只 verified，且含代理人地址 + 送达地址
    assert t["contacts"], "应有 verified 联系方式"
    assert all(c["confidence"] == "verified" for c in t["contacts"])
    kinds = {c["kind"] for c in t["contacts"]}
    assert "registered_agent_address" in kinds
    assert "dos_process_address" in kinds
    # 无电话/邮箱编造
    assert not any(c["kind"] in ("phone", "email") for c in t["contacts"])


def test_build_tree_person_owner():
    t = ownership.build_tree(_ADDR, owner_name="John Smith",
                             owner_source="TopHap MCP",
                             sos_fetch=_dos_fetch_ok)
    by_id = {n["id"]: n for n in t["nodes"]}
    assert by_id["owner"]["type"] == "person"
    assert by_id["owner"]["confidence"] == "verified"
    # 自然人不再穿透 SoS
    assert "sos-agent" not in by_id
    assert any("自然人" in c for c in t["caveats"])


def test_build_tree_sos_fail_degrades():
    def _boom(name):
        raise TimeoutError("connect timeout")
    t = ownership.build_tree(_ADDR, owner_name="JC SPLENDID LLC",
                             owner_source="TopHap MCP", sos_fetch=_boom)
    assert t["owner_resolved"]
    by_id = {n["id"]: n for n in t["nodes"]}
    assert "sos-agent" not in by_id  # L2 缺失但整树不崩
    assert any("穿透链中断" in c for c in t["caveats"])
    assert t["sos"]["queried"] is True


def test_build_tree_no_owner():
    t = ownership.build_tree(_ADDR, owner_name=None)
    assert t["owner_resolved"] is False
    assert len(t["nodes"]) == 1  # 只有 L0
    assert any("未解析到契约持有人" in c for c in t["caveats"])


def test_build_tree_non_ny():
    t = ownership.build_tree("123 Main St, Tampa, FL 33602",
                             owner_name="SUNSHINE HOLDINGS LLC",
                             owner_source="TopHap MCP",
                             sos_fetch=_dos_fetch_ok)
    assert t["sos"]["queried"] is False
    assert any("FL" in c and "暂不支持" in c for c in t["caveats"])


def test_inferred_nodes_carry_verify_label():
    # 模糊匹配 → L2 降级为 inferred，display 带 [待验证]
    def _fuzzy(name):
        return {"ok": True, "records": [{
            "dos_id": "999", "name": "JC SPLENDID HOLDINGS LLC",
            "entity_type": "DOMESTIC LIMITED LIABILITY COMPANY",
            "filed": "2020-01-01", "jurisdiction": "New York",
            "agent_name": "Some Agent", "agent_address": "1 Main St, NY, NY, 10001",
            "ceo_name": "", "ceo_address": "",
            "process_name": "", "process_address": "",
        }], "note": "命中 1 条"}
    t = ownership.build_tree(_ADDR, owner_name="JC SPLENDID LLC",
                             owner_source="TopHap MCP", sos_fetch=_fuzzy)
    by_id = {n["id"]: n for n in t["nodes"]}
    agent = by_id["sos-agent"]
    assert agent["confidence"] == "inferred"
    assert agent["display"].endswith(ownership.NEED_VERIFY)


def test_inferred_person_guess_labeled():
    t = ownership.build_tree(_ADDR, owner_name="CHEN WEI HOLDINGS LLC",
                             owner_source="TopHap MCP", sos_fetch=_dos_fetch_ok)
    by_id = {n["id"]: n for n in t["nodes"]}
    guess = by_id.get("inferred-person")
    assert guess is not None
    assert guess["confidence"] == "inferred"
    assert guess["display"].endswith(ownership.NEED_VERIFY)
    assert any("CHEN WEI" in c.upper() or "Chen Wei" in c for c in t["caveats"])


def test_contacts_verified_only_filter():
    # 防御性：即使 sos_fetch 返回奇怪数据，contacts 也只留 verified
    t = ownership.build_tree(_ADDR, owner_name="JC SPLENDID LLC",
                             owner_source="TopHap MCP", sos_fetch=_dos_fetch_ok)
    for c in t["contacts"]:
        assert c["confidence"] == "verified"
        assert c["value"], "空联系方式不应出现"


# ---------- 端点编排 ----------

def test_tree_for_address_empty():
    t = ownership.tree_for_address("")
    assert t["ok"] is False
    assert "地址为空" in t["caveats"]


def test_tree_for_address_with_owner_skips_tophap(monkeypatch):
    # 显式 owner_name → 不调 TopHap（TopHap 挂掉也不影响）
    def _nope(*a, **k):
        raise AssertionError("should not call tophap")
    monkeypatch.setattr("app.tophap.enrich_address", _nope)
    t = ownership.tree_for_address(_ADDR, owner_name="JC SPLENDID LLC",
                                   sos_fetch=_dos_fetch_ok)
    assert t["owner_resolved"] is True
    assert any(n["id"] == "sos-agent" for n in t["nodes"])


def test_tree_for_address_tophap_owner(monkeypatch):
    fields = [
        {"key": "owner_name", "value": "JC SPLENDID LLC",
         "note": "TopHap 业主记录（公共记录）；公司持有"},
        {"key": "subject_state", "value": "NY"},
    ]
    monkeypatch.setattr("app.tophap.enrich_address",
                        lambda address, log=None: {"ok": True, "fields": fields,
                                                   "note": "ok"})
    t = ownership.tree_for_address(_ADDR, sos_fetch=_dos_fetch_ok)
    by_id = {n["id"]: n for n in t["nodes"]}
    assert by_id["owner"]["name"] == "JC SPLENDID LLC"
    assert by_id["owner"]["confidence"] == "verified"
    assert by_id["sos-agent"]["name"] == "jing chen"


def test_tree_for_address_tophap_down(monkeypatch):
    monkeypatch.setattr("app.tophap.enrich_address",
                        lambda address, log=None: {"ok": False, "fields": [],
                                                   "note": "TopHap token 已过期"})
    t = ownership.tree_for_address(_ADDR, sos_fetch=_dos_fetch_ok)
    assert t["owner_resolved"] is False
    assert any("TopHap" in c for c in t["caveats"])
