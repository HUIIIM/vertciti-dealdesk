#!/usr/bin/env bash
#
# DealDesk 部署前 diff 门禁（台账第 9 项：vercel-deploy 静态双副本同步自动化）。
#
# 按 AGENTS.md 的三条 rsync 规则做 dry-run diff：
#   规则 1：app/    -> vercel-deploy/app/
#   规则 2：static/ -> vercel-deploy/static/
#   规则 3：static/ -> vercel-deploy/ 根
#            （排除 api/、app/、static/、vercel.json、requirements.txt、dealdesk-seed.db）
#
# 任一处失步 → 非零退出并打印失步文件清单，拦截部署。
# 设计：--checksum 按内容比（touch 一下改时间不算过关）；
#       -rL（故意不用 -a）：只比文件内容，不比权限/时间戳——目录 setgid
#       位、mtime 这类环境噪音不影响 Vercel 部署内容，门禁只拦真正的失步；
#       -n 干跑，不改任何文件；--delete 也进清单（staging 多了脏文件同样拦截）。
#
# 用法：bash tools/pre_deploy_diff_gate.sh   （仓库根或任意目录均可）
# 退出码：0=三方全部对齐；1=失步（清单已打印）；2=环境错误
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

DEPLOY_DIR="vercel-deploy"
FAILED=0

die()  { echo "[diff-gate][错误] $*" >&2; exit 2; }
note() { echo "[diff-gate] $*"; }

command -v rsync >/dev/null 2>&1 || die "未找到 rsync，请先安装"
[ -d "${DEPLOY_DIR}" ] || die "缺少 ${DEPLOY_DIR}/（部署 staging 目录）"
[ -d "app" ] || die "缺少 app/"
[ -d "static" ] || die "缺少 static/"

# check_rule <规则名> <rsync 参数...>（src dest 放在最后）
check_rule() {
    local rule_name="$1"; shift
    note "检查 ${rule_name} ..."
    local out
    out="$(rsync -rL -n --checksum --delete --itemize-changes \
        --out-format='%i %n%L' "$@" 2>&1)" || die "rsync 执行失败（${rule_name}）"
    if [ -n "${out}" ]; then
        FAILED=1
        echo "----- [失步] ${rule_name} -----"
        # 失步文件清单：去掉 itemize 前缀，只留文件名
        echo "${out}" | sed 's/^[^ ]*  *//'
        echo "----- 清单结束 -----"
    else
        note "  对齐：${rule_name}"
    fi
}

# 规则 1：app/ -> vercel-deploy/app/
check_rule "规则1 app/ -> vercel-deploy/app/" \
    --exclude='__pycache__/' --exclude='.env' --exclude='dealdesk.db' \
    app/ "${DEPLOY_DIR}/app/"

# 规则 2：static/ -> vercel-deploy/static/
check_rule "规则2 static/ -> vercel-deploy/static/" \
    static/ "${DEPLOY_DIR}/static/"

# 规则 3：static/ -> vercel-deploy/ 根
# （AGENTS.md 排除项 + staging 自身目录 api/、app/、static/、.vercel/）
check_rule "规则3 static/ -> vercel-deploy/ 根" \
    --exclude='api/' --exclude='app/' --exclude='static/' --exclude='.vercel/' \
    --exclude='vercel.json' --exclude='requirements.txt' --exclude='dealdesk-seed.db' \
    --exclude='.DS_Store' \
    static/ "${DEPLOY_DIR}/"

if [ "${FAILED}" -ne 0 ]; then
    echo "[diff-gate] 拦截：vercel-deploy/ 与仓库源失步，禁止部署。" >&2
    echo "[diff-gate] 修复：按 AGENTS.md 三条 rsync 规则重新同步（或跑 tools/deploy.sh），再重跑本门禁。" >&2
    exit 1
fi

note "三方全部对齐，门禁通过。"
exit 0
