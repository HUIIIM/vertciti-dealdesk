"""DealDesk PDF 备忘录测试（标准库 unittest）.

覆盖：
1. pdf_report.build_pdf 对住宅/商业/否决项目都能生成有效 PDF 字节流。
2. PDF 内容包含项目名（文本可提取）。
3. /api/projects/{pid}/pdf 接口返回 application/pdf。

运行：.venv/bin/python -m pytest tests/test_pdf.py -q
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["DEALDESK_DB"] = os.path.join(os.path.dirname(__file__), "test-pdf.db")

from app import db, pdf_report  # noqa: E402
from app import scoring_commercial as com  # noqa: E402
from app import scoring_residential as res  # noqa: E402
from test_scoring import base_commercial, base_residential  # noqa: E402


def _fresh_db():
    p = os.environ["DEALDESK_DB"]
    if os.path.exists(p):
        os.remove(p)
    db.init_db()


class TestPdfReport(unittest.TestCase):
    def test_residential_pdf(self):
        _fresh_db()
        d = base_residential()
        p = db.create_project("residential", "PDF 测试住宅", "1 Test Rd, Queens, NY",
                              d, res.score(d))
        pdf = pdf_report.build_pdf(p)
        self.assertTrue(pdf.startswith(b"%PDF"), "不是有效 PDF")
        self.assertGreater(len(pdf), 10000, "PDF 过小，可能渲染失败")

    def test_veto_pdf(self):
        _fresh_db()
        d = base_residential(rent_source="proforma")
        s = res.score(d)
        self.assertEqual(s["grade"], "否决")
        p = db.create_project("residential", "PDF 否决测试", "2 Test Rd, Bronx, NY",
                              d, s)
        pdf = pdf_report.build_pdf(p)
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_commercial_pdf(self):
        _fresh_db()
        d = base_commercial()
        p = db.create_project("commercial", "PDF 测试商业", "3 Test Blvd, Manhattan, NY",
                              d, com.score(d))
        pdf = pdf_report.build_pdf(p)
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_pdf_contains_project_name(self):
        _fresh_db()
        d = base_residential()
        p = db.create_project("residential", "Queens 双拼 PDFNAME", "1 Test Rd, Queens, NY",
                              d, res.score(d))
        pdf = pdf_report.build_pdf(p)
        # 子集字体用自定义编码，用 pymupdf 提文本验证
        import pymupdf, tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(pdf)
            path = f.name
        try:
            doc = pymupdf.open(path)
            text = "".join(page.get_text() for page in doc)
        finally:
            os.remove(path)
        self.assertIn("PDFNAME", text)
        self.assertIn("Queens", text)

    def test_pdf_api_endpoint(self):
        _fresh_db()
        from fastapi.testclient import TestClient
        from app.main import app
        d = base_residential()
        p = db.create_project("residential", "API PDF 测试", "1 Test Rd, Queens, NY",
                              d, res.score(d))
        client = TestClient(app)
        r = client.get(f"/api/projects/{p['id']}/pdf")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "application/pdf")
        self.assertTrue(r.content.startswith(b"%PDF"))
        self.assertIn("attachment", r.headers.get("content-disposition", ""))
        # 404
        r2 = client.get("/api/projects/999999/pdf")
        self.assertEqual(r2.status_code, 404)


if __name__ == "__main__":
    unittest.main()
