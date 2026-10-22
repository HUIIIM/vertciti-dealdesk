import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
import fs from "node:fs";
import path from "node:path";
const ROOT = "/home/user/vertciti-website", BASE = "http://127.0.0.1:8812";
const files = [];
(function walk(d) { for (const f of fs.readdirSync(d)) { const p = path.join(d, f); if (f === ".git" || f === "node_modules" || f === "api" || f === "console" || f === "scripts") continue;
  if (fs.statSync(p).isDirectory()) walk(p); else if (f.endsWith(".html") && !f.startsWith("google")) files.push("/" + path.relative(ROOT, p)); } })(ROOT);
const urlOf = (f) => f.endsWith("/index.html") ? f.slice(0, -10) : f;
const exists = (u) => { let p = decodeURIComponent(u.split("#")[0].split("?")[0]); if (!p || p === "/") return true;
  if (/^\/(api|news|en\/news)\//.test(p) || /^\/(feed\.xml|sitemap\.xml|llms(-full)?\.txt|data-room\.json)$/.test(p)) return true;
  const fp = path.join(ROOT, p); return fs.existsSync(fp) && (fs.statSync(fp).isFile() || fs.existsSync(path.join(fp, "index.html"))); };
const out = [];
const b = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium" });
for (const f of files) {
  const u = urlOf(f);
  for (const w of [1440, 390]) {
    const ctx = await b.newContext({ viewport: { width: w, height: 900 } });
    const p = await ctx.newPage(); const errs = [];
    p.on("pageerror", (e) => errs.push("pageerror: " + e.message.slice(0, 120)));
    p.on("console", (m) => { if (m.type() === "error" && !/api\/live|Failed to load resource/.test(m.text())) errs.push(m.text().slice(0, 140)); });
    try { await p.goto(BASE + u, { waitUntil: "networkidle", timeout: 20000 }); } catch (e) { out.push({ u, w, fatal: String(e).slice(0, 100) }); await ctx.close(); continue; }
    for (let y = 0; y < 12000; y += 600) { await p.mouse.wheel(0, 600); await p.waitForTimeout(30); }
    await p.waitForTimeout(300);
    const r = await p.evaluate(() => {
      const vw = document.documentElement.clientWidth;
      const over = [];
      for (const el of document.querySelectorAll("body *")) {
        const cs = getComputedStyle(el); if (cs.display === "none" || cs.visibility === "hidden" || el.closest("[hidden],dialog:not([open]),.drawer")) continue;
        const rc = el.getBoundingClientRect(); if (rc.width === 0 || rc.height === 0) continue;
        if (rc.right > vw + 1 || rc.left < -1) { let a = el.parentElement, clipped = false; while (a) { const s = getComputedStyle(a); if (/(auto|scroll|hidden|clip)/.test(s.overflowX)) { clipped = true; break; } a = a.parentElement; }
          if (!clipped) over.push((el.tagName + "." + [...el.classList].join(".")).slice(0, 60) + "@" + Math.round(rc.right)); }
        if (/^H[1-6]$/.test(el.tagName) && rc.width < 200 && el.textContent.trim().length > 12) over.push("NARROW-HEADING " + el.tagName + ":" + el.textContent.trim().slice(0, 20) + "@" + Math.round(rc.width));
      }
      const links = [...document.querySelectorAll("a[href],link[href],script[src],img[src],source[src]")].map((e) => e.getAttribute("href") || e.getAttribute("src")).filter((h) => h && h.startsWith("/") && !h.startsWith("//"));
      const q = (s) => document.querySelector(s);
      return { hscroll: document.scrollingElement.scrollWidth > vw + 1, over: [...new Set(over)].slice(0, 6), links: [...new Set(links)],
        title: document.title, desc: q('meta[name="description"]')?.content || "", canon: q('link[rel="canonical"]')?.getAttribute("href") || "",
        alt: [...document.querySelectorAll('link[rel="alternate"][hreflang]')].map((l) => l.hreflang), h1: document.querySelectorAll("h1").length,
        lang: document.documentElement.lang, imgNoAlt: [...document.images].filter((i) => !i.hasAttribute("alt")).length,
        emptyH: [...document.querySelectorAll("h1,h2,h3")].filter((h) => !h.textContent.trim()).length,
        dupIds: (() => { const c = {}; document.querySelectorAll("[id]").forEach((e) => c[e.id] = (c[e.id] || 0) + 1); return Object.keys(c).filter((k) => c[k] > 1); })(),
        placeholder: (document.body.innerText.match(/待确认|TODO|lorem|TBD|\[\s*\]/gi) || []).length };
    });
    let axe = [];
    if (w === 1440) { const res = await new AxeBuilder({ page: p }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze(); axe = res.violations.map((v) => `${v.id}(${v.impact})x${v.nodes.length}`); }
    out.push({ u, w, ...r, broken: r.links.filter((h) => !exists(h)), links: undefined, axe, errs: [...new Set(errs)].slice(0, 4) });
    await ctx.close();
  }
}
await b.close();
fs.writeFileSync("/home/user/site/audit.json", JSON.stringify(out, null, 1));
console.log("pages", files.length, "rows", out.length);
