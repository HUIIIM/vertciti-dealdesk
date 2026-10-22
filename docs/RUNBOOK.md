# DealDesk 运维手册（v2）

> 部署 / 回滚的硬规则以 [AGENTS.md](../AGENTS.md)「构建与部署」为准，本手册不重复、只补充 v2 新增部分。

## 1. 启动

| 场景 | 命令 |
|---|---|
| 本机（SQLite） | `./run.sh` → <http://127.0.0.1:8100/app/>（v2 工作台），`/` 为 v1 页面 |
| 指定库文件 | `DEALDESK_DB=/home/…/deals.db ./run.sh` |
| Postgres | `DATABASE_URL=postgresql://user:pass@host/db ./run.sh`（`postgres://` 也认） |

首次连到某个库会自动跑 Alembic 迁移到 head（同进程同一库只跑一次）。手动：
`python -m app.services.persistence.migrate upgrade|current`。

## 2. 环境变量

| 变量 | 缺省 | 作用 |
|---|---|---|
| `DATABASE_URL` | 空 | 设了就用 Postgres（生产） |
| `DEALDESK_DB` | 仓库根 `dealdesk.db` | SQLite 库路径（开发） |
| `DEALDESK_AUTH` | off | `on`：v2 接口需 `Authorization: Bearer <token>`；off 时所有请求视为本机董事长 |
| `DEALDESK_AUTH_PROTECT_V1` | 空 | `1`：v1 项目增删改也要求“分析”及以上 |
| `DEALDESK_AUTH_FAIL_LIMIT` / `_WINDOW` | 20 / 300 秒 | 同一 IP 错令牌达上限即 429 |
| `DEALDESK_ERROR_WEBHOOK` | 空 | 未捕获异常 POST 到该地址（Slack / 飞书等） |
| `DEALDESK_LOG_LEVEL` | INFO | JSON 结构化日志级别 |
| `TOPHAP_*`、`RENTCAST_API_KEY` | — | 数据源；token 只放 `.env`（600），**绝不写进日志 / 代码** |

## 3. 用户与权限

```bash
python -m app.core.security add-user miao chairman "苗总"   # 打印一次性 token，只显示这一次
```
角色：`chairman` 董事长（付款审批、归档、用户管理）· `analyst` 分析 · `viewer` 只读。
任何人不能审批自己发起的申请。令牌只存 sha256；丢了就新建用户 / 重新发放，无法找回。

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
