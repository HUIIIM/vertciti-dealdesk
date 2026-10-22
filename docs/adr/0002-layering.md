# ADR 0002：domain / services / api 三层

- 状态：已采纳（2026-10-22）
- 决定：`app/domain` 纯计算（无 I/O，可性质测试）；`app/services` 编排、持久化、外部数据源；
  `app/api` 只做 HTTP 适配（校验、权限依赖、响应模型）。`app/main.py` 只装配（≤ 100 行，现 ~35 行）。
  旧导入路径用 `sys.modules` 别名兼容，v1 脚本与测试无需改动。
- v2 代码执行更严的门：ruff ALL 规则（`ruff-strict.toml`，每条豁免写原因）+ mypy strict，CI 阻塞。
