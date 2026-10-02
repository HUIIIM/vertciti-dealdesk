#!/usr/bin/env bash
#
# DealDesk 一键部署脚本：部署前自动把 repo 根同步到 vercel-deploy/，
# 再调用 vc-deploy 发布到 Vercel 生产环境并等待 READY。
#
# 用法：bash tools/deploy.sh   （在仓库根或任意目录执行均可）
# 失败时以非零退出码退出。
#
set -euo pipefail

# ---- 定位仓库根（脚本所在目录的上一级） ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

VC_DEPLOY="$HOME/workspace/skills/vercel/bin/vc-deploy"
PROJECT="vertciti-dealdesk"
TEAM="vertciti"
DEPLOY_DIR="vercel-deploy"

log()  { echo "[deploy] $*"; }
fail() { echo "[deploy][失败] $*" >&2; exit 1; }

log "==== DealDesk 部署开始 ===="
log "仓库根：${REPO_ROOT}"

# ---- 前置检查 ----
command -v rsync >/dev/null 2>&1 || fail "未找到 rsync，请先安装"
[ -x "${VC_DEPLOY}" ] || fail "未找到部署工具：${VC_DEPLOY}"
[ -d "${DEPLOY_DIR}/api" ] || fail "缺少 ${DEPLOY_DIR}/api（Vercel serverless 入口，不应被删除）"

# ---- 步骤 1：同步 app/ ----
log "步骤 1/6：同步 app/ -> ${DEPLOY_DIR}/app/ ..."
rsync -a --delete --delete-excluded \
    --exclude='__pycache__' \
    --exclude='.env' \
    --exclude='dealdesk.db' \
    app/ "${DEPLOY_DIR}/app/" \
    || fail "app/ 同步失败"
log "  app/ 同步完成"

# ---- 步骤 2：同步 static/ ----
log "步骤 2/6：同步 static/ -> ${DEPLOY_DIR}/static/ ..."
rsync -a --delete --delete-excluded \
    --exclude='__pycache__' \
    --exclude='.env' \
    --exclude='dealdesk.db' \
    static/ "${DEPLOY_DIR}/static/" \
    || fail "static/ 同步失败"
log "  static/ 同步完成"

# ---- 步骤 3：复制根静态文件 ----
log "步骤 3/6：复制根静态文件到 ${DEPLOY_DIR}/ 根 ..."
for f in index.html workbench.html workbench.js uw-commercial.html uw-commercial.js app.js style.css; do
    if [ -f "static/${f}" ]; then
        cp "static/${f}" "${DEPLOY_DIR}/${f}" \
            || fail "复制 static/${f} 失败"
        log "  已复制 static/${f} -> ${DEPLOY_DIR}/${f}"
    else
        log "  跳过 ${f}（static/ 下不存在）"
    fi
done

# ---- 步骤 4：复制 requirements.txt ----
log "步骤 4/6：复制 requirements.txt ..."
[ -f "requirements.txt" ] || fail "仓库根缺少 requirements.txt"
cp "requirements.txt" "${DEPLOY_DIR}/requirements.txt" \
    || fail "requirements.txt 复制失败"
log "  requirements.txt 同步完成"

# ---- 步骤 5：一致性校验（不动 api/ 目录） ----
log "步骤 5/6：一致性校验 ..."
diff -rq app "${DEPLOY_DIR}/app" --exclude=__pycache__ \
    || fail "校验失败：app 与 ${DEPLOY_DIR}/app 存在差异"
diff -rq static "${DEPLOY_DIR}/static" \
    || fail "校验失败：static 与 ${DEPLOY_DIR}/static 存在差异"
log "  校验通过：app/、static/ 与部署目录完全一致（api/ 未动）"

# ---- 步骤 6：部署到 Vercel 并等待 READY ----
log "步骤 6/6：部署到 Vercel（项目 ${PROJECT}，团队 ${TEAM}），等待 READY ..."
DEPLOY_URL="$("${VC_DEPLOY}" "${DEPLOY_DIR}" "${PROJECT}" --team "${TEAM}")" \
    || fail "vc-deploy 执行失败"
log "部署成功！"
log "部署 URL：${DEPLOY_URL}"
log "==== DealDesk 部署完成 ===="
