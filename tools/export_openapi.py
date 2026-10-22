#!/usr/bin/env python3
"""导出后端 OpenAPI（只含 /api/v2，键排序）→ 前端用 openapi-typescript 生成类型安全客户端。

用法（仓库根或 frontend/ 下）：python3 tools/export_openapi.py frontend/openapi.json
CI 会重新导出并 git diff，接口改了而前端类型没重新生成即失败。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402


def main(out: str) -> None:
    spec = app.openapi()
    spec["paths"] = {p: v for p, v in spec["paths"].items() if p.startswith("/api/v2")}
    Path(out).write_text(json.dumps(spec, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}: {len(spec['paths'])} paths")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "frontend/openapi.json")
