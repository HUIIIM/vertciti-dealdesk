#!/bin/bash
# Codespace 启动时自动拉起 DealDesk（幂等：已在跑则直接退出）
set -u
cd /workspaces/vertciti-dealdesk || exit 0
if pgrep -f "[u]vicorn app.main:app" > /dev/null 2>&1; then
  exit 0
fi
nohup bash run.sh > /tmp/dealdesk.log 2>&1 &
# 尽力把预览端口设为 public，失败不影响启动（private 时物主登录 GitHub 仍可访问）
gh codespace ports visibility 8100:public --codespace "${CODESPACE_NAME:-}" >> /tmp/dealdesk.log 2>&1 || true
