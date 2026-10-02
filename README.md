![DealDesk](docs/assets/hero.png)

[![CI](https://github.com/HUIIIM/vertciti-dealdesk/actions/workflows/ci.yml/badge.svg)](https://github.com/HUIIIM/vertciti-dealdesk/actions/workflows/ci.yml)
[![Secret scan](https://github.com/HUIIIM/vertciti-dealdesk/actions/workflows/gitleaks.yml/badge.svg)](https://github.com/HUIIIM/vertciti-dealdesk/actions/workflows/gitleaks.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

# DealDesk · 房地产交易核保台

**vertciti 出品，Miao 自用的房地产运营工具。30 秒看清一笔交易值不值得做。**

录入一套房子的价格、租金、贷款 → DealDesk 按保守口径算出全口径现金需求、
打分、敏感性分析，生成带图的中文核保报告。筛 deal，不靠感觉。

![DealDesk demo](docs/assets/demo.gif)

*上面：一笔 Queens 两家庭交易 → 仪表盘 B 级 68.7 分 → 一键打开带图核保报告。*

## 快速开始 — 30 秒

```bash
./run.sh        # 自动建虚拟环境、装依赖、初始化数据库
```

浏览器打开 **http://127.0.0.1:8100**，点「新建项目」，3 分钟看到第一份打分。

手动方式：

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8100
```

## 它是怎么工作的

![架构](docs/assets/architecture.png)

输入交易 → 调研管线抓公开数据（TopHap 公共记录、可比成交、税费）→
核保引擎建模（现金流、回本测算、敏感性、评分卡）→ 图表层画图 →
输出 HTML 交互报告 + PDF 备忘录。全程中文，数据不出本机（SQLite）。

## 核心功能

![仪表盘](docs/assets/dashboard.png)

- **交易录入**：住宅 / 商业双轨中文表单，费用与风险字段按保守口径预填
- **一键打分**：双轨独立打分引擎，A / B / C / 不收录四档；硬否决项
  （浮动利率、5 年内 balloon、无退出预案、pro-forma 数字等）红色置顶
- **敏感性分析**：租金 ±10%、利率 ±2% 五档 what-if，看现金流 / CoC /
  DSCR / 入场 cap 变化
- **三张图讲清结论**：现金流回本测算、敏感性分析、评分构成
  （HTML 内联 SVG，PDF 嵌入 PNG，零 matplotlib 依赖）
- **项目对比**：最多 3 个项目并排对比
- **全面分析工作台**（`/workbench.html`）：估值评估、可比成交、市场调查、
  六维市场报告；一键把测算结果送入打分引擎
- **智能搜集 intake**：纯地址 / 房源链接 / PDF（flyer、OM）三选一，
  自动搜集公开房源、公共记录、租金、周边、历史价格
- **全口径现金需求**：每笔 deal 自动汇总首付＋交割费＋首年 capex＋储备金

![报告图表](docs/assets/report-charts.png)

## 诚实约定

这是筛选辅助工具，**不构成投资建议**。核心规则：

- 每个字段标注来源＋抓取时间＋可信度；抓不到的标"需手动补"，绝不编数
- 房源页 / PDF 的数字一律标"卖方口径、待验证"，独立验证先于任何结论
- 只碰公开页面、遵守 robots.txt；被反爬拦截立刻停手并记录，降级走手动录入
- 每笔真实交易签约 / 交割 / 报税前，必须经持牌本地房地产律师、
  CPA / 税务师、title company 审查

## 数据源（可选 enrich）

DealDesk 可接入 TopHap（公共房产记录聚合，MCP 协议）补充公共记录口径字段
（估值参考＋区间、贷款与产权历史、计税估值、法拍预警、可比成交等）。
默认**关闭**；打开前工作台照常走公开搜集 pipeline。
可信度标定：公共记录 = 高，算法估值 / CMA = 中（含区间），算法租金 = 低。

## 运行测试

```bash
rm -f dealdesk.db   # 避免开发副产品 DB 串扰（服务运行时先停服务再删库）
.venv/bin/python -m pytest tests/ -q   # 180+ 个用例
```

## 项目结构

```
dealdesk/
  app/            # FastAPI 后端：打分引擎、敏感性分析、SQLite 项目库、报告
  tools/          # 一次性脚本（如 TopHap OAuth 首次授权）
  docs/           # 集成说明文档 + assets
  static/         # 中文前端（无构建，纯 HTML/JS/CSS）
  tests/          # 单元测试
  run.sh          # 一键启动
  requirements.txt
  ATTRIBUTION.md  # 开源致谢与协议说明
```

## 贡献

欢迎 Issue 与 PR。先读 [CONTRIBUTING.md](CONTRIBUTING.md)，
核心原则：测试必须钉住 headline 数字、代码注释如实标注假设、绝不编造数据。

## 关于 vertciti

vertciti 为 Miao 构建运营人生的个人 AI 基础设施；DealDesk 是其中
"把工具做扎实"的一种证明。

- 官网：[vertciti.com](https://vertciti.com)
- 创始人 X：[@Miaojiahuii](https://x.com/Miaojiahuii)

## 许可证

MIT — 见 [LICENSE](LICENSE)。
