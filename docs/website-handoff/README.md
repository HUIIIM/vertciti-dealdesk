# 官网 DealDesk 产品页（交给 vertciti-website）

照官网 `/echowatch/` 的结构做：同一套页头页脚、CSS、脚本，只换页面元信息和正文。

| 文件 | 放到 vertciti-website 的 |
|---|---|
| `dealdesk/index.html` | `/dealdesk/index.html`（中文） |
| `en/dealdesk/index.html` | `/en/dealdesk/index.html`（英文） |
| `preview-*.png` | 只是截图，不要放进网站 |

重新生成（官网页头页脚改版后）：
```bash
curl -sSL https://vertciti.com/echowatch/ -o ew.html
curl -sSL https://vertciti.com/en/echowatch/ -o ew-en.html
python3 -I build.py ew.html ew-en.html .
```

## 业务版图 `/business/` 还要改两处（中文；英文 `/en/business/` 同理）

1. 产品线卡片：标题加链接、说明写具体：
```html
<article class="line-card">
<h2 class="line-name"><a href="/dealdesk/">DealDesk 交易核保台</a></h2>
<p class="line-what">MIT 开源、自托管的房地产交易核保台：住宅与商业双轨核保，每个关键数字记录来源与复核人；按“能让回报摆动多少”排出先核哪个，反方备忘录由固定规则生成、不经 AI；反推最高出价，投委会到持有期复盘全程留痕。</p>
<p class="line-who"><span class="line-k">给谁</span>给要在投委会上说清“这个数从哪来、谁核过”的房地产投资人与小型基金；也给正在把采购交给 AI 智能体的运营者。</p>
</article>
```
2. 状态卡标题链接从 `https://vertciti-dealdesk.vercel.app` 改为 `/dealdesk/`，里程碑更新为：
```html
<p class="status-line"><span class="status-k">最近里程碑</span>v2 交易工作台完成开发并进入代码评审（分层后端与数据库迁移、React 前端、中英双语、角色权限与审计） <span class="status-date">2026-10-22</span></p>
<p class="status-line"><span class="status-k">下一步</span>v2 工作台上线生产（日期待定）</p>
<p class="status-asof" data-asof="2026-10-22">数据截至 2026-10-22</p>
```

上线前对照官网规矩：状态与日期如实；v2 未上线前不写“已上线”；sitemap / feed / 站内搜索索引若有清单要把 `/dealdesk/` 加进去。
