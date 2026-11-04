#!/usr/bin/env bash
# TopHap token 自愈 cron 脚本：调 app/token_watch.py 的 ensure_fresh_token()，
# 刷新成功后把新 token 同步到 Vercel 生产环境变量并触发 redeploy。
# 【2026-11-04 注】Vercel 腿已退役（见文末退役闸）；现行分发＝VM 单面推送。
#
# 用法（cron）：cd ~/workspace/vertcity/dealdesk && tools/tophap-auto-refresh.sh
# - 没刷新（还够用 / 无法刷新）：直接 exit 0，什么都不做。
# - 刷新成功：更新 Vercel vertciti-dealdesk（team vertciti）的
#   TOPHAP_ACCESS_TOKEN / TOPHAP_TOKEN_EXPIRES_AT（production），然后
#   vc-deploy 重新部署 vercel-deploy/ 目录。
#
# --push：跳过 ensure_fresh_token，直接把 .env 当前值推到 Vercel 并 redeploy。
#   用于"已走浏览器手动重授权、.env 已是新 token"的情形（此时 ensure_fresh_token
#   会判"还够用"而跳过推送）。token-watch cron 的步骤 2d 必须用此模式。
#
# 兜底（2026-10-23）：vc-deploy 上传步若命中 Vercel api-upload-free 429
#   （免费档上传配额耗尽），改走 redeploy-without-upload——对当前生产最新
#   READY deployment 调 POST /v13/deployments（deploymentId＋target=
#   production）发起 redeploy，不上传任何文件；redeploy 按发起时刻的现行
#   env 构建，正好带上刚同步的 TopHap token。触发条件写死：仅 api-upload-
#   free 类 429；其他失败形态原样报错停手；redeploy 本身被拦/失败不套娃
#   兜底，错误原文保留。redeploy READY 后的验证仍由调用方按原验证步双
#   域名回读 /api/tophap/status（token_expired=false、core_ready=true）。
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

PUSH_ONLY=0
if [ "${1:-}" = "--push" ]; then
  PUSH_ONLY=1
  echo "[tophap-auto-refresh] --push 模式：跳过 ensure_fresh_token，直接推送 .env 当前值"
fi

if [ "$PUSH_ONLY" = "0" ]; then

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
fi # PUSH_ONLY=0

# === Vercel 分发腿退役闸（2026-11-04 协议工程组核定）===
# vertciti.com 生产承接面已迁出 Vercel（董事长令＋SRE 事实单）；vertciti-dealdesk
# 部署经实测已被平台禁用（DEPLOYMENT_DISABLED）。分发终态＝VM 单面
# （tools/tophap_vm_push.py 由巡检轮调用）。本闸默认关：Vercel 同步＋redeploy
# 整段跳过；如平台面将来恢复，置 TOPHAP_VERCEL_SYNC=1 显式重启本腿。
if [ "${TOPHAP_VERCEL_SYNC:-0}" != "1" ]; then
  echo "[tophap-auto-refresh] Vercel 分发腿已退役（2026-11-04），跳过同步与 redeploy；分发走 VM 推送面"
  exit 0
fi

# （--push 或刷新成功）把 .env 里的值推到 Vercel（python 内读 .env，不经 shell 变量）
"$PY" - <<EOF
import sys
sys.path.insert(0, "$VC_LIB_DIR")
sys.path.insert(0, "$REPO_ROOT")
from vc_lib import api

PROJECT = "vertciti-dealdesk"
TEAM_SLUG = "vertciti"
KEYS = ("TOPHAP_ACCESS_TOKEN", "TOPHAP_TOKEN_EXPIRES_AT")

# .env 直接读（ensure_fresh_token 刚写过，或 --push 模式下是手动重授权的新值）
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
DEPLOY_LOG="$(mktemp)"
set +e
"$VC_LIB_DIR/vc-deploy" vercel-deploy vertciti-dealdesk --team vertciti >"$DEPLOY_LOG" 2>&1
DEPLOY_RC=$?
set -e
if [ "$DEPLOY_RC" = "0" ]; then
  cat "$DEPLOY_LOG"
  rm -f "$DEPLOY_LOG"
  echo "[tophap-auto-refresh] 完成"
  exit 0
fi
if ! grep -q "api-upload-free" "$DEPLOY_LOG"; then
  # 非 api-upload-free 失败：原样报错停手，不兜底
  cat "$DEPLOY_LOG" >&2
  rm -f "$DEPLOY_LOG"
  echo "[tophap-auto-refresh] vc-deploy 失败（exit $DEPLOY_RC，非 api-upload-free 429），原样停手" >&2
  exit "$DEPLOY_RC"
fi
echo "[tophap-auto-refresh] vc-deploy 命中 api-upload-free 429，改走 redeploy-without-upload 兜底" >&2
cat "$DEPLOY_LOG" >&2
rm -f "$DEPLOY_LOG"

# 兜底：对当前生产最新 READY deployment 发起 redeploy（不上传文件，
# 按发起时刻现行 env 构建）；被拦/失败即 RuntimeError 原文退出，不再兜底。
"$PY" - <<EOF
import json, sys, time
sys.path.insert(0, "$VC_LIB_DIR")
from vc_lib import api

PROJECT = "vertciti-dealdesk"
TEAM_SLUG = "vertciti"

teams = api("GET", "/v2/teams").get("teams", [])
team = next((t for t in teams if t["slug"] == TEAM_SLUG), None)
if not team:
    raise SystemExit(f"team slug {TEAM_SLUG!r} 不存在")
tid = team["id"]

projs = api("GET", f"/v9/projects?teamId={tid}&limit=50").get("projects", [])
proj = next((p for p in projs if p["name"] == PROJECT), None)
if not proj:
    raise SystemExit(f"project {PROJECT!r} 不存在")
pid = proj["id"]

deps = api("GET", f"/v6/deployments?projectId={pid}&teamId={tid}"
           "&target=production&state=READY&limit=20").get("deployments", [])
src = next((d for d in deps if d.get("readyState") == "READY"), None)
if not src:
    raise SystemExit("找不到现行生产 READY deployment，兜底停手")
src_id = src.get("uid") or src.get("id")
print(f"[tophap-auto-refresh] redeploy 源部署：{src_id}")

dep = api("POST", f"/v13/deployments?teamId={tid}",
          {"name": PROJECT, "deploymentId": src_id, "target": "production"})
new_id = dep.get("id")
if not new_id:
    raise SystemExit(f"redeploy 创建失败：{dep}")
print(f"[tophap-auto-refresh] redeploy 已创建：{new_id}，等待 READY…")

deadline = time.time() + 300
while time.time() < deadline:
    time.sleep(5)
    cur = api("GET", f"/v13/deployments/{new_id}?teamId={tid}")
    state = cur.get("readyState")
    if state == "READY":
        print(f"[tophap-auto-refresh] redeploy READY：{new_id}"
              f" https://{cur.get('url', '')}")
        break
    if state in ("ERROR", "CANCELED"):
        raise SystemExit(f"redeploy {state}：{json.dumps(cur)[:1000]}")
else:
    raise SystemExit("redeploy 等待 READY 超时（300s）")
EOF
echo "[tophap-auto-refresh] 完成（redeploy-without-upload 兜底路径）"
