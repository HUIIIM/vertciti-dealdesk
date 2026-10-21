# DealDesk 工程化与设计改造路线（v1，2026-10-21）

## 现状体检（脚本实测）
| 指标 | 数值 | 企业级目标 |
|---|---|---|
| 后端代码 | 约 13,900 行；main.py 1,407 行（路由集中） | 按领域拆分，单文件 ≤ 400 行 |
| 超过 100 行的函数 | 20 个（最长 build_enhanced_pdf 407 行） | ≤ 60 行，复杂度可测 |
| 返回类型标注 | 356 / 489 函数（约 73%） | 100%，mypy 严格模式通过 |
| 依赖 | 只有下限 | 加上限（本次已做），再加锁文件 |
| CI | 只跑 pytest + gitleaks | 规范、覆盖率、类型、漏洞扫描（本次已加 quality.yml） |
| 前端 | 5,500 行原生 JS，innerHTML 115 处 | 全部经 vcSafe.html 转义（本次已加 safe.js） |

## 本次已完成（第 1 步：护栏）
1. requirements.txt：每个依赖加大版本上限。
2. pyproject.toml：pytest、覆盖率、ruff（只开真错误规则）、mypy 配置。
3. .github/workflows/quality.yml：ruff → pytest + 覆盖率 ≥ 70% → mypy（先报告）→ pip-audit。
4. .pre-commit-config.yaml：提交前跑 ruff 与 gitleaks。
5. static/safe.js：安全渲染工具；SECURITY.md。

## 下一步（按顺序，每步必须 pytest 全绿）
2. 拆 main.py：routers/ 按 residential、commercial、workbench、reports、intake 拆分；只搬代码不改逻辑；每拆一个跑一次全量测试。
3. 拆长函数：先拆 pdf_uw.build_enhanced_pdf、excel_uw.build_uw_xlsx、scoring_commercial.score；用金标准对比测试（tests/test_golden_compare.py）锁定输出不变。
4. 前端：115 处 innerHTML 逐个改为 vcSafe.html；外部数据（地址、OCR 结果、上传文件名）优先。
5. 类型：mypy 从“报告”改为“阻塞”，逐模块开启 check_untyped_defs。

## 设计改造（参考同行）
- Dealpath：以交易为中心组织任务、审批与文件 → 首页改为“交易列表”，点进单笔交易。
- DealFlowPro：提取的每个数值带可信度、标出矛盾、反推最高出价 → 每个数字旁显示来源与可信度，矛盾黄标，结论卡给“最高出价”。
- DealCheck：同一套数据反复压力测试 → 敏感性标签页用滑块实时看回报变化。
- 单笔交易页结构：结论卡（结论 · 最高出价 · Cap Rate · DSCR · IRR · 现金回报）→ 标签页：租金表 / T12 / 模型 / 敏感性 / 文件 / 报告。
