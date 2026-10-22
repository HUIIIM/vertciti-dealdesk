#!/usr/bin/env python3
"""录制前端页面测试夹具：对本地后端（种子数据）调用页面用到的全部 GET / 只读 POST，存成 JSON。

用法：python3 tools/record_web_fixtures.py http://127.0.0.1:8130 frontend/src/test/fixtures.json
夹具来自真实后端响应 → 页面测试用的是真实数据形状，后端改了口径重录即可。
"""
from __future__ import annotations

import json
import sys
import urllib.request

B, OUT = sys.argv[1], sys.argv[2]
GETS = ["/api/v2/me", "/api/v2/catalog", "/api/v2/deals", "/api/v2/settings/views", "/api/v2/health", "/api/v2/settings/data-sources",
        "/api/v2/settings/templates?kind=kill_criteria", "/api/v2/compare?ids=1,2", "/api/v2/portfolio"]
for d in (1, 2):
    GETS += [f"/api/v2/deals/{d}", f"/api/v2/deals/{d}/passports", f"/api/v2/deals/{d}/versions", f"/api/v2/deals/{d}/redteam",
             f"/api/v2/deals/{d}/committee/packs", f"/api/v2/deals/{d}/documents", f"/api/v2/deals/{d}/conflicts",
             f"/api/v2/deals/{d}/decisions", f"/api/v2/deals/{d}/tasks", f"/api/v2/deals/{d}/approvals", f"/api/v2/deals/{d}/events?limit=300",
             f"/api/v2/deals/{d}/holding", f"/api/v2/deals/{d}/committee"]


def call(m: str, p: str, body: object | None = None) -> tuple[int, object]:
    r = urllib.request.Request(B + p, method=m, data=None if body is None else json.dumps(body).encode(),
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


out: dict[str, object] = {}
for p in GETS:
    out[f"GET {p}"] = call("GET", p)
deal = call("GET", "/api/v2/deals/1")[1]
vid = deal["deal"]["current_version_id"]  # type: ignore[index]
out[f"GET /api/v2/deals/1/versions/{vid}"] = call("GET", f"/api/v2/deals/1/versions/{vid}")
res = call("GET", "/api/v2/deals/2")[1]
rvid = res["deal"]["current_version_id"]  # type: ignore[index]
out[f"GET /api/v2/deals/2/versions/{rvid}"] = call("GET", f"/api/v2/deals/2/versions/{rvid}")
versions = call("GET", "/api/v2/deals/1/versions")[1]
out["GET /api/v2/deals/1/diff"] = call("GET", f"/api/v2/deals/1/diff?a={versions[-1]['id']}&b={versions[0]['id']}")  # type: ignore[index]
out["GET /api/v2/deals/1/passport"] = call("GET", "/api/v2/deals/1/passport?field=analysis.exit_cap_rate")
inputs = call("GET", f"/api/v2/deals/1/versions/{vid}")[1]["inputs"]  # type: ignore[index]
out["POST /api/v2/model/commercial"] = call("POST", "/api/v2/model/commercial", inputs)
rin = call("GET", f"/api/v2/deals/2/versions/{rvid}")[1]["inputs"]  # type: ignore[index]
out["POST /api/v2/model/residential"] = call("POST", "/api/v2/model/residential", rin)
for d in (1, 2):
    out[f"POST /api/v2/deals/{d}/scenarios"] = call("POST", f"/api/v2/deals/{d}/scenarios", {})
    out[f"POST /api/v2/deals/{d}/max-bid"] = call("POST", f"/api/v2/deals/{d}/max-bid", {"targets": [], "include_kill_criteria": True})
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1, sort_keys=True)
print(f"wrote {len(out)} fixtures → {OUT}")
