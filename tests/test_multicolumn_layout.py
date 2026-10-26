"""PDF 多栏版式阅读顺序校验测试。

背景：pypdf extract_text 按内容流顺序拼接，双栏 flyer 的内容流常逐行
交错左右栏，数字可能错位。现实现：visitor 坐标采集 → 双栏检测
（中部无片段跨越的空槽）→ 按栏重排（左栏自上而下 → 右栏）→ 结果附
layout / layout_notice 诚实标注（多栏已重排、请人工复核关键字段）。

诚实边界：真实双栏 OM 样本本轮未获取（公网检索被本机沙箱出口挡），
本测试用高仿真合成双栏件（reportlab 按行交错绘制，模拟 InDesign 类
导出顺序）验证检测/重排/提取链路；生产对真实多栏件走同一路径。
"""

from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import pdf_intake

LEFT_LINES = [
    "1500 Atlantic Ave",
    "Offering Price: $4,350,000",
    "Building: 12,500 SF",
    "In-Place NOI: $285,000",
    "Cap Rate 6.55%",
    "Built 1928",
]
RIGHT_LINES = [
    "Suite 1A Laundromat",
    "Suite 2B Pizzeria",
    "Suite 3C Deli Mart",
    "Suite 4D Pharmacy",
    "Value-add upside",
    "Motivated seller",
]


def _twocol_pdf_bytes() -> bytes:
    """双栏 flyer：内容流逐行交错绘制（L1,R1,L2,R2…），模拟真实导出顺序。"""
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)  # letter 612x792
    y = 720
    for l, r in zip(LEFT_LINES, RIGHT_LINES):
        c.drawString(50, y, l)
        c.drawString(330, y, r)
        y -= 22
    c.save()
    return buf.getvalue()


def _onecol_pdf_bytes() -> bytes:
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    y = 720
    for ln in LEFT_LINES:
        c.drawString(72, y, ln)
        y -= 20
    c.save()
    return buf.getvalue()


def test_naive_extraction_interleaves_columns(tmp_path):
    """先证危害真实存在：朴素提取的文本里右栏行插进左栏中间。"""
    p = tmp_path / "twocol.pdf"
    p.write_bytes(_twocol_pdf_bytes())
    pages, note = pdf_intake.extract_text_pages(str(p))
    assert pages and not note
    text = pages[0]
    # 左栏第 2 行（价格）之后紧跟的不应是左栏第 3 行——内容流交错使然
    assert text.index("Suite 1A") < text.index("Building: 12,500 SF")


def test_detect_and_rebuild_column_major(tmp_path):
    p = tmp_path / "twocol.pdf"
    p.write_bytes(_twocol_pdf_bytes())
    info = pdf_intake.analyze_pdf_layout(str(p))
    assert info["multi_column_pages"] == [1]
    entry = info["pages"][0]
    assert entry["columns"] == 2
    assert entry["interleaved"] is True
    rebuilt = entry["rebuilt_text"]
    # 按栏重排：全部左栏行在全部右栏行之前
    assert rebuilt.index("Cap Rate") < rebuilt.index("Suite 1A")
    assert rebuilt.index("In-Place NOI") < rebuilt.index("Motivated seller")


def test_upload_applies_layout_and_extracts_correctly(tmp_path):
    p = tmp_path / "twocol.pdf"
    p.write_bytes(_twocol_pdf_bytes())
    d = pdf_intake.run_commercial_pdf_upload(str(p), "twocol.pdf")
    flat = {f["key"]: f for f in d["fields"]}
    assert flat["analysis.purchase_price"]["value"] == 4350000
    assert flat["analysis.underwritten_noi"]["value"] == 285000
    assert flat["property.net_rentable_sf"]["value"] == 12500
    # 诚实标注在位：多栏页 + 已重排 + 人工复核提示
    assert d["layout"]["multi_column_pages"] == [1]
    assert d["layout"]["rebuilt_pages"] == [1]
    assert "人工复核" in d["layout_notice"]


def test_single_column_no_layout_flag(tmp_path):
    p = tmp_path / "onecol.pdf"
    p.write_bytes(_onecol_pdf_bytes())
    info = pdf_intake.analyze_pdf_layout(str(p))
    assert info["multi_column_pages"] == []
    d = pdf_intake.run_commercial_pdf_upload(str(p), "onecol.pdf")
    assert "layout_notice" not in d
    flat = {f["key"]: f for f in d["fields"]}
    assert flat["analysis.purchase_price"]["value"] == 4350000
