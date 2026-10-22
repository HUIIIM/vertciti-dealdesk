"""上线用的 Vercel 路由片段（docs/deploy/vercel-v2.json）不能与代码漂移。

/app/ 在 Vercel 上走 CDN 静态，不经 FastAPI，所以 CSP 只能靠 vercel.json 下发——必须与 APP_CSP 逐字一致；
旧页面地址必须全部跳到 /app/（v1 界面已下线），且引用的静态文件真实存在。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.api.admin import LEGACY_PAGES
from app.core.hardening import APP_CSP, SECURITY_HEADERS

ROOT = Path(__file__).resolve().parent.parent
FRAG = json.loads((ROOT / "docs/deploy/vercel-v2.json").read_text(encoding="utf-8"))


def _matches(source: str, path: str) -> bool:
    rx = "^" + re.sub(r":(\w+)\*", ".*", source) + "$"
    return re.match(rx, path) is not None


def test_csp_and_security_headers_match_code():
    app_rule = next(h for h in FRAG["headers"] if h["source"] == "/app/(.*)")
    got = {h["key"]: h["value"] for h in app_rule["headers"]}
    assert got["Content-Security-Policy"] == APP_CSP
    for k, v in SECURITY_HEADERS.items():
        assert got[k] == v


def test_every_legacy_page_redirects_to_app():
    for page in LEGACY_PAGES:
        assert any(_matches(r["source"], page) and r["destination"] == "/app/" for r in FRAG["redirects"]), page


def test_rewrites_point_at_built_files():
    assert (ROOT / "static/app/index.html").is_file()
    index = (ROOT / "static/app/index.html").read_text(encoding="utf-8")
    for asset in re.findall(r'(?:src|href)="/app/assets/([^"]+)"', index):
        assert (ROOT / "static/app/assets" / asset).is_file(), asset
    dests = {r["destination"] for r in FRAG["rewrites"]}
    assert "/static/app/index.html" in dests and "/static/app/assets/:path*" in dests
