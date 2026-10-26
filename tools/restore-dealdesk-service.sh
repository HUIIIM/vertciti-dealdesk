#!/usr/bin/env bash
# DealDesk 本机常驻服务自愈脚本（P1-3 fallback 持久化层）
# 背景：VM 每日重启清空 /etc，/etc/systemd/system/dealdesk.service 随之丢失，
#       此前靠人工按 plan §0 两步重建（2026-10-07 起连续 10 天）。
# 本脚本 + Muse cron（dealdesk-resident-watchdog，每小时）构成自动恢复：
# unit 唯一真源 = <monorepo>/03-产品与工程/dealdesk.service.system-level（持久盘）
# （2026-10-19 路径修订：该文件已随信息归纳迁至 03-产品与工程/，旧址 deliverables/ 兜底）
# 行为：健康时只读检查、零写操作；异常时才重装 unit 并拉起服务。幂等，可反复执行。
set -u

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${DEALDESK_APP_DIR:-$(dirname -- "$SCRIPT_DIR")}"
MONOREPO_ROOT="$(dirname -- "$APP_DIR")"
UNIT_SRC="${DEALDESK_UNIT_SRC:-$MONOREPO_ROOT/03-产品与工程/dealdesk.service.system-level}"
[ -f "$UNIT_SRC" ] || UNIT_SRC="$MONOREPO_ROOT/deliverables/dealdesk.service.system-level"
UNIT_DST="/etc/systemd/system/dealdesk.service"
URL="http://127.0.0.1:8100/"

state="$(systemctl is-active dealdesk.service 2>/dev/null || true)"
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$URL" 2>/dev/null || echo 000)"

if [ "$state" = "active" ] && [ "$code" = "200" ]; then
  echo "HEALTHY state=$state http=$code"
  exit 0
fi

echo "RECOVERING state=$state http=$code"

# 1) unit 缺失或与镜像不一致才重装（/etc 被清后走这条）
if ! cmp -s "$UNIT_SRC" "$UNIT_DST" 2>/dev/null; then
  cp "$UNIT_SRC" "$UNIT_DST"
  echo "unit installed from mirror"
fi

# 2) watcher 依赖目录兜底（持久盘内，正常都在）
mkdir -p "$APP_DIR/uploads/pending"

# 3) 重载并启用（含开机自启 symlink；VM 不重启的日子靠 Restart=always 自愈崩溃）
systemctl daemon-reload
systemctl enable --now dealdesk.service

# 4) 验收：就绪轮询，最多等 60 秒，间隔递增（2/3/5/8/12/15/15）
#    修订 2026-10-19：原固定 5×3s=15s 窗口短于 uvicorn 冷启动耗时（ExecStartPre
#    DB 初始化＋进程拉起实测可达 ~37s），探针在服务就绪前打 http=000 误报
#    RECOVERY_FAILED（2026-10-19 19:06 轮假 P0）。改轮询：任一次 active+200
#    即判就绪；60s 耗尽仍未就绪才走下方 RECOVERY_FAILED 原失败路径。
waited=0
for delay in 2 3 5 8 12 15 15; do
  sleep "$delay"
  waited=$((waited + delay))
  state="$(systemctl is-active dealdesk.service 2>/dev/null || true)"
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$URL" 2>/dev/null || echo 000)"
  if [ "$state" = "active" ] && [ "$code" = "200" ]; then
    echo "probe ready after ${waited}s"
    break
  fi
  echo "probe waiting ${waited}s state=$state http=$code"
done

echo "RESULT state=$state http=$code pending_dir=$([ -d "$APP_DIR/uploads/pending" ] && echo present || echo MISSING)"
if [ "$state" = "active" ] && [ "$code" = "200" ]; then
  echo "RECOVERED"
  exit 0
fi
echo "RECOVERY_FAILED"
exit 1
