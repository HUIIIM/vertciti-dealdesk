# Changelog

格式参照 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [2.0.0] — 未发布（2026-10-22）

v1 全部计算结果不变（金标准 0 偏离，见 ADR 0001）。

### 新增
- **v2 交易工作台**（`/app/`）：流水线看板 / 表格、交易页（结论卡 + 10 个标签页）、2–4 笔并排比较、设置；
  ⌘K 命令面板、J/K/Enter/E/⌘S/? 快捷键、密度切换、暗色模式；手机端只读。
- **58 个 `/api/v2` 端点**：交易生命周期七阶段与关卡（不能跳阶段，回退须写原因）、版本快照与对比、
  数字护照（来源 / 页码 / 可信度 / 复核 / 新鲜度）、跨来源矛盾登记与裁决、红队面板、情景加权、
  反推最高出价（多约束取最紧，写明卡价约束）、投委会投票与投委会包、决策日志（数字快照冻结）、
  任务 / 审批（付款仅董事长、不能自批）/ 文件、持有期事后归因、审计查询。
- 角色权限（董事长 / 分析 / 只读）、Bearer 令牌（只存哈希）、错令牌限流、安全响应头与严格 CSP。
- 结构化 JSON 日志 + 请求编号 + 未捕获异常环形缓冲 / webhook。
- 备份 / 恢复工具 `tools/db_backup.py`；运维手册 `docs/RUNBOOK.md`；ADR 0001–0005。

### 变更
- 后端分为 domain / services / api 三层，`app/main.py` 1,407 → ~35 行；旧导入路径保持可用。
- 数据层改为 SQLAlchemy 2 + Alembic，支持 Postgres（`DATABASE_URL`）；v1 老库原地接管。

### 修复
- 利率极小（浮点下 (1+r)^n == 1）时月供算成 $0 → 按零利率摊还（性质测试发现）。
- 访问日志操作人误记为 system；新建表单回车不提交；若干对比度与 ARIA 问题。

### 质量
- 测试 633 个（含金标准、性质测试、Postgres 套件）；前端 vitest 51 个、Playwright E2E 11 个（含 axe 与 CSP 违规检测）。
- CI：ruff（v2 ALL 规则）、mypy strict（v2）、覆盖率门槛、pip-audit、npm audit、gitleaks、CodeQL、Dependabot。
