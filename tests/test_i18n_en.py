"""EN 界面（2026-10-16，PH launch 阻塞项）后端 lang 测试。

守三件事：
1. lang="en" 时 verdict / veto / confidence / compute-plus 的用户可见叙事文案为英文；
2. verdict 档位词、分数、结构等机读口径与 zh 完全一致（只换文案不换逻辑）；
3. 默认（不传 lang）中文逐字不变——零回归。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from app import commercial_plus as cp
from app import confidence, scoring_residential, uw_commercial, verdict
from app.main import app

client = TestClient(app)


def _score(total=85, vetoes=None):
    return {"total": total, "grade": "A",
            "vetoes": vetoes or [],
            "metrics": {"cash_flow_monthly": 320, "dscr": 1.35}}


class TestVerdictEN:
    def test_veto_reason_and_usage_en(self):
        v = verdict.verdict("residential",
                            _score(85, [{"code": "x", "message": "hard flaw"}]),
                            72, {}, lang="en")
        assert v["verdict"] == "别碰"  # 档位词 canonical 不动（前端双语渲染）
        assert any(r.startswith("Veto: ") for r in v["reasons"])
        assert v["usage"] == "Screening aid only — not investment advice."

    def test_circuit_breaker_en(self):
        v = verdict.verdict("residential", _score(85), 35, {}, lang="en")
        assert v["verdict"] == "Insufficient data — manual review required"
        assert v["circuit_broken"]
        assert "Circuit breaker" in v["reasons"][-1]
        assert "Too little evidence" in v["one_liner"]

    def test_p0_downgrade_reason_en(self):
        v = verdict.verdict("residential", _score(85), 72,
                            {"p0_gaps": ["No structured rent roll"]}, lang="en")
        assert v["verdict"] == "再看看"
        assert any("downgraded one notch" in r for r in v["reasons"])

    def test_commercial_buy_one_liner_en(self):
        v = verdict.verdict("commercial", _score(85), 72, {}, lang="en")
        assert v["verdict"] == "BUY"
        assert v["one_liner"].startswith("Price, cash flow and leverage")

    def test_default_zh_unchanged(self):
        v = verdict.verdict("residential", _score(85), 35, {})
        assert v["verdict"] == "数据不足，需人工评估"
        assert v["usage"] == "筛选辅助工具，不构成投资建议。"


class TestVetoEN:
    def test_subject_to_vetoes_en(self):
        d = {"rate_type": "fixed", "structure": "subject_to",
             "insurance_available": True}
        codes = {v["code"]: v["message"]
                 for v in scoring_residential.check_vetoes(d, {}, lang="en")}
        assert codes["no_exit"].startswith("No-exit-plan veto")
        assert codes["no_dos_plan"].startswith("No due-on-sale backup-plan veto")

    def test_subject_to_vetoes_zh_default(self):
        d = {"rate_type": "fixed", "structure": "subject_to",
             "insurance_available": True}
        codes = {v["code"]: v["message"]
                 for v in scoring_residential.check_vetoes(d, {})}
        assert "无退出预案否决" in codes["no_exit"]


class TestConfidenceEN:
    def test_labels_and_notes_en_same_score(self):
        comps = [{"sale_date": "2026-06-01", "price": 500000, "sf": 1200,
                  "adjustment_pct": 3, "distance_miles": 0.8}] * 5
        zh = confidence.compute("residential", comps, {})
        en = confidence.compute("residential", comps, {}, lang="en")
        assert en["score"] == zh["score"]
        assert en["factors"]["comps_nq"]["label"] == "Comps count & quality"
        assert "high-quality comps" in en["factors"]["comps_nq"]["note"]
        assert en["label"] != zh["label"]


class TestCommercialPlusEN:
    def test_labels_en(self):
        out = cp.compute_plus(uw_commercial.example_39_main(),
                              with_stress=True, lang="en")
        plus = out["plus"]
        assert "Bank-basis NOI" in plus["dscr_dual"]["trailing"]["label"]
        items = [r["item"] for r in plus["noi_bank_bridge"]["rows"]]
        assert items[-1] == "Bank-basis NOI"
        scenarios = [r["scenario"] for r in plus["stress"]["rows"]]
        assert scenarios[0] == "Base"
        assert any(s.startswith("Rate +") for s in scenarios)

    def test_default_zh(self):
        out = cp.compute_plus(uw_commercial.example_39_main(), with_stress=False)
        assert "银行口径 NOI" in out["plus"]["dscr_dual"]["trailing"]["label"]


class TestApiLang:
    def test_verdict_api_en(self):
        r = client.post("/api/verdict", json={
            "track": "residential", "score": _score(85), "confidence": 35,
            "evidence": {}, "lang": "en"})
        assert r.status_code == 200
        assert r.json()["verdict"] == "Insufficient data — manual review required"

    def test_score_api_en_veto(self):
        r = client.post("/api/score", json={
            "track": "residential", "name": "t", "address": "t",
            "input": {"price": 500000, "monthly_rent": 3000, "rate": 6.5,
                      "structure": "subject_to"},
            "lang": "en"})
        assert r.status_code == 200
        msgs = [v["message"] for v in r.json()["vetoes"]]
        assert any(m.startswith("No-exit-plan veto") for m in msgs)
