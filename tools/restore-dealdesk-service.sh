#!/usr/bin/env bash
# DealDesk 本机常驻服务自愈脚本（P1-3 fallback 持久化层）
# 背景：VM 每日重启清空 /etc，/etc/systemd/system/dealdesk.service 随之丢失，
#       此前靠人工按 plan §0 两步重建（2026-10-07 起连续 10 天）。
# 本脚本 + Muse cron（dealdesk-resident-watchdog，每小时）构成自动恢复：
# unit 唯一真源 = <monorepo>/03-产品与工程/dealdesk.service.system-level（持久盘）
# （2026-10-19 路径修订：该文件已随信息归纳迁至 03-产品与工程/，旧址 deliverables/ 兜底）
# 行为：健康时对服务面只读检查、零写操作（仅向持久盘事件日志记一行）；异常时才重装 unit 并拉起服务。幂等，可反复执行。
set -u

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${DEALDESK_APP_DIR:-$(dirname -- "$SCRIPT_DIR")}"
MONOREPO_ROOT="$(dirname -- "$APP_DIR")"
UNIT_SRC="${DEALDESK_UNIT_SRC:-$MONOREPO_ROOT/03-产品与工程/dealdesk.service.system-level}"
[ -f "$UNIT_SRC" ] || UNIT_SRC="$MONOREPO_ROOT/deliverables/dealdesk.service.system-level"
UNIT_DST="/etc/systemd/system/dealdesk.service"
URL="http://127.0.0.1:8100/"

# 结构化事件日志（2026-11-03 补于 detached 谱系、2026-11-07 随判据对齐合入本谱系）：
# 每轮一行落持久盘，使自愈实绩可机检计数，不再只靠 cron 摘要。
# 字段：时刻(UTC)／结果／触发态／HTTP／动作。只加落行、不改任何出口的判定与退出码。
EVENT_LOG="$APP_DIR/.dealdesk-watchdog-events.log"
log_event() {
  printf '%s outcome=%s state=%s http=%s action=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "${state:-?}" "${code:-?}" "$2" >> "$EVENT_LOG" 2>/dev/null || true
}

# 健康判据（定版文，cron 任务体 2026-10-22 改字、与本谓词同文）：unit active，且根路径
# GET 回 307 且 Location 指向 /app/（应用正常入口跳转），或根路径直回 200——同列健康；
# 且 /app/ 回 200（307 支的跟跳落点校验与 200 支的实体校验共用此条，根 200 而 /app/
# 不通的假象面判不健康）。不得以「根路径非 200」单独判故障。探针必须 GET（不跟随
# 跳转，要看跳转本身）。healthy() 只判定、不动作；三处判定（初始／轮询／终判）一律走此谓词。
probe_root() {
  local out
  out="$(curl -s -D - -o /dev/null --max-time 5 "$URL" 2>/dev/null || true)"
  code="$(printf '%s' "$out" | awk 'NR==1 {print $2}')"
  [ -n "$code" ] || code="000"
  location="$(printf '%s' "$out" | tr -d '\r' | awk 'tolower($1)=="location:" {print $2; exit}')"
  app_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "${URL}app/" 2>/dev/null || echo 000)"
}

healthy() {
  [ "$state" = "active" ] || return 1
  if [ "$code" = "307" ]; then
    case "$location" in
      */app/|*/app) ;;
      *) return 1 ;;
    esac
  elif [ "$code" != "200" ]; then
    return 1
  fi
  [ "$app_code" = "200" ]
}

state="$(systemctl is-active dealdesk.service 2>/dev/null || true)"
probe_root

if healthy; then
  echo "HEALTHY state=$state http=$code"
  log_event "HEALTHY" "none"
  exit 0
fi

echo "RECOVERING state=$state http=$code"

# 1) unit 缺失或与镜像不一致才重装（/etc 被清后走这条）
action="start_only"
if ! cmp -s "$UNIT_SRC" "$UNIT_DST" 2>/dev/null; then
  cp "$UNIT_SRC" "$UNIT_DST"
  action="reinstall+start"
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
  probe_root
  if healthy; then
    echo "probe ready after ${waited}s"
    break
  fi
  echo "probe waiting ${waited}s state=$state http=$code"
done

echo "RESULT state=$state http=$code pending_dir=$([ -d "$APP_DIR/uploads/pending" ] && echo present || echo MISSING)"
if healthy; then
  echo "RECOVERED"
  log_event "RECOVERED" "$action"
  exit 0
fi
echo "RECOVERY_FAILED"
log_event "RECOVERY_FAILED" "$action"
exit 1
