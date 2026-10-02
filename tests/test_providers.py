"""多数据源 fallback 链测试：TopHap → RentCast → 公开网页 → Census 保底。"""
import app.providers as pv
import app.research_pipeline as rp


def _field(key, value, source="Test"):
    return {"key": key, "label": key, "value": value, "display": str(value),
            "source": source, "source_url": "", "fetched_at": "t",
            "confidence": "高", "seller_claimed": False, "claim_label": "",
            "note": "", "status": "filled"}


class _BoomTophap(pv.TophapProvider):
    """TopHap 直接抛异常：验证链能接住并让 RentCast 接管。"""
    name = "TopHap MCP"

    def available(self):
        return True, ""

    def enrich(self, address, log):
        raise RuntimeError("simulated tophap boom")


class _FakeRentcast(pv.RentcastProvider):
    name = "RentCast"

    def available(self):
        return True, ""

    def enrich(self, address, log):
        return {"ok": True,
                "fields": [_field("beds", 3, "RentCast"),
                           _field("taxes_annual", 5000, "RentCast")],
                "provider": self.name, "note": "fake rentcast ok"}


class _FailProvider(pv.BaseProvider):
    name = "FakeFail"

    def available(self):
        return True, ""

    def enrich(self, address, log):
        return {"ok": False, "fields": [], "provider": self.name,
                "note": "上游挂了"}


def test_chain_rentcast_takes_over_when_tophap_raises():
    """TopHap 抛异常 → RentCast 接管成为 primary，不崩。"""
    chain = pv.run_chain("123 Main St, Tampa, FL 33602",
                         providers=[_BoomTophap(), _FakeRentcast()])
    assert chain["ok"] is True
    assert chain["primary_provider"] == "RentCast"
    by_key = {f["key"]: f for f in chain["fields"]}
    assert by_key["beds"]["value"] == 3
    assert by_key["beds"]["source"] == "RentCast"
    # TopHap 的失败被记录在案
    statuses = {r["provider"]: r["status"] for r in chain["provider_results"]}
    assert statuses["TopHap MCP"] == "failed"


def test_chain_skips_rentcast_without_key(monkeypatch):
    """无 RENTCAST_API_KEY → available() False，链跳过不报错。"""
    monkeypatch.delenv("RENTCAST_API_KEY", raising=False)
    # 确保 .env loader 也没写进去（测试环境）
    p = pv.RentcastProvider()
    ok, reason = p.available()
    assert ok is False
    assert "RENTCAST_API_KEY" in reason
    # 链中跳过：diagnostics 提到 RentCast，但整体不抛异常
    chain = pv.run_chain("123 Main St, Tampa, FL 33602", providers=[p])
    assert chain["ok"] is False
    assert chain["provider_results"][0]["status"] == "skipped"
    assert "RentCast" in chain["diagnostics"]


def test_chain_census_fallback_when_all_fail(monkeypatch):
    """上游全挂 → Census 保底仍有输出（州）。"""
    monkeypatch.setattr(pv.geocode, "geocode_state",
                        lambda a: {"state": "FL", "matched_address": "123 Main St, Tampa, FL 33602",
                                   "lat": 27.9, "lng": -82.4})
    chain = pv.run_chain("123 Main St, Tampa, FL 33602",
                         providers=[_FailProvider(), pv.CensusProvider()])
    assert chain["ok"] is True
    by_key = {f["key"]: f for f in chain["fields"]}
    assert by_key["state_confirmed"]["value"] == "FL"
    assert by_key["state_confirmed"]["source"] == "U.S. Census Geocoder"


def test_chain_all_fail_returns_chinese_diagnostics(monkeypatch):
    """连 Census 都无匹配 → 中文诊断，不静默。"""
    monkeypatch.setattr(pv.geocode, "geocode_state",
                        lambda a: {"state": None, "matched_address": None,
                                   "lat": None, "lng": None})
    chain = pv.run_chain("火星某路 1 号",
                         providers=[_FailProvider(), pv.CensusProvider()])
    assert chain["ok"] is False
    assert chain["fields"] == []
    assert chain["primary_provider"] is None
    assert "FakeFail" in chain["diagnostics"]
    assert "Census" in chain["diagnostics"]
    assert "上游挂了" in chain["diagnostics"]


def test_priority_merge_tophap_beats_rentcast():
    """同 key 冲突：TopHap 胜出；RentCast 只补缺。来源标注各自保留。"""
    class _P1(pv.BaseProvider):
        name = "TopHap MCP"

        def available(self):
            return True, ""

        def enrich(self, address, log):
            return {"ok": True, "fields": [_field("beds", 3, "TopHap MCP")],
                    "provider": self.name, "note": ""}

    class _P2(pv.BaseProvider):
        name = "RentCast"

        def available(self):
            return True, ""

        def enrich(self, address, log):
            return {"ok": True,
                    "fields": [_field("beds", 5, "RentCast"),
                               _field("baths", 2, "RentCast")],
                    "provider": self.name, "note": ""}

    chain = pv.run_chain("x", providers=[_P1(), _P2()])
    assert chain["ok"] is True
    assert chain["primary_provider"] == "TopHap MCP"
    by_key = {f["key"]: f for f in chain["fields"]}
    assert by_key["beds"]["value"] == 3  # TopHap 胜出
    assert by_key["beds"]["source"] == "TopHap MCP"
    assert by_key["baths"]["value"] == 2  # RentCast 补缺
    assert by_key["baths"]["source"] == "RentCast"


def test_rentcast_field_mapping():
    """RentCast 响应 → DealDesk 字段映射正确，每字段带来源/时间/可信度。"""
    rec = {
        "propertyType": "Single Family", "bedrooms": 3, "bathrooms": 2.5,
        "squareFootage": 1800, "lotSize": 7500, "yearBuilt": 1985,
        "assessorID": "APN-123", "county": "Hillsborough", "zoning": "RS-75",
        "lastSalePrice": 250000, "lastSaleDate": "2020-05-15T00:00:00.000Z",
        "taxAssessments": {"2023": {"year": 2023, "value": 200000},
                           "2024": {"year": 2024, "value": 216513}},
        "propertyTaxes": {"2024": {"year": 2024, "total": 4065}},
        "features": {"floorCount": 2, "unitCount": 1},
        "hoa": {"fee": 100},
        "owner": {"names": ["Jane Doe"]},
        "history": {"2020-05-15": {"event": "Sale", "date": "2020-05-15T00:00:00.000Z",
                                   "price": 250000}},
    }
    fields = pv._map_rentcast(rec)
    by_key = {f["key"]: f for f in fields}
    assert by_key["beds"]["value"] == 3
    assert by_key["baths"]["value"] == 2.5
    assert by_key["building_sf"]["value"] == 1800
    assert by_key["lot_sf"]["value"] == 7500
    assert by_key["year_built"]["value"] == 1985
    assert by_key["stories"]["value"] == 2
    assert by_key["building_units"]["value"] == 1
    assert by_key["parcel_id"]["value"] == "APN-123"
    assert by_key["county"]["value"] == "Hillsborough"
    assert by_key["zoning"]["value"] == "RS-75"
    assert by_key["owner_name"]["value"] == "Jane Doe"
    assert by_key["hoa_monthly"]["value"] == 100
    assert by_key["tax_assessed_value"]["value"] == 216513  # 取最新年份
    assert "2024" in by_key["tax_assessed_value"]["note"]
    assert by_key["taxes_annual"]["value"] == 4065
    assert by_key["last_sale_price"]["value"] == 250000
    assert by_key["last_sale_date"]["value"] == "2020-05-15"
    assert len(by_key["price_history"]["value"]) == 1
    # 诚实铁律：每字段带来源/时间/可信度
    for f in fields:
        assert f["source"] == "RentCast"
        assert f["fetched_at"]
        assert f["confidence"]
        assert f["status"] == "filled"


def test_rentcast_mapping_skips_missing():
    """缺字段的记录不崩，只映射有的。"""
    fields = pv._map_rentcast({"propertyType": "Land"})
    assert [f["key"] for f in fields] == ["property_type_detail"]
    assert pv._map_rentcast({}) == []
    assert pv._map_rentcast(None) == []


def test_run_address_pipeline_uses_chain(monkeypatch):
    """run_address_pipeline 走 provider 链：primary/链路信息进结果。"""
    fake_fields = [_field("beds", 4, "RentCast")]
    fake_chain = {"ok": True, "fields": fake_fields,
                  "primary_provider": "RentCast",
                  "provider_results": [{"provider": "RentCast", "status": "ok",
                                        "note": "ok"}],
                  "diagnostics": "", "log": []}
    monkeypatch.setattr(rp.providers, "run_chain",
                        lambda address, log=None: fake_chain)
    d = rp.run_address_pipeline("123 Main St, Tampa, FL 33602")
    assert d["primary_provider"] == "RentCast"
    assert len(d["provider_chain"]) == 1
    assert {f["key"] for f in d["fields"]} == {"beds"}
    assert d["address"] == "123 Main St, Tampa, FL 33602"


def test_run_address_pipeline_all_fail_has_diagnostics(monkeypatch):
    """全挂时 run_address_pipeline 返回中文诊断。"""
    fake_chain = {"ok": False, "fields": [], "primary_provider": None,
                  "provider_results": [], "diagnostics": "TopHap MCP：挂了",
                  "log": []}
    monkeypatch.setattr(rp.providers, "run_chain",
                        lambda address, log=None: fake_chain)
    d = rp.run_address_pipeline("123 Main St, Tampa, FL 33602")
    assert d["fields"] == []
    assert "diagnostics" in d
    assert "TopHap MCP" in d["diagnostics"]
    assert len(d["manual_needed"]) > 0
