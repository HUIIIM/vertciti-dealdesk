# ADR 0003：SQLAlchemy 2 + Alembic，SQLite 开发 / Postgres 生产

- 状态：已采纳（2026-10-22）
- 决定：同一套模型与迁移同时支持 SQLite（零配置本机）与 Postgres（生产，`DATABASE_URL`）。
  迁移用 `render_as_batch` 兼容 SQLite 改表；首次连库自动升级到 head；v1 老库可被原地接管、数据不丢。
  所有业务表带审计字段（created_by / created_at / updated_at），重要动作另写 audit_log（改前 / 改后）。
- SQLite 用 NullPool：库文件被删重建（测试 / 运维）不会拿到失效连接；迁移缓存按 inode 识别同一库。
- CI 两套都跑：`tests/pg_plugin.py` 让同一批测试在 Postgres 16 上每测试一个独立库。
