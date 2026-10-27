# DealDesk 运维手册（v2）

> 部署 / 回滚的硬规则以 [AGENTS.md](../AGENTS.md)「构建与部署」为准，本手册不重复、只补充 v2 新增部分。

## 1. 启动

| 场景 | 命令 |
|---|---|
| 本机（SQLite） | `./run.sh` → <http://127.0.0.1:8100/app/>（v2 工作台）；`/` 307 到 `/app/`（v1 单页已下线） |
| 指定库文件 | `DEALDESK_DB=/home/…/deals.db ./run.sh` |
| Postgres | `DATABASE_URL=postgresql://user:pass@host/db ./run.sh`（`postgres://` 也认） |

首次连到某个库会自动跑 Alembic 迁移到 head（同进程同一库只跑一次）。手动：
`python -m app.services.persistence.migrate upgrade|current`。

## 2. 环境变量

| 变量 | 缺省 | 作用 |
|---|---|---|
| `DATABASE_URL` | 空 | 设了就用 Postgres（生产） |
| `DEALDESK_DB` | 仓库根 `dealdesk.db` | SQLite 库路径（开发） |
| `DEALDESK_AUTH` | off | `on`：v2 接口认 Bearer 令牌或 Google 登录会话 cookie；off 时所有请求视为本机董事长 |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` | 空 | Google 登录凭证（OAuth 客户端）；回调 URI 须与控制台登记逐字一致，定版值：`https://vertciti-dealdesk.vercel.app/auth/google/callback`；三者齐全登录页才出现 Google 按钮 |
| `DEALDESK_TOKEN_LOGIN_ENABLED` | 空（关） | `1`：登录页同时保留令牌粘贴入口（过渡期）；Google 未配置时前端自动回退显示令牌表单防锁死，不受此开关影响 |
| `DEALDESK_SESSION_COOKIE_SECURE` | 1 | 会话 cookie 的 Secure 属性；本机 HTTP 调试可设 0，生产必须保持 1 |
| `DEALDESK_AUTH_PROTECT_V1` | 空 | `1`（且 `DEALDESK_AUTH=on`）：v1 持久化面（项目 / uw 项目 / 对比 / 研究证据 / 摄入待处理与已提取队列）读要求登录、增删改要求“分析”及以上；无状态计算面（`/api/score` 等）不在此列、保持公开。生产已设 `1` |
| `DEALDESK_AUTH_FAIL_LIMIT` / `_WINDOW` | 20 / 300 秒 | 同一 IP 错令牌达上限即 429 |
| `DEALDESK_MAX_BODY_MB` | 32 | 请求体硬上限；分块上传也边收边计数，超限 413 |
| `DEALDESK_TRUST_PROXY` | 空 | `1`：在可信反向代理（Vercel 等）后，限流按 X-Forwarded-For 第一跳计 IP；**生产必须设**，否则所有人共用代理 IP、一人输错令牌全员被锁 |
| `DEALDESK_ERROR_WEBHOOK` | 空 | 未捕获异常 POST 到该地址（Slack / 飞书等） |
| `DEALDESK_LOG_LEVEL` | INFO | JSON 结构化日志级别 |
| `TOPHAP_*`、`RENTCAST_API_KEY` | — | 数据源；token 只放 `.env`（600），**绝不写进日志 / 代码** |

## 3. 用户与权限

```bash
python -m app.core.security add-user miao chairman "苗总"   # 打印一次性 token，只显示这一次
```
角色：`chairman` 董事长（付款审批、归档、用户管理）· `analyst` 分析 · `viewer` 只读。
任何人不能审批自己发起的申请。令牌只存 sha256；丢了就新建用户 / 重新发放，无法找回。

**Google 登录（2026-10-22 起主登录方式）**：邮箱 == username 匹配既有用户（大小写不敏感）且 `active` 才放行，
不开放注册——给受邀朋友开号就是用其 Google 邮箱建用户。登录后发服务端会话（`web_sessions` 表、可吊销、
30 天滑动续期），cookie `dd_session`（HttpOnly + Secure + SameSite=Lax）。停用用户即断其新登录；
已发会话在下一次校验时同步失效（resolve 时查 active）。董事长 Google 账号行（986miao@gmail.com、chairman）
须在生产库在案，上线前核查项见施工回执。

## 4. 排障

1. 用户报错时让对方给出界面上的**请求编号**（响应头 `X-Request-ID`）。
2. 日志按编号检索：每行 JSON 带 `request_id`、`actor`、`path`、`status`、`ms`。
3. 最近 100 条未捕获异常（含堆栈）：`GET /api/v2/admin/errors`（需审计权限）。
4. 健康检查：`GET /api/v2/health`（不需登录），返回版本、库类型与迁移版本。
5. 部署后第一动作仍是 `GET /api/tophap/status` 冒烟（AGENTS.md）。

## 5. 备份与恢复

```bash
python3 tools/db_backup.py backup ~/backups          # SQLite 在线快照 / Postgres pg_dump -Fc；文件 600 权限
python3 tools/db_backup.py verify ~/backups/dealdesk-20261022T030000Z.sqlite3
python3 tools/db_backup.py restore <文件> --yes       # 先把现库另存为 *.pre-restore-<时间>，可回退
```
- 备份放 home 分区（`/tmp` 是 512M tmpfs），**不要提交进仓库**（`backups/` 已 gitignore）。
- 建议：每日 cron 备份 + 每周一次 `verify` 抽检；恢复演练每季度一次。
- 生产 Postgres 以托管服务的时间点恢复（PITR）为主，本工具为补充。

## 6. 数据迁移（改表结构）

1. 改 `app/services/persistence/schema.py`；
2. 新建 `migrations/versions/000N_<说明>.py`（新增 NOT NULL 列必须带 `server_default`，老库才能升级）；
3. `tests/test_persistence.py` 的 head 断言改为新版本号；
4. SQLite 与 Postgres 两套 CI 都绿再合并。

## 7. 安全

- 响应头：nosniff、`X-Frame-Options: DENY`、Referrer-Policy、Permissions-Policy；`/app/` 另有严格 CSP（只允许同源脚本 / 样式）。
- 只认 `Authorization` 头、不读 cookie → 无 CSRF 面。
- 发布前跑 data-room 敏感扫描（AGENTS.md）；CI 有 gitleaks、CodeQL、pip-audit、npm audit。
