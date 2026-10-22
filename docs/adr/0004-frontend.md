# ADR 0004：v2 前端 = TypeScript + React + Vite，构建产物入库

- 状态：已采纳（2026-10-22）
- 决定：`frontend/` 源码，`static/app/` 为构建产物并提交进仓库——保持“无构建步骤直接跑”的部署形态
  （AGENTS.md），CI 重新构建并 `git diff` 保证产物与源码一致。API 客户端由后端 OpenAPI 生成
  （`npm run gen:api`），接口改了前端没重新生成 → CI 失败。禁止 `dangerouslySetInnerHTML`（ESLint 规则）。
- 路由用 hash（`#/deals/1/model`）：静态托管无需服务端回退规则。
- 依赖版本选发布满两周以上的版本，降低供应链投毒窗口；Dependabot 设 7 天冷却。
