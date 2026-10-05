"""verdict 三档引擎测试：四规则全覆盖."""

from app import verdict


def _score(total=85, vetoes=None):
    return {"total": total, "grade": "A",
            "vetoes": vetoes or [],
            "metrics": {"cash_flow_monthly": 320, "dscr": 1.35}}


class TestResidential:
    def test_worth_it_base(self):
        v = verdict.verdict("residential", _score(85), 72, {})
        assert v["verdict"] == "值得买"
        assert not v["circuit_broken"]

    def test_veto_forces_no(self):
        v = verdict.verdict("residential", _score(85, [{"code": "x", "message": "硬伤"}]), 72, {})
        assert v["verdict"] == "别碰"
        assert any("一票否决" in r for r in v["reasons"])

    def test_confidence_circuit_breaker(self):
        v = verdict.verdict("residential", _score(85), 35, {})
        assert v["verdict"] == "数据不足，需人工评估"
        assert v["circuit_broken"]

    def test_p0_downgrade(self):
        v = verdict.verdict("residential", _score(85), 72,
                            {"p0_gaps": ["缺 rent roll"]})
        assert v["verdict"] == "再看看"
        assert any("降一档" in r for r in v["reasons"])

    def test_price_arbitration(self):
        v = verdict.verdict("residential", _score(85), 72,
                            {"ask_price": 1_500_000, "value_hi": 1_320_000})
        assert v["verdict"] == "再看看"
        assert any("价格仲裁" in r for r in v["reasons"])

    def test_divergence_hold(self):
        v = verdict.verdict("residential", _score(85), 72, {"divergence_pct": 30})
        assert v["verdict"] == "再看看"

    def test_divergence_human(self):
        v = verdict.verdict("residential", _score(85), 72, {"divergence_pct": 45})
        assert v["verdict"] == "需人工复核"
        assert v["circuit_broken"]

    def test_usage_line(self):
        v = verdict.verdict("residential", _score(85), 72, {})
        assert "不构成投资建议" in v["usage"]


class TestCommercial:
    def test_buy_base(self):
        v = verdict.verdict("commercial", _score(85), 72, {})
        assert v["verdict"] == "BUY"

    def test_p0_downgrade(self):
        v = verdict.verdict("commercial", _score(85), 72,
                            {"p0_gaps": ["缺结构化 rent roll"]})
        assert v["verdict"] == "HOLD"
        assert any("降一档" in r for r in v["reasons"])

    def test_price_arbitration_caps_hold(self):
        v = verdict.verdict("commercial", _score(90), 72,
                            {"ask_price": 5_000_000, "value_hi": 4_200_000})
        assert v["verdict"] == "HOLD"

    def test_dscr_deadline_pass(self):
        s = _score(40)
        s["metrics"]["dscr"] = 0.9
        v = verdict.verdict("commercial", s, 72, {})
        assert v["verdict"] == "PASS"

    def test_divergence_rules(self):
        v = verdict.verdict("commercial", _score(85), 72, {"divergence_pct": 30})
        assert v["verdict"] == "HOLD"
        v2 = verdict.verdict("commercial", _score(85), 72, {"divergence_pct": 45})
        assert v2["verdict"] == "需人工复核"

    def test_confidence_breaker(self):
        v = verdict.verdict("commercial", _score(85), 39, {})
        assert v["verdict"] == "数据不足，需人工评估"

    def test_uspap_line(self):
        v = verdict.verdict("commercial", _score(85), 72, {})
        assert "USPAP" in v["usage"]


class TestPhase5Round3:
    """第三轮微修复回归：DSCR 0.00 根除 / 单点术语统一."""

    def test_com_no_rr_one_liner_no_zero_dscr(self):
        # A1：无 rent roll 时 dscr 回退 0.0，不许印"DSCR 0.00 < 1.0"
        s = _score(40)
        s["metrics"]["dscr"] = 0.0
        v = verdict.verdict("commercial", s, 72, {})
        assert v["verdict"] == "PASS"
        assert "0.00" not in v["one_liner"]
        assert v["one_liner"] == "无 rent roll，DSCR 无法核保（待接数据）"

    def test_com_with_rr_zero_dscr_keeps_template(self):
        # 有 rent roll 时 dscr=0 视为真数，保留原模板（不误伤）
        s = _score(40)
        s["metrics"]["dscr"] = 0.0
        v = verdict.verdict("commercial", s, 72, {"has_rent_roll": True})
        assert "DSCR 0.00 < 1.0" in v["one_liner"]

    def test_com_no_rr_dscr_none(self):
        s = _score(40)
        s["metrics"]["dscr"] = None
        v = verdict.verdict("commercial", s, 72, {})
        assert "0.00" not in v["one_liner"]
        assert "无法核保" in v["one_liner"]

    def test_res_no_rent_data_one_liner(self):
        # A1（remote R1）：住宅无租金数据时不许印"DSCR 只有 0.00"
        s = _score(40)
        s["metrics"]["dscr"] = 0.0
        v = verdict.verdict("residential", s, 72, {})
        assert v["verdict"] == "别碰"
        assert "0.00" not in v["one_liner"]
        assert "无法核保" in v["one_liner"]

    def test_price_arb_single_point(self):
        # item 7：单点估值时只说"单点"，不许说"区间上界"
        v = verdict.verdict("commercial", _score(90), 72,
                            {"ask_price": 5_000_000, "value_lo": 4_200_000,
                             "value_hi": 4_200_000})
        assert any("（单点）" in r and "区间上界" not in r
                   for r in v["reasons"] if "价格仲裁" in r)

    def test_price_arb_range_keeps_upper(self):
        # 真区间时保留"估值区间上界"
        v = verdict.verdict("commercial", _score(90), 72,
                            {"ask_price": 5_000_000, "value_lo": 4_000_000,
                             "value_hi": 4_200_000})
        assert any("估值区间上界" in r for r in v["reasons"] if "价格仲裁" in r)
