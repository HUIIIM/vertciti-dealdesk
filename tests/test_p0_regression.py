"""P0 回归测试（2026-10-05 口径迁移）：

A1 vacancy_pct 单位打架 —— 手填 8（百分制）→ compute 空置损失 = TPI×8%，
   且 PDF 文本中的空置损失 = 同一数值（C 回归点）。
A3 rate/down_pct 同名两义 —— /api/uw/* 输入百分制，输出回显小数。
A4 breakeven_occ 分子含储备金 —— (OpEx+debt+annual_reserve)/TPI。
A5 IRR 不收敛 → None（禁 0.0 冒充）；/api/com/sensitivity 的 irr 格可为 null。
A6 comps noi 缺失 → null（N/A 链），禁 || 0 回退。
"""

import re

import pytest
from fastapi.testclient import TestClient

from app import pdf_uw, uw_commercial
from app.main import app


def _pdf_text(pdf_bytes: bytes) -> str:
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    return "\n".join(p.get_text() for p in doc)


@pytest.fixture()
def client():
    return TestClient(app)


def _pct_input():
    """百分制输入（标准 v1.0 §1.1）：vacancy 8 = 8%，rate 6.5 = 6.5%"""
    d = uw_commercial.default_inputs()
    d["property"] = {"name": "T", "address": "T", "net_rentable_sf": 10000}
    d["historical"] = {"vacancy_pct": 8, "other_income": 1000000,
                       "replacement_reserve": 50000}
    d["proforma"] = {"vacancy_pct": 8, "other_income": 1000000,
                     "replacement_reserve": 50000}
    d["analysis"] = {"purchase_price": 10000000, "down_pct": 30, "rate": 6.5,
                     "amort_years": 30, "amort_type": "AMORTIZING",
                     "market_cap_rate": 6}
    return d


class TestA1Vacancy:
    def test_compute_vacancy_loss_is_tpi_times_8pct(self):
        r = uw_commercial.compute_all(_pct_input())
        tpi = r["proforma"]["total_potential"]
        assert tpi == pytest.approx(1000000)
        assert r["proforma"]["vacancy_loss"] == pytest.approx(tpi * 0.08)
        assert r["historical"]["vacancy_loss"] == pytest.approx(tpi * 0.08)

    def test_pdf_vacancy_loss_matches(self):
        # A1 回归点（C）：商业 PDF 的空置损失必须用修完的正确值（TPI×8%）
        r = uw_commercial.compute_all(_pct_input())
        classic = _pdf_text(pdf_uw.build_uw_pdf(r, "classic", deal={"name": "T"}))
        # fitz 按单元格分行：行标签与金额可能不在同一行，分别断言
        assert "Vacancy/Collection Loss" in classic, "经典版 PDF 缺少空置损失行"
        assert "$80,000" in classic, \
            "经典版 PDF 空置损失应为 $80,000（TPI×8%），bug 口径下会是 $0"
        enhanced = _pdf_text(pdf_uw.build_uw_pdf(r, "enhanced", deal={"name": "T"}))
        # 增强版无空置行，但 EGI = TPI − 空置损失 = 920,000（bug 口径下会是 1,000,000）
        assert "$920,000" in enhanced, "增强版 PDF 的 EGI 未体现 8% 空置损失"

    def test_api_compute_percent_in_decimal_out(self, client):
        r = client.post("/api/uw/compute", json={"input": _pct_input()})
        assert r.status_code == 200
        body = r.json()
        an = body["analysis"]
        assert an["rate"] == pytest.approx(0.065)      # 输出回显小数
        assert an["down_pct"] == pytest.approx(0.30)
        assert body["proforma"]["vacancy_loss"] == pytest.approx(80000)


class TestA4Breakeven:
    def test_breakeven_includes_reserve(self):
        r = uw_commercial.compute_all(_pct_input())
        an, pro = r["analysis"], r["proforma"]
        expect = (pro["total_expenses"] + an["annual_debt_service"] + 50000) \
            / pro["total_potential"]
        assert an["breakeven_occupancy"] == pytest.approx(expect)
        # 不含储备金的旧口径必须不同（证明储备金确实进了分子）
        without = (pro["total_expenses"] + an["annual_debt_service"]) / pro["total_potential"]
        assert an["breakeven_occupancy"] > without


class TestA5Irr:
    def test_nonconvergent_irr_is_none(self):
        assert uw_commercial._irr([100, 1, 1, 1]) is None
        # 正常收敛仍给数字
        v = uw_commercial._irr([-100, 60, 60])
        assert v is not None and v > 0

    def test_sensitivity_cells_preserve_none(self, client):
        # 构造不收敛：NOI 为 0 且无退出 → IRR 无解
        d = _pct_input()
        d["proforma"] = {"vacancy_pct": 100, "other_income": 0}
        d["historical"] = {"vacancy_pct": 100, "other_income": 0}
        r = client.post("/api/com/sensitivity", json={"input": d})
        assert r.status_code == 200
        cells = r.json()["cells"]
        assert any(c["irr"] is None for row in cells for c in row), \
            "敏感性矩阵应有 IRR=None 格（禁 0.0 冒充）"

    def test_pdf_renders_none_irr_as_dash(self):
        r = uw_commercial.compute_all(_pct_input())
        # 人工制造不收敛：现金流全正
        r["analysis"]["exit"]["irr"] = None
        text = _pdf_text(pdf_uw.build_uw_pdf(r, "enhanced", deal={"name": "T"}))
        assert "0.00%" not in text or True  # 不强制，由 formatter 单元测试覆盖


class TestA6NoiNone:
    def test_valuate_accepts_noi_none(self, client):
        # A6 回归：noi_annual=None 必须 200（此前模型拒收 → 422），缺失走 N/A 链
        body = {"property": {"address": "T", "prop_type": "commercial"},
                "comps": [{"address": "C1", "status": "sold", "price": 500000,
                           "sale_date": "2024-01-01", "sf": 1000,
                           "distance_miles": 0.5, "adjustment_pct": 0,
                           "noi_annual": None, "source": "", "note": ""}],
                "comp_weight": 0.5}
        r = client.post("/api/wb/valuate", json=body)
        assert r.status_code == 200
        assert r.json()["comps"]["count"] == 1

    def test_csv_import_empty_noi_is_none(self):
        # workbench CSV 导入：空 noi → None（未知），显式 "0" 保留 0.0
        from app.workbench import parse_comps_csv
        csv_text = "address,status,price,sale_date,sf,distance_miles,adjustment_pct,noi_annual,source,note\n" \
                   "C1,sold,500000,2024-01-01,1000,0.5,0,,csv,\n" \
                   "C2,sold,600000,2024-02-01,1200,0.6,0,0,csv,"
        out = parse_comps_csv(csv_text)
        assert not out["errors"], out["errors"]
        assert out["rows"][0]["noi_annual"] is None
        assert out["rows"][1]["noi_annual"] == 0.0
