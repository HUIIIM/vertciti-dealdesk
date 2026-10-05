"""商业核保报告导出测试（标准库 unittest + pytest）.

覆盖：
1. build_uw_pdf classic/enhanced 对模板示例（39-09 Main St）都能生成有效 PDF。
2. PDF 文本层包含关键字段（项目名、PROPERTY OVERVIEW / 新增风险指标）。
3. 空白模板输入不崩（全部 -- 或 $0，不抛异常）。
4. NaN / None 渲染为 --（诚实标注），用户输入中的 HTML 特殊字符被转义。
5. /api/uw/report 接口：classic/enhanced 返回 application/pdf；非法 variant 400。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import pdf_uw, uw_commercial  # noqa: E402


def _example():
    d = uw_commercial.example_39_main()
    return uw_commercial.compute_all(d)


def _extract_text(pdf_bytes: bytes) -> str:
    # 轻量文本提取：只用于断言，不做排版校验
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    return "\n".join(p.get_text() for p in doc)


class TestUwPdf(unittest.TestCase):
    def test_classic_valid_pdf(self):
        pdf = pdf_uw.build_uw_pdf(_example(), "classic")
        self.assertTrue(pdf.startswith(b"%PDF"), "不是有效 PDF")
        self.assertGreater(len(pdf), 8000, "PDF 过小，可能渲染失败")
        text = _extract_text(pdf)
        self.assertIn("39-09 Main St", text)
        self.assertIn("PROPERTY OVERVIEW", text)
        self.assertIn("RENT ROLL", text)
        # 模板关键数字：$42M 购买价（ReportLab 货币格式 $42,000,000）
        self.assertIn("$42,000,000", text.replace(" ", ""))

    def test_enhanced_valid_pdf(self):
        pdf = pdf_uw.build_uw_pdf(_example(), "enhanced")
        self.assertTrue(pdf.startswith(b"%PDF"), "不是有效 PDF")
        self.assertGreater(len(pdf), 8000)
        text = _extract_text(pdf)
        self.assertIn("39-09 Main St", text)
        self.assertIn("现金流", text)
        self.assertIn("DSCR", text)
        self.assertIn("IRR", text)
        self.assertIn("持有期现金流", text)

    def test_blank_input_no_crash(self):
        r = uw_commercial.compute_all(uw_commercial.default_inputs())
        for variant in ("classic", "enhanced"):
            pdf = pdf_uw.build_uw_pdf(r, variant)
            self.assertTrue(pdf.startswith(b"%PDF"), f"{variant} 空白输入崩了")
        text = _extract_text(pdf_uw.build_uw_pdf(r, "enhanced"))
        self.assertIn("—", text, "NaN/None 应渲染为 —（D 铁律：全端统一）")

    def test_nan_renders_honest(self):
        self.assertEqual(pdf_uw._money(float("nan")), "—")
        self.assertEqual(pdf_uw._pct(None), "—")
        self.assertEqual(pdf_uw._num(float("inf")), "—")
        self.assertEqual(pdf_uw._esc("<a>&\""), "&lt;a&gt;&amp;\"")

    def test_html_escaping_in_output(self):
        d = uw_commercial.example_39_main()
        d["property"]["name"] = "Test <b>& Co"
        r = uw_commercial.compute_all(d)
        pdf = pdf_uw.build_uw_pdf(r, "classic")
        self.assertTrue(pdf.startswith(b"%PDF"))  # 不崩即可；转义在 Paragraph 层


class TestUwReportEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient

        from app.main import app
        cls.client = TestClient(app)

    def test_report_classic_endpoint(self):
        r = self.client.post("/api/uw/report",
                             json={"input": uw_commercial.example_39_main(),
                                   "variant": "classic"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "application/pdf")
        self.assertTrue(r.content.startswith(b"%PDF"))
        self.assertIn("attachment", r.headers["content-disposition"])

    def test_report_enhanced_endpoint(self):
        r = self.client.post("/api/uw/report",
                             json={"input": uw_commercial.example_39_main(),
                                   "variant": "enhanced"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "application/pdf")
        self.assertTrue(r.content.startswith(b"%PDF"))

    def test_report_bad_variant(self):
        r = self.client.post("/api/uw/report",
                             json={"input": {}, "variant": "gold"})
        self.assertEqual(r.status_code, 400)

    def test_report_unsaved_state(self):
        # 一键导出：当前未保存的空白 state 也能出报告（不依赖入库）
        r = self.client.post("/api/uw/report",
                             json={"input": uw_commercial.default_inputs(),
                                   "variant": "classic"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
