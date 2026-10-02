# Realyzer → DealDesk 复制实施方案

> 研究对象：https://github.com/stanjdev/realyzer（Next.js + React/Redux，86 小时个人项目）
> 研究日期：2026-10-01
> 结论一句话：realyzer 真正值得复制的只有**一件事**——地址输入 → 自动算出房产税估算。其余（mortgage 公式、PDF 打印页）DealDesk 已有更强的实现，不必复制。

---

## 1. Realyzer 可复制点清单（原理一句话）

| # | 可复制点 | 原理一句话 | DealDesk 现状 |  verdict |
|---|---------|-----------|--------------|---------|
| 1 | **地址 → 自动房产税** | 地址经 Mapbox Geocoding 拿到州名 → 查 50 州平均税率表 → `税 = 房价 × 州税率 / 12` 自动填入 | 无。住宅 `taxes_annual`（`static/workbench.js` 的 `p-tax`）、商业 `property_tax`（`static/uw-commercial.js`）全靠手填 | **P0，复制** |
| 2 | 50 州税率表 | Cheerio 实时抓 WalletHub 页面（`pages/api/scraper/propertyTaxRateScraper.js`），每次打开页面都抓一次，**不存库**，选择器极脆（一改版就挂） | 无此表 | **P0，但改实现**：不要学它实时抓，改静态表（见 §3） |
| 3 | Mortgage calculator | 标准等额本息公式，输入首付比/利率/年限 → 输出月供（`components/Results.js` L33-44） | 已有且更强：`app/finance.py`（PITI/摊销），商业页有完整 debt 结构 | 不复制 |
| 4 | PDF 报告页 | 另一个路由 `/results`，把同一份 Redux state 重新排版 + 用户上传的 logo/照片 + 地图 → 浏览器打印（`components/ResultsPDF.js`，`pages/results.js`） | 已有 `app/pdf_uw.py`（`build_classic_pdf` / `build_enhanced_pdf`，Pillow 原生 PDF，Vercel 兼容）+ `app/charts.py`（3 张图）+ `app/report_narrative.py` | 不复制它的"打印页"思路；**P1 是把我们自己的 PDF 接完**（见 §5） |
| 5 | 地图进报告 | `map.getCanvas().toDataURL()` 截 Mapbox 画布 → base64 存 Redux → 报告页 `<img>` 显示（`components/Map.jsx`，实际已注释掉，没跑通） | 无 | 不复制（它自己都没跑通） |
| 6 | 房源照片抓取 | `imgScraper.js` 抓 Redfin 页面图片（作者自己标注 "BUGGY"） | 已有 `app/image_intake.py`（截图 intake） | 不复制 |

### Realyzer 的链路细节（精确到文件/行，供对照）

```
用户输入地址 (components/Inputs.js, input name="address")
  → 点 "Search Address" (components/Map.jsx, loadAddress())
  → GET https://api.mapbox.com/geocoding/v5/mapbox.places/{address}.json?access_token=KEY
  → response.features[0].context[3].text        // ⚠️ 脆弱：依赖 context 数组第 4 个是州
  → dispatch(changeValue(stateName, "americanState"))
  → 页面加载时 GET /api/scraper/propertyTaxRateScraper  // Cheerio 实时抓 WalletHub
  → propertyTaxRates = { "California": "0.70%", ... }   // 存 Redux，不持久化
  → calculatedPropertyTax = round((rate/100 * purchasePrice) / 12)
  → dispatch(changeValue(calculatedPropertyTax, "propertyTaxes"))  // 自动填入，可手改
```

它的三个工程教训（我们不要重蹈）：
1. **实时抓税率是错的**：每次打开页面都去爬 WalletHub，又慢又脆（选择器 `#scroller > main > article > ... > table` 一改版就全挂），且税率一年变一次，根本不需要实时。
2. **`context[3]` 取州名是错的**：Mapbox context 数组顺序不保证，新版 API 已改成按 `id` 前缀（`region.*`）的对象。
3. **地图截图进报告没跑通**：相关代码全注释掉了。

---

## 2. DealDesk 落点总览

| P | 事项 | 落点文件 | 落点函数/位置 |
|---|------|---------|--------------|
| P0 | 50 州税率静态表 | 新建 `app/data/state_tax_rates.py` | `STATE_PROPERTY_TAX = {...}` + `get_rate(state_abbr)` |
| P0 | 地址 → 州（零 key） | 新建 `app/geocode.py` | `geocode_state(address) -> "NY"`（Census Geocoder，无 key） |
| P0 | API：地址 → 税率估算 | `app/main.py` 新增路由 | `POST /api/tax/estimate` |
| P0 | 住宅页自动填税 | `static/workbench.js` | 地址输入框 `blur` → 调 API → 填 `p-tax`（可覆盖） |
| P0 | 商业页自动填税 | `static/uw-commercial.js` | `property.address` 变更 → 调 API → 填 `property_tax`（可覆盖） |
| P1 | PDF 报告接完 | `app/main.py` + `app/pdf_uw.py` | 把 `build_classic_pdf` / `build_enhanced_pdf` 接到路由，用**当前页面 state**（`/tmp` SQLite 在 Vercel 不持久，别走 DB） |
| P1 | 报告里标税率来源 | `app/pdf_uw.py` | 税那一行加脚注 "州平均税率估算（Tax Foundation 2024），待验证" |
| P2 | 税率表年度刷新 | cron 或手动脚本 | 新建 `tools/refresh_tax_rates.py`（一年跑一次，人工确认后更新静态表） |

---

## 3. P0 实施方案：地址 → 自动房产税

### 3.1 数据源决策：静态表，不实时抓

**理由**：
- 州平均税率一年变一次，实时抓纯属浪费且引入故障点（realyzer 的反例）。
- WalletHub 是二手源；一手源是 Tax Foundation（基于 Census ACS），每年更新一次。
- 静态表 = 零网络依赖 = Vercel serverless 下零失败率。

**刷新机制**：每年 Tax Foundation 发新表后，跑一次 `tools/refresh_tax_rates.py`（人工核对 diff 后合入），不搞自动爬。

### 3.2 静态税率表（Tax Foundation 2024，effective rate）

> 来源：Tax Foundation《Property Taxes by State and County》（2024，基于 Census ACS），经 countrytaxcalc.com / homes.com 交叉核对。
> 口径：**州平均 effective 税率 = 全州实缴房产税总额 / 全州住房总值**。注意这是州平均，**具体 county/municipality 差异巨大**（如 NY 州平均 1.30%，NYC Class 1 实际约 0.8%，郊区可达 2.5%+）。
> 必须在 UI 和报告里标：`州平均税率估算 · 待验证`。

```python
# app/data/state_tax_rates.py
"""美国各州平均 effective property tax rate（静态表）.

来源：Tax Foundation《Property Taxes by State and County》(2024)，基于 U.S. Census Bureau ACS。
口径：州平均 effective rate = 实缴税总额 / 住房总值。county 级差异巨大，仅作估算初值。
刷新：每年 Tax Foundation 更新后，人工核对并更新本表（见 tools/refresh_tax_rates.py）。
"""

SOURCE = "Tax Foundation 2024（基于 Census ACS）"
SOURCE_URL = "https://taxfoundation.org/data/all/state/property-taxes-by-state-and-county/"
CALIBRATION_NOTE = "州平均税率估算，待独立验证"

# key: USPS 州缩写，value: effective rate（小数，如 0.0130 = 1.30%）
STATE_PROPERTY_TAX = {
    "AL": 0.0037, "AK": 0.0094, "AZ": 0.0048, "AR": 0.0056, "CA": 0.0070,
    "CO": 0.0050, "CT": 0.0154, "DE": 0.0054, "DC": 0.0060, "FL": 0.0078,
    "GA": 0.0079, "HI": 0.0029, "ID": 0.0050, "IL": 0.0188, "IN": 0.0076,
    "IA": 0.0133, "KS": 0.0121, "KY": 0.0074, "LA": 0.0055, "ME": 0.0098,
    "MD": 0.0092, "MA": 0.0100, "MI": 0.0119, "MN": 0.0100, "MS": 0.0058,
    "MO": 0.0089, "MT": 0.0061, "NE": 0.0144, "NV": 0.0050, "NH": 0.0150,
    "NJ": 0.0188, "NM": 0.0063, "NY": 0.0130, "NC": 0.0066, "ND": 0.0092,
    "OH": 0.0136, "OK": 0.0079, "OR": 0.0081, "PA": 0.0126, "RI": 0.0112,
    "SC": 0.0049, "SD": 0.0100, "TN": 0.0052, "TX": 0.0140, "UT": 0.0048,
    "VT": 0.0151, "VA": 0.0078, "WA": 0.0075, "WV": 0.0051, "WI": 0.0132,
    "WY": 0.0053,
}

# 全名 → 缩写（Census geocoder 返回缩写；Mapbox/用户手输可能返回全名，兜底用）
STATE_NAME_TO_ABBR = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "district of columbia": "DC", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN",
    "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
    "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH",
    "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH",
    "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY",
}


def get_rate(state: str) -> float | None:
    """州缩写或全名 → effective rate；查不到返回 None（调用方必须处理，不能瞎填）。"""
    if not state:
        return None
    s = state.strip()
    abbr = s.upper() if len(s) == 2 else STATE_NAME_TO_ABBR.get(s.lower())
    return STATE_PROPERTY_TAX.get(abbr) if abbr else None
```

### 3.3 地址 → 州：Census Geocoder（零 key、零成本）

**为什么不用 Mapbox**：realyzer 用 Mapbox 需要 `REACT_APP_MAPBOXGL_ACCESSTOKEN`（付费 key，且前端暴露）。DealDesk 要的是**后端**从地址拿州，Census Geocoder 是联邦政府免费接口，无 key、无配额（合理使用），返回里直接带 `addressComponents.state`（USPS 缩写），比 Mapbox 的 `context[3]` 可靠一个数量级。

已实测可用（2026-10-01）：
```
GET https://geocoding.geo.census.gov/geocoder/locations/onelineaddress
    ?address=4600+Silver+Hill+Rd,+Washington,+DC+20233&benchmark=2020&format=json
→ result.addressMatches[0].addressComponents.state == "DC"
→ result.addressMatches[0].coordinates == {x: -76.92, y: 38.84}
```

```python
# app/geocode.py
"""地址 → 州（USPS 缩写），零 key 方案：U.S. Census Bureau Geocoder.

免费、无 key、无需注册。benchmark 用 Public_AR_Census2020。
注意：Census geocoder 对商业地址/新楼盘覆盖不如商用 API，失败时返回 None，
调用方降级为"用户手选州"或"不填"，绝不瞎猜。
"""
from __future__ import annotations

import httpx

_CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
_TIMEOUT = 12


def geocode_state(address: str) -> dict:
    """返回 {"state": "NY"|None, "matched_address": str|None, "lat": float|None, "lng": float|None}.

    任何失败（超时/无匹配/格式变化）都返回 state=None，不抛异常。
    """
    out = {"state": None, "matched_address": None, "lat": None, "lng": None}
    if not address or not address.strip():
        return out
    try:
        r = httpx.get(_CENSUS_URL, params={
            "address": address.strip(), "benchmark": "2020", "format": "json",
        }, timeout=_TIMEOUT)
        if r.status_code != 200:
            return out
        matches = (r.json().get("result") or {}).get("addressMatches") or []
        if not matches:
            return out
        m = matches[0]
        comp = m.get("addressComponents") or {}
        coords = m.get("coordinates") or {}
        out["state"] = (comp.get("state") or "").upper() or None
        out["matched_address"] = m.get("matchedAddress")
        out["lng"], out["lat"] = coords.get("x"), coords.get("y")
        return out
    except Exception:
        return out
```

**需要 key 的升级路径**（P2，按需）：如果 Census 覆盖不够，备选是 Mapbox Geocoding（后端调，不暴露 key）或 SmartyStreets。**不要**把 key 放前端（realyzer 就是这么干的，`REACT_APP_MAPBOXGL_ACCESSTOKEN` 直接进浏览器）。

### 3.4 API 路由

```python
# app/main.py（新增）
from . import geocode as _geocode
from .data import state_tax_rates as _tax

@app.post("/api/tax/estimate")
def tax_estimate(payload: dict):
    """地址 → 州 → 州平均税率 → 年房产税估算。

    body: {"address": "...", "price": 18500000}
    返回: {"state": "NY", "rate": 0.013, "annual_tax": 240500,
           "source": "Tax Foundation 2024（基于 Census ACS）",
           "confidence": "州平均税率估算，待独立验证",
           "matched_address": "1250 BROADWAY, NEW YORK, NY, 10001"}
    查不到州或税率时返回 {"state": None, ...}，前端不填数、不报错。
    """
    address = (payload.get("address") or "").strip()
    price = payload.get("price") or 0
    g = _geocode.geocode_state(address)
    rate = _tax.get_rate(g["state"]) if g["state"] else None
    annual = round(price * rate) if (rate and price > 0) else None
    return {
        "state": g["state"],
        "rate": rate,
        "annual_tax": annual,
        "matched_address": g["matched_address"],
        "source": _tax.SOURCE,
        "source_url": _tax.SOURCE_URL,
        "confidence": _tax.CALIBRATION_NOTE,
    }
```

### 3.5 前端接入（两处）

**住宅页**（`static/workbench.js`）：地址输入框 `blur` 时调一次（不要每个 keystroke 都调，realyzer 的注释里自己也吐槽过这个问题）：

```js
// static/workbench.js（示意，接在地址输入框逻辑旁）
async function autoFillTaxFromAddress() {
  const addrEl = document.getElementById('p-addr');      // 地址输入框（以实际 id 为准）
  const taxEl  = document.getElementById('p-tax');       // 年房产税输入框
  const price  = num('p-price');
  if (!addrEl || !addrEl.value.trim() || !price) return;
  if (taxEl.dataset.autofilled === '1' && taxEl.value) return; // 用户已手改过就不覆盖
  try {
    const r = await fetch('/api/tax/estimate', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ address: addrEl.value, price })
    });
    const d = await r.json();
    if (d.annual_tax) {
      taxEl.value = d.annual_tax;
      taxEl.dataset.autofilled = '1';
      showTaxBadge(taxEl, `${d.state} 州平均税率 ${(d.rate*100).toFixed(2)}% 估算 · 待验证`);
      recalc(); // 触发已有重算链
    }
  } catch (e) { /* 静默降级：不填，不打断用户 */ }
}
```

**商业页**（`static/uw-commercial.js`）：`property.address` 变更时调 API → 填 `property_tax`（商业页 state 路径），同样**用户手改后不再覆盖**（`dataset.autofilled` 标记位模式）。

**铁律（必须做）**：
1. 自动填的税旁边必须有来源 badge：`州平均税率估算 · 待验证`（realyzer 只在 info 弹窗里藏了一行小字，我们要做到输入框旁边）。
2. 用户手改后，自动逻辑**永不覆盖**（`dataset.autofilled` + 值非空检查）。
3. 查不到州 → **不填**，不报错，不瞎猜。
4. 房价变化时税估算要跟着变（realyzer 是这么做的：`calculatedPropertyTax` 依赖 `purchasePrice`），但同样尊重手改标记。

---

## 4. P1：PDF 报告补齐（不复制 realyzer 的打印页，用我们自己的）

realyzer 的 PDF 本质是"另开一个路由做浏览器打印"，字段是同一份 state 的重新排版。DealDesk 已经有更强的原生 PDF（Pillow，无浏览器依赖，Vercel 兼容），**缺的只是接线**：

| 步骤 | 落点 | 说明 |
|------|------|------|
| 1 | `app/main.py` 新增 `POST /api/report/uw-pdf` | body 直接收**页面当前 state JSON**（别从 DB 读：Vercel `/tmp` SQLite 不持久，读 DB 会丢用户未保存的输入） |
| 2 | `app/pdf_uw.py::build_classic_pdf(r)` | 已有 442 行实现，检查字段映射是否覆盖新 intake 字段（`analysis.market_cap_rate` 等） |
| 3 | `app/pdf_uw.py::build_enhanced_pdf(r)` | 同上，确认 DSCR/IRR/盈亏平衡入住率/equity multiple/持有退出分析都在 |
| 4 | 税行脚注 | 在房产税那一行加 `（州平均税率估算，Tax Foundation 2024，待验证）`——呼应 P0 的诚实标注 |
| 5 | 前端按钮 | `static/uw-commercial.html` 报告区加"导出 PDF"按钮 → `fetch` 当前 state → 下载 blob |

**不要**学 realyzer 把 logo/照片/base64 地图塞进报告（它地图截图自己都没跑通）。DealDesk 报告已有 `app/charts.py` 的 3 张图（现金流回本/敏感性/评分构成），足够。

---

## 5. P2（按需，不急）

1. **税率表年度刷新**：`tools/refresh_tax_rates.py`——拉 Tax Foundation 新表，diff 旧表，输出待人工确认的变更清单。一年跑一次。
2. **County 级税率**：州平均误差大（如 TX 州平均 1.40%，Austin Travis County 实际 ~1.8%）。升级路径：ATTOM API（付费）或各 county assessor 抓取。先不做，P0 的州平均 + "待验证"标注已够用。
3. **保险自动估算**：realyzer 用 `房价 × 0.5% / 12` 自动填保险（`components/Inputs.js` L57）。DealDesk 可照抄这个逻辑，同样标"估算口径"。一行代码的事，排 P2 只是因为不如税常用。
4. **Mapbox 升级**：Census geocoder 覆盖不足时，后端调 Mapbox（key 放服务端环境变量，**绝不**放前端）。

---

## 6. 诚实标注清单（DealDesk 铁律：自动填的数字必须标来源+置信度）

| 自动填的字段 | 来源标注 | 置信度 |
|-------------|---------|--------|
| 年房产税（住宅/商业） | Tax Foundation 2024（基于 Census ACS）+ Census Geocoder 定州 | **州平均税率估算，待独立验证**——county 实际税率可能差 ±50% |
| 保险（若做 P2-3） | 房价 × 0.5% 经验系数 | **经验估算，待验证** |
| PDF  intake 字段（已上线） | 卖方 PDF | 卖方材料口径、待独立验证（已有） |

**禁止**：把州平均税率当成该物业实际税率参与" definitive"结论；报告里税行不标来源。

---

## 7. 工作量估计

| 项 | 工作量 |
|---|-------|
| P0（税率表 + geocode + API + 两页前端） | 约 2-3 小时（含测试） |
| P1（PDF 接线 + 税行脚注） | 约 1-2 小时（`pdf_uw.py` 已有实现，主要是接线和字段映射检查） |
| P2 | 按需，不排期 |

## 8. 与 realyzer 的最终对比（给用户的诚实说法）

realyzer 能、DealDesk 将能：
- ✅ 地址输入 → 自动估算房产税（realyzer 的核心卖点，我们用更可靠的实现复制）

realyzer 能、DealDesk 早已更强：
- ✅ Mortgage 计算（我们有完整 PITI + 摊销 + 商业 debt 结构）
- ✅ PDF 报告（我们是原生 PDF + 3 张分析图，它只是浏览器打印页）

realyzer 宣称但没跑通的：
- ❌ 地图截图进报告（代码全注释）
- ❌ 房源照片抓取（作者自标 BUGGY）

realyzer 做错、我们不学的：
- ❌ 每次打开页面实时爬 WalletHub（脆、慢、没必要）
- ❌ Mapbox key 放前端
- ❌ `context[3]` 取州名（顺序不保证）
