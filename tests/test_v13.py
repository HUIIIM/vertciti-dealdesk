"""DealDesk v1.2/v1.3 口径补丁测试（标准库 unittest）.

覆盖：
1. 首付浮动制公式（两线共用）：基础分分段线性＋现金流强度上浮（buyer-box.md v2.2 /
   buyer-box-commercial.md v1.2，Miao 亲定 2026-09-28 晚）。
2. 商业线首付浮动制集成（权重 10）。
3. 商业线高价抛售退出软化 v1.3 的补充场景。
4. 负净值风险旗 v2.3/v1.3 的补充场景。

运行：.venv/bin/python -m unittest discover -s tests -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import scoring_commercial as com  # noqa: E402
from app import scoring_residential as res  # noqa: E402
from app.finance import floating_down_payment_score  # noqa: E402
from test_v11 import base_commercial, base_residential, dp_points  # noqa: E402


class TestFloatingFormula(unittest.TestCase):
    """floating_down_payment_score(dp%, strength) -> (score100, base, bonus)."""

    def test_base_anchors(self):
        self.assertEqual(floating_down_payment_score(5, 0.0), (100.0, 100.0, 0.0))
        self.assertEqual(floating_down_payment_score(8, 0.0), (85.0, 85.0, 0.0))
        self.assertEqual(floating_down_payment_score(10, 0.0), (70.0, 70.0, 0.0))
        self.assertEqual(floating_down_payment_score(15, 0.5), (40.0, 40.0, 0.0))

    def test_linear_segments(self):
        score, base, bonus = floating_down_payment_score(6.5, 0.0)
        self.assertAlmostEqual(base, 92.5, places=2)
        score, base, bonus = floating_down_payment_score(9, 0.0)
        self.assertAlmostEqual(base, 77.5, places=2)
        score, base, bonus = floating_down_payment_score(12, 0.0)
        self.assertAlmostEqual(base, 58.0, places=2)

    def test_zero_at_25_and_clamped_beyond(self):
        score, base, bonus = floating_down_payment_score(25, 0.0)
        self.assertEqual(base, 0.0)
        score, base, bonus = floating_down_payment_score(30, 0.0)
        self.assertEqual(base, 0.0)  # lin_map 在 25% 处 clamp

    def test_bonus_ramps_from_60pct_strength(self):
        _, _, b0 = floating_down_payment_score(10, 0.6)
        self.assertEqual(b0, 0.0)
        _, _, b1 = floating_down_payment_score(10, 0.8)
        self.assertAlmostEqual(b1, 7.5, places=2)
        _, _, b2 = floating_down_payment_score(10, 1.0)
        self.assertEqual(b2, 15.0)

    def test_total_capped_at_100(self):
        score, base, bonus = floating_down_payment_score(3, 1.0)
        self.assertEqual(score, 100.0)
        self.assertEqual(bonus, 15.0)  # bonus 照算，总分封顶

    def test_strength_clamped(self):
        _, _, b = floating_down_payment_score(10, 2.0)
        self.assertEqual(b, 15.0)
        _, _, b = floating_down_payment_score(10, -1.0)
        self.assertEqual(b, 0.0)


class TestCommercialFloatingDownPayment(unittest.TestCase):
    """商业线首付浮动制（权重 10）：基础分＋上浮，封顶 10 分."""

    def test_5pct_full(self):
        self.assertEqual(dp_points(com.score(base_commercial(down_payment=50000))), 10.0)

    def test_10pct_floating(self):
        # 基础 70＋上浮 15（NOI/DSCR 维度满分）→ 85 → 8.5/10
        self.assertAlmostEqual(dp_points(com.score(base_commercial(down_payment=100000))),
                               8.5, places=1)

    def test_15pct_floating(self):
        # 基础 40＋上浮 15 → 55 → 5.5/10
        self.assertAlmostEqual(dp_points(com.score(base_commercial(down_payment=150000))),
                               5.5, places=1)

    def test_over_20pct_flags_re0_approval(self):
        # >20%：基础 16＋上浮 15 → 31 → 3.1/10，且 detail 提示需 RE-0 特批（整体硬上限）
        s = com.score(base_commercial(down_payment=210000))
        self.assertAlmostEqual(dp_points(s), 3.1, places=1)
        detail = [d for d in s["dimensions"] if d["key"] == "down_payment"][0]["detail"]
        self.assertIn("RE-0 特批", detail)

    def test_subject_to_12pct_no_hard_veto(self):
        # v1.2 起商业 subject-to 首付无 8%/15% 硬否决
        s = com.score(base_commercial(structure="subject_to", down_payment=120000))
        self.assertEqual(s["vetoes"], [])
        self.assertAlmostEqual(dp_points(s), 7.3, places=1)


class TestFlipSoftenedExtra(unittest.TestCase):
    """v1.3 抛售软化补充：风险旗不影响打分维度之外的等级，且 refi 字段经 API 校验."""

    def test_flip_flag_costs_risk_points_only(self):
        # 同一 deal：挂抛售旗 vs 不挂——总分差恰好是风险维度的 3 分扣分
        a = com.score(base_commercial(exit_flip_dependent_only=True, refi_cashout_viable=True))
        b = com.score(base_commercial(exit_flip_dependent_only=False))
        self.assertAlmostEqual(b["total"] - a["total"], 3.0, places=1)

    def test_flip_without_refi_flag_but_hold_viable_keeps_grade(self):
        s = com.score(base_commercial(exit_flip_dependent_only=True,
                                      refi_cashout_viable=False))
        self.assertIn(s["grade"], ("A", "B", "C"))


class TestNegativeEquityExtra(unittest.TestCase):
    """v2.3/v1.3 负净值风险旗补充：零净值无旗；负净值旗不叠加扣分之外的否决."""

    def test_zero_equity_no_flag(self):
        s = res.score(base_residential(price=154463))  # 贷款 154463 == 价格 → 零净值
        risk_detail = [d for d in s["dimensions"] if d["key"] == "risk"][0]["detail"]
        self.assertNotIn("负净值入场", risk_detail)
        self.assertEqual(s["vetoes"], [])

    def test_negative_equity_commercial_flag_costs_only_risk_points(self):
        a = com.score(base_commercial(as_is_appraisal=900000))
        b = com.score(base_commercial(as_is_appraisal=1100000))
        self.assertAlmostEqual(b["total"] - a["total"], 3.0, places=1)


if __name__ == "__main__":
    unittest.main()
