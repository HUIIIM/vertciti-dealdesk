# 给 Muse：DealDesk v2 上线指令

> 目标：让 `dealdesk.vercel.app` 跑上 v2（新工作台在 `/app/`）。
> 代码已在 GitHub：`v2` 分支，PR #3（https://github.com/HUIIIM/vertciti-dealdesk/pull/3）。**不用 bundle，也不要再开 PR。**
> 全程遵守仓库 `AGENTS.md`；任何一步失败就停下报告，不要硬推。

## 0. 前提
- 不要提交 `.env`、`dealdesk.db`、`e2e.db`、`.tophap-oauth-state.json`、`__pycache__/`。

## 1. 取代码
```bash
git fetch origin v2 && git checkout v2   # 以 PR #3 的最新提交为准
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

## 3. PR
PR #3 已开（Claude 维护，CI 红了会自动修）。等它 CI 绿、HUIIIM 合并后，从 `main` 部署。

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

## 6. 老版已下线（HUIIIM 已定）
- 仓库已删除 v1 页面文件（`static/index.html`、`d.*`、`workbench.*`、`uw-commercial.*` 等），FastAPI 对旧地址回 307 → `/app/`。
- `tools/deploy.sh` 步骤 3 会删掉 `vercel-deploy/` 根目录里的旧副本——**手动同步时也必须删**，否则 Vercel 先发静态文件，用户看到的还是老版。
- `vercel-deploy/vercel.json`：把 **`docs/deploy/vercel-v2.json`** 里的 `redirects` / `rewrites` / `headers` 合并进去（原有 `/api/*` → serverless 的规则保留不动）。
  这份片段由 `tests/test_vercel_v2_routing.py` 守着：CSP 与代码逐字一致、旧地址全覆盖、引用的构建文件真实存在。
  `/app/` 在 Vercel 上走 CDN 静态、不经 FastAPI，所以**严格 CSP 只能靠这份 headers 下发**，漏了就没有 CSP。
- 删掉 `vercel.json` 里给旧页面内联脚本配的 CSP hash 和 `/d → /d.html` 之类的旧 rewrite。

## 7. 部署后验收（curl 200 不算）
1. `curl https://vertciti-dealdesk.vercel.app/api/tophap/status` → 不是 500。500 就立刻用 Vercel 回滚到上一健康部署，不要重复部署同一包。
2. 真浏览器打开 `https://dealdesk.vercel.app/app/`：能看到新版工作台（白底、Nunito Sans 字体、交易列表），控制台无 CSP 报错。
3. 右上角切 EN/中文，界面跟着变。
4. 新建一笔交易→刷新→还在（证明 Postgres 生效）。
5. 手机宽度打开：只读、不报错。
6. 截图 1–5 发回给 HUIIIM。

## 8. 发布前
跑敏感扫描：`bash ~/workspace/vertcity/security-watch/data-room-gate.sh`，FAIL 则停。
