"""DealDesk 报告图表测试（标准库 unittest）.

覆盖：
1. charts.prep_* 数据准备：种子数据能算出序列；缺数返回 None（不编数）。
2. svg_* 输出为合法 SVG；缺数时渲染"—"占位。
3. png_* 输出为合法 PNG；中文不依赖外部资源（仓库自带字体）。
4. report_narrative 导语/结论：关键数字落字、不崩；否决项目有结论句。

运行：.venv/bin/python -m pytest tests/test_charts.py -q
"""

import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import charts, report_narrative, sensitivity  # noqa: E402
from app import scoring_commercial as com  # noqa: E402
from app import scoring_residential as res  # noqa: E402
from test_scoring import base_commercial, base_residential  # noqa: E402


def _B(t):
    return f"<b>{t}</b>"


def _T(t):
    return t


class TestChartPrep(unittest.TestCase):
    def test_cashflow_residential(self):
        s = res.score(base_residential())
        prep = charts.prep_cashflow("residential", s["metrics"])
        self.assertIsNotNone(prep)
        self.assertEqual(len(prep["cumulative"]), 11)
        # 起点 = -现金投入
        self.assertAlmostEqual(prep["cumulative"][0],
                               -s["metrics"]["cash_invested"], places=0)
        self.assertIsNotNone(prep["breakeven"])

    def test_cashflow_commercial(self):
        s = com.score(base_commercial())
        prep = charts.prep_cashflow("commercial", s["metrics"])
        self.assertIsNotNone(prep)
        self.assertEqual(len(prep["cumulative"]), 11)

    def test_cashflow_missing(self):
        self.assertIsNone(charts.prep_cashflow("residential", {}))
        self.assertIsNone(charts.prep_cashflow("residential",
                                               {"cash_flow_monthly": 100}))

    def test_sensitivity(self):
        d = base_residential()
        prep = charts.prep_sensitivity("residential", sensitivity.run("residential", d))
        self.assertIsNotNone(prep)
        self.assertEqual(len(prep["rent"]), 5)
        self.assertEqual(len(prep["rate"]), 5)
        self.assertEqual(prep["rent"][2]["label"], "基准")

    def test_sensitivity_missing(self):
        self.assertIsNone(charts.prep_sensitivity("residential", None))
        self.assertIsNone(charts.prep_sensitivity("residential", {}))

    def test_dimensions(self):
        s = res.score(base_residential())
        dims = charts.prep_dimensions(s["dimensions"])
        self.assertEqual(len(dims), len(s["dimensions"]))
        for x in dims:
            self.assertGreaterEqual(x["ratio"], 0.0)
            self.assertLessEqual(x["ratio"], 1.0)


class TestChartRender(unittest.TestCase):
    def setUp(self):
        d = base_residential()
        s = res.score(d)
        self.cf = charts.prep_cashflow("residential", s["metrics"])
        self.sp = charts.prep_sensitivity(
            "residential", sensitivity.run("residential", d))
        self.dm = charts.prep_dimensions(s["dimensions"])

    def test_svg_wellformed(self):
        for svg in (charts.svg_cashflow(self.cf),
                    charts.svg_sensitivity(self.sp),
                    charts.svg_dimensions(self.dm)):
            self.assertTrue(svg.startswith("<svg"))
            self.assertTrue(svg.rstrip().endswith("</svg>"))

    def test_svg_placeholder(self):
        for svg in (charts.svg_cashflow(None),
                    charts.svg_sensitivity(None),
                    charts.svg_dimensions([])):
            self.assertIn("—", svg)
            self.assertTrue(svg.rstrip().endswith("</svg>"))

    def test_png_valid(self):
        for buf in (charts.png_cashflow(self.cf),
                    charts.png_sensitivity(self.sp),
                    charts.png_dimensions(self.dm),
                    charts.png_cashflow(None)):
            self.assertTrue(isinstance(buf, io.BytesIO))
            self.assertEqual(buf.read(8), b"\x89PNG\r\n\x1a\n")

    def test_png_no_tofu_font(self):
        # 仓库字体存在且可加载（中文不方框的前提）
        self.assertTrue(os.path.exists(charts._FONT_PATH))


class TestNarrative(unittest.TestCase):
    def _project(self, d, track, name="测试项目"):
        s = (res if track == "residential" else com).score(d)
        return {"track": track, "name": name, "address": "1 Test Rd",
                "input": d, "score": s}

    def test_lead_has_numbers(self):
        p = self._project(base_residential(), "residential")
        paras = report_narrative.lead_paragraphs(p, _B, _T)
        self.assertGreaterEqual(len(paras), 2)
        text = "".join(paras)
        self.assertIn(str(p["score"]["total"]), text)
        self.assertIn("1 Test Rd", text)

    def test_conclusion_grades(self):
        p = self._project(base_residential(), "residential")
        text = "".join(report_narrative.conclusion_paragraphs(p, _B, _T))
        self.assertIn("结论", text)

    def test_conclusion_veto(self):
        d = base_residential(rent_source="proforma")
        p = self._project(d, "residential")
        self.assertEqual(p["score"]["grade"], "否决")
        text = "".join(report_narrative.conclusion_paragraphs(p, _B, _T))
        self.assertIn("一票否决", text)

    def test_conclusion_commercial(self):
        p = self._project(base_commercial(), "commercial")
        text = "".join(report_narrative.conclusion_paragraphs(p, _B, _T)
                       + report_narrative.lead_paragraphs(p, _B, _T))
        self.assertIn("结论", text)


if __name__ == "__main__":
    unittest.main()
