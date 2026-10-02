#!/usr/bin/env bash
# TopHap token 自愈 cron 脚本：调 app/token_watch.py 的 ensure_fresh_token()，
# 刷新成功后把新 token 同步到 Vercel 生产环境变量并触发 redeploy。
#
# 用法（cron）：cd ~/workspace/vertcity/dealdesk && tools/tophap-auto-refresh.sh
# - 没刷新（还够用 / 无法刷新）：直接 exit 0，什么都不做。
# - 刷新成功：更新 Vercel vertciti-dealdesk（team vertciti）的
#   TOPHAP_ACCESS_TOKEN / TOPHAP_TOKEN_EXPIRES_AT（production），然后
#   vc-deploy 重新部署 vercel-deploy/ 目录。
#
# 注意：token 明文只在 python 进程内存与 .env（600）里流转，
# 本脚本的日志一律不打印 token 值。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
PY="$REPO_ROOT/.venv/bin/python"
VC_LIB_DIR="$HOME/workspace/skills/vercel/bin"

if [ ! -x "$PY" ]; then
  echo "[tophap-auto-refresh] 找不到 $PY，中止" >&2
  exit 2
fi

RESULT_JSON="$("$PY" - <<'EOF'
import json, sys
sys.path.insert(0, ".")
from app.token_watch import ensure_fresh_token
print(json.dumps(ensure_fresh_token()))
EOF
)"

REFRESHED="$("$PY" -c "import json,sys; print(1 if json.loads(sys.argv[1]).get('refreshed') else 0)" "$RESULT_JSON")"
REASON="$("$PY" -c "import json,sys; print(json.loads(sys.argv[1]).get('reason',''))" "$RESULT_JSON")"

if [ "$REFRESHED" != "1" ]; then
  echo "[tophap-auto-refresh] 未刷新：$REASON"
  exit 0
fi

echo "[tophap-auto-refresh] $REASON"

# 刷新成功：把 .env 里的新值推到 Vercel（python 内读 .env，不经 shell 变量）
"$PY" - <<EOF
import sys
sys.path.insert(0, "$VC_LIB_DIR")
sys.path.insert(0, "$REPO_ROOT")
from vc_lib import api

PROJECT = "vertciti-dealdesk"
TEAM_SLUG = "vertciti"
KEYS = ("TOPHAP_ACCESS_TOKEN", "TOPHAP_TOKEN_EXPIRES_AT")

# .env 直接读（ensure_fresh_token 刚写过，是最新值）
env_map = {}
with open("$REPO_ROOT/.env") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if k.strip() in KEYS:
                env_map[k.strip()] = v.strip()
missing = [k for k in KEYS if k not in env_map]
if missing:
    raise SystemExit(f".env 缺少 {missing}，不同步 Vercel")

teams = api("GET", "/v2/teams").get("teams", [])
team = next((t for t in teams if t["slug"] == TEAM_SLUG), None)
if not team:
    raise SystemExit(f"team slug {TEAM_SLUG!r} 不存在")
tid = team["id"]

existing = api("GET", f"/v9/projects/{PROJECT}/env?teamId={tid}").get("envs", [])
by_key = {}
for e in existing:
    if "production" in (e.get("target") or []):
        by_key.setdefault(e["key"], e)

for key in KEYS:
    value = env_map[key]
    ent = by_key.get(key)
    if ent:
        api("PATCH", f"/v9/projects/{PROJECT}/env/{ent['id']}?teamId={tid}",
            {"value": value})
        print(f"[tophap-auto-refresh] Vercel env 已更新：{key}（production）")
    else:
        api("POST", f"/v10/projects/{PROJECT}/env?teamId={tid}",
            {"key": key, "value": value, "type": "encrypted",
             "target": ["production"]})
        print(f"[tophap-auto-refresh] Vercel env 已创建：{key}（production）")
EOF

echo "[tophap-auto-refresh] 触发 redeploy（vercel-deploy/ -> vertciti-dealdesk）…"
"$VC_LIB_DIR/vc-deploy" vercel-deploy vertciti-dealdesk --team vertciti
echo "[tophap-auto-refresh] 完成"
