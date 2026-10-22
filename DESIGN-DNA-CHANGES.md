# DealDesk · vertciti DNA 统一改造（2026-10-21）

只改界面，不动任何业务逻辑、计算、接口与文字口径。

## 改了什么
- 新增 `static/vc-dna.css`（最后加载）：把原深色主题的全部颜色变量映射到 vertciti 品牌色（白底黑字、信号橙点睛、验证绿 / 证据黄 / 风险红状态色）；全部直角；去掉毛玻璃；按钮与输入框最小 44 px；焦点框 3 px 信号橙；字体改为 Nunito Sans / 苹方（系统字体栈）；尊重“减少动态效果”。
- 5 个页面（index、d、workbench、uw-commercial、res-legacy）顶部加入与 vertciti.com 一致的黑色品牌条：vertciti / DealDesk（当前，橙线）/ 仿冒预警 / vertciti 业务版图。
- `static/*.css`、`*.html`、`*.js` 中写死的深色色值（82 + 商业页 15 处）按同一张映射表替换为品牌色。
- 去掉 Google Fonts（Inter）外链：访客浏览器不再连接第三方字体服务。
- `assets/social-preview-vertciti.png`：GitHub 仓库社交预览图（Settings → Social preview 上传）。
- `_brand-dna/vc-product.css`：vertciti 产品统一界面层，后续新页面直接使用其类名（vc-btn、vc-card、vc-st 等）。

## 色彩映射（节选）
| 原色 | 新色 | 用途 |
|---|---|---|
| #060a13 / #0a0f1c | #F5F5F5 / #FFFFFF | 页面底 |
| #0d1526 等 surface | #FFFFFF | 卡片 |
| #e9eff9 | #000000 | 正文 |
| #2dd4bf（teal） | #C93410 | 强调（信号橙深色版，白底文字对比度 ≥ 4.5:1） |
| #34d399 | #1D8348 | 正向 / 已验证 |
| #fbbf24 | #8A5A00（文字）/ 证据黄（底） | 提示 / 建设中 |
| #f87171 | #B3261E | 风险 / 错误 |

## 验收
- 静态页面截图（1280 宽）：index、workbench、uw-commercial 改前改后均已核对，无残留深色块。
- JS 语法检查全部通过；Python 代码未改动。
- 待你本地执行：`bash run.sh` 后 `pytest tests/`（本次环境无法联网安装依赖，未能运行；因未改 Python，预期结果不变）。

## 回滚
删除 `static/vc-dna.css` 引用并恢复本次提交即可。

## 补完（2026-10-21，第二轮）
第一轮只改了 `static/`；用户可分享/下载的服务端产物仍是旧青绿配色。本轮补齐，做到“跟官网 DNA 一样”：
- 新增 `app/brand.py`：后端唯一品牌令牌源（值取自 `_brand-dna/tokens.json` + 上表映射）。
- HTML 核保报告（`app/report.py`）、市场调查报告（`app/workbench.py`）：官网黑色品牌条（通栏）、Nunito Sans 字栈、直角、发丝线表格、等宽数字、黑底按钮悬停信号橙、3px 橙焦点框。
- 图表（`app/charts.py`，SVG + PNG）：青绿 → 信号橙，圆角 → 直角，白底小字用橙深色版 `#C93410`。
- PDF：核保备忘录（`pdf_report.py`）、商业核保经典版/增强版（`pdf_uw.py`）、Tear Sheet（`tearsheet.py`）全部换品牌色；**增强版由整页深色改为白底**（官网原则：白底黑字，黑色只用于品牌条/表头；打印不费墨）。
- Excel（`excel_uw.py`）：墨黑表头、证据黄输入格、验证绿基准格。
- 品牌条在 EN 模式（`?lang=en`）可翻译；5 个页面加载 `static/safe.js`；`workbench.js`/`uw-commercial.js` 的 `esc` 补全 `>`、`'` 转义。
- 验证：572 测试全过；无头 Chromium 对 5 个页面 + 2 份报告注入 XSS 载荷，0 触发、0 JS 报错；PDF 逐页渲染目检。
- 内联 `<style>` 已变（index / workbench / uw-commercial）：部署前用 `python3 tools/csp_hashes.py` 重算 hash 写入 `vercel-deploy/vercel.json`（若 CSP 含 style-src hash）。内联 `<script>` 未变。
