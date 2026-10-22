"""Workbench EN layer (static/i18n-wb.js): translates UI text, never half-translates user text."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parent.parent / "static" / "i18n-wb.js"
NODE = shutil.which("node")

CASES = {
    "全面分析工作台": "Full Analysis Workbench",
    "调查完整度：已填 3/6，已核实 1/6": "Research completeness: filled 3/6, verified 1/6",
    "$/SF 分布（已采用案例，4 个）": "$/SF distribution (adopted comps, 4)",
    "第 2 年": "Year 2",
    "⏳ 解析 PDF《flyer.pdf》中…": "⏳ Parsing PDF «flyer.pdf»…",
    "两种方法都无有效值，无法调和": "Neither approach has a valid value — cannot reconcile",
    # user-typed / unknown Chinese stays exactly as it was (never half-translated)
    "供给紧张，租金上涨": "供给紧张，租金上涨",
    "坦帕 供给 紧张": "坦帕 供给 紧张",
    "no chinese here": "no chinese here",
}


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_translator_cases():
    script = (
        "global.window={DD_LANG:'en',DD_EN_DICT:{},alert(){},confirm(){}};"
        "global.document={readyState:'loading',addEventListener(){}};"
        f"require({json.dumps(str(JS))});"
        f"const c={json.dumps(list(CASES))};"
        "console.log(JSON.stringify(c.map(s=>window.WB_T(s))));"
    )
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True).stdout
    assert dict(zip(CASES, json.loads(out))) == CASES


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_zh_is_untouched():
    script = (
        "global.window={DD_LANG:'zh',DD_EN_DICT:{}};"
        "global.document={readyState:'loading',addEventListener(){}};"
        f"require({json.dumps(str(JS))});"
        "console.log(typeof window.WB_T);"
    )
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True).stdout.strip()
    assert out == "undefined"  # zh: the EN layer installs nothing (only the toggle button)


UWC = JS.parent / "i18n-uwc.js"
UWC_CASES = {
    "投资分析": "Investment analysis",
    "已填 5 个字段": "Filled 5 fields",
    "未映射 3 项": "Unmapped 3 item(s)",
    "全面分析工作台": "Full Analysis Workbench",  # workbench dict still present
    "卡拉特公司": "卡拉特公司",  # a tenant name typed in Chinese stays as is
}


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_per_page_dictionary_merges():
    script = (
        "global.window={DD_LANG:'en',DD_EN_DICT:{},alert(){},confirm(){}};"
        "global.document={readyState:'loading',addEventListener(){}};"
        f"require({json.dumps(str(UWC))});require({json.dumps(str(JS))});"
        f"const c={json.dumps(list(UWC_CASES))};"
        "console.log(JSON.stringify(c.map(s=>window.WB_T(s))));"
    )
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True).stdout
    assert dict(zip(UWC_CASES, json.loads(out))) == UWC_CASES
