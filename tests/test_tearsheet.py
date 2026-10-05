"""一键 Tear Sheet 测试（台账 2026-10-05 待做第 1 项）。

覆盖：
1. build_tearsheet_data：39-09 Main St 模板示例 → 12 个关键指标齐全、
   highlights 恰好 3 条、next_step 非空；规则引擎：DSCR<1.0 触发"危"、
   数据缺口触发补数建议。
2. build_tearsheet_pdf：有效 PDF 且严格 1 页；文本层含 TEAR SHEET/DSCR/
   全口径现金需求；空白输入不崩且含诚实 "—" 标注。
3. /api/uw/tearsheet：返回 application/pdf，1 页。
4. 备忘录封面页：cover_tearsheet=True 比无封面多 1 页，首页含 TEAR SHEET。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import pdf_uw, tearsheet, uw_commercial  # noqa: E402


def _example():
    d = uw_commercial.example_39_main()
    d["analysis"]["amort_type"] = "AMORTIZING"  # 诚实口径：本息摊还
    return uw_commercial.compute_all(d)


def _deal(r):
    return {"name": "39-09 Main St", "address": "39-09 Main St, Flushing NY",
            "has_rent_roll": True}


def _text(pdf_bytes: bytes) -> str:
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    return "\n".join(p.get_text() for p in doc)


def _pages(pdf_bytes: bytes) -> int:
    from pypdf import PdfReader
    import io
    return len(PdfReader(io.BytesIO(pdf_bytes)).pages)


class TestTearsheetData(unittest.TestCase):
    def test_key_metrics_present(self):
        data = tearsheet.build_tearsheet_data(_example(), _deal(_example()))
        labels = [m[0] for m in data["metrics"]]
        for want in ("收购价", "在手 NOI", "预测 NOI", "在手 Cap Rate",
                     "全口径现金需求", "月供（本息）", "DSCR（预测）",
                     "DSCR（在手）", "盈亏平衡出租率", "预测现金回报",
                     "持有期 IRR", "股本倍数"):
            self.assertIn(want, labels, f"关键指标缺失：{want}")
        vals = dict(data["metrics"])
        # 39-09 Main：$42M 收购价必须印出来（非 —）
        self.assertEqual(vals["收购价"], "$42,000,000")
        self.assertNotEqual(vals["DSCR（预测）"], "—")

    def test_exactly_three_highlights_and_next_step(self):
        data = tearsheet.build_tearsheet_data(_example(), _deal(_example()))
        self.assertEqual(len(data["highlights"]), 3)
        self.assertTrue(all(h["text"] for h in data["highlights"]))
        self.assertTrue(data["next_step"])
        # 39-09 Main 预测 DSCR 1.13 → 应有一条 DSCR 警告
        joined = " ".join(h["text"] for h in data["highlights"])
        self.assertIn("DSCR", joined)

    def test_dscr_critical_rule(self):
        d = uw_commercial.example_39_main()
        d["analysis"]["rate"] = 12  # 高利率压垮 DSCR
        r = uw_commercial.compute_all(d)
        data = tearsheet.build_tearsheet_data(r, _deal(r))
        levels = [h["level"] for h in data["highlights"]]
        self.assertIn("危", levels)
        self.assertIn("放弃或重谈价格", data["next_step"])

    def test_data_gap_honesty(self):
        r = uw_commercial.compute_all(uw_commercial.default_inputs())
        data = tearsheet.build_tearsheet_data(r, {"has_rent_roll": False})
        vals = dict(data["metrics"])
        self.assertEqual(vals["收购价"], "—", "缺收购价不许印 $0")
        self.assertEqual(vals["DSCR（预测）"], "—", "缺数 DSCR 不许印 0.00×")
        self.assertIn("补齐缺失字段", data["next_step"])
        self.assertIn("危", [h["level"] for h in data["highlights"]])


class TestTearsheetPdf(unittest.TestCase):
    def test_standalone_is_exactly_one_page(self):
        r = _example()
        pdf = tearsheet.build_tearsheet_pdf(r, _deal(r))
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertEqual(_pages(pdf), 1, "一页纸必须严格 1 页")

    def test_standalone_text_layer(self):
        text = _text(tearsheet.build_tearsheet_pdf(_example(), _deal(_example())))
        for want in ("TEAR SHEET", "DSCR", "全口径现金需求", "下一步建议",
                     "$42,000,000"):
            self.assertIn(want, text, f"文本层缺失：{want}")

    def test_blank_input_no_crash(self):
        r = uw_commercial.compute_all(uw_commercial.default_inputs())
        pdf = tearsheet.build_tearsheet_pdf(r, {"has_rent_roll": False})
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertEqual(_pages(pdf), 1)
        self.assertIn("—", _text(pdf), "缺数必须渲染 —")

    def test_memo_cover_adds_one_page(self):
        r = _example()
        deal = {"name": "39-09 Main St", "address": "39-09 Main St",
                "has_rent_roll": True}
        plain = pdf_uw.build_uw_pdf(r, "enhanced", deal=deal)
        covered = pdf_uw.build_uw_pdf(r, "enhanced", deal=deal,
                                      cover_tearsheet=True)
        self.assertEqual(_pages(covered), _pages(plain) + 1,
                         "备忘录封面页应多 1 页")
        import fitz
        first = fitz.open(stream=covered, filetype="pdf")[0].get_text()
        self.assertIn("TEAR SHEET", first, "首页应为 Tear Sheet")


class TestTearsheetEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from app.main import app
        cls.client = TestClient(app)

    def test_endpoint_returns_pdf(self):
        d = uw_commercial.example_39_main()
        r = self.client.post("/api/uw/tearsheet",
                             json={"input": d, "name": "39-09 Main St",
                                   "address": "39-09 Main St"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("application/pdf", r.headers["content-type"])
        self.assertEqual(_pages(r.content), 1)

    def test_endpoint_blank_input(self):
        r = self.client.post("/api/uw/tearsheet",
                             json={"input": uw_commercial.default_inputs()})
        self.assertEqual(r.status_code, 200)
        self.assertIn("application/pdf", r.headers["content-type"])


if __name__ == "__main__":
    unittest.main()
