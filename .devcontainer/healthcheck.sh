#!/usr/bin/env bash
# Codespace 创建时质量门（被 devcontainer.json 的 postCreateCommand 调用）
# 必查项失败 -> 退出非零 -> 创建标红。用法: bash .devcontainer/healthcheck.sh [python|node]
set -u
STACK="${1:-python}"
FAIL=0
say(){ echo "[healthcheck] $1"; }
need(){ # need <描述> <命令...>
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then say "PASS: $desc"; else say "FAIL: $desc"; FAIL=1; fi
}

say "stack=$STACK"
if [ "$STACK" = "python" ]; then
  need "python >= 3.12" python3 -c "import sys; assert sys.version_info >= (3,12)"
  need "pip 可用" python3 -m pip --version
  need "依赖一致性 pip check" python3 -m pip check
elif [ "$STACK" = "node" ]; then
  need "node >= 20" node -e "assert(parseInt(process.versions.node.split('.')[0]) >= 20)"
  need "npm 可用" npm --version
fi
need "git 身份已配置" git config user.name

if [ "$FAIL" -ne 0 ]; then
  say "RESULT: FAIL —— 按 SOP 修好或重建，不许带病开工"
  exit 1
fi
say "RESULT: PASS"
