"""DealDesk 评分引擎单元测试（标准库 unittest）.

约定：测试钉住 headline 数字；改引擎必须同步改断言（学自 C2）。
运行：.venv/bin/python -m unittest discover -s tests -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import scoring_commercial as com  # noqa: E402
from app import scoring_residential as res  # noqa: E402
from app.finance import monthly_payment, remaining_balance, wrap_analysis  # noqa: E402


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
        "exit_primary": "持有+mark-to-market", "exit_backup": "出售给私人买家",
        "buyer_pool_evidence": "同类资产近12个月有3宗成交",
        "reserves_months_ds": 8, "is_value_add_vacant": False,
        "risk_flags": [], "market_pop_employment": 2, "market_vacancy_trend": 2,
        "market_rent_trend": 1, "market_landlord_friendly": 1,
    }
    d.update(over)
    return d


class TestFinance(unittest.TestCase):
    def test_monthly_payment(self):
        # 100k, 6%, 30yr -> 约 $599.55
        self.assertAlmostEqual(monthly_payment(100000, 6.0, 30), 599.55, places=1)

    def test_remaining_balance_zero_at_end(self):
        self.assertAlmostEqual(remaining_balance(100000, 6.0, 30, 30), 0.0, places=0)

    def test_wrap_spread_positive(self):
        w = wrap_analysis(150000, 3.0, 30, 220000, 20000, 8.0, 30, 5)
        self.assertGreater(w["monthly_spread"], 0)
        # 总利润 = 首付 + 利差*月数 + 本金差
        expect = 20000 + w["monthly_spread"] * 60 + (w["wrap_balance_at_exit"] - w["underlying_balance_at_exit"])
        self.assertAlmostEqual(w["total_profit"], expect, places=0)


class TestResidential(unittest.TestCase):
    def test_phoenix_like_subto_scores_a(self):
        s = res.score(base_residential())
        self.assertEqual(s["vetoes"], [])
        # 按 buyer-box v2.1 字面口径：单门 $418/月、CoC 67%、DSCR 1.59、
        # 3.07% 固定 27 年、首付 3.4%（≤5% 满分）=> 91.1 分 A 级（钉住 headline 数字）
        self.assertAlmostEqual(s["total"], 91.1, places=1)
        self.assertEqual(s["grade"], "A")
        m = s["metrics"]
        self.assertGreater(m["cash_flow_per_door"], 300)
        self.assertGreaterEqual(m["dscr"], 1.25)

    def test_negative_equity_flag_not_veto(self):
        # v2.3：负净值不再单独否决——强现金流/DSCR/储备/退出 → 无否决＋"负净值入场"风险旗
        s = res.score(base_residential(price=140000))  # 贷款 154463 > 140000
        codes = [v["code"] for v in s["vetoes"]]
        self.assertNotIn("negative_equity", codes)
        self.assertEqual(s["vetoes"], [])
        risk_detail = [d for d in s["dimensions"] if d["key"] == "risk"][0]["detail"]
        self.assertIn("负净值入场", risk_detail)

    def test_negative_equity_missing_exit_still_vetoed(self):
        # Phase 5 新规则：subject-to 下只有"完全没有退出策略"才否决；
        # 单一退出策略（exit_primary）即可解除 no_exit（备选路径硬性要求取消）。
        s = res.score(base_residential(price=140000, exit_primary=""))
        codes = [v["code"] for v in s["vetoes"]]
        self.assertIn("no_exit", codes)
        self.assertNotIn("negative_equity", codes)
        self.assertEqual(s["grade"], "否决")

    def test_subject_to_exit_primary_clears_no_exit(self):
        # Phase 5：选了退出策略 → no_exit 解除（exit_backup 缺失也不再否决）
        s = res.score(base_residential(price=140000, exit_backup=""))
        codes = [v["code"] for v in s["vetoes"]]
        self.assertNotIn("no_exit", codes)

    def test_non_subject_to_no_exit_veto(self):
        # Phase 5：普通购买/贷款购买结构下，退出预案否决永不出现
        s = res.score(base_residential(price=140000, structure="standard",
                                       exit_primary="", exit_backup=""))
        codes = [v["code"] for v in s["vetoes"]]
        self.assertNotIn("no_exit", codes)
        self.assertNotIn("no_dos_plan", codes)

    def test_no_auth_release_never_vetoes(self):
        # Phase 5（P0-1）："卖方拒绝签 authorization to release"永不自动否决
        s = res.score(base_residential(price=140000,
                                       seller_signed_auth_release=False))
        codes = [v["code"] for v in s["vetoes"]]
        self.assertNotIn("no_auth_release", codes)

    def test_floating_rate_veto(self):
        s = res.score(base_residential(rate_type="floating"))
        codes = [v["code"] for v in s["vetoes"]]
        self.assertIn("floating_rate", codes)

    def test_short_balloon_veto(self):
        s = res.score(base_residential(balloon_years=3))
        codes = [v["code"] for v in s["vetoes"]]
        self.assertIn("short_balloon", codes)

    def test_proforma_rent_veto(self):
        s = res.score(base_residential(rent_source="proforma"))
        codes = [v["code"] for v in s["vetoes"]]
        self.assertIn("proforma_rent", codes)

    def test_no_exit_veto(self):
        s = res.score(base_residential(exit_primary="", exit_backup=""))
        codes = [v["code"] for v in s["vetoes"]]
        self.assertIn("no_exit", codes)

    def test_down_payment_125pct_floating(self):
        # v2.2 浮动制：12.5% 首付不再归零——基础 55＋上浮约 10.35 → 9.8/15
        s = res.score(base_residential(down_payment=20000))  # 12.5%
        dp_dim = [d for d in s["dimensions"] if d["key"] == "down_payment"][0]
        self.assertAlmostEqual(dp_dim["points"], 9.8, places=1)

    def test_low_reserves_auto_flag(self):
        s = res.score(base_residential(reserves_months_piti=2))
        risk = [d for d in s["dimensions"] if d["key"] == "risk"][0]
        self.assertLess(risk["points"], 15)
        self.assertIn("储备金不足", risk["detail"])


class TestCommercial(unittest.TestCase):
    def test_retail_strip_scores(self):
        s = com.score(base_commercial())
        self.assertEqual(s["vetoes"], [])
        m = s["metrics"]
        # 手工验算关键数：EGI=155000*0.92=142600
        self.assertAlmostEqual(m["egi"], 142600, places=0)
        # OpEx=19800+9000+11408+7130+4000=51338
        self.assertAlmostEqual(m["opex"], 51338, places=0)
        # NOI=91262；月供 900k@6%/30yr=5396.48
        self.assertAlmostEqual(m["noi"], 91262, places=0)
        self.assertGreater(m["dscr"], 1.25)
        self.assertGreaterEqual(s["total"], 50)

    def test_dscr_below_125_veto(self):
        d = base_commercial()
        d["tranches"] = [{"balance": 900000, "rate": 12.0, "rate_type": "fixed",
                          "term_years": 15, "balloon_years": None}]
        s = com.score(d)
        codes = [v["code"] for v in s["vetoes"]]
        self.assertIn("low_dscr", codes)
        self.assertEqual(s["grade"], "否决")

    def test_negative_equity_flag_not_veto(self):
        # v1.3：负净值（成交价高于 as-is 评估值）不再单独否决——强基本面 → 无否决＋风险旗
        s = com.score(base_commercial(as_is_appraisal=900000))
        codes = [v["code"] for v in s["vetoes"]]
        self.assertNotIn("negative_equity", codes)
        self.assertEqual(s["vetoes"], [])
        risk_detail = [d for d in s["dimensions"] if d["key"] == "risk"][0]["detail"]
        self.assertIn("负净值入场", risk_detail)

    def test_negative_equity_weak_dscr_still_vetoed(self):
        # 补偿条件缺一：DSCR 不达标 → low_dscr 否决拦下（不是负净值否决）
        d = base_commercial(as_is_appraisal=900000)
        d["tranches"] = [{"balance": 900000, "rate": 12.0, "rate_type": "fixed",
                          "term_years": 15, "balloon_years": None}]
        s = com.score(d)
        codes = [v["code"] for v in s["vetoes"]]
        self.assertIn("low_dscr", codes)
        self.assertNotIn("negative_equity", codes)
        self.assertEqual(s["grade"], "否决")

    def test_environmental_veto(self):
        s = com.score(base_commercial(phase1_clear=False))
        codes = [v["code"] for v in s["vetoes"]]
        self.assertIn("environmental", codes)

    def test_rollover_cliff_veto(self):
        s = com.score(base_commercial(walt_years=1.5, concentration_12mo_pct=45))
        codes = [v["code"] for v in s["vetoes"]]
        self.assertIn("rollover_cliff", codes)

    def test_out_of_scope_veto(self):
        s = com.score(base_commercial(asset_class="other"))
        codes = [v["code"] for v in s["vetoes"]]
        self.assertIn("out_of_scope", codes)


if __name__ == "__main__":
    unittest.main()
