# 给 Muse：DealDesk v2 上线指令

> 目标：让 `dealdesk.vercel.app` 跑上 v2（新工作台在 `/app/`）。
> 代码在附件 `dealdesk-v2.bundle`（git bundle，含 `origin/main..v2` 共 17 个提交，v2 头 = `3f95d64`）。
> 全程遵守仓库 `AGENTS.md`；任何一步失败就停下报告，不要硬推。

## 0. 前提
- 本机仓库 `~/…/vertciti-dealdesk` 的 `main` 与 GitHub 一致，且 `git rev-parse origin/main` = `c8f29a45a1064ebb7f97330961494b5e6b066f0c`（bundle 的基点）。不一致先报告。
- 不要提交 `.env`、`dealdesk.db`、`e2e.db`、`.tophap-oauth-state.json`、`__pycache__/`、`dealdesk-v2.bundle`。

## 1. 导入代码
```bash
cd <仓库根>
git bundle verify /path/to/dealdesk-v2.bundle
git fetch /path/to/dealdesk-v2.bundle v2:v2
git checkout v2 && git log --oneline -1      # 应为 3f95d64 fix(v2): 独立审查 20 项…
```

## 2. 本机质量门（全部必须通过）
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
rm -f dealdesk.db && PYTHONPATH=. .venv/bin/pytest tests/ -q          # 含金标准，必须 exit 0
.venv/bin/ruff check app tests tools
.venv/bin/ruff check --config ruff-strict.toml app/domain/v2 app/services/v2 app/api/v2 app/core app/services/persistence app/paths.py --exclude app/services/persistence/migrations
.venv/bin/mypy app            # v2 模块 0 错；v1 的报错只报告不拦
cd frontend && npx -y npm@11.21.0 ci && npm run typecheck && npm run lint && npm run test:cov && npm run build && git diff --exit-code -- ../static/app && cd ..
```

## 3. 推 GitHub、开 PR
```bash
git push -u origin v2
```
在 GitHub 开 PR：`v2 → main`，标题 `feat: DealDesk v2 工作台（分层后端 + React 前端 + 中英双语）`。等 CI（quality / codeql）全绿再继续。合并由 HUIIIM 决定。

## 4. Vercel 生产环境变量（项目 `vertciti-dealdesk`，Production）
| 变量 | 值 | 说明 |
|---|---|---|
| `DATABASE_URL` | Postgres 连接串（Neon / Vercel Postgres 均可） | **必须**：Serverless 留不住 SQLite，没有它保存的数据会丢 |
| `DEALDESK_TRUST_PROXY` | `1` | **必须**：否则一人输错令牌全员被锁 |
| 认证相关 | 见 `docs/RUNBOOK.md`「用户与权限」 | 开认证并建用户：`.venv/bin/python -m app.core.security add-user <名> chairman` |

首次连 Postgres 需跑迁移（见 `docs/RUNBOOK.md`「迁移」）。token/密码**不要**写进日志、代码、聊天。

## 5. 部署
```bash
# 同步 vercel-deploy/（三条 rsync 规则，见 AGENTS.md），然后：
bash tools/pre_deploy_diff_gate.sh          # 必须 exit 0
# 改过 static/ 内联 JS 的话：python tools/csp_hashes.py 重算并写入 vercel-deploy/vercel.json
~/workspace/vertcity/deliverables/ship-gate/ship-gate dealdesk   # 统一流水线（tools/deploy.sh 已废弃，仅兜底）
```
**注意两个坑：**
1. 根目录同步规则排除了 `app/`，所以 `/app/` 必须能到达：确认 `vercel-deploy/vercel.json` 里 `/app` 和 `/app/(.*)` 指向 `static/app/…`（或指向 serverless 由 FastAPI 提供）。SPA 深链（如 `/app/deals/123`）要回落到 `static/app/index.html`。
2. `/app/` 要带严格 CSP（`app/core/hardening.py` 的 `APP_CSP`）。如果 `/app/` 走 Vercel 静态而不经 FastAPI，需在 `vercel.json` 的 `headers` 里给 `/app/(.*)` 加同一条 CSP 和安全头。

## 6. 首页 `/`（待 HUIIIM 拍板，默认 A）
- **A（推荐）**：`vercel.json` 加 `{"source": "/", "destination": "/app/", "permanent": false}` 重定向；旧页面保留在 `/d` 等原路径。
- B：首页保留旧版，在旧页加一个“进入新版工作台”入口（改 v1 字节会让金标准挂，需同步更新 golden，单独提交说明）。

## 7. 部署后验收（curl 200 不算）
1. `curl https://vertciti-dealdesk.vercel.app/api/tophap/status` → 不是 500。500 就立刻用 Vercel 回滚到上一健康部署，不要重复部署同一包。
2. 真浏览器打开 `https://dealdesk.vercel.app/app/`：能看到新版工作台（白底、Nunito Sans 字体、交易列表），控制台无 CSP 报错。
3. 右上角切 EN/中文，界面跟着变。
4. 新建一笔交易→刷新→还在（证明 Postgres 生效）。
5. 手机宽度打开：只读、不报错。
6. 截图 1–5 发回给 HUIIIM。

## 8. 发布前
跑敏感扫描：`bash ~/workspace/vertcity/security-watch/data-room-gate.sh`，FAIL 则停。
