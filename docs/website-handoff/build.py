"""从官网 EchoWatch 产品页（同一套页头页脚 / CSS / 脚本）生成 DealDesk 产品页（中、英）。

用法：python3 build.py <echowatch 中文页.html> <echowatch 英文页.html> <输出目录>
输出 <输出目录>/dealdesk/index.html 与 <输出目录>/en/dealdesk/index.html，放进 vertciti-website 对应路径即可。
页头、导航、页脚、隐私弹窗原样沿用 EchoWatch 页，只替换 <head> 里的页面元信息和 <main> 内容。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

APP = "https://vertciti-dealdesk.vercel.app"
MAIL_ZH = "mailto:contact@vertciti.com?subject=DealDesk%20%E8%AF%95%E7%94%A8"
MAIL_EN = "mailto:contact@vertciti.com?subject=DealDesk%20trial"
ASOF = "2026-10-22"

ZH = {
    "title": "DealDesk 交易核保台 · 产品 ｜ vertciti",
    "desc": "DealDesk：MIT 开源、自托管的房地产交易核保台。住宅与商业双轨核保，每个数字带来源与复核记录；"
            "按“能让回报摆动多少”排出先核哪个，反方备忘录不经 AI；反推最高出价，投委会到持有期复盘全程留痕。",
    "og": "开源、自托管的房地产交易核保台：数字护照、先核哪个、不经 AI 的反方备忘录、反推最高出价。",
    "crumbs": ("首页", "/", "业务版图", "/business/"), "canonical": "/dealdesk/",
    "main": f"""<nav aria-label="面包屑" class="crumbs wrap"><ol><li><a href="/">首页</a></li><li><a href="/business/">业务版图</a></li><li><span aria-current="page">DealDesk</span></li></ol></nav>
<section class="sec" id="product">
<div class="wrap">
<div class="sec-head">
<p class="eyebrow">product · <span class="cn">产品</span></p>
<h1 class="sec-title page-title">DealDesk 交易核保台</h1>
<p class="sec-lede">把一笔房地产交易从看房、核保、上投委会到持有期复盘放在一张台面上：住宅看月供与现金回报，商业看 IRR、DSCR 与 NOI；每个关键数字都写明从哪来、谁核过。缺的数显示“—”，不拿 0 凑。MIT 开源、自托管，数据只留在你自己的服务器上。</p>
</div>
<div class="cta-row">
<a class="btn btn-primary" href="{APP}" rel="noopener">打开在线版</a>
<a class="btn btn-secondary" href="{MAIL_ZH}">申请试用</a>
<a class="btn btn-text" href="#features">能做什么</a>
</div>
</div>
</section>
<section class="sec alt" id="features">
<div class="wrap">
<div class="sec-head">
<p class="eyebrow">features · <span class="cn">能力</span></p>
<h2 class="sec-title">能做什么</h2>
</div>
<div class="lines-grid">
<article class="line-card"><h3 class="line-name">住宅与商业双轨核保</h3><p class="line-what">住宅按月供、现金回报与买家清单打分；商业从租金表、T12 算到 NOI、Cap Rate、DSCR 与 IRR。每次运行有编号，任何人可按编号重算，核对结果是否一字不差。</p></article>
<article class="line-card"><h3 class="line-name">每个数字一本护照</h3><p class="line-what">关键数字记录来源文件、页码、可信度和复核人；开启认证后，录入人不能自己复核（四眼原则）。跨来源对不上的数单列为矛盾，裁决前不当真。</p></article>
<article class="line-card"><h3 class="line-name">先核哪个</h3><p class="line-what">别人只告诉你“有几处待核”；这里把每一处按“它能让主回报指标摆动多少个基点”排序，第一条就是最该先去追的那份文件。</p></article>
<article class="line-card"><h3 class="line-name">反方备忘录，不经 AI</h3><p class="line-what">上投委会前，系统先写“这笔交易最可能怎么失败”：擦边的淘汰条件、押在单一假设上的结论、亏钱的悲观情景、没核完的数。每条由固定规则拼成，可复现，数据不足就不写。</p></article>
<article class="line-card"><h3 class="line-name">反推最高出价</h3><p class="line-what">把所有淘汰条件（DSCR 底线、现金回报、IRR 等）同时代入，反推还能出的最高价，并标出卡住价格的那一条；拖动价格可以即时试算每条底线还剩多少余量。</p></article>
<article class="line-card"><h3 class="line-name">投委会到持有期复盘</h3><p class="line-what">投委会材料一键生成，主席一票否决；买入后录实际 NOI，对照当时的承销逐条归因“错在哪条假设”。角色权限分主席、分析师、查看者，所有改动写入审计时间线。</p></article>
</div>
</div>
</section>
<section class="sec" id="demo">
<div class="wrap">
<div class="sec-head">
<p class="eyebrow">deploy · <span class="cn">部署</span></p>
<h2 class="sec-title">怎么用起来</h2>
<p class="sec-lede">在线版是创始人自用的生产环境（N=1 实证）。自己部署：Python 3.11 以上，一条 <code>./run.sh</code> 在本机起服务；生产用 Postgres。界面中英切换，61 个 REST 接口附 OpenAPI 规范。</p>
</div>
<div class="support-links">
<a class="btn btn-secondary" href="{APP}" rel="noopener">打开在线版</a>
<a class="btn btn-secondary" href="https://github.com/HUIIIM/vertciti-dealdesk" rel="noopener">源码仓库</a>
</div>
</div>
</section>
<section class="sec status-sec alt" id="status">
<div class="wrap">
<div class="status-grid">
<article class="status-card">
<div class="status-top"><h2 class="status-name">项目状态</h2><span class="status-stage"><span aria-hidden="true">🟢</span> 持续运营</span></div>
<p class="status-line"><span class="status-k">最近里程碑</span>v2 交易工作台完成开发并进入代码评审：分层后端与数据库迁移、React 前端、中英双语、角色权限与审计 <span class="status-date">{ASOF}</span></p>
<p class="status-line"><span class="status-k">下一步</span>v2 工作台上线生产（日期待定）</p>
<p class="status-qualifier">在线版目前仍是 v1 界面；v2 工作台上线前，上面部分能力只能自部署体验。不作收益或性能承诺。</p>
<p class="status-asof" data-asof="{ASOF}">数据截至 {ASOF}</p>
</article>
</div>
</div>
</section>
<section aria-label="下一步" class="sec page-cta">
<div class="wrap">
<h2 class="sec-title">下一步</h2>
<p class="sec-lede">先打开在线版看看，再来信谈试用；或回到业务版图看其他产品线。</p>
<div class="cta-row">
<a class="btn btn-primary" href="{MAIL_ZH}">来信 contact@vertciti.com</a>
<a class="btn btn-secondary" href="/business/">业务版图</a>
<a class="btn btn-text" href="/">回首页</a>
</div>
</div>
</section>
""",
}

EN = {
    "title": "DealDesk Underwriting Desk · Product | vertciti",
    "desc": "DealDesk: an MIT-licensed, self-hosted real-estate underwriting desk. Residential and commercial underwriting, "
            "a source and review trail for every key number, a ranked verify-first queue, a devil's-advocate memo written "
            "by fixed rules rather than AI, and a max-bid solver.",
    "og": "Open-source, self-hosted real-estate underwriting: number passports, verify-first, a rule-based devil's-advocate memo, max bid.",
    "crumbs": ("Home", "/en.html", "Business", "/en/business/"), "canonical": "/en/dealdesk/",
    "main": f"""<nav aria-label="Breadcrumb" class="crumbs wrap"><ol><li><a href="/en.html">Home</a></li><li><a href="/en/business/">Business</a></li><li><span aria-current="page">DealDesk</span></li></ol></nav>
<section class="sec" id="product">
<div class="wrap">
<div class="sec-head">
<p class="eyebrow">product</p>
<h1 class="sec-title page-title">DealDesk Underwriting Desk</h1>
<p class="sec-lede">One desk for a real-estate deal, from first look and underwriting to the investment committee and the post-purchase review. Residential deals are read through mortgage payment and cash-on-cash; commercial deals through IRR, DSCR and NOI. Every key number records where it came from and who checked it. Missing numbers show as "—", never as 0. MIT-licensed and self-hosted: your data stays on your own server.</p>
</div>
<div class="cta-row">
<a class="btn btn-primary" href="{APP}/?lang=en" rel="noopener">Open the live app</a>
<a class="btn btn-secondary" href="{MAIL_EN}">Request a trial</a>
<a class="btn btn-text" href="#features">What it does</a>
</div>
</div>
</section>
<section class="sec alt" id="features">
<div class="wrap">
<div class="sec-head">
<p class="eyebrow">features</p>
<h2 class="sec-title">What it does</h2>
</div>
<div class="lines-grid">
<article class="line-card"><h3 class="line-name">Residential and commercial underwriting</h3><p class="line-what">Residential deals are scored on payment, cash-on-cash and a buyer checklist; commercial deals run from rent roll and T12 to NOI, cap rate, DSCR and IRR. Every run has an ID that anyone can recompute to check the result matches exactly.</p></article>
<article class="line-card"><h3 class="line-name">A passport for every number</h3><p class="line-what">Key numbers record the source file, page, confidence and reviewer. With sign-in on, whoever entered a number cannot also verify it (four-eyes rule). Figures that disagree across sources are listed as conflicts and not trusted until resolved.</p></article>
<article class="line-card"><h3 class="line-name">Verify first</h3><p class="line-what">Other tools tell you how many items are unverified. DealDesk ranks each one by how many basis points it can swing the main return metric, so the first line is the document to chase first.</p></article>
<article class="line-card"><h3 class="line-name">A devil's-advocate memo, without AI</h3><p class="line-what">Before committee, the system writes how this deal is most likely to fail: kill criteria it barely clears, conclusions resting on one assumption, a losing downside scenario, unverified numbers. Each point comes from fixed rules, is reproducible, and is left out when the data is missing.</p></article>
<article class="line-card"><h3 class="line-name">Max bid, solved backwards</h3><p class="line-what">All kill criteria (DSCR floor, cash-on-cash, IRR and more) are applied at once to solve for the highest price you can still pay, and the binding constraint is named. Drag the price to see how much room each floor has left.</p></article>
<article class="line-card"><h3 class="line-name">From committee to post-mortem</h3><p class="line-what">Committee packs are generated in one step, with a chairman veto. After purchase, enter actual NOI and see which underwriting assumption the variance comes from. Roles are chairman, analyst and viewer; every change lands in an audit timeline.</p></article>
</div>
</div>
</section>
<section class="sec" id="demo">
<div class="wrap">
<div class="sec-head">
<p class="eyebrow">deploy</p>
<h2 class="sec-title">How to run it</h2>
<p class="sec-lede">The live app is the founder's own production instance (an N=1 proof). To self-host: Python 3.11 or later, then <code>./run.sh</code> starts it locally; use Postgres in production. The interface switches between Chinese and English, and the 61 REST endpoints come with an OpenAPI spec.</p>
</div>
<div class="support-links">
<a class="btn btn-secondary" href="{APP}/?lang=en" rel="noopener">Open the live app</a>
<a class="btn btn-secondary" href="https://github.com/HUIIIM/vertciti-dealdesk" rel="noopener">Source code</a>
</div>
</div>
</section>
<section class="sec status-sec alt" id="status">
<div class="wrap">
<div class="status-grid">
<article class="status-card">
<div class="status-top"><h2 class="status-name">Project status</h2><span class="status-stage"><span aria-hidden="true">🟢</span> Live &amp; ongoing</span></div>
<p class="status-line"><span class="status-k">Latest milestone</span>The v2 deal workbench is built and in code review: layered backend with database migrations, React front end, Chinese/English interface, roles and audit <span class="status-date">{ASOF}</span></p>
<p class="status-line"><span class="status-k">Next step</span>v2 workbench goes to production (date TBD)</p>
<p class="status-qualifier">The live app still shows the v1 interface; until v2 ships, some of the features above are available only when self-hosted. No return or performance claims.</p>
<p class="status-asof" data-asof="{ASOF}">Data as of {ASOF}</p>
</article>
</div>
</div>
</section>
<section aria-label="Next" class="sec page-cta">
<div class="wrap">
<h2 class="sec-title">Next</h2>
<p class="sec-lede">Open the live app first, then write to us about a trial, or go back to the business overview.</p>
<div class="cta-row">
<a class="btn btn-primary" href="{MAIL_EN}">Email contact@vertciti.com</a>
<a class="btn btn-secondary" href="/en/business/">Business</a>
<a class="btn btn-text" href="/en.html">Home</a>
</div>
</div>
</section>
""",
}


def build(src: str, c: dict) -> str:
    s = src
    s = re.sub(r"<title>.*?</title>", f"<title>{c['title']}</title>", s, count=1, flags=re.S)
    s = re.sub(r'<meta content="[^"]*" name="description"/>', f'<meta content="{c["desc"]}" name="description"/>', s, count=1)
    for prop in ("og:title", "twitter:title"):
        s = re.sub(rf'<meta content="[^"]*" (property|name)="{prop}"/>',
                   lambda m: f'<meta content="vertciti — {c["title"].split(" ｜")[0].split(" |")[0]}" {m.group(1)}="{prop}"/>', s, count=1)
    for prop in ("og:description", "twitter:description"):
        s = re.sub(rf'<meta content="[^"]*" (property|name)="{prop}"/>', lambda m: f'<meta content="{c["og"]}" {m.group(1)}="{prop}"/>', s, count=1)
    s = s.replace("/en/echowatch/", "/en/dealdesk/").replace("/echowatch/", "/dealdesk/")
    home, home_url, biz, biz_url = c["crumbs"]
    ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": home, "item": "https://vertciti.com" + home_url},
        {"@type": "ListItem", "position": 2, "name": biz, "item": "https://vertciti.com" + biz_url},
        {"@type": "ListItem", "position": 3, "name": "DealDesk", "item": "https://vertciti.com" + c["canonical"]}]}
    s = re.sub(r'<script type="application/ld\+json">\{"@context": "https://schema.org", "@type": "BreadcrumbList".*?</script>',
               lambda _m: f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>', s, count=1, flags=re.S)
    i = s.index('<main id="main" tabindex="-1">') + len('<main id="main" tabindex="-1">')
    j = s.index("</main>", i)
    out = s[:i] + c["main"] + s[j:]
    assert "EchoWatch" not in out[i:i + len(c["main"])], "正文里不应残留 EchoWatch"
    return out


if __name__ == "__main__":
    zh_src, en_src, out = Path(sys.argv[1]).read_text(), Path(sys.argv[2]).read_text(), Path(sys.argv[3])
    (out / "dealdesk").mkdir(parents=True, exist_ok=True)
    (out / "en" / "dealdesk").mkdir(parents=True, exist_ok=True)
    (out / "dealdesk" / "index.html").write_text(build(zh_src, ZH))
    (out / "en" / "dealdesk" / "index.html").write_text(build(en_src, EN))
    print("ok")
