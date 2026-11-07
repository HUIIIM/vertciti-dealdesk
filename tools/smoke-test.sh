#!/usr/bin/env bash
# DealDesk 每日冒烟测试：POST 生产 /api/wb/intake/run，测 3 个固定地址
# 每日 cron 运行；任一失败 exit 1
# 注意：不 push、不 commit，只做只读探测。

set -u

# 2026-11-02 生产鉴权收紧：/api/wb/intake/run 需 analyst 及以上 Bearer 凭证。
# 凭证只从环境变量 DEALDESK_SMOKE_TOKEN 读取（cron 运行前 source 密钥文件注入）；
# 未设置即明确报错退出，禁止静默裸调用。
if [ -z "${DEALDESK_SMOKE_TOKEN:-}" ]; then
  echo "[DealDesk 冒烟测试] 错误：环境变量 DEALDESK_SMOKE_TOKEN 未设置，拒绝无凭证调用生产接口。" >&2
  exit 2
fi

# 生产已切自有 VM 并以 dealdesk.vertciti.com 对外；Vercel 部署为回滚靶，
# 其用户库独立，生产签发的 token 在彼处不被认，故冒烟目标改指生产域名。
BASE="https://dealdesk.vertciti.com"
TIMEOUT=60
SLEEP_BETWEEN=3
MIN_FIELDS=15

NOW=$(TZ=America/New_York date "+%Y-%m-%d %H:%M %Z")

ADDRS=(
  "NY商业|450 West 44th Street, New York, NY 10036"
  "TX住宅|1 Main St, Houston, TX 77002"
  "CA商业|500 S Grand Ave, Los Angeles, CA 90071"
)

pass=0
total=${#ADDRS[@]}
declare -a report_lines
declare -a fail_detail
fail_detail=()

i=0
for item in "${ADDRS[@]}"; do
  i=$((i+1))
  label="${item%%|*}"
  addr="${item#*|}"

  tmpfile=$(mktemp)
  retried=0
  http=$(curl -s -m "$TIMEOUT" -o "$tmpfile" -w "%{http_code}" \
    -X POST "$BASE/api/wb/intake/run" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $DEALDESK_SMOKE_TOKEN" \
    -d "{\"text\":\"$addr\",\"mode\":\"address\"}" 2>/dev/null)
  rc=$?
  # 传输层失败判据＝curl 非零退出或状态 000（旧写法 || echo "000" 在 curl 已自印
  # 000 时会叠成 000000，2026-11-07 本地模拟实证，故改以退出码＋状态双判并归一化）
  if [ "$rc" -ne 0 ] || [ "$http" = "000" ]; then
    http="000"
    # 2026-11-07 中枢照准：传输层失败（超时无响应体）先重试一次再判失败。
    # 缘起：2026-11-07 07:43 冒烟 NY/TX 首呼各烧满 60s 回 000、同轮第三呼通过、
    # 07:58 复测 3/3 全过，定性瞬时冷启型卡顿——重试吸收该类误报；
    # 重试事实在报告行显名（通过行加注／失败详情加行），不静默吞。
    retried=1
    sleep 5
    http=$(curl -s -m "$TIMEOUT" -o "$tmpfile" -w "%{http_code}" \
      -X POST "$BASE/api/wb/intake/run" \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer $DEALDESK_SMOKE_TOKEN" \
      -d "{\"text\":\"$addr\",\"mode\":\"address\"}" 2>/dev/null)
    rc=$?
    [ "$rc" -ne 0 ] && http="000"
  fi

  if [ "$http" = "200" ]; then
    fields=$(jq -r '.fields | length' "$tmpfile" 2>/dev/null || echo "NA")
    primary=$(jq -r '.primary_provider // empty' "$tmpfile" 2>/dev/null || echo "")
    ok=1
    [ "$fields" = "NA" ] && ok=0
    [ "$fields" -lt "$MIN_FIELDS" ] 2>/dev/null && ok=0
    [ -z "$primary" ] && ok=0
    if [ "$ok" = "1" ]; then
      pass=$((pass+1))
      line="地址$i ($label): 通过 fields=$fields primary=$primary"
      [ "$retried" = "1" ] && line="$line（首呼 000，重试后通过）"
      report_lines+=("$line")
    else
      report_lines+=("地址$i ($label): 失败 fields=$fields primary=${primary:-空}")
      diag=$(jq -r '.diagnostics // "无diagnostics"' "$tmpfile" 2>/dev/null | head -c 800)
      chain=$(jq -c '.provider_chain // []' "$tmpfile" 2>/dev/null)
      fail_detail+=("[$label] HTTP=$http fields=$fields primary=${primary:-空}")
      fail_detail+=("  diagnostics: $diag")
      fail_detail+=("  provider_chain: $chain")
    fi
  else
    report_lines+=("地址$i ($label): 失败 HTTP=$http")
    diag=$(head -c 500 "$tmpfile" 2>/dev/null || echo "无返回体")
    fail_detail+=("[$label] HTTP=$http (curl 返回码，非 200)")
    [ "$retried" = "1" ] && fail_detail+=("  首呼 HTTP=000，间隔 5s 已重试一次，仍失败")
    fail_detail+=("  返回体前500字符: $diag")
  fi
  rm -f "$tmpfile"

  if [ "$i" -lt "$total" ]; then
    sleep "$SLEEP_BETWEEN"
  fi
done

echo "[DealDesk 冒烟测试] $NOW"
for line in "${report_lines[@]}"; do
  echo "$line"
done
if [ "${#fail_detail[@]}" -gt 0 ]; then
  echo "--- 失败详情 ---"
  for d in "${fail_detail[@]}"; do
    echo "$d"
  done
fi
echo "结果: $pass/$total 通过"

[ "$pass" -eq "$total" ]
