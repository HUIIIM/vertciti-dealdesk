"""前后端计算黄金样本对照测试（台账第 13 项，P0，2026-10-15）。

目的：`static/uw-commercial.js` 的 JS 计算引擎自称与 `app/uw_commercial.py`
「逐公式对应」，此前无任何机制守住——后端改了口径前端静默漂移
（实证：第 10 项 amortPayment 前端按年复利、后端按月复利，年供差约 1.2%）。

机制：Node 抽取 JS 纯计算段（golden_js_runner.mjs）与后端 compute_all
跑同一批 fixture deal（tests/golden_fixtures.json，4 个：常态 /
退化输入 / 0 利率＋退出 cap 联动 / IO 高利率），逐比率对照
（cap/DSCR/debt_yield/IRR/月供/剩余本金等 24 个键路径）；
None（后端）与 NaN（前端，JSON 里为 null）同判为 N/A。

变异守卫：test_golden_mutation_turns_red 故意改坏前端月供公式一处，
对照必须变红——证明本对照真的能抓漂移，而不是恒绿摆设。

本项验收后原台账第 9 项（覆盖系统性错位）、第 10 项（amortisation
口径双轨）一并关闭：#10 的前端修复即在本项内完成（按月摊还对齐）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import uw_commercial

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FIXTURES = json.loads((HERE / "golden_fixtures.json").read_text())
RUNNER = HERE / "golden_js_runner.mjs"
JS_FILE = ROOT / "static" / "uw-commercial.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node 不可用，跳过 JS 对照")

GRID = [
    {"loan": 3045000, "rate_dec": 0.065, "years": 25, "after": 5},
    {"loan": 1000000, "rate_dec": 0.0, "years": 20, "after": 7},
    {"loan": 2240000, "rate_dec": 0.1275, "years": 30, "after": 10},
    {"loan": 500000, "rate_dec": 0.0325, "years": 15, "after": 15},
    {"loan": 750000, "rate_dec": 0.09, "years": 30, "after": 0},
]

# 对照键路径 → 口径类（money=金额容差，ratio=比率容差）
COMPARE_PATHS = {
    "rent_roll.total_annual_lease": "money",
    "rent_roll.total_annual_uw": "money",
    "rent_roll.occupancy": "ratio",
    "historical.noi": "money",
    "proforma.noi": "money",
    "proforma.total_expenses": "money",
    "analysis.loan_bal": "money",
    "analysis.net_liquidity": "money",
    "analysis.total_uses": "money",
    "analysis.annual_debt_service": "money",
    "analysis.inplace_cap": "ratio",
    "analysis.projected_noi": "money",
    "analysis.projected.dscr": "ratio",
    "analysis.inplace.dscr": "ratio",
    "analysis.breakeven_occupancy": "ratio",
    "analysis.roi": "ratio",
    "analysis.exit.sale_price": "money",
    "analysis.exit.remaining_loan": "money",
    "analysis.exit.sale_proceeds": "money",
    "analysis.exit.irr": "ratio",
    "analysis.exit.equity_multiple": "ratio",
    "per_sf.price_per_sf": "money",
    "per_sf.noi_per_sf": "money",
}


def _run_js(js_path: Path, tmp_path: Path) -> dict:
    jobs_file = tmp_path / "golden_jobs.json"
    jobs_file.write_text(json.dumps({"fixtures": FIXTURES, "grid": GRID}))
    proc = subprocess.run(
        [NODE, str(RUNNER), str(js_path), str(jobs_file)],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, f"JS runner failed: {proc.stderr[:500]}"
    return json.loads(proc.stdout)


def _get(d, path):
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _close(a, b, kind) -> bool:
    """None/NaN（JS 侧 JSON null）同判；数值按口径容差。"""
    if a is None or b is None:
        return a is None and b is None
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return a == b
    diff = abs(float(a) - float(b))
    if kind == "money":
        return diff <= max(0.02, 1e-6 * max(abs(float(a)), abs(float(b))))
    return diff <= max(1e-6, 1e-6 * max(abs(float(a)), abs(float(b))))


def _compare_fixture(name: str, backend: dict, js: dict) -> list[str]:
    bad = []
    for path, kind in COMPARE_PATHS.items():
        bv, jv = _get(backend, path), _get(js, path)
        if not _close(bv, jv, kind):
            bad.append(f"{name}:{path} backend={bv} js={jv}")
    # debt_yield（派生）：proforma NOI / 贷款额，两边各自从产出派生后对照
    for side, res in (("backend", backend), ("js", js)):
        pass
    b_noi, b_loan = _get(backend, "analysis.projected_noi"), _get(backend, "analysis.loan_bal")
    j_noi, j_loan = _get(js, "analysis.projected_noi"), _get(js, "analysis.loan_bal")
    b_dy = None if (b_noi is None or not b_loan) else b_noi / b_loan
    j_dy = None if (j_noi is None or not j_loan) else j_noi / j_loan
    if not _close(b_dy, j_dy, "ratio"):
        bad.append(f"{name}:debt_yield(derived) backend={b_dy} js={j_dy}")
    # 月供（派生）：年还贷额 / 12
    b_m = None if _get(backend, "analysis.annual_debt_service") is None \
        else _get(backend, "analysis.annual_debt_service") / 12
    j_m = None if _get(js, "analysis.annual_debt_service") is None \
        else _get(js, "analysis.annual_debt_service") / 12
    if not _close(b_m, j_m, "money"):
        bad.append(f"{name}:monthly_payment(derived) backend={b_m} js={j_m}")
    return bad


def test_golden_compare_all_fixtures(tmp_path):
    js_out = _run_js(JS_FILE, tmp_path)
    all_bad: list[str] = []
    for name, data in FIXTURES.items():
        backend = uw_commercial.compute_all(json.loads(json.dumps(data)))
        all_bad += _compare_fixture(name, backend, js_out["results"][name])
    assert not all_bad, "前后端漂移：\n" + "\n".join(all_bad)


def test_golden_helper_grid(tmp_path):
    """helper 级对照：amortPayment/remainingBal 网格（利率 0/中/高、到期/期初）。"""
    js_out = _run_js(JS_FILE, tmp_path)
    bad = []
    for g, jg in zip(GRID, js_out["grid"]):
        rate_pct = g["rate_dec"] * 100.0
        b_annual = uw_commercial.amort_payment(g["loan"], rate_pct, g["years"])
        b_balance = uw_commercial.remaining_balance(
            g["loan"], rate_pct, g["years"], b_annual, g["after"])
        if not _close(b_annual, jg["annual"], "money"):
            bad.append(f"grid{g}: annual backend={b_annual} js={jg['annual']}")
        if not _close(b_annual / 12, jg["monthly"], "money"):
            bad.append(f"grid{g}: monthly backend={b_annual / 12} js={jg['monthly']}")
        if not _close(b_balance, jg["balance"], "money"):
            bad.append(f"grid{g}: balance backend={b_balance} js={jg['balance']}")
    assert not bad, "helper 漂移：\n" + "\n".join(bad)


def test_golden_mutation_turns_red(tmp_path):
    """变异守卫：故意改坏前端月供公式（月利率 /12 → /11），对照必须变红。"""
    src = JS_FILE.read_text()
    anchor = "const r = rate / 12, m = n * 12;"
    assert anchor in src, "变异锚点不在（amortPayment 结构已变，更新本测试锚点）"
    mutated = tmp_path / "uw-commercial.mutated.js"
    mutated.write_text(src.replace(anchor, "const r = rate / 11, m = n * 12;", 1))
    js_out = _run_js(mutated, tmp_path)
    backend = uw_commercial.compute_all(json.loads(json.dumps(FIXTURES["deal_normal"])))
    bad = _compare_fixture("deal_normal", backend, js_out["results"]["deal_normal"])
    assert bad, "变异后对照仍全绿——对照机制失效（恒绿摆设）"
    assert any("annual_debt_service" in b or "monthly_payment" in b for b in bad), \
        f"变异应首先体现在还贷额，实际漂移项：{bad}"
