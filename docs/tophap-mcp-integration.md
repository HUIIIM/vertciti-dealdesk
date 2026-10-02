# TopHap MCP 集成说明（DealDesk 数据源）

## 1. 实测结论（2026-09-28，浏览器登录态实地验证）

| 项目 | 实测结果 |
|---|---|
| MCP 页面 | https://www.tophap.com/mcp |
| Server URL | `https://mcp.tophap.com/api/mcp` |
| 认证方式 | 标准 OAuth（Streamable HTTP）；**无 API key**；页面两次强调 "Free while in beta - sign in with your TopHap account, no API key" |
| 费用 | beta 期间免费 |
| Tool 面（照抄） | `find_property_by_address`, `search_properties`, `get_property_detail`, `get_property_insights`, `get_property_cma`, `get_building_units`, `search_schools`, `get_school_detail`, `lookup_area_boundary`（共 9 个） |
| 未授权探测 | 无 token 调 endpoint 返回 HTTP 401（符合 OAuth 预期） |

## 2. 待验证（需首次 OAuth 授权后实测）

- 9 个 tool 各自的 **参数 schema**（当前对参数键做多样式兼容：`address`/`query`；`property_id`/`propertyId`/`id`，授权后以 `tools/list` 返回的 `inputSchema` 校准）。
- 各 tool 返回 payload 的字段路径（当前为防御式映射：命中则映射，缺失则跳过）。
- OAuth 各端点（`WWW-Authenticate` → resource metadata → authorization server metadata → 动态注册）的实际行为；脚本按 RFC 8414/9728/7591 + PKCE 实现，server 行为差异处会直接报错说明。
- `hatch-vault` 存取 refresh token 的端到端验证（脚本内为 fail-safe 语义：存不进则中止，绝不落盘）。

## 3. 架构

```
intake（地址/链接/PDF/截图）
  └─ research_pipeline.run_address_pipeline
       ├─ ① DDG 公开搜集 pipeline（原有，永远在线）
       └─ ② TopHap enrich（TOPHAP_ENABLED=1 且有 token 才跑）
            find_property_by_address → get_property_detail →
            get_property_insights / get_property_cma →（best-effort）search_schools
       └─ merge_fields() 按"高/中/低/卖方口径"合并 ①+②
```

- `app/tophap.py`：适配器（JSON-RPC/SSE 解析、tool 链路、字段映射、token 刷新、降级）。
- `tools/tophap_oauth_setup.py`：首次 OAuth 授权独立脚本（见第 5 节）。
- `GET /api/tophap/status`：开关/授权/连通性/核心 tool 齐全性检查。

## 4. 字段映射表

| DealDesk 字段 | 来源 tool | 可信度 | 说明 |
|---|---|---|---|
| `beds` / `baths` / `building_sf` / `lot_sf` / `year_built` | get_property_detail | 高 | 公共记录口径 |
| `property_type_detail` / `parcel_id` / `building_units` | get_property_detail | 高 | 物业档案 |
| `tophap_value` / `tophap_value_range` | get_property_insights | 中 | 算法估值＋置信区间，非成交价 |
| `taxes_annual` / `tax_assessed_value` | get_property_insights | 高 | 税务记录 |
| `price_history` / `last_sale_price` / `last_sale_date` | get_property_insights | 高 | 成交记录 |
| `open_loans` / `loan_history` | get_property_insights | 高 | subject-to 核保关键输入；仍需 title/statement 独立验证 |
| `ownership_history` | get_property_insights | 高 | 产权历史 |
| `pre_foreclosure` | get_property_insights | 高 | 有记录=硬风险信号 |
| `monthly_rent` | get_property_insights | 低 | 算法租金估算，仅参考 |
| `tophap_comps` | get_property_cma | 中 | recorded sales 口径；建议工作台筛选后重跑比较法 |
| `tophap_schools` | search_schools | 中 | best-effort，不阻塞主链路 |

每字段统一携带：`source="TopHap MCP"`、`fetched_at`、`confidence`、`seller_claimed=false`。
`search_properties` / `get_building_units` / `get_school_detail` / `lookup_area_boundary`
已预留，可按需扩展（condo 单元明细、学区深挖、区域边界）。

## 5. OAuth 首次授权（Miao 只需做 1 步）

```bash
cd ~/workspace/vertcity/dealdesk
.venv/bin/python tools/tophap_oauth_setup.py
# 若浏览器打不开 localhost 回调：加 --manual，按提示粘贴跳转 URL 或 code
```

脚本流程：裸调取 401 → `WWW-Authenticate` 发现 → 授权服务器元数据 →
RFC 7591 动态注册 public client（PKCE，无 client_secret）→ 打印授权 URL →
**用户在已登录 TopHap 的浏览器打开并点 Approve**（唯一手动步骤）→
localhost 回调拿 code → 换 token。

落盘策略：

| 凭证 | 去向 |
|---|---|
| access_token（短期） | `.env` → `TOPHAP_ACCESS_TOKEN`（gitignored） |
| token_endpoint / client_id / expires_in（非敏感） | `.env` |
| refresh_token（长期） | **不持久化**（2026-09-29 变更：Secure Vault 按平台设计是 opaque 的，存进的值读不回，静默刷新此路不通） |
| client_secret（如 server 下发） | 不持久化 |

日常运行时：401 → 直接降级回 DDG pipeline，日志记中文原因并提示重跑授权脚本
（`tools/tophap_oauth_setup.py`，需浏览器里点 Approve）。不再尝试 refresh。

## 6. 降级矩阵

| 场景 | 行为 |
|---|---|
| `TOPHAP_ENABLED != 1` | 不调 TopHap，pipeline 与原来完全一致 |
| 无 access token | 记 skipped 日志，降级；note 指向授权脚本 |
| 401（token 过期） | 直接降级并提示重授权（2026-09-29 起不再尝试 refresh，见上） |
| 403 / 429 / 超时 / 连接失败 | 中文记日志，降级 |
| tools/list 缺核心 tool | 缺失环节跳过，其余继续 |
| find 无 property_id | 整链降级（无法定位） |
| 单个 tool 返回异常结构 | 该环节跳过，不崩整链 |

## 6.5 生产环境 token 轮换 SOP（2026-10-01 补充）

token 为短期（约 1 小时有效期）。过期后：
1. 本机跑 `.venv/bin/python tools/tophap_oauth_setup.py --manual`，浏览器点 Approve 拿新 token（写入本机 `.env`）
2. 用脚本把新 token 推到 Vercel 环境变量：
   ```
   cd ~/workspace/vertcity/dealdesk && .venv/bin/python - <<'EOF'
   import sys, os
   sys.path.insert(0, os.path.expanduser("~/workspace/skills/vercel/bin"))
   from vc_lib import api
   env = dict(l.split("=", 1) for l in open(".env") if "=" in l and not l.startswith("#"))
   TEAM = "team_QxXqQxZFY4NehOJd76UjkIXn"; PROJECT = "prj_8yRsROvVeOyk31En55tOSV1yRIFz"
   existing = api("GET", f"/v10/projects/{PROJECT}/env?teamId={TEAM}")
   for key in ["TOPHAP_ACCESS_TOKEN", "TOPHAP_TOKEN_EXPIRES_AT", "TOPHAP_ENABLED"]:
       for e in existing.get("envs", []):
           if e["key"] == key:
               api("DELETE", f"/v10/projects/{PROJECT}/env/{e['id']}?teamId={TEAM}")
       api("POST", f"/v10/projects/{PROJECT}/env?teamId={TEAM}",
           {"key": key, "value": env.get(key, "").strip(), "type": "encrypted",
            "target": ["production", "preview"]})
   EOF
   ```
3. 重新部署（`vc-deploy`），新环境变量才生效
4. 监控：`tools/tophap_token_watch.py` 可被 cron 每天调用，过期前 24h 告警（exit 1）

## 7. 安全约束

- 密钥绝不硬编码；`.env` 已 gitignore。
- refresh_token / client_secret 不持久化（Vault opaque 读不回）、永不打印、永不进日志。
- git 只做本地 commit，不 push（等一次性 token）。
- 本文档中"实测"仅指 2026-09-28 浏览器实地验证的 9 个 tool 名与 OAuth 形态；
  参数 schema 与返回结构标注为待验证，不伪装成实测。
