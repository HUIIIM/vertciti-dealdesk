"""Confidence Score 测试：6 因子权重与红线."""

from app import confidence


def _comps(n=5, months=3, dist=0.5):
    return [{"address": f"comp {i}", "price": 500_000, "sf": 1000,
             "sale_date": "2026-07-01", "distance_miles": dist,
             "adjustment_pct": 5, "type_match": True}
            for i in range(n)]


class TestConfidence:
    def test_high_confidence(self):
        c = confidence.compute("residential", _comps(5), {
            "noi_evidence": "audited_ttm", "cap_evidence": "market_pull",
            "cap_pull_count": 5,
            "methods": {"income": (480_000, 520_000), "sales": (490_000, 510_000)}})
        assert c["score"] >= 80
        assert "高置信" in c["label"]

    def test_weights_sum(self):
        c = confidence.compute("residential", _comps(5), {})
        assert abs(sum(f["weighted"] for f in c["factors"].values()) - c["score"]) < 0.2

    def test_no_comps_low(self):
        c = confidence.compute("residential", [], {"noi_evidence": "none"})
        assert c["score"] < 40
        assert "熔断" in c["label"]

    def test_cap_ceiling_60_commercial(self):
        # 无 cap 提取证据：商业 Confidence 天花板 60
        c = confidence.compute("commercial", _comps(5), {
            "noi_evidence": "audited_ttm", "cap_evidence": "band_of_investment",
            "methods": {"income": (480_000, 520_000), "sales": (490_000, 510_000)}})
        assert c["score"] <= 60
        assert any("天花板 60" in n for n in c["notes"])

    def test_proforma_noi_lower(self):
        a = confidence.compute("residential", _comps(3), {"noi_evidence": "proforma"})
        b = confidence.compute("residential", _comps(3), {"noi_evidence": "audited_ttm"})
        assert a["factors"]["noi_q"]["score"] < b["factors"]["noi_q"]["score"]

    def test_disclaimer_separates_evidence_from_recommendation(self):
        c = confidence.compute("residential", _comps(3), {})
        assert "不是推荐强度" in c["disclaimer"]

    def test_formula_public(self):
        c = confidence.compute("residential", _comps(3), {})
        assert "25" in c["formula"] and "10" in c["formula"]

    def test_gross_adjustment_penalty(self):
        comps = _comps(5)
        for c in comps:
            c["adjustment_pct"] = 30
        c = confidence.compute("residential", comps, {})
        assert "gross adjustment" in c["factors"]["comps_nq"]["note"]
