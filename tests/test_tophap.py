"""TopHap 适配器 v2 测试：实测 9 tools 链路 + OAuth/refresh + 降级。

全部 fixture/模拟：不调用真实公网、不读真实 token、不写真实 .env/vault。
测试铁律：跑前已删 dealdesk.db 隔离。"""
import importlib.util
import json
from pathlib import Path

import pytest

from app import research_pipeline as rp
from app import tophap

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def env_clean(monkeypatch):
    monkeypatch.setenv("TOPHAP_ENABLED", "0")
    for k in ("TOPHAP_ACCESS_TOKEN", "TOPHAP_TOKEN",
              "TOPHAP_TOKEN_ENDPOINT", "TOPHAP_CLIENT_ID"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TOPHAP_MCP_URL", "https://mcp.tophap.local/api/mcp")


# ---------- fixtures ----------

TOOLS9 = ["find_property_by_address", "search_properties", "get_property_detail",
          "get_property_insights", "get_property_cma", "get_building_units",
          "search_schools", "get_school_detail", "lookup_area_boundary"]

DETAIL = {
    "propertyType": "Single Family", "parcelId": "1-234-56",
    "bedrooms": 4, "bathrooms": 2.5, "livingAreaSqft": 2800,
    "lotSizeSqft": 6000, "yearBuilt": 1998,
}
INSIGHTS = {
    "estimatedValue": {"value": 500000, "low": 450000, "high": 550000},
    "tax": {"annualAmount": 9000, "assessedValue": 480000},
    "salesHistory": [{"date": "2022-05-01", "type": "sale", "price": 440000}],
    "loans": [{"amount": 350000, "rate": 7.5, "date": "2023-03-01",
               "lender": "Bank X", "status": "open"}],
    "ownershipHistory": [{"owner": "Jane Doe", "from": "2015", "to": ""}],
    "rentEstimate": {"monthly": 3200},
}
CMA = {"comparables": [
    {"address": "124 Main St", "price": 495000, "saleDate": "2026-06-01",
     "beds": 4, "baths": 2, "sqft": 2700, "distance": 0.3},
    {"address": "130 Main St", "price": 510000, "saleDate": "2026-04-15",
     "beds": 4, "baths": 2.5, "sqft": 2900, "distance": 0.5},
]}
SCHOOLS = {"schools": [{"name": "PS 101", "rating": 8, "distance": 0.4}]}


class FakeResp:
    def __init__(self, body, status=200, ctype="application/json"):
        self.status_code = status
        self.headers = {"content-type": ctype}
        self._body = body

    @property
    def text(self):
        return self._body if isinstance(self._body, str) else json.dumps(self._body)

    def json(self):
        return json.loads(self.text)


def _result(payload):
    return {"jsonrpc": "2.0", "id": 3,
            "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}


def make_chain_post(calls, tools9=TOOLS9, fail_first_call_401=False,
                    token_resp=None):
    state = {"n_calls": 0}

    def fake_post(url, json=None, headers=None, timeout=None, data=None):  # noqa: A002
        body = json or {}
        method = body.get("method")
        if url == "https://auth.tophap.local/token":
            calls.append(("token-endpoint", None))
            return FakeResp(token_resp or {"access_token": "new-at"})
        if method == "initialize":
            calls.append(("rpc", "initialize"))
            return FakeResp({"jsonrpc": "2.0", "id": 1, "result": {}})
        if method == "tools/list":
            calls.append(("rpc", "tools/list"))
            return FakeResp({"jsonrpc": "2.0", "id": 2, "result": {
                "tools": [{"name": n} for n in tools9]}})
        if method == "tools/call":
            name = (body.get("params") or {}).get("name")
            state["n_calls"] += 1
            if fail_first_call_401 and state["n_calls"] == 1:
                calls.append(("rpc", f"tools/call:{name}:401"))
                return FakeResp({}, status=401)
            calls.append(("rpc", f"tools/call:{name}"))
            payload = {"find_property_by_address": {"property_id": "th_123",
                                                    "matched_address": "123 Main St"},
                       "get_property_detail": DETAIL,
                       "get_property_insights": INSIGHTS,
                       "get_property_cma": CMA,
                       "search_schools": SCHOOLS}.get(name, {})
            return FakeResp(_result(payload))
        if method == "notifications/initialized":
            return FakeResp({})
        return FakeResp({"jsonrpc": "2.0", "id": 0,
                         "error": {"message": "unknown"}}, status=400)

    return fake_post


def _enable(monkeypatch, calls, **kw):
    monkeypatch.setenv("TOPHAP_ENABLED", "1")
    monkeypatch.setenv("TOPHAP_ACCESS_TOKEN", "fake-at")
    monkeypatch.setattr(tophap.httpx, "post", make_chain_post(calls, **kw))
    monkeypatch.setattr(tophap, "write_dotenv",
                        lambda updates: calls.append(("dotenv", sorted(updates))))


# ---------- 开关与降级 ----------

def test_disabled_never_calls_http(monkeypatch):
    calls = []
    monkeypatch.setattr(tophap.httpx, "post", make_chain_post(calls))
    out = tophap.enrich_address("123 Main St, Tampa, FL 33602")
    assert out["ok"] is False and out["fields"] == []
    assert calls == []


def test_missing_token_points_to_oauth_script(monkeypatch):
    monkeypatch.setenv("TOPHAP_ENABLED", "1")
    calls = []
    monkeypatch.setattr(tophap.httpx, "post", make_chain_post(calls))
    out = tophap.enrich_address("123 Main St, Tampa, FL 33602")
    assert out["ok"] is False
    assert "tophap_oauth_setup.py" in out["note"]
    assert calls == []


# ---------- 主链路 ----------

def test_chain_calls_real_tools_in_order(monkeypatch):
    calls = []
    _enable(monkeypatch, calls)
    out = tophap.enrich_address("123 Main St, Tampa, FL 33602")
    assert out["ok"] is True
    seq = [c[1] for c in calls if c[0] == "rpc"]
    assert seq[0] == "initialize" and seq[1] == "tools/list"
    tool_seq = [c.split("tools/call:")[1] for c in seq if c.startswith("tools/call")]
    assert tool_seq[0] == "find_property_by_address"
    assert "get_property_detail" in tool_seq
    assert "get_property_insights" in tool_seq
    assert "get_property_cma" in tool_seq
    assert "find_property_by_address" in out["tool_used"]


def test_detail_mapping(monkeypatch):
    calls = []
    _enable(monkeypatch, calls)
    out = tophap.enrich_address("123 Main St, Tampa, FL 33602")
    by_key = {f["key"]: f for f in out["fields"]}
    assert by_key["building_sf"]["value"] == 2800
    assert by_key["lot_sf"]["value"] == 6000
    assert by_key["year_built"]["value"] == 1998
    assert by_key["beds"]["value"] == 4
    assert by_key["parcel_id"]["value"] == "1-234-56"
    assert by_key["building_sf"]["confidence"] == "高"


def test_insights_mapping(monkeypatch):
    calls = []
    _enable(monkeypatch, calls)
    out = tophap.enrich_address("123 Main St, Tampa, FL 33602")
    by_key = {f["key"]: f for f in out["fields"]}
    assert by_key["tophap_value"]["value"] == 500000
    assert by_key["tophap_value"]["confidence"] == "中"
    assert by_key["tophap_value_range"]["value"] == [450000.0, 550000.0]
    assert by_key["taxes_annual"]["value"] == 9000
    assert by_key["tax_assessed_value"]["value"] == 480000
    assert by_key["last_sale_price"]["value"] == 440000
    assert by_key["open_loans"]["confidence"] == "高"
    assert "subject-to" in by_key["open_loans"]["note"]
    assert by_key["monthly_rent"]["confidence"] == "低"


def test_cma_mapping(monkeypatch):
    calls = []
    _enable(monkeypatch, calls)
    out = tophap.enrich_address("123 Main St, Tampa, FL 33602")
    by_key = {f["key"]: f for f in out["fields"]}
    comps = by_key["tophap_comps"]
    assert comps["confidence"] == "中"
    assert len(comps["value"]) == 2
    assert comps["value"][0]["address"] == "124 Main St"
    assert comps["value"][0]["price"] == 495000
    assert "recorded sales" in comps["note"]


def test_schools_best_effort(monkeypatch):
    calls = []
    _enable(monkeypatch, calls)
    out = tophap.enrich_address("123 Main St, Tampa, FL 33602")
    by_key = {f["key"]: f for f in out["fields"]}
    assert by_key["tophap_schools"]["value"][0]["name"] == "PS 101"


def test_all_fields_carry_provenance(monkeypatch):
    calls = []
    _enable(monkeypatch, calls)
    out = tophap.enrich_address("123 Main St, Tampa, FL 33602")
    assert out["fields"]
    for f in out["fields"]:
        assert f["source"] == "TopHap MCP", f["key"]
        assert f["fetched_at"], f["key"]
        assert f["confidence"] in ("高", "中", "低"), f["key"]
        assert f["seller_claimed"] is False, f["key"]


def test_missing_cma_tool_skips_gracefully(monkeypatch):
    calls = []
    tools8 = [t for t in TOOLS9 if t != "get_property_cma"]
    _enable(monkeypatch, calls, tools9=tools8)
    out = tophap.enrich_address("123 Main St, Tampa, FL 33602")
    assert out["ok"] is True
    assert "tophap_comps" not in {f["key"] for f in out["fields"]}
    assert "get_property_cma" not in out["tool_used"]


def test_find_without_property_id_degrades(monkeypatch):
    calls = []
    monkeypatch.setenv("TOPHAP_ENABLED", "1")
    monkeypatch.setenv("TOPHAP_ACCESS_TOKEN", "fake-at")

    def fake_post(url, json=None, headers=None, timeout=None, data=None):  # noqa: A002
        body = json or {}
        if body.get("method") == "tools/list":
            return FakeResp({"jsonrpc": "2.0", "id": 2, "result": {
                "tools": [{"name": n} for n in TOOLS9]}})
        if body.get("method") == "tools/call":
            return FakeResp(_result({"candidates": []}))
        return FakeResp({"jsonrpc": "2.0", "id": 1, "result": {}})
    monkeypatch.setattr(tophap.httpx, "post", fake_post)
    out = tophap.enrich_address("123 Main St, Tampa, FL 33602")
    assert out["ok"] is False and "property_id" in out["note"]


# ---------- 401 → refresh → 重试 / 降级 ----------

def test_401_triggers_refresh_and_retry(monkeypatch):
    calls = []
    _enable(monkeypatch, calls, fail_first_call_401=True)
    monkeypatch.setenv("TOPHAP_TOKEN_ENDPOINT", "https://auth.tophap.local/token")
    monkeypatch.setenv("TOPHAP_CLIENT_ID", "cid-1")
    monkeypatch.setattr(tophap, "vault_read_secret",
                        lambda name: "rt-123" if name == "tophap_refresh_token" else None)
    monkeypatch.setattr(tophap, "vault_store_secret", lambda n, v: True)
    out = tophap.enrich_address("123 Main St, Tampa, FL 33602")
    assert out["ok"] is True
    assert ("token-endpoint", None) in calls
    assert ("dotenv", ["TOPHAP_ACCESS_TOKEN"]) in calls
    by_key = {f["key"]: f for f in out["fields"]}
    assert by_key["tophap_value"]["value"] == 500000


def test_401_without_refresh_degrades_with_reauth_note(monkeypatch):
    calls = []
    _enable(monkeypatch, calls, fail_first_call_401=True)
    monkeypatch.setattr(tophap, "vault_read_secret", lambda name: None)
    out = tophap.enrich_address("123 Main St, Tampa, FL 33602")
    assert out["ok"] is False
    assert "tophap_oauth_setup.py" in out["note"]


def test_try_refresh_rejected_returns_false(monkeypatch):
    monkeypatch.setenv("TOPHAP_TOKEN_ENDPOINT", "https://auth.tophap.local/token")
    monkeypatch.setenv("TOPHAP_CLIENT_ID", "cid-1")
    monkeypatch.setattr(tophap, "vault_read_secret", lambda name: "rt-bad")
    monkeypatch.setattr(tophap.httpx, "post",
                        lambda *a, **k: FakeResp({"error": "invalid_grant"}, status=400))
    assert tophap.try_refresh() is False


# ---------- vault fail-safe ----------

def test_vault_helpers_fail_safe(monkeypatch):
    def boom(*a, **k):
        raise OSError("no vault")
    monkeypatch.setattr(tophap.subprocess, "run", boom)
    assert tophap.vault_store_secret("x", "y") is False
    assert tophap.vault_read_secret("x") is None


def test_vault_read_nonzero_rc_returns_none(monkeypatch):
    class R:
        returncode = 1
        stdout = b""
    monkeypatch.setattr(tophap.subprocess, "run", lambda *a, **k: R())
    assert tophap.vault_read_secret("x") is None


# ---------- pipeline 集成 ----------

def test_pipeline_run_includes_tophap_when_enabled(monkeypatch):
    monkeypatch.setenv("TOPHAP_ENABLED", "1")
    monkeypatch.setenv("TOPHAP_ACCESS_TOKEN", "t")
    monkeypatch.setattr(rp, "ddg_search", lambda q, log, max_results=8: [])
    th_fields = [{"key": "tax_assessed_value", "label": "计税估值", "value": 480000,
                  "display": "$480,000", "source": "TopHap MCP", "source_url": "",
                  "fetched_at": "t", "confidence": "高", "seller_claimed": False,
                  "claim_label": "", "note": "公共记录", "status": "filled"}]
    monkeypatch.setattr(tophap, "enrich_address",
                        lambda address, log=None: {"ok": True, "fields": th_fields,
                                                   "tool_used": "find_property_by_address",
                                                   "note": "ok"})
    d = rp.run_address_pipeline("123 Main St, Tampa, FL 33602")
    by_key = {f["key"]: f for f in d["fields"]}
    assert by_key["tax_assessed_value"]["source"] == "TopHap MCP"
    assert by_key["tophap_enrich_status"]["status"] == "filled"


def test_pipeline_run_degrades_when_tophap_off(monkeypatch):
    monkeypatch.setattr(rp, "ddg_search", lambda q, log, max_results=8: [])

    def fake_fetch(url, log):
        rp._log(log, "抓取", "blocked", "HTTP 403")
        return {"ok": False, "note": "blocked", "blocked": True}
    monkeypatch.setattr(rp, "fetch_page", fake_fetch)
    d = rp.run_address_pipeline("123 Main St, Tampa, FL 33602")
    assert d["fields"] == []
    assert "tophap_enrich_status" not in {f["key"] for f in d["fields"]}
    assert len(d["manual_needed"]) > 0


def test_merge_keeps_ddg_high_and_adds_tophap_unique(monkeypatch):
    calls = []
    _enable(monkeypatch, calls)
    th = tophap.enrich_address("123 Main St, Tampa, FL 33602")
    ddg = [{"key": "building_sf", "label": "建筑面积 SF", "value": 2100,
            "display": "2100 SF", "source": "county 网页", "source_url": "",
            "fetched_at": "t", "confidence": "高", "seller_claimed": False,
            "claim_label": "", "note": "", "status": "filled"}]
    merged = rp.merge_fields(ddg + th["fields"])
    by_key = {f["key"]: f for f in merged}
    assert by_key["building_sf"]["value"] == 2100  # 同可信度 tie，独立网页在前
    assert "open_loans" in by_key  # TopHap 独有字段并入


# ---------- status ----------

def test_status_disabled(monkeypatch):
    st = tophap.status()
    assert st["enabled"] is False and "TOPHAP_ENABLED" in st["note"]


def test_status_missing_token(monkeypatch):
    monkeypatch.setenv("TOPHAP_ENABLED", "1")
    st = tophap.status()
    assert st["enabled"] is True and st["configured"] is False
    assert "tophap_oauth_setup.py" in st["note"]


def test_status_core_ready(monkeypatch):
    calls = []
    _enable(monkeypatch, calls)
    st = tophap.status()
    assert st["reachable"] is True and st["core_ready"] is True
    assert "get_property_cma" in st["tools"]


def test_status_reports_missing_core_tool(monkeypatch):
    calls = []
    tools8 = [t for t in TOOLS9 if t != "get_property_cma"]
    _enable(monkeypatch, calls, tools9=tools8)
    st = tophap.status()
    assert st["reachable"] is True and st["core_ready"] is False
    assert "get_property_cma" in st["note"]


# ---------- OAuth 脚本纯函数 ----------

def _load_oauth_script():
    spec = importlib.util.spec_from_file_location(
        "tophap_oauth_setup", str(REPO / "tools" / "tophap_oauth_setup.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_oauth_parse_www_authenticate():
    mod = _load_oauth_script()
    h = ('Bearer resource_metadata="https://mcp.tophap.com/'
         '.well-known/oauth-protected-resource", error="invalid_token"')
    assert mod.parse_www_authenticate(h) == (
        "https://mcp.tophap.com/.well-known/oauth-protected-resource")
    assert mod.parse_www_authenticate("") is None


def test_oauth_pkce_pair_verifies():
    import base64
    import hashlib
    mod = _load_oauth_script()
    verifier, challenge = mod.pkce_pair()
    expect = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expect and len(verifier) >= 43


def test_oauth_build_authorize_url():
    mod = _load_oauth_script()
    url = mod.build_authorize_url(
        {"authorization_endpoint": "https://auth.tophap.com/authorize"},
        "cid-1", "CHAL", "STATE1", scope="openid")
    assert url.startswith("https://auth.tophap.com/authorize?")
    assert "code_challenge=CHAL" in url and "code_challenge_method=S256" in url
    assert "client_id=cid-1" in url and "state=STATE1" in url


def test_write_dotenv_roundtrip(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("A=1\nTOPHAP_ACCESS_TOKEN=old\n")
    monkeypatch.setattr(tophap, "dotenv_path", lambda: env_file)
    tophap.write_dotenv({"TOPHAP_ACCESS_TOKEN": "new", "TOPHAP_CLIENT_ID": "c"})
    content = env_file.read_text()
    assert "A=1" in content and "TOPHAP_ACCESS_TOKEN=new" in content
    assert "old" not in content and "TOPHAP_CLIENT_ID=c" in content
