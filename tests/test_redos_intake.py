"""ReDoS（CodeQL py/polynomial-redos）：病态长文本不能把 PDF 抽取拖成平方级。

正则只从数字串开头起匹配（结果与原来相同：数字串中间起的匹配必然同终点），
单元号限 20 字符。
"""
from __future__ import annotations

import time

import pytest

from app.domain import validators
from app.services import pdf_intake

N = 40_000
EVIL = ["," * N, "9" * N, "." * N, "Unit" * (N // 4), "total " + "," * N]


@pytest.mark.parametrize("text", EVIL, ids=["commas", "nines", "dots", "units", "total-line"])
def test_pathological_text_is_linear(text):
    t0 = time.perf_counter()
    pdf_intake.parse_pdf_text(text, "x.pdf")
    pdf_intake.parse_commercial_pdf_text(text, "x.pdf")
    validators._sf_on_lines(text)
    assert time.perf_counter() - t0 < 2.0


def test_normal_text_still_parses():
    txt = "Asking $1,250,000\n3 bed 2.5 bath 1,850 sq ft\nSuite 101 Coffee Co 1,200 SF $4,000\n"
    keys = {f["key"]: f["value"] for f in pdf_intake.parse_pdf_text(txt, "x.pdf")["fields"]}
    assert keys.get("building_sf") == 1850 and keys.get("beds") == 3 and keys.get("baths") == 2.5
    assert validators._sf_on_lines("Total rentable 12,500 SF") == [(12500.0, "Total rentable 12,500 SF")]
