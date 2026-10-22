#!/usr/bin/env python3
"""打印 static/*.html 内联 <script>/<style> 的 CSP sha256 hash，供更新 vercel-deploy/vercel.json。

AGENTS.md 铁律：改了内联 JS 必须同步重算 CSP hash（曾因 hash 未更新导致全站 #app 空白，curl 200 看不出）。
用法：python3 tools/csp_hashes.py [static 目录]   → 每页一行 script-src / style-src hash 列表
"""
from __future__ import annotations

import base64
import hashlib
import pathlib
import re
import sys


def inline_hashes(html: str, tag: str) -> list[str]:
    out = []
    for m in re.finditer(rf"<{tag}(?![^>]*\bsrc=)[^>]*>(.*?)</{tag}>", html, re.S):
        digest = hashlib.sha256(m.group(1).encode("utf-8")).digest()
        out.append("'sha256-" + base64.b64encode(digest).decode() + "'")
    return out


def main() -> None:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "static")
    for page in sorted(root.glob("*.html")):
        text = page.read_text(encoding="utf-8")
        print(f"{page.name}\n  script-src {' '.join(inline_hashes(text, 'script')) or '(none)'}"
              f"\n  style-src  {' '.join(inline_hashes(text, 'style')) or '(none)'}")


if __name__ == "__main__":
    main()
