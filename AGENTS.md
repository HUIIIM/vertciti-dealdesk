# AGENTS.md — AI agent 操作手册（DealDesk）

> 给打开这个仓库的 AI agent：按本手册干活，不许凭记忆编脚本、编命令。
> 仓库：DealDesk 房地产交易核保台（`HUIIIM/vertciti-dealdesk`，MIT，公开）。
> 技术栈：Python 后端（`app/main.py`，uvicorn）＋ 纯静态前端（`static/`）＋ SQLite。

## 快速开始

```bash
./run.sh        # 自动建 .venv、装依赖、初始化数据库，跑 http://127.0.0.1:8100
```

手动：`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
→ `.venv/bin/python -c "from app import db; db.init_db()"`
→ `.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8100`

## 测试（铁律）

```bash
rm -f dealdesk.db && .venv/bin/pytest tests/ -q
```
- 本机 shell 直接跑 pytest 会 `ModuleNotFoundError: No module named 'app'`
  （连已存在的 test_ownership.py 也一样，非代码问题）：必须加
  `PYTHONPATH=.`，即 `PYTHONPATH=. .venv/bin/pytest tests/ -q`。
  （2026-10-09 实证）

- **跑测试前必删 `dealdesk.db`**（仓库根的开发副产品库）：历史上 `DEALDESK_DB` 在
  `app.db` import 之后才生效、脏库会让 `test_list_sorted_by_cash_to_close` 误挂。
  v2 起连库改为懒读（tests/conftest.py 会话级临时库），但删库成本为零，仍保留此步。
- v2 质量门（CI 同款，提交前本机全跑）：
  - `ruff check app tests tools`
  - `ruff check --config ruff-strict.toml app/domain/v2 app/services/v2 app/api/v2 app/core app/services/persistence app/paths.py --exclude app/services/persistence/migrations`
  - `mypy app`（v2 模块 strict 必须 0 错；v1 只报告）
  - 金标准 `tests/test_golden_v1.py` 偏离即失败：**改 v1 报告字节（哪怕折一行 CSS）也会挂**，
    这是有意的（docs/adr/0001-golden-master.md）。
  - Postgres：`PG_ADMIN_URL=postgresql://… pytest -p tests.pg_plugin tests/test_persistence.py tests/test_v2_*.py`
  - 前端（`cd frontend`）：`npx -y npm@11.21.0 ci` → `npm run typecheck && npm run lint && npm run test:cov && npm run build`
    → `git diff --exit-code -- ../static/app`；E2E：`CHROMIUM_PATH=… npm run e2e`。
    改了后端 v2 接口必须 `npm run gen:api` 并提交 `openapi.json` 与 `src/api/schema.d.ts`。
- `/tmp` 是 512M tmpfs：`app/pdf_intake.py` 曾因写 `/tmp` 爆盘；编码/大文件
  一律用 home 分区路径。
- 真浏览器 E2E 的 route 代理转发坑（2026-10-14 实证）：Chromium 经 CDP 暴露的
  `post_data_buffer` 对 `fetch(FormData+File)` 只含 multipart 头（实测 196 字节、
  无文件体），httpx 原样转发后服务端收到空文件、回 400"文件过小或为空"——
  这是测试脚手架的锅，不是产品 bug（curl/httpx 直传同文件均 200）。E2E 脚本
  须对上传端点做 multipart 重建（用同一测试文件按原 boundary 补回文件体），
  或改走非拦截通道；JSON POST 不受此影响。

## 构建与部署

- 本地即生产形态：无构建步骤，后端 `app/`＋静态 `static/` 直接跑。v2 前端源码在 `frontend/`，
  构建产物 `static/app/` 入库（随 `static/` 一起同步到 vercel-deploy/）。
- v2 运维（环境变量、用户与权限、备份恢复、排障、迁移）：见 `docs/RUNBOOK.md`。
- 生产部署源是 `vercel-deploy/`（`app/`、`static/`、根静态文件、`requirements.txt`
  必须与仓库根对齐，全量同步）。部署命令：
  `~/workspace/skills/vercel/bin/vc-deploy` → Vercel 项目 `vertciti-dealdesk`。
- 部署前必跑 `tools/pre_deploy_diff_gate.sh`（台账第 9 项门禁）：按下方三条 rsync
  规则 dry-run diff，失步→非零退出＋清单，直接拦截；`tools/deploy.sh` 已在
  vc-deploy 调用前强制执行。
- 改了 `static/` 内联 JS 必须同步重算 CSP hash 并写入 `vercel.json`
 （曾因 hash 未更新导致全站 #app 空白，curl 200 看不出）。
- 部署后必验生产 URL 真实渲染（curl 200 不算验证）。
- **坏部署处置（2026-10-09 实证 dpl_69pJZCYCShhyrofoqHsuMugNjG8j）**：
  生产部署后若全站 500（含未改动的端点），先判"坏部署"而非"坏代码"——
  用同 bundle 打 preview 部署验证：preview 正常即证代码无辜。
  处置顺序：① 立即用 Vercel API redeploy 上一健康部署回滚（2 分钟恢复）；
  ② 再用同一 bundle 做一次干净生产部署。部署后第一动作永远是
  `GET /api/tophap/status` 冒烟，500 则回滚、不反复重部署同一 bundle。
- vercel-deploy/ 有**两处**静态副本：根目录一份 ＋ `static/` 子目录一份
  （与仓库 `static/` 三方对齐，缺任一=生产页面版本错乱）；rsync 同步三条：
  `app/ → vercel-deploy/app/`、`static/ → vercel-deploy/static/`、
  `static/ → vercel-deploy/`（根，排除 api/、app/、vercel.json、
  requirements.txt、dealdesk-seed.db）。

## Git 规范

- Conventional commits；作者邮箱用 GitHub noreply，**绝不发明邮箱**
  - 正确的 noreply 是 `HUIIIM <130162274+HUIIIM@users.noreply.github.com>`（130162274 = HUIIIM 的账号 ID）。
    历史上用过的 `102184733+HUIIIM@…` 的 ID 属于另一个账号（crfairbanks-sps），提交会算到别人名下，
    官网仓的 Vercel 预览因此被拦（2026-10-22 实证）——不要再用。
 （曾用 `javis@vertciti.com` 导致 Vercel 部署被 block）。
- **绝不提交**：`.env`（600 权限，含 TopHap token）、`dealdesk.db`、
  `.tophap-oauth-state.json`、`__pycache__/`。
- push 事项由 parent 定夺；本仓库默认只 commit 不 push。

## 禁区

- TopHap token 只活 1 小时、无 refresh token：过期走 OAuth 重授权，
  **绝不把 token 明文写进日志/代码/记忆**。
- 未知数据保持未知：缺数渲染"—"，**绝不编数字**（NOI 未知不许写 $0）。
- 百分比口径：商业空置率等一律按"百分比数"（15 表示 15%），小数口径是 P0 bug。
- 敏感扫描：发布前跑 data-room 门禁（token/私钥/身份证号为 FAIL）。
- 覆盖率目标 ≥80%；对外发布走 GC＋CEO 评审（见仓库外发布流程）。

## 常用命令

| 动作 | 命令 |
|---|---|
| 启动 | `./run.sh` |
| 测试 | `rm -f dealdesk.db && .venv/bin/pytest tests/ -q` |
| v2 工作台 | `http://127.0.0.1:8100/app/` |
| 加用户 | `.venv/bin/python -m app.core.security add-user <名> <chairman\|analyst\|viewer>` |
| 备份 | `.venv/bin/python tools/db_backup.py backup ~/backups` |
| 查 TopHap 状态 | `curl http://127.0.0.1:8100/api/tophap/status` |
| 生产状态 | `curl https://vertciti-dealdesk.vercel.app/api/tophap/status` |
| 敏感扫描 | `bash ~/workspace/vertcity/security-watch/data-room-gate.sh` |
