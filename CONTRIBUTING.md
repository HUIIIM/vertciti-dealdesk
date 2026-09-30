# Contributing to vertciti-dealdesk

感谢你愿意贡献！本项目是 vertciti 出品的房地产交易核保工具，
欢迎 Issue 与 Pull Request。

## 基本流程

1. Fork 本仓库，基于 `main` 建分支（`feat/...` / `fix/...` / `docs/...`）
2. 本地跑通全量测试后再提交 PR
3. PR 描述写清：改了什么、为什么、测试怎么验证

## 开发环境

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8100
```

运行测试：

```bash
rm -f dealdesk.db
.venv/bin/python -m pytest tests/ -q
```

## 代码规范

- 纯函数计算优先于状态：金融数学放 `app/finance.py`，打分逻辑放
  `app/scoring_*.py`，便于单元测试
- 每个新计算必须配套单元测试，且测试必须**钉住 headline 数字**
  （手工验算的关键数值）
- 注释如实标注假设：未验证的参数不得当作已知事实写进代码

## 诚实铁律（必读）

1. 绝不编造数据：抓不到的字段标"需手动补"
2. 卖方口径的数字一律标"卖方口径、待验证"
3. 每个外部字段携带来源＋抓取时间＋可信度
4. 只碰公开页面、遵守 robots.txt；被反爬拦截立刻停手并记录

违反以上任何一条的 PR 将被拒绝。

## 开源致谢

开发中参考的开源项目见 [ATTRIBUTION.md](ATTRIBUTION.md)：
只借鉴功能形态与指标思想，代码全部独立重写。
