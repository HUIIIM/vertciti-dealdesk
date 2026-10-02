# DealDesk 可靠性审计报告

- 日期：2026-10-01
- 触发：Miao 对产品稳定性不满（"这产品做的太差"），要求解决所有可能发生和预想到的问题
- 方法：3 个并行审计小组（web 抓取链路 / TopHap+地理编码 / PDF+数值计算）+ 队长复核修复
- 范围：`app/main.py`、`app/research_pipeline.py`、`app/tophap.py`、`app/pdf_intake.py`、`app/geocode.py`、`app/finance.py`、`app/uw_commercial.py`、`app/scoring_*.py`

---

## 一、已修复（18 项）

### P0（1 项）

| # | 问题 | 修复 | 测试证据 |
|---|------|------|---------|
| 1 | 文件上传先全量 `await file.read()` 进内存再校验大小，超大文件可 OOM 打爆 worker | 新增 `_check_upload_size()`：先查 `Content-Length` 头预检，超限直接 400 拒绝；三个上传端点（2×PDF + 1×图片）全部接入 | `test_image_reject_too_big` 通过（曾因 413/400 不一致失败，已统一为 400 保持向后兼容） |

### P1（12 项）

| # | 问题 | 修复 | 文件 |
|---|------|------|------|
| 2 | `/api/uw/compute` 裸调 `compute_all`，异常直接 500 无中文 | 加 try/except → 500 中文"计算失败" | `app/main.py` |
| 3 | `/api/tax/estimate`：address 非字符串 → 500；price=inf → `round(inf)` 500；price 负数静默 None；geocode 异常 → 500 | `isinstance` 校验 + `math.isfinite` + 非负检查 + geocode try/except 降级；address 限 200 字符 | `app/main.py` |
| 4 | 手动 `model_validate` 抛 `ValidationError` 变成 500 而非 422（7 个 wb_* 路由） | 新增 `_validate()` helper 统一转 422 中文 | `app/main.py` |
| 5 | TopHap `enrich_address` 无过期预检，过期 token 照样发起多次 RPC 才 401 | 入口加 `is_token_expired()` 预检（60 秒缓冲），过期直接降级不碰网络 | `app/tophap.py` |
| 6 | per-tool 的 `except MCPError` 把 `MCPAuthError`(401) 吞成"跳过"，链路带部分字段返回 ok=True | 三个环节（detail/insights/cma）对 `MCPAuthError` 单独 `raise`，整链终止 | `app/tophap.py` |
| 7 | PDF `extract_text` 把 `\n` 全压成空格 → 商业地址正则（`re.M` 的 `^` 锚点）失效，地址提取静默变少 | 只折叠行内空白、保留换行 | `app/pdf_intake.py` |
| 8 | 加密 PDF 的 `pdftotext` 可能在 stdin 等密码挂起 60s | `stdin=subprocess.DEVNULL` | `app/pdf_intake.py` |
| 9 | `hold_years` 极大（如 1e12）→ `range(1, 1e12)` 请求挂起（DoS） | 钳制到 1–50 年 | `app/uw_commercial.py` |
| 10 | `finance.monthly_payment` / `remaining_balance` 极端利率 `(1+r)**n` 抛 `OverflowError` → 500 | 新增 `_safe_pow`（溢出返回 None）+ 利率钳制 [0,100]% | `app/finance.py` |
| 11 | `compute_rent_roll` 的 tenants 数组混入非 dict → `t.get` 抛 `AttributeError` → 500 | `isinstance(t, dict)` 脏行跳过 | `app/uw_commercial.py` |
| 12 | PDF 上传只校验扩展名不校验内容（伪装文件导致误导性错误） | 加 `%PDF-` 魔数校验，两个 PDF 端点 | `app/main.py` |
| 13 | TopHap 失败时地址 pipeline 直接 0 字段（用户看到"啥都出不来"） | Census Geocoder 兜底：至少返回州（`state_confirmed` 字段） | `app/research_pipeline.py` |

### P2（5 项）

| # | 问题 | 修复 |
|---|------|------|
| 14 | `pdftotext` 的 `stderr.decode()` 非 UTF-8 时 `UnicodeDecodeError` 丢失原始错误 | `errors='ignore'` |
| 15 | `docs/tophap-mcp-integration.md` 仍描述已下线的 Vault 静默刷新流程（与代码不一致） | 更新为"401 直接降级"，补充生产 token 轮换 SOP |
| 16 | TopHap token 剩余有效期无监控手段 | 新增 `token_expires_in_hours()` + `token_expiry_report()` + `tools/tophap_token_watch.py`（cron 每日调用，<24h 告警 exit 1） |
| 17 | `/api/tax/estimate` 空 body 时 FastAPI 原生英文 422 | `payload: dict \| None = None`，可控降级 |
| 18 | 图片上传端点在 main.py 层无大小预检 | `_check_upload_size(request, 15MB)` |

### 测试证据

```
pytest tests/ --deselect tests/test_intake.py::test_address_pipeline_degradation
→ 172 passed, 1 deselected
```
（deselect 的是 pre-existing 失败，stash 干净版同样挂，与本次改动无关）

新增函数验证：
- `tophap.token_expiry_report()` → `expiring_soon`，剩余 0.7h，中文建议动作
- `tools/tophap_token_watch.py` → exit 1 + stderr 警告
- `geocode.geocode_state("1600 Pennsylvania Ave...")` → `DC`
- `/api/tax/estimate` 非字符串 address → 422；`price=inf` → 422；负 price → 422

---

## 二、待用户决策（4 项）

### D1. TopHap token 只有 1 小时有效期（最严重）

- **现状**：实测 token 从授权到过期恰好 1 小时。意味着生产环境每小时都要人工重授权（浏览器点 Approve）+ 推 Vercel 环境变量 + 重部署，否则 TopHap 数据断供。
- **影响**：不可持续。用户半夜查房时 TopHap 大概率是过期的。
- **建议方案**（三选一，需 Miao 定）：
  - A. 联系 TopHap 申请更长有效期的 token（或确认是否支持 refresh_token——当前授权脚本根本没存 refresh_token，如果 TopHap 下发了，存到 `.env` + Vercel 环境变量即可实现静默续期，这是最干净的解法）
  - B. 接受现状：把 TopHap 降为"增强数据源"而非关键路径（已部分实现：Census 兜底保证基础字段）
  - C. 换数据源：ATTOM API 等付费 API 有长期 key，但要花钱
- **临时措施**：`tools/tophap_token_watch.py` 已就绪，cron 每天跑，过期前 24h 告警（但 1 小时有效期下"24h 预警"实际意义不大——每次授权后 1 小时内有效）

### D2. Vercel 生产环境无 poppler，PDF intake 永远不可用

- **现状**：`pdftotext` 是系统依赖，Vercel serverless 无此二进制。生产环境任何 PDF 上传都返回"系统缺少 pdftotext，请手动录入"。
- **影响**：用户在手机上（生产环境）传 PDF 永远失败，只能本机用。
- **建议方案**：
  - A. 部署时带 poppler 二进制（Vercel 支持 `vercel.json` 的 `functions.includeFiles` 或用 layer，但 Python serverless 下编译 poppler 较麻烦）
  - B. 换纯 Python PDF 解析库（如 `pypdf`/`pdfplumber`，零系统依赖，直接进 `requirements.txt`）——推荐，改动小
  - C. 明确标注"生产环境暂不支持 PDF"，引导用户用本机

### D3. `_div` 零分母返回 0.0（误导性数字）

- **现状**：全现金收购（无贷款）时 DSCR 显示 0.00，会被误读为"资不抵债"，真实含义是"不适用/无穷大"。`purchase_price=0` 时 cap rate 显示 0%，`net_rentable_sf=0` 时所有 per-SF 指标显示 0。
- **影响**：数字"看起来正常"但含义完全错误，比崩溃更危险。
- **建议方案**：`_div` 返回 `None`，前端统一渲染"N/A"。需要 Miao 确认展示口径（这是产品决策，不是技术 bug）。

### D4. `_irr` 无解时返回 0.0（误导性数字）

- **现状**：现金流全正/全负（无符号变化）时 IRR 数学上无解，当前返回 0.0，前端显示"IRR 0.00%"会被当成真实测算。
- **建议方案**：返回 `None`，前端显示"无解/不适用"。同样需要 Miao 确认口径。

---

## 三、TopHap Token 监控方案

### 现状
- `/api/tophap/status` 返回 `token_expired: bool`（已有）
- 新增 `tophap.token_expires_in_hours() -> float | None`
- 新增 `tophap.token_expiry_report() -> {hours_left, status, action}`（中文建议动作）
- 新增 `tools/tophap_token_watch.py`：cron 每日调用；`expiring_soon`/`expired`/`unknown` 时 exit 1 + stderr 中文告警

###  cron 建议配置
```cron
# 每天 08:00 America/New_York 检查 TopHap token
0 8 * * * cd ~/workspace/vertcity/dealdesk && .venv/bin/python tools/tophap_token_watch.py
```

### 重要限制
- **绝不自动重授权**：OAuth 需要浏览器里点 Approve，必须人工触发。监控只告警，不自动修。
- **1 小时有效期下**：每日 cron 的预警窗口实际不足（见 D1），D1 解决前建议每次使用前人工检查 `/api/tophap/status`。

---

## 四、后续预防机制

1. **上传端点规范**：所有文件上传必须走 `_check_upload_size` 预检 + 魔数校验（已建立模式，新端点照抄）
2. **手动 `model_validate` 规范**：一律用 `_validate()` helper，不直接调 `model_validate`（已建立模式）
3. **外部调用规范**：必须有 timeout、有中文日志、有降级返回值（不抛裸异常到路由层）
4. **误导性数字审查**：新增计算函数时，评审必须回答"分母为零/无解时返回什么？用户会误读吗？"
5. **文档同步**：代码行为变更时，`docs/` 下相关文档必须同步更新（本次已补 tophap 文档的 Vault 和 Vercel SOP）
6. **审计回归**：本报告的 3 份原始审计在 `/tmp/audit-a-web.md`、`/tmp/audit-b-tophap.md`、`/tmp/audit-c-pdf-calc.md`（临时文件）；建议下次大功能上线前重跑一次三组审计

---

## 五、未修复的 P2（进日常迭代）

- DDG 搜索限流时静默返回空（应区分"服务不可用"与"无结果"）
- `fetch_page` 无页面大小上限（大页面内存风险）
- DNS 解析（`getaddrinfo`）无超时
- pipeline 总耗时无上限（最坏 200+ 秒）
- robots.txt 失败吞异常且进缓存
- `merge_fields` 冲突时备注可能丢失
- 日志截断（`url[:80]` 等）与分钟级时间戳
- `geocode.py` 超时 12s 在 Vercel 下偏大、benchmark 硬编码
- TopHap `discover_tools` 每次重做 initialize（无缓存）
- `find` 模糊匹配（partialMatch）无检查
- `down_pct` 填 30（想表达 30%）导致静默错数
- `finance.monthly_payment` 与 `uw_commercial.amort_payment` 百分制/小数制口径不一致（埋雷）

---

*注：本报告只记录本次审计周期的工作。git 历史未动，未 push。*
