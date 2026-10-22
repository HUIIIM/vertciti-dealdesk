"""v1 金标准对比（v2 蓝图 §8.1：v1 与 v2 对同一批交易的所有输出数字一致，差异 = 0）。

- 函数层：tests/golden_v1/fn_cases.jsonl.gz（v1 全量测试实际传入纯计算函数的参数，1565 组）
- API 层：tests/golden_v1/api_cases.jsonl.gz（测试请求 + 交易矩阵，覆盖每个确定性端点）
期望输出由 v1 代码录制（GOLDEN_RECORD=1），之后任何重构都不得改变一个数字。
确需改口径时：先改 v1 行为的测试与说明，再重录并在提交信息里写清原因。
"""

from __future__ import annotations

import json
import os

import pytest

from golden_lib import (GOLDEN_DIR, network_blocked, read_jsonl_gz, run_api_cases, run_fn_case,
                        write_jsonl_gz)

RECORD = os.environ.get("GOLDEN_RECORD") == "1"
FN_CASES = read_jsonl_gz(GOLDEN_DIR / "fn_cases.jsonl.gz")
API_CASES = read_jsonl_gz(GOLDEN_DIR / "api_cases.jsonl.gz")


def _first_diff(a, b, path="$"):
    """返回首个差异的路径与两侧值（便于定位，而不是一屏 JSON）。"""
    if type(a) is not type(b):
        return path, a, b
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f"{path}.{k}", a.get(k, "<缺失>"), b.get(k, "<缺失>")
            d = _first_diff(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}.len", len(a), len(b)
        for i, (x, y) in enumerate(zip(a, b)):
            d = _first_diff(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    return None if a == b else (path, a, b)


def _check(kind: str, actual: list, cases: list, label) -> None:
    path = GOLDEN_DIR / f"{kind}_expected.jsonl.gz"
    if RECORD:
        write_jsonl_gz(path, [{"out": o} for o in actual])
        pytest.skip(f"已录制 {len(actual)} 条 {kind} 金标准")
    expected = [r["out"] for r in read_jsonl_gz(path)]
    assert len(expected) == len(actual), "用例数与期望数不一致——用例文件被改动？"
    diffs = []
    for i, (e, a) in enumerate(zip(expected, actual)):
        # 经 JSON 往返，消除 tuple/list 等表示差异，只比内容
        a = json.loads(json.dumps(a, ensure_ascii=False, sort_keys=True))
        d = _first_diff(e, a)
        if d:
            diffs.append(f"#{i} {label(cases[i])}  {d[0]}: v1={str(d[1])[:120]!r} now={str(d[2])[:120]!r}")
    assert not diffs, f"{len(diffs)} 条 {kind} 输出偏离 v1：\n" + "\n".join(diffs[:30])


def test_golden_fn_layer():
    with network_blocked():
        actual = [run_fn_case(c) for c in FN_CASES]
    _check("fn", actual, FN_CASES, lambda c: f"{c['mod']}.{c['fn']}")


def test_golden_api_layer(tmp_path, monkeypatch):
    monkeypatch.setenv("DEALDESK_DB", str(tmp_path / "golden.db"))
    from fastapi.testclient import TestClient

    from app.main import app
    with network_blocked(), TestClient(app) as client:
        actual = run_api_cases(API_CASES, client)
    _check("api", actual, API_CASES, lambda c: f"{c['method']} {c['url']}")


def test_golden_is_deterministic(tmp_path, monkeypatch):
    """同一 v1 代码连跑两次结果必须一致——否则金标准本身不可信。抽样 API 前 200 条。"""
    from fastapi.testclient import TestClient

    from app.main import app
    runs = []
    for n in range(2):
        monkeypatch.setenv("DEALDESK_DB", str(tmp_path / f"det{n}.db"))
        with network_blocked(), TestClient(app) as client:
            runs.append(run_api_cases(API_CASES[:200], client))
    assert runs[0] == runs[1]
