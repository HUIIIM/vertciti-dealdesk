# DealDesk · 房地产交易核保台

vertciti 房地产收购部自研的 deal 分析平台：**中文前台 + Python 后端**，
住宅 / 商业双轨独立核保，评分口径严格对齐内部 buyer box。

- 住宅线：`buyer-box.md v2.3`（100 分制：现金流 30 / 贷款条款 25 / 首付 15 / 市场 15 / 风险逆向扣分 15）
- 商业线：`buyer-box-commercial.md v1.3`（100 分制：NOI-DSCR 30 / 租约 20 / 贷款条款 15 / 首付 10 / 市场 10 / 风险逆向扣分 15；另有封顶降级机制）

代码全部独立重写，未复制任何第三方代码；参考的开源项目见 [ATTRIBUTION.md](ATTRIBUTION.md)，
学习笔记见 `../deliverables/real-estate-acquisitions/deal-scout/tool-study-notes.md`。

## 功能

- **项目录入**：住宅 / 商业双轨中文表单，费用默认值已按 buyer box 保守口径预填
  （住宅：空置 8%、维修 8%、CapEx 8%、管理费 10%；商业：管理费 ≥8%、税按 +10% 重估风险）
- **一键打分**：A / B / C / 不收录四档，硬否决项红色置顶提示（浮动利率、5 年内 balloon、
  无退出预案、pro-forma 租金/NOI、无 authorization to release、无可行退出等；负净值/抛售依赖改为风险旗）
- **敏感性分析**：租金 ±10%、利率 ±2% 五档 what-if 表，看现金流 / CoC / DSCR / 入场 cap 变化
- **项目对比**：最多 3 个项目并排对比
- **打分报告**：中文可打印报告页（浏览器打印 → 另存为 PDF）
- **本地项目库**：SQLite（`dealdesk.db`），数据不出本机
- **全口径现金需求**：每笔 deal 自动汇总首付＋交割费＋初期维修/首年 capex＋储备金（＋TI/LC），
  对应"手头资金有限"硬约束下的现金规划

## 快速开始

```bash
cd ~/workspace/vertcity/dealdesk
./run.sh        # 自动建虚拟环境、装依赖、初始化数据库
```

浏览器打开 **http://127.0.0.1:8100**。

手动方式：

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8100
```

运行测试：`.venv/bin/python -m unittest discover -s tests -v`（48 个用例，含 headline 数字钉住测试）

## 评分口径说明（实现细节）

> 口径声明：两 buyer box 只规定了**维度与总权重**（住宅 30/25/15/15/15、商业 30/20/15/10/10/15）
> 和关键阈值（如 ≥$500/≥8.5% 满分、DSCR<1.25 否决）。**维度内部的线性插值与子项权重分配
> 为 DealDesk v1.3 实施规则**（下表），已如实列出。

### 住宅线（buyer-box.md v2.3）

| 维度 | 权重 | 映射规则 |
|---|---|---|
| 现金流指标 | 30 | 单门现金流/CoC/DSCR 综合：单门 ≥$500 满分、$300 及格线线性；CoC ≥15% 满分、12% 及格线；DSCR ≥1.5 满分、1.25 及格线；三者按 60/20/20 加权 |
| 贷款条款 | 25 | 利率 ≤3% 满分 15 分（3–6% 线性降至 8 分，6–8% 降至 0）；剩余 ≥25 年满分 10 分；银行正式承接 +2（封顶 25） |
| 首付比例 | 15 | **浮动制（v2.2）**：基础分按首付比例线性插值（≤5%→100，8%→85，10%→70，15%→40，25%→0）；现金流强度（现金流维度得分率）≥60% 起上浮最高 ＋15 分、封顶 100；按权重折算。≤10% 为正常区间，>10% 需 RE-0 特批。deal 越好、可承受首付越高 |
| 市场与升值 | 15 | 人口流入 0–4＋就业 0–4＋库存/DOM 0–4＋历史增值 0–3；未评估 = 0（不编造） |
| 风险逆向扣分 | 15 | 15 分起，每 1 个实质风险旗扣 3 分；储备金 <6 个月 PITI 自动追加风险旗；**负净值入场自动追加风险旗（v2.3 起不再单独否决）** |

分级：≥80 A（日报头条）· 65–79 B（日报收录）· 50–64 C（观察名单）· <50 不收录。
硬否决（任一触发即"否决"）：浮动利率 / 5 年内 balloon / 无主＋备退出路径 /
subject-to 无 due-on-sale 备用预案 / 逾期 >90 天无折价对冲 / 无保险路径 /
拒签 authorization to release / pro-forma 租金 / HOA 巨额欠费或 title 硬伤 / 欺诈。
（v2.3 起负净值不再单独否决，改"负净值入场"风险旗＋补偿条件制：现金流为正、DSCR、储备金、
可行退出路径缺一由对应否决项拦下。）

费用口径（F4）：OpEx = 税＋保险＋HOA＋业主水电＋维修%×租金＋CapEx%×租金＋管理费%×EGI；
NOI 不含还本付息；DSCR = NOI ÷ 年还本付息。

### 商业线（buyer-box-commercial.md v1.3）

| 维度 | 权重 | 映射规则 |
|---|---|---|
| NOI 与 DSCR | 30 | 入场 cap ≥8.5% 满分 20（7.5% 及格线）；spread ≥150bps 得 5 分（≥100bps 得 3）；DSCR ≥1.35 得 5 分（<1.25 直接否决不参与打分） |
| 租约质量 | 20 | WALT ≥5 年满分 10（3–5 年线性，<3 年 0 分）；全 NNN +4、无集中到期 +3、租户信用达标 +3 |
| 贷款/交易条款 | 15 | 最长剩余期限 ≥10 年 8 分；无 balloon 或 ≥10 年 4 分；seller financing 结构 +3（封顶 15） |
| 首付比例 | 10 | **浮动制（v1.2）**：基础分按首付比例线性插值（≤5%→100，8%→85，10%→70，15%→40，25%→0）；现金流强度（NOI/DSCR 维度得分率）≥60% 起上浮最高 ＋15 分、封顶 100；按权重折算。≤10% 为正常区间，>10% 需 RE-0 特批，>20% 不进日报 |
| 市场基本面 | 10 | 人口/就业 0–3＋类别空置趋势 0–3＋租金走势 0–2＋房东友好度 0–2；未评估 = 0 |
| 风险逆向扣分 | 15 | 15 分起，每 1 个风险旗扣 3 分；储备金不足（<6 个月 debt service，value-add <12 个月）自动追加；**负净值入场自动追加风险旗（v1.3 起不再单独否决）**；**退出含抛售成分自动追加"退出依赖高价抛售"风险旗（v1.3 起不再单独否决）** |

硬否决：资产类别在范围外（office、酒店已纳入 in scope）/
浮动利率 / 5 年内 balloon / 无退出预案＋买家池证据 / Phase I 环境红旗 / TI-LC 无资金覆盖 /
rollover 悬崖（WALT<2 且 12 个月到期 >40%）/ pro-forma NOI 无 rent roll / 拒签 authorization to release /
zoning 不合规 / 欺诈 / DSCR<1.25（酒店专项 ≥1.35）/
**无可行退出 no_viable_exit**（v1.3：退出完全依赖短期高价抛售、且 refi/持有收租皆不成立时才否决）/
office 在租率 <80% / office WALT <4 年 / 酒店无经营记录 / 酒店卖方 pro-forma RevPAR。
（v1.3 起：① 删除"只能靠短期高价抛售解套"一票否决——高价抛售可接受，条件是 refi 能独立成立
（refi 后能拿出钱）或持有收租成立，含抛售成分的挂风险旗呈报 Miao 定夺；② 负净值不再单独否决，
改风险旗＋补偿条件制。）

NOI 口径（F13/F14/F15）：EGI =（合同租金＋其他收入）×(1−空置)；OpEx 含税 ×1.1 重估上浮；
重置储备取 max（类别 $/psf 或 $/单元/年，5%×EGI）；净现金流再扣还本付息、储备、TI/LC 摊销；
入场 cap = 保守重算 NOI ÷（成交价＋交割费＋首年必投 capex＋酒店 PIP capex）。

**v1.1 专项口径**：
- Office：空置/坏账假设强制 ≥12%（输入更低也按 12%）；在租率 ≥80%、WALT ≥4 年；租金 −10% 压力测试 DSCR 仍需 ≥1.25，
  不通过则封顶降级为 C（非一票否决）；TI/LC 须逐项核算（未逐项 = 自动风险旗）；纯投机性空置办公不看。
- 酒店：不设固定空置率；RevPAR 取 trailing 12 个月与过去 3 年平均孰低（录入人按孰低填年总营收，卖方 pro-forma = 否决）；
  管理费 ≥5% 营收、FF&E reserve ≥4% 营收（输入更低也按此收取）；DSCR ≥1.35；品牌 PIP capex 全额计入收购成本；
  淡季月份现金流须覆盖当月 debt service（未通过 = 不能进 A 级）；特许经营协议 ≥10 年或有续期权；
  无经营记录的新建/烂尾酒店 = 不收录。
- **封顶降级**（downgrades，非一票否决）：office 压力测试失败最高 C 级；value-add 预租率 <70% 不能进 A 级
  （降为 B）；酒店淡季覆盖未通过不能进 A 级。
- **cash-to-close（一级字段）** = 现金首付＋交割费＋储备金（n 个月 debt service/PITI）＋首年 capex/TI-LC（＋酒店 PIP capex）；
  金额硬上限不硬编码（待 Miao 给数额）；列表支持 `?sort=cash_to_close` 升序。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/health | 健康检查 |
| GET/POST | /api/projects | 项目列表（`?sort=cash_to_close` 按全口径现金需求升序）/ 新建（自动打分入库） |
| GET/PUT/DELETE | /api/projects/{id} | 读取（含最新引擎重算）/ 更新 / 删除 |
| POST | /api/score | 一键打分（不入库，录入预览用） |
| POST | /api/sensitivity | 敏感性分析 |
| GET | /api/compare?ids=1,2,3 | 项目对比 |
| GET | /api/projects/{id}/report | 中文打分报告（可打印页） |

## 项目结构

```
dealdesk/
  app/
    main.py               # FastAPI 路由 + 静态前端挂载
    models.py             # Pydantic 输入模型（百分制约定）
    finance.py            # 共享金融数学（F1–F15）
    scoring_residential.py# 住宅评分引擎（buyer-box v2.3）
    scoring_commercial.py # 商业评分引擎（buyer-box-commercial v1.3）
    sensitivity.py        # 敏感性分析
    db.py                 # SQLite 项目库
    report.py             # 中文打印报告
  static/                 # 中文前端（index.html / app.js / style.css，无构建）
  tests/                  # 单元测试（48 个）
  run.sh                  # 一键启动
  requirements.txt
  ATTRIBUTION.md          # 开源致谢与协议说明
```

## 待办

- [ ] 在 GitHub 创建私有仓库 `HUIIIM/vertciti-dealdesk`（需 Miao 或授权人操作）
- [ ] 推送 main 分支到该私有仓
- [ ] 手机 Claude App：在 GitHub Settings → Applications → Claude → Repository access 中手动授权新仓库

## 诚实声明

本工具为筛选辅助，不构成投资建议；"估算"数字以标注假设为准，未核实项不得进 A 级；
每笔真实交易签约/交割/报税前，必须经持牌本地房地产律师、CPA/税务师、title company 审查。
