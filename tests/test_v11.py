"""DealDesk v1.1 口径补丁测试（标准库 unittest）.

覆盖：住宅 subject-to 首付评分 v2.1 / office 专项核保 / hotel 专项核保 /
cash-to-close 一级字段 / value-add 70% 预租 A 级门禁 / 短期抛售一票否决 /
API Pydantic 严格校验中文错误 / 列表按 cash-to-close 升序。
运行：.venv/bin/python -m unittest discover -s tests -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import scoring_commercial as com  # noqa: E402
from app import scoring_residential as res  # noqa: E402
from app.finance import monthly_payment  # noqa: E402


def base_residential(**over):
    d = {
        "structure": "subject_to", "price": 159900, "down_payment": 5437,
        "loan_balance": 154463, "rate": 3.07, "rate_type": "fixed",
        "term_years_remaining": 27, "balloon_years": None, "is_assumption": False,
        "monthly_rent": 2050, "other_income_monthly": 0, "units": 1,
        "rent_source": "comps_verified",
        "taxes_annual": 1800, "insurance_annual": 1200, "hoa_monthly": 0,
        "utilities_owner_monthly": 0,
        "vacancy_pct": 8, "maint_pct": 8, "capex_pct": 8, "mgmt_pct": 10,
        "closing_costs": 2000, "initial_repairs": 0, "other_liens": 0,
        "seller_delinquent_days": 0, "has_discount_hedge": False,
        "insurance_available": True, "seller_signed_auth_release": True,
        "hoa_arrears_severe": False, "title_defect": False, "fraud_flag": False,
        "exit_primary": "长期持有收租", "exit_backup": "DSCR refi",
        "due_on_sale_plan": "可 refi 出来", "reserves_months_piti": 6,
        "risk_flags": [], "market_pop": 3, "market_employment": 3,
        "market_inventory": 2, "market_appreciation": 2,
    }
    d.update(over)
    return d


def base_commercial(**over):
    d = {
        "asset_class": "retail_strip", "structure": "seller_financing",
        "price": 1000000, "closing_costs": 20000, "capex_y1": 10000,
        "down_payment": 100000,
        "tranches": [{"balance": 900000, "rate": 6.0, "rate_type": "fixed",
                      "term_years": 30, "balloon_years": None}],
        "annual_base_rent": 150000, "other_income_annual": 5000,
        "other_income_verified": True, "vacancy_pct": 8,
        "tax_annual": 18000, "insurance_annual": 9000, "mgmt_pct": 8,
        "maint_pct": 5, "property_age_years": 15, "utilities_cam_gap_annual": 4000,
        "building_sf": 15090, "units": 0, "ti_lc_annual_amort": 6000,
        "market_cap_rate_pct": 7.0, "market_cap_source": "LoopNet 近12个月",
        "walt_years": 4.2, "all_nnn": True, "concentration_12mo_pct": 18,
        "tenant_quality_ok": True, "escalations_ok": True,
        "as_is_appraisal": 1020000, "phase1_clear": True, "zoning_ok": True,
        "ti_lc_unfunded_over_12mo": False, "noi_evidence": "rent_roll",
        "seller_signed_auth_release": True, "fraud_flag": False,
        "exit_primary": "hold", "exit_backup": "出售给私人买家",
        "buyer_pool_evidence": "同类资产近12个月有3宗成交",
        "reserves_months_ds": 8, "is_value_add_vacant": False,
        "risk_flags": [], "market_pop_employment": 2, "market_vacancy_trend": 2,
        "market_rent_trend": 1, "market_landlord_friendly": 1,
        "exit_flip_dependent_only": False, "pre_lease_pct": 0,
    }
    d.update(over)
    return d


def base_office(**over):
    d = base_commercial(
        asset_class="office", price=2000000, closing_costs=40000, capex_y1=20000,
        down_payment=100000,
        tranches=[{"balance": 1900000, "rate": 6.0, "rate_type": "fixed",
                   "term_years": 25, "balloon_years": None}],
        annual_base_rent=360000, other_income_annual=10000,
        tax_annual=40000, insurance_annual=15000, utilities_cam_gap_annual=5000,
        building_sf=20000, ti_lc_annual_amort=8000,
        market_cap_rate_pct=7.5, walt_years=5, all_nnn=False,
        concentration_12mo_pct=15, as_is_appraisal=2050000,
        occupancy_pct=85, ti_lc_itemized=True,
    )
    d.update(over)
    return d


def base_hotel(**over):
    d = base_commercial(
        asset_class="hotel", price=3000000, closing_costs=60000, capex_y1=30000,
        down_payment=150000,
        tranches=[{"balance": 2850000, "rate": 7.0, "rate_type": "fixed",
                   "term_years": 25, "balloon_years": None}],
        annual_base_rent=0, other_income_annual=0, vacancy_pct=0,
        tax_annual=30000, insurance_annual=12000, utilities_cam_gap_annual=0,
        building_sf=40000, units=80, ti_lc_annual_amort=0,
        market_cap_rate_pct=8.0, walt_years=0, all_nnn=False,
        concentration_12mo_pct=0, escalations_ok=False,
        as_is_appraisal=3100000,
        hotel_revenue_annual=900000, hotel_opex_annual=450000,
        revpar_source="verified_conservative", hotel_mgmt_pct=5, hotel_ff_e_pct=4,
        has_operating_history=True, pip_capex=50000, franchise_term_ok=True,
        low_season_covers_ds=True,
    )
    d.update(over)
    return d


def dp_points(score_result):
    return [d for d in score_result["dimensions"] if d["key"] == "down_payment"][0]["points"]


class TestResidentialFloatingDownPayment(unittest.TestCase):
    """buyer-box.md v2.2：subject-to 首付浮动制（基础分＋现金流强度上浮，封顶 100）."""

    def test_subto_5pct_full_marks(self):
        s = res.score(base_residential(down_payment=7995))  # 159900*5%
        self.assertEqual(dp_points(s), 15.0)

    def test_subto_8pct_floating(self):
        # 基础 85＋上浮约 10.35 → 95.35 → 14.3/15（v2.1 下是 12.0）
        s = res.score(base_residential(down_payment=12792))  # 159900*8%
        self.assertAlmostEqual(dp_points(s), 14.3, places=1)

    def test_subto_10pct_floating(self):
        # 基础 70＋上浮约 10.35 → 80.35 → 12.1/15（v2.1 下是 6.0）
        s = res.score(base_residential(down_payment=15990))  # 159900*10%
        self.assertAlmostEqual(dp_points(s), 12.1, places=1)

    def test_midpoint_65pct_capped_at_full(self):
        # 基础 92.5＋上浮约 10.35 → 封顶 100 → 15.0/15
        s = res.score(base_residential(down_payment=10393.5))  # 6.5%
        self.assertEqual(dp_points(s), 15.0)

    def test_34pct_still_full(self):
        s = res.score(base_residential())
        self.assertEqual(dp_points(s), 15.0)

    def test_weak_cashflow_gets_no_bonus(self):
        # 现金流强度 <60% → 无上浮：10% 首付只得基础 70 分 → 10.5/15
        s = res.score(base_residential(down_payment=15990, monthly_rent=1100))
        self.assertAlmostEqual(dp_points(s), 10.5, places=1)

    def test_strong_deal_beats_weak_deal_same_down(self):
        # 同样 10% 首付：deal 好（强现金流）得分高于 deal 差的——浮动制的核心
        strong = dp_points(res.score(base_residential(down_payment=15990)))
        weak = dp_points(res.score(base_residential(down_payment=15990, monthly_rent=1100)))
        self.assertGreater(strong, weak)
        self.assertAlmostEqual(strong - weak, 1.6, places=1)  # 12.1 - 10.5

    def test_subto_12pct_no_hard_veto(self):
        # v2.2 起 subject-to 首付在 8%/10% 无任何硬否决
        s = res.score(base_residential(down_payment=19188))  # 12%
        self.assertEqual(s["vetoes"], [])


class TestOfficeUnderwriting(unittest.TestCase):
    """buyer-box-commercial.md v1.1 office 专项核保."""

    def test_office_healthy_deal_passes(self):
        s = com.score(base_office())
        self.assertEqual(s["vetoes"], [])
        self.assertEqual(s["downgrades"], [])
        self.assertEqual(s["grade"], "A")

    def test_office_vacancy_floor_12pct(self):
        # 输入 8% 也按 12% 测算
        m = com.compute_metrics(base_office(vacancy_pct=8))
        self.assertEqual(m["vacancy_used_pct"], 12.0)
        # 输入 15% 则按输入值
        m2 = com.compute_metrics(base_office(vacancy_pct=15))
        self.assertEqual(m2["vacancy_used_pct"], 15.0)

    def test_office_low_occupancy_veto(self):
        s = com.score(base_office(occupancy_pct=70))
        codes = [v["code"] for v in s["vetoes"]]
        self.assertIn("office_low_occupancy", codes)
        self.assertEqual(s["grade"], "否决")

    def test_office_walt_veto(self):
        s = com.score(base_office(walt_years=2.5))
        codes = [v["code"] for v in s["vetoes"]]
        self.assertIn("office_walt", codes)
        self.assertEqual(s["grade"], "否决")

    def test_office_rent_stress_downgrade_not_veto(self):
        # DSCR 1.325 通过硬门槛，但 -10% 租金后 1.156 <1.25：降级为 C，不是直接否决
        d = base_office(
            annual_base_rent=340000,
            tranches=[{"balance": 1900000, "rate": 6.5, "rate_type": "fixed",
                       "term_years": 25, "balloon_years": None}])
        s = com.score(d)
        self.assertEqual(s["vetoes"], [])
        codes = [g["code"] for g in s["downgrades"]]
        self.assertIn("office_rent_stress", codes)
        self.assertEqual(s["grade"], "C")
        self.assertGreaterEqual(s["total"], 80)  # 原始分够 A，证明是降级机制在起作用

    def test_office_ti_lc_not_itemized_flag(self):
        s = com.score(base_office(ti_lc_itemized=False))
        risk = [d for d in s["dimensions"] if d["key"] == "risk"][0]
        self.assertLess(risk["points"], 15)
        self.assertIn("TI/LC 未逐项", risk["detail"])


class TestHotelUnderwriting(unittest.TestCase):
    """buyer-box-commercial.md v1.1 hotel 专项核保."""

    def test_hotel_healthy_deal_passes(self):
        s = com.score(base_hotel())
        self.assertEqual(s["vetoes"], [])
        self.assertEqual(s["grade"], "A")

    def test_hotel_mgmt_fee_floor_5pct(self):
        # 输入 3% 也按 5% 收取：900000*5% = 45000
        m = com.compute_metrics(base_hotel(hotel_mgmt_pct=3))
        self.assertAlmostEqual(m["opex_detail"]["management"], 45000, places=0)

    def test_hotel_ffe_floor_4pct(self):
        # 输入 2% 也按 4% 计提：900000*4% = 36000
        m = com.compute_metrics(base_hotel(hotel_ff_e_pct=2))
        self.assertAlmostEqual(m["ff_e_annual"], 36000, places=0)

    def test_hotel_dscr_gate_is_135(self):
        # DSCR 1.307：通用 1.25 门槛下能过，酒店 1.35 专项下必须否决
        d = base_hotel(tranches=[{"balance": 2850000, "rate": 7.5, "rate_type": "fixed",
                                  "term_years": 20, "balloon_years": None}])
        s = com.score(d)
        self.assertGreater(s["metrics"]["dscr"], 1.25)
        codes = [v["code"] for v in s["vetoes"]]
        self.assertIn("low_dscr", codes)
        self.assertEqual(s["grade"], "否决")

    def test_hotel_no_operating_history_veto(self):
        s = com.score(base_hotel(has_operating_history=False))
        codes = [v["code"] for v in s["vetoes"]]
        self.assertIn("hotel_no_history", codes)
        self.assertEqual(s["grade"], "否决")

    def test_hotel_proforma_revpar_veto(self):
        s = com.score(base_hotel(revpar_source="proforma"))
        codes = [v["code"] for v in s["vetoes"]]
        self.assertIn("hotel_proforma_revpar", codes)

    def test_hotel_low_season_downgrade(self):
        s = com.score(base_hotel(low_season_covers_ds=False))
        self.assertEqual(s["vetoes"], [])
        codes = [g["code"] for g in s["downgrades"]]
        self.assertIn("hotel_low_season", codes)
        self.assertNotEqual(s["grade"], "A")

    def test_hotel_pip_capex_in_cash(self):
        # cash_invested = 150000+60000+30000+50000(PIP) = 290000
        m = com.compute_metrics(base_hotel())
        self.assertAlmostEqual(m["cash_invested"], 290000, places=0)

    def test_hotel_missing_opex_flag(self):
        s = com.score(base_hotel(hotel_opex_annual=0))
        risk = [d for d in s["dimensions"] if d["key"] == "risk"][0]
        self.assertLess(risk["points"], 15)
        self.assertIn("部门/固定费用", risk["detail"])


class TestCashToClose(unittest.TestCase):
    """cash-to-close 一级字段：首付＋交割费＋储备金＋首年 capex（＋酒店 PIP）."""

    def test_residential_cash_to_close_sum(self):
        s = res.score(base_residential())
        m = s["metrics"]
        # cash_invested = 5437+2000+0；reserves_cash = 6 * piti
        expect = 7437 + 6 * m["piti"]
        self.assertAlmostEqual(m["cash_to_close"], expect, places=0)
        self.assertAlmostEqual(m["total_cash_required"], m["cash_to_close"], places=0)

    def test_commercial_cash_to_close_includes_reserves_and_ti_lc(self):
        s = com.score(base_commercial())
        m = s["metrics"]
        monthly_ds = m["annual_debt_service"] / 12
        expect = 100000 + 20000 + 10000 + 8 * monthly_ds + 6000
        self.assertAlmostEqual(m["cash_to_close"], expect, places=0)


class TestValueAddPreleaseGate(unittest.TestCase):
    """value-add 预租 <70% 不能进 A 级."""

    def test_prelease_below_70_caps_at_b(self):
        s = com.score(base_office(is_value_add_vacant=True, reserves_months_ds=12,
                                  pre_lease_pct=50))
        self.assertGreaterEqual(s["total"], 80)  # 原始分够 A
        codes = [g["code"] for g in s["downgrades"]]
        self.assertIn("value_add_prelease", codes)
        self.assertEqual(s["grade"], "B")

    def test_prelease_above_70_keeps_a(self):
        s = com.score(base_office(is_value_add_vacant=True, reserves_months_ds=12,
                                  pre_lease_pct=75))
        self.assertEqual(s["grade"], "A")
        self.assertEqual(s["downgrades"], [])


class TestFlipExitSoftened(unittest.TestCase):
    """buyer-box-commercial.md v1.3：高价抛售退出软化——不再单独否决，挂风险旗."""

    def _risk_detail(self, s):
        return [d for d in s["dimensions"] if d["key"] == "risk"][0]["detail"]

    def test_flip_with_refi_viable_no_veto_with_flag(self):
        # refi 能独立成立 → 正常打分＋"退出依赖高价抛售"风险旗
        s = com.score(base_commercial(exit_flip_dependent_only=True,
                                      refi_cashout_viable=True))
        codes = [v["code"] for v in s["vetoes"]]
        self.assertNotIn("flip_only_exit", codes)
        self.assertNotIn("no_viable_exit", codes)
        self.assertNotEqual(s["grade"], "否决")
        self.assertIn("退出依赖高价抛售", self._risk_detail(s))

    def test_flip_with_hold_viable_no_veto_with_flag(self):
        # refi 不通但持有收租成立（DSCR 达标＋现金流为正）→ 不否决＋风险旗
        s = com.score(base_commercial(exit_flip_dependent_only=True,
                                      refi_cashout_viable=False))
        codes = [v["code"] for v in s["vetoes"]]
        self.assertNotIn("no_viable_exit", codes)
        self.assertNotEqual(s["grade"], "否决")
        self.assertIn("退出依赖高价抛售", self._risk_detail(s))

    def test_flip_with_nothing_viable_vetoed(self):
        # refi 不通＋持有收租不成立（DSCR 达标但扣储备/TI-LC 后现金流为负）→ no_viable_exit 否决
        s = com.score(base_commercial(exit_flip_dependent_only=True,
                                      refi_cashout_viable=False,
                                      ti_lc_annual_amort=30000))
        codes = [v["code"] for v in s["vetoes"]]
        self.assertIn("no_viable_exit", codes)
        self.assertNotIn("low_dscr", codes)  # DSCR 本身达标，否决只来自无可行退出
        self.assertEqual(s["grade"], "否决")

    def test_normal_exit_no_flag(self):
        s = com.score(base_commercial(exit_flip_dependent_only=False))
        self.assertNotIn("退出依赖高价抛售", self._risk_detail(s))


class TestAPIStrictValidation(unittest.TestCase):
    """API 层 Pydantic 严格校验：非法字段/类型/越界值返回中文 422."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls._db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
        os.environ["DEALDESK_DB"] = cls._db
        from app import db
        db.init_db()  # TestClient 非 with 模式不跑 lifespan，需手动建表
        from fastapi.testclient import TestClient
        from app.main import app
        cls.client = TestClient(app)

    def _payload(self, track="residential", **over):
        data = base_residential() if track == "residential" else base_commercial()
        data.update(over)
        return {"track": track, "name": "测试", "address": "测试地址", "input": data}

    def test_extra_field_422_chinese(self):
        p = self._payload(bogus_field_xyz=1)
        r = self.client.post("/api/score", json=p)
        self.assertEqual(r.status_code, 422)
        detail = r.json()["detail"]
        self.assertIn("bogus_field_xyz", detail)
        self.assertIn("不支持的字段", detail)

    def test_wrong_type_422_chinese(self):
        p = self._payload(vacancy_pct="abc")
        r = self.client.post("/api/score", json=p)
        self.assertEqual(r.status_code, 422)
        self.assertIn("vacancy_pct", r.json()["detail"])

    def test_out_of_range_422_chinese(self):
        p = self._payload(vacancy_pct=150)
        r = self.client.post("/api/score", json=p)
        self.assertEqual(r.status_code, 422)
        self.assertIn("vacancy_pct", r.json()["detail"])

    def test_name_address_in_input_tolerated(self):
        # 前端 collectForm 会把 name/address 留在 input 里，API 层剥离后不报错
        p = self._payload()
        p["input"]["name"] = "测试"
        p["input"]["address"] = "测试地址"
        r = self.client.post("/api/score", json=p)
        self.assertEqual(r.status_code, 200)

    def test_list_sorted_by_cash_to_close(self):
        c = self.client
        r1 = c.post("/api/projects", json=self._payload("residential", down_payment=5000))
        r2 = c.post("/api/projects", json=self._payload("residential", down_payment=50000))
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        items = c.get("/api/projects?track=residential&sort=cash_to_close").json()
        vals = [p["cash_to_close"] for p in items]
        self.assertEqual(vals, sorted(vals))
        self.assertLess(items[0]["cash_to_close"], items[1]["cash_to_close"])


if __name__ == "__main__":
    unittest.main()
