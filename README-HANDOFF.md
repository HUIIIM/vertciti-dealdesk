# HANDOFF — DealDesk

## 这是什么
房地产交易承销（underwriting）工作台：录入物业 -> 多源估值/评分 -> 生成承销报告与 tearsheet。
N=1 展示与引流定位（GitHub -> vertciti.com -> newsletter），仅美国市场。生产在 Vercel。

## 目录结构
- `app/`：FastAPI 应用主体。`app/main.py` 入口；`app/routers/intake.py` 录入路由；估值/评分在 `app/scoring_*.py`、`app/uw_*.py`、`app/finance.py`；报告在 `app/report*.py`、`app/pdf_*.py`、`app/tearsheet.py`；`app/tophap.py` 为 TopHap 数据源接入（OAuth 令牌见 `app/token_watch.py`）；`app/db.py`/`app/models.py` 为 SQLite 数据层
- `static/`：前端静态资源（工作台 UI）
- `tests/`：pytest 测试套件（530+ 用例）
- `tools/`：运维脚本（含 TopHap OAuth 刷新脚本；**令牌文件已按交接规则剔除，不在包内**）
- `docs/`、`assets/`：文档与素材

## 登录界面与后台入口
- 无终端用户登录体系（单用户内部工具 + 公开展示面）。工作台入口即 `app/main.py` 挂载的页面与 `static/`。
- 第三方数据源 TopHap 走 OAuth（`app/tophap.py`），令牌不在本包内。

## 怎么跑
```bash
bash run.sh            # 自动建 .venv、装 requirements、初始化 DB，起 http://127.0.0.1:8100
# 或手动：uvicorn app.main:app --host 127.0.0.1 --port 8100
```
环境变量：复制 `.env.example`（若有）为 `.env` 自行填写；`dealdesk.db` 为本地数据文件，未随包（代码会自动建库）。

## 技术栈
Python 3 + FastAPI + uvicorn、SQLite、ReportLab/OpenPyXL（报告）、原生前端静态页。

## 设计改造提示
品牌令牌见 `_brand-dna/`。UI 对齐目标：官网风格（黑白 + 信号橙 #FF4713 等，Nunito Sans + 苹方）。
