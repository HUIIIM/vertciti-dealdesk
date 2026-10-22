#!/usr/bin/env python3
"""从录制结果构建金标准用例（只在锁定 v1 时运行一次）。

步骤（仓库根执行）：
  1. FN_CAPTURE_OUT=/path/fn.jsonl PYTHONPATH=tools/golden:. pytest -p fn_capture_plugin -q
  2. CAPTURE_OUT=/path/api.jsonl   PYTHONPATH=tools/golden:. pytest -p api_capture_plugin -q
  3. python tools/golden/build_cases.py /path/fn.jsonl /path/api.jsonl
  4. GOLDEN_RECORD=1 pytest tests/test_golden_v1.py   （用 v1 代码录期望输出）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from golden_lib import GOLDEN_DIR, write_jsonl_gz  # noqa: E402

# 依赖外部网络/进程状态的端点：断网下仍锁定其降级输出，但不作为矩阵展开
NETWORK = {"/api/wb/comps/pull", "/api/wb/intake/run", "/api/wb/research"}


def main(fn_path: str, api_path: str) -> None:
    fn_cases = [json.loads(line) for line in open(fn_path, encoding="utf-8")]
    write_jsonl_gz(GOLDEN_DIR / "fn_cases.jsonl.gz", fn_cases)

    by_fn: dict[str, list] = {}
    for c in fn_cases:
        by_fn.setdefault(f"{c['mod']}.{c['fn']}", []).append(c["args"])

    def first_args(key: str) -> list[dict]:
        seen, out = set(), []
        for a in by_fn.get(key, []):
            if a["a"] and isinstance(a["a"][0], dict):
                k = json.dumps(a["a"][0], sort_keys=True)
                if k not in seen:
                    seen.add(k)
                    out.append(a["a"][0])
        return out

    res_inputs = first_args("scoring_residential.score")
    com_inputs = first_args("scoring_commercial.score")
    uw_inputs = first_args("uw_commercial.compute_all")

    api: list[dict] = []
    add = lambda m, u, j=None, **kw: api.append({"method": m, "url": u, "json": j, **kw})  # noqa: E731

    # 1) 测试套件实际发出的请求（项目 CRUD 用例依赖自增 id，由下方矩阵覆盖）
    for line in open(api_path, encoding="utf-8"):
        c = json.loads(line)
        if "/projects" in c["url"]:
            continue
        add(c["method"], c["url"], c["json"])

    # 2) 静态 GET
    for u in ("/api/health", "/api/uw/template", "/api/wb/markets", "/api/uw/rentroll/template.xlsx",
              "/api/tophap/status", "/api/wb/intake/pending"):
        add("GET", u)

    # 3) 住宅 / 商业打分矩阵
    n_proj = 0
    for track, inputs in (("residential", res_inputs), ("commercial", com_inputs)):
        for i, inp in enumerate(inputs):
            for lang in ("zh", "en"):
                add("POST", "/api/score", {"track": track, "name": f"g{i}", "address": f"g{i}",
                                           "input": inp, "lang": lang})
            add("POST", "/api/sensitivity", {"track": track, "input": inp, "tiers": {}})
            add("POST", "/api/projects", {"track": track, "name": f"金标准 {track} {i}",
                                          "address": f"{i} Golden St", "input": inp}, capture_id=True)
            add("GET", "/api/projects/{pid:%d}" % n_proj)
            add("GET", "/api/projects/{pid:%d}/report" % n_proj)
            add("GET", "/api/projects/{pid:%d}/pdf" % n_proj)
            n_proj += 1
    add("GET", "/api/projects")
    add("GET", "/api/projects?track=residential&sort=cash_to_close")
    add("GET", "/api/compare?ids={pid:0},{pid:1},{pid:2}")

    # 4) 商业核保矩阵（compute_all 输入集）
    for inp in uw_inputs:
        add("POST", "/api/uw/compute", {"input": inp})
        for lang in ("zh", "en"):
            add("POST", "/api/uw/compute-plus", {"input": inp, "lang": lang})
        add("POST", "/api/com/sensitivity", {"input": inp})
        for v in ("classic", "enhanced"):
            add("POST", "/api/uw/report", {"input": inp, "variant": v})
        add("POST", "/api/uw/tearsheet", {"input": inp, "name": "Golden", "address": "1 Golden St"})
        add("POST", "/api/uw/report/xlsx", {"input": inp})

    # 5) 断网下的外部数据端点（锁定降级路径）
    for addr in ("450 W 44th St, New York, NY 10036", "1500 Atlantic Ave, Brooklyn, NY 11213", ""):
        add("POST", "/api/tax/estimate", {"address": addr, "price": 1850000})
        add("POST", "/api/wb/ownership/tree", {"address": addr})
        add("POST", "/api/wb/sell-readiness/score", {"address": addr})

    write_jsonl_gz(GOLDEN_DIR / "api_cases.jsonl.gz", api)
    print(f"fn cases: {len(fn_cases)}  api cases: {len(api)}  "
          f"(res {len(res_inputs)} / com {len(com_inputs)} / uw {len(uw_inputs)})")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
