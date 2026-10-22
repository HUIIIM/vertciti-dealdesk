// 验收 §8.5：键盘可完成“新建交易 → 承销 → 生成投委会包”全流程（只按键，不点鼠标）。
// 验收 §8.3：axe 无障碍扫描，严重 / 关键级问题为 0。真实后端 + 隔离库（playwright.config.ts webServer）。
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

/** 只用 Tab 把焦点移到可访问名称匹配的元素（最多 120 次），模拟纯键盘用户。 */
async function tabTo(page: Page, name: RegExp, max = 120): Promise<void> {
  for (let i = 0; i < max; i++) {
    await page.keyboard.press("Tab");
    const label = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el) return "";
      const lab = el.getAttribute("aria-label") ?? (el.id ? document.querySelector(`label[for="${el.id}"]`)?.textContent : "") ?? "";
      const wrap = el.closest("label")?.textContent ?? "";
      return `${lab} ${wrap} ${el.textContent ?? ""}`;
    });
    if (name.test(label)) return;
  }
  throw new Error(`Tab ${max} 次没找到 ${name}`);
}

test("纯键盘：新建交易 → 承销（租金表 / T12 / 模型）→ 保存版本 → 生成投委会包", async ({ page }) => {
  await page.goto("/app/#/");
  await expect(page.getByRole("heading", { name: /笔交易/ })).toBeVisible();
  await page.keyboard.press("n");                                   // N：新建
  const dlg = page.getByRole("dialog", { name: "新建交易" });
  await expect(dlg).toBeVisible();
  await page.keyboard.type("键盘验收 · 120 Grand St");               // 焦点已在“交易名称”
  await page.keyboard.press("Tab");
  await page.keyboard.type("120 Grand St, Brooklyn, NY");
  await page.keyboard.press("Tab");
  await page.keyboard.type("3,200,000");
  await page.keyboard.press("Enter");                               // 表单提交（淘汰条件已按商业默认模板预填）
  await expect(page).toHaveURL(/#\/deals\/\d+\/model$/);
  await expect(page.getByRole("heading", { name: "键盘验收 · 120 Grand St" })).toBeVisible();

  await page.keyboard.press("Escape");
  await page.locator("body").press("2");                            // 2：租金表
  await expect(page.getByRole("heading", { name: "租金表" })).toBeVisible();
  await tabTo(page, /\+ 加租户/);
  await page.keyboard.press("Enter");
  await tabTo(page, /第 1 行月租/);
  await page.keyboard.type("26000");
  await page.keyboard.press("Tab");

  await page.keyboard.press("Escape");
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.keyboard.press("3");                                   // 3：T12
  await expect(page.getByRole("heading", { name: "T12 · 现金流" })).toBeVisible();
  await tabTo(page, /房产税 预测/);
  await page.keyboard.type("48000");
  await page.keyboard.press("Tab");

  await page.keyboard.press("Control+s");                           // ⌘S / Ctrl+S：保存版本
  const save = page.getByRole("dialog", { name: "保存承销版本" });
  await expect(save).toBeVisible();
  await page.keyboard.type("首版：键盘录入租金与税");
  await page.keyboard.press("Enter");
  await expect(save).toBeHidden();
  await expect(page.getByText(/第 1 版/).first()).toBeVisible();
  await expect(page.getByTestId("metric-irr_pct")).not.toHaveText(/—/);

  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.keyboard.press("8");                                   // 8：投委会
  await expect(page.getByRole("heading", { name: "投委会包" })).toBeVisible();
  await tabTo(page, /生成 PDF/);
  const dl = page.waitForEvent("download");
  await page.keyboard.press("Enter");
  const file = await dl;
  expect(file.suggestedFilename()).toMatch(/\.pdf$/);
  await expect(page.getByRole("heading", { name: "已生成" })).toBeVisible();
  await expect(page.getByText(/投委会包已生成 · sha256 [0-9a-f]{12}/)).toBeVisible();
});

let seeded = 0;
test.describe("无障碍（有真实数据）", () => {
  test.beforeAll(async ({ request }) => {
    // 自备数据：一笔商业交易 + 一版承销 + 一条来源与矛盾，页面上的表格、图表、状态都会渲染出来
    const tpl = await (await request.get("/api/uw/template")).json();
    const d = await (await request.post("/api/v2/deals", { data: { name: "无障碍样例", track: "commercial", address: "1 A11y St",
      asking_price: 42000000, kill_criteria: [{ metric: "dscr", op: "<", threshold: 1.25 }] } })).json();
    seeded = d.id;
    await request.post(`/api/v2/deals/${seeded}/versions`, { data: { inputs: tpl.example_39_main, label: "样例" } });
    for (const [src, v] of [["OM", 5], ["电话", 5.75]] as const)
      await request.post(`/api/v2/deals/${seeded}/evidence`, { data: { field: "analysis.exit_cap_rate", value: v, source: src, method: "pdf", confidence: "high" } });
  });
  for (const [name, tab] of [["流水线", null], ["交易概览", ""], ["模型", "/model"], ["红队", "/risk"], ["文件与证据", "/files"],
    ["投委会", "/committee"], ["日志", "/log"], ["比较", "compare"], ["设置", "settings"]] as const) {
  test(`${name}页无严重 / 关键问题`, async ({ page }) => {
    const path = tab === null ? "/app/#/" : tab === "compare" ? `/app/#/compare?ids=${seeded}` : tab === "settings" ? "/app/#/settings/templates"
      : `/app/#/deals/${seeded}${tab}`;
    // 入场动效会让元素短暂半透明：无障碍扫描量的是静止状态的对比度，按“减少动态效果”跑
    await page.emulateMedia({ reducedMotion: "reduce" });
    // 严格 CSP（app/core/hardening.py）下页面不得触发任何违规：样式 / 脚本 / 图片都只能同源
    await page.addInitScript(() => {
      const w = window as unknown as { __csp: string[] };
      w.__csp = [];
      document.addEventListener("securitypolicyviolation", (e) => w.__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
    });
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(500);
    expect(await page.evaluate(() => (window as unknown as { __csp: string[] }).__csp)).toEqual([]);
    const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    const bad = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(bad.map((v) => `${v.id}: ${v.help} (${v.nodes.length}) ${v.nodes.slice(0, 2).map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
  });
  }
});

test("旧版页面已下线：旧地址都跳到 v2 工作台", async ({ page }) => {
  for (const p of ["/", "/workbench.html", "/uw-commercial.html", "/d.html?addr=1%20Main%20St", "/d"]) {
    await page.goto(p);
    await expect(page).toHaveURL(/\/app\/(#.*)?$/);
  }
});

test("手机 390 宽：只读——看得到数字与进度，没有任何写操作入口", async ({ browser, request }) => {
  const d = await (await request.post("/api/v2/deals", { data: { name: "手机只读", track: "commercial", address: "1 St", kill_criteria: [] } })).json();
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await page.goto(`/app/#/deals/${d.id}`);
  await expect(page.getByRole("note")).toContainText("只读");
  await expect(page.getByRole("heading", { name: "手机只读" })).toBeVisible();
  await expect(page.getByRole("link", { name: /去推进阶段/ })).toHaveCount(0);
  for (const name of [/添加/, /申请付款/, /记录决策/, /推进到/, /保存第一版/]) {
    await expect(page.getByRole("button", { name })).toHaveCount(0);
  }
  await page.goto("/app/#/");
  await expect(page.getByRole("button", { name: /新建交易/ })).toHaveCount(0);
  await page.close();
});

test("字体与官网一致：Nunito Sans 自托管加载成功，正文实际用它渲染", async ({ page }) => {
  await page.goto("/app/#/");
  await expect(page.getByRole("heading", { name: /笔交易/ })).toBeVisible();
  const r = await page.evaluate(async () => {
    await document.fonts.ready;
    const loaded = [...document.fonts].filter((f) => f.family.replace(/"/g, "") === "Nunito Sans" && f.status === "loaded").length;
    return { loaded, check: document.fonts.check('800 16px "Nunito Sans"', "DealDesk 39"), family: getComputedStyle(document.body).fontFamily };
  });
  expect(r.loaded).toBeGreaterThan(0);
  expect(r.check).toBe(true);
  expect(r.family.startsWith('"Nunito Sans"')).toBe(true);
});

test("出价空间：键盘拖动试算价，实时给出该价下的回报与每条淘汰条件", async ({ page, request }) => {
  const tpl = await (await request.get("/api/uw/template")).json();
  const d = await (await request.post("/api/v2/deals", { data: { name: "试算出价", track: "commercial", address: "2 Bid St",
    kill_criteria: [{ metric: "dscr", op: "<", threshold: 1.25 }, { metric: "irr_pct", op: "<", threshold: 12 }] } })).json();
  await request.post(`/api/v2/deals/${d.id}/versions`, { data: { inputs: tpl.example_39_main, label: "样例" } });
  await page.goto(`/app/#/deals/${d.id}`);
  const slider = page.getByRole("slider", { name: "试算出价" });
  await expect(slider).toBeVisible();
  await slider.focus();
  for (let i = 0; i < 12; i++) await page.keyboard.press("ArrowLeft");   // 往下压价
  const out = page.locator(".trial-out");
  await expect(out).toContainText(/相对要价 -\d/);
  await expect(out).toContainText("IRR");
  await expect(out.locator(".status")).toHaveCount(2);                   // 两条淘汰条件逐条给结论
  await out.getByRole("button", { name: "回到要价" }).click();
  await expect(out).toHaveCount(0);
});

test("别人做不到的：先核哪个 + 反方备忘录（不经 AI），真实后端出数", async ({ page, request }) => {
  const tpl = await (await request.get("/api/uw/template")).json();
  const d = await (await request.post("/api/v2/deals", { data: { name: "反方样例", track: "commercial", address: "3 Doubt St",
    kill_criteria: [{ metric: "irr_pct", op: "<", threshold: 12 }] } })).json();
  await request.post(`/api/v2/deals/${d.id}/versions`, { data: { inputs: tpl.example_39_main, label: "样例" } });
  for (const [src, v] of [["OM", 5], ["经纪人电话", 5.75]] as const)
    await request.post(`/api/v2/deals/${d.id}/evidence`, { data: { field: "analysis.exit_cap_rate", value: v, source: src, method: "pdf", confidence: "high" } });
  await page.goto(`/app/#/deals/${d.id}`);
  const vf = page.getByRole("region", { name: "先核哪个" });
  await expect(vf.locator("li")).toHaveCount(3);
  await expect(vf.locator("li").first()).toContainText(/\d+ bp/);
  await page.goto(`/app/#/deals/${d.id}/risk`);
  const memo = page.getByRole("region", { name: "反方备忘录" });
  await expect(memo).toContainText(/\d+ 条高危/);
  await expect(memo).toContainText("已触发淘汰条件");
  await expect(memo).toContainText("不经 AI");
});

test("中英切换：点 EN 后整页英文（用户数据除外），刷新不丢；再点“中文”切回", async ({ page, request }) => {
  const tpl = await (await request.get("/api/uw/template")).json();
  const d = await (await request.post("/api/v2/deals", { data: { name: "Lang Check", track: "commercial", address: "9 Lang St",
    kill_criteria: [{ metric: "irr_pct", op: "<", threshold: 12 }] } })).json();
  await request.post(`/api/v2/deals/${d.id}/versions`, { data: { inputs: tpl.example_39_main, label: "v1" } });
  await page.goto(`/app/#/deals/${d.id}`);
  await page.getByRole("button", { name: "Switch to English" }).click();
  await page.waitForLoadState("load");
  const CJK = /[　-〿一-鿿＀-￯]/;
  for (const tab of ["", "/model", "/risk", "/files", "/committee", "/log"]) {
    await page.goto(`/app/#/deals/${d.id}${tab}`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(400);
    const text = await page.locator("main").innerText();
    const hits = text.split("\n").filter((l) => CJK.test(l));
    expect(hits, `tab ${tab || "overview"}`).toEqual([]);
  }
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await page.getByRole("button", { name: "切换到中文" }).click();
  await page.waitForLoadState("load");
  await expect(page.getByRole("tab", { name: "概览" }).or(page.getByText("概览").first())).toBeVisible();
});
