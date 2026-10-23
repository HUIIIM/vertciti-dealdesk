import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { App } from "@/App";
import { ToastHost } from "@/components/ui";
import { calls, override } from "@/test/server";

const at = (hash: string) => { window.location.hash = hash; return render(<ToastHost><App /></ToastHost>); };
const posted = (path: string) => calls.filter((c) => c.method !== "GET" && c.path.startsWith(path));
const heading = (name: string | RegExp) => screen.findByRole("heading", { name }, { timeout: 3000 });

describe("概览：决策、任务、审批、回退", () => {
  it("记 BUY 决策、加任务并完成、申请并批准付款、回退须写原因", async () => {
    override("GET /api/v2/deals/1/tasks", 200, [{ id: 1, deal_id: 1, title: "Phase I 环评", status: "open", stage: "diligence", assignee: "", due: "", created_by: "local" }]);
    override("GET /api/v2/deals/1/approvals", 200, [{ id: 7, deal_id: 1, kind: "payment", title: "定金", amount: 500000, status: "pending", created_by: "u_analyst", decided_by: null, decided_at: null, note: "" }]);
    at("#/deals/1");
    await heading("阶段推进");
    await userEvent.click(screen.getByRole("button", { name: "BUY" }));
    await userEvent.type(screen.getByLabelText(/理由/), "投委会通过；按反推最高价出价");
    await userEvent.click(screen.getByRole("button", { name: "记录决策" }));
    await waitFor(() => expect(posted("/api/v2/deals/1/decisions")[0]?.body).toMatchObject({ verdict: "BUY" }));
    await userEvent.click(await screen.findByLabelText("完成：Phase I 环评"));
    await waitFor(() => expect(posted("/api/v2/deals/1/tasks/1")[0]?.body).toEqual({ status: "done" }));
    await userEvent.type(screen.getByLabelText("新任务"), "产权调查");
    await userEvent.click(screen.getByRole("button", { name: "添加" }));
    await waitFor(() => expect(posted("/api/v2/deals/1/tasks").some((c) => (c.body as { title?: string })?.title === "产权调查")).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: "批准" }));
    await waitFor(() => expect(posted("/api/v2/deals/1/approvals/7/decide")[0]?.body).toMatchObject({ approve: true }));
    await userEvent.type(screen.getByLabelText("金额"), "250000");
    await userEvent.click(screen.getByRole("button", { name: "申请付款" }));
    await waitFor(() => expect(posted("/api/v2/deals/1/approvals").some((c) => (c.body as { amount?: number })?.amount === 250000)).toBe(true));
    await userEvent.click(screen.getByText("回退或放弃"));
    expect(screen.getByRole("button", { name: "回到发现" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("原因（必填）"), "要价变了");
    await userEvent.click(screen.getByRole("button", { name: "回到发现" }));
    await waitFor(() => expect(posted("/api/v2/deals/1/stage")[0]?.body).toMatchObject({ target: "sourcing", reason: "要价变了" }));
  });
});

describe("敏感性与红队", () => {
  it("标已读、拖滑块重算、改情景概率、反推最高出价", async () => {
    at("#/deals/1/risk");
    await heading("红队面板：最可能出错的 5 个假设");
    await userEvent.click(await screen.findByRole("button", { name: /我已读完/ }));
    await waitFor(() => expect(posted("/api/v2/deals/1/redteam/read")).toHaveLength(1));
    fireEvent.change(screen.getByLabelText("租金水平"), { target: { value: "-15" } });
    await waitFor(() => expect(calls.some((c) => c.path === "/api/v2/model/commercial"
      && Math.abs(((c.body as { tenants?: { monthly_rent: number }[] }).tenants?.[0]?.monthly_rent ?? 0) - 83333.34 * 0.85) < 0.01)).toBe(true), { timeout: 3000 });
    fireEvent.change(await screen.findByLabelText("悲观概率"), { target: { value: "30" } });
    expect(await screen.findByText("105")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/目标 IRR/), { target: { value: "10" } });
    await userEvent.click(screen.getByRole("button", { name: "反算" }));
    await waitFor(() => expect(posted("/api/v2/deals/1/max-bid").some((c) => JSON.stringify(c.body).includes('"min":10'))).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: "复位" }));
  });
});

describe("投委会", () => {
  it("投票、生成 PDF / Excel、校验原件", async () => {
    at("#/deals/1/committee");
    await heading("投委会表决");
    await userEvent.click(screen.getByRole("button", { name: "生成 PDF" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/v2/deals/1/committee/pack.pdf")).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: "生成 Excel" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/v2/deals/1/committee/pack.xlsx")).toBe(true));
    override("POST /api/v2/committee/verify", 200, { genuine: false, sha256: "ff", message: "未登记：这份文件不是本系统生成的原件" });
    const input = screen.getByLabelText("选择要校验的文件") as HTMLInputElement;
    await userEvent.upload(input, new File(["%PDF"], "ic.pdf", { type: "application/pdf" }));
    expect(await screen.findByText(/未登记/)).toBeInTheDocument();
  });
});

describe("文件与证据", () => {
  it("上传文件、裁决矛盾（理由必填）", async () => {
    at("#/deals/1/files");
    await heading("跨来源矛盾登记");
    const prompt = vi.spyOn(window, "prompt").mockReturnValue("以 OM 为准");
    await userEvent.click(await screen.findByRole("button", { name: "采用 OM" }));
    await waitFor(() => expect(posted("/api/v2/deals/1/conflicts/1/resolve")[0]?.body).toEqual({ value: 5, note: "以 OM 为准" }));
    prompt.mockRestore();
    await userEvent.upload(screen.getByLabelText("选择文件"), new File(["x"], "om.pdf", { type: "application/pdf" }));
    await waitFor(() => expect(posted("/api/v2/deals/1/documents")).toHaveLength(1));
    await userEvent.click(screen.getByRole("button", { name: /退出 Cap Rate/ }));
    expect(await screen.findByRole("dialog", { name: /数字护照/ })).toBeInTheDocument();
  });
});

describe("持有期、日志、租金表、T12、市场", () => {
  it("录实际数", async () => {
    at("#/deals/1/holding");
    await heading("实际 vs 承销");
    const noi = screen.getByLabelText("实际 NOI");
    fireEvent.focus(noi); fireEvent.change(noi, { target: { value: "1800000" } }); fireEvent.blur(noi);
    await userEvent.click(screen.getByRole("button", { name: "录入" }));
    await waitFor(() => expect(posted("/api/v2/deals/1/actuals")[0]?.body).toMatchObject({ noi: 1800000 }));
  });
  it("归因：每步都算得出才画瀑布图；有一步未知就不画、如实说明", async () => {
    const attribution = (steps: { key: string; label: string; contribution_pct_points: number | null }[]) => ({
      available: true, metric: "irr_pct", underwritten: 12, actual_implied: 9.5, total_pct_points: -2.5, note: "按实际 NOI 重算", reason: null, steps });
    const base = { actuals: [], basis: { from_buy_decision: true, run_id: "R1", version_id: 2, version_no: 2 },
      variance: [{ period: "2026", year: 1, occupancy_pct: 91, noi: { actual: 1500000, underwritten: 1600000, variance: -100000, variance_pct: -6.25 } }] };
    override("GET /api/v2/deals/1/holding", 200, { ...base, attribution: attribution([{ key: "noi", label: "NOI", contribution_pct_points: -2.5 }]) });
    const { unmount } = at("#/deals/1/holding");
    expect(await screen.findByRole("img", { name: "IRR归因瀑布图" }, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.getByText(/（BUY 决策时冻结）/)).toBeInTheDocument();
    expect(screen.getByText(/第\s*1\s*年/)).toBeInTheDocument();
    unmount();
    override("GET /api/v2/deals/1/holding", 200, { ...base, attribution: attribution([{ key: "noi", label: "NOI", contribution_pct_points: null }]) });
    at("#/deals/1/holding");
    expect(await screen.findByText(/不画瀑布图/, undefined, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "IRR归因瀑布图" })).toBeNull();
  });
  it("录实际数失败时报错，不假装成功", async () => {
    override("PUT /api/v2/deals/1/actuals", 422, { detail: "期间格式不对" });
    at("#/deals/1/holding");
    await heading("实际 vs 承销");
    await userEvent.click(screen.getByRole("button", { name: "录入" }));
    expect(await screen.findByText(/期间格式不对/)).toBeInTheDocument();
  });
  it("住宅交易的 T12 只列运营费用", async () => {
    at("#/deals/2/t12");
    expect(await heading("运营费用")).toBeInTheDocument();
  });
  it("市场：拉到可比成交时出表和散点图，$/SF 按面积算、缺面积不算", async () => {
    override("POST /api/wb/comps/pull", 200, { ok: true, rows: [
      { address: "1 Main St", price: 2000000, sf: 4000, sale_date: "2026-03-01", distance_miles: 0.4, source: "TopHap" },
      { address: "2 Main St", price: 3000000, sf: 5000, sale_date: "2026-05-01", distance_miles: 1.2, source: "TopHap" },
      { address: "3 Main St", price: 1000000, sf: null, sale_date: "2026-06-01", distance_miles: null, source: "TopHap" }] });
    at("#/deals/1/market");
    await heading("可比成交");
    await userEvent.click(screen.getByRole("button", { name: "拉取可比成交" }));
    expect(await screen.findByRole("img", { name: "可比成交：$/SF 与距离" })).toBeInTheDocument();
    const row = screen.getByText("3 Main St").closest("tr")!;
    expect(within(row).getAllByText("—").length).toBeGreaterThan(0);
  });
  it("选两版看差异、校验运行编号", async () => {
    override("GET /api/v2/deals/1/diff", 200, (await import("@/test/fixtures.json")).default["GET /api/v2/deals/1/diff"][1]);
    override("POST /api/v2/runs", 200, { run_id: "R1", identical: true, same_engine: true, stored_engine: "a", current_engine: "a", stored_sha256: "x", recomputed_sha256: "x" });
    at("#/deals/1/log");
    await heading("承销版本");
    await userEvent.click(await screen.findByLabelText("A：第 1 版"));
    await userEvent.click(screen.getByLabelText("B：第 2 版"));
    expect(await screen.findByText(/第 1 版 → 第 2 版/)).toBeInTheDocument();
    expect(screen.getAllByText("收购价").length).toBeGreaterThan(0);
  });
  it("租金表加删租户、T12 改科目", async () => {
    at("#/deals/1/rentroll");
    await heading("租金表");
    await userEvent.click(screen.getByRole("button", { name: "+ 加租户" }));
    expect(screen.getByLabelText("第 2 行租户")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("第 2 行租户"), "咖啡店");
    await userEvent.click(screen.getByLabelText("删除第 2 行"));
    expect(screen.queryByLabelText("第 2 行租户")).toBeNull();
    await act(async () => { window.location.hash = "#/deals/1/t12"; window.dispatchEvent(new HashChangeEvent("hashchange")); });
    await heading("T12 · 现金流");
    const tax = screen.getByLabelText("房产税 预测");
    fireEvent.focus(tax); fireEvent.change(tax, { target: { value: "310000" } }); fireEvent.blur(tax);
    expect(await screen.findByRole("region", { name: "未保存的草稿" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "放弃改动" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "未保存的草稿" })).toBeNull());
  });
  it("市场：数据源不可用时如实说明", async () => {
    override("POST /api/wb/comps/pull", 200, { ok: false, error: "TopHap 未启用" });
    override("POST /api/wb/ownership/tree", 200, { ok: true, owner_resolved: false, nodes: [{ id: "p", level: 0, display: "39-09 Main St", confidence: "verified", relation: "标的物业", sources: [{ source: "请求地址" }] }], caveats: ["州未知"] });
    override("POST /api/wb/sell-readiness/score", 200, { ok: true, score: 25, max_score: 100, tier_note: "动机中", signals: [{ id: "a", label: "持有年限", status: "hit", earned: 25, points: 25, value: "12 年", source: "公共记录" }], caveats: [] });
    at("#/deals/1/market");
    await heading("可比成交");
    await userEvent.click(screen.getByRole("button", { name: "拉取可比成交" }));
    expect(await screen.findByText(/TopHap 未启用/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "穿透产权" }));
    expect(await screen.findByText("州未知")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "计算" }));
    expect(await screen.findByText("+25")).toBeInTheDocument();
  });
});

describe("设置与外观", () => {
  it("创建用户显示一次性令牌；保存模板", async () => {
    override("GET /api/v2/admin/users", 200, []);
    override("POST /api/v2/admin/users", 201, { id: 1, username: "ana", display_name: "Ana", role: "analyst", active: true, token: "dd_secret", note: "" });
    at("#/settings/users");
    await heading("邀请用户");
    await userEvent.type(screen.getByLabelText("Google 邮箱"), "ana@gmail.com");
    await userEvent.type(screen.getByLabelText("用户名"), "ana");
    await userEvent.click(screen.getByRole("button", { name: "邀请" }));
    expect(await screen.findByText("dd_secret")).toBeInTheDocument();
    expect(posted("/api/v2/admin/users")[0]?.body).toMatchObject({ username: "ana", email: "ana@gmail.com", role: "analyst" });
    await act(async () => { window.location.hash = "#/settings/templates"; window.dispatchEvent(new HashChangeEvent("hashchange")); });
    await userEvent.click(await screen.findByRole("button", { name: "保存模板" }));
    await waitFor(() => expect(posted("/api/v2/settings/templates")).toHaveLength(1));
  });
  it("密度 / 主题切换写到根元素；保存视图；登录提交", async () => {
    at("#/");
    await screen.findByText("4 笔交易");
    await userEvent.click(screen.getByRole("button", { name: "紧凑" }));
    expect(document.documentElement.dataset.density).toBe("compact");
    await userEvent.click(screen.getByRole("button", { name: /切换到深色/ }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    const prompt = vi.spyOn(window, "prompt").mockReturnValue("我的视图");
    await userEvent.click(screen.getByRole("button", { name: "保存当前视图" }));
    await waitFor(() => expect(posted("/api/v2/settings/views")[0]?.body).toMatchObject({ name: "我的视图" }));
    prompt.mockRestore();
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    const box = await screen.findByRole("combobox", { name: "命令栏搜索" });
    await userEvent.type(box, "紧凑");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("combobox", { name: "命令栏搜索" })).toBeNull());
  });
  it("令牌登录后带 Bearer 头重新加载", async () => {
    override("GET /api/v2/me", 200, { username: "anonymous", role: "viewer", role_label: "只读", display_name: "匿名", auth: true, permissions: [] });
    at("#/");
    const input = await screen.findByLabelText("访问令牌");
    await userEvent.type(input, "dd_tok");
    await userEvent.click(within(input.closest("form")!).getByRole("button", { name: "进入" }));
    expect(sessionStorage.getItem("dd.token")).toBe("dd_tok");
  });
  it("Google 登录：登录页给 Google 按钮；回跳 #auth= 存会话令牌并抹掉地址栏；#auth_error= 显示原因", async () => {
    override("GET /api/v2/me", 200, { username: "anonymous", role: "viewer", role_label: "只读", display_name: "匿名", auth: true, permissions: [] });
    override("GET /api/v2/auth/providers", 200, { google: true });
    window.location.hash = "#auth_error=not_invited";
    render(<ToastHost><App /></ToastHost>);
    expect(await screen.findByRole("alert")).toHaveTextContent("还没有被邀请");
    expect(await screen.findByRole("link", { name: "使用 Google 账号登录" })).toHaveAttribute("href", "/api/v2/auth/google/start");
    expect(window.location.hash).toBe("#/");
    const { consumeAuthFragment, getToken, setToken } = await import("@/api/client");
    window.location.hash = "#auth=dds_abc";
    expect(consumeAuthFragment()).toBeNull();
    expect(localStorage.getItem("dd.token")).toBe("dds_abc");
    expect(getToken()).toBe("dds_abc");
    expect(window.location.hash).toBe("#/");
    window.location.hash = "#/deals/1";
    expect(consumeAuthFragment()).toBeNull();
    setToken(null);
    expect(getToken()).toBeNull();
  });
  it("设置 · 用户：改邮箱、停用别人；自己不出现停用按钮", async () => {
    override("GET /api/v2/admin/users", 200, [
      { id: 1, username: "local", display_name: "本机", role: "chairman", active: true, email: null },
      { id: 2, username: "pat", display_name: "Pat", role: "analyst", active: true, email: "pat@g.com" }]);
    override("PATCH /api/v2/admin/users/pat", 200, { id: 2, username: "pat", display_name: "Pat", role: "analyst", active: false, email: "p2@g.com" });
    at("#/settings/users");
    const box = await screen.findByLabelText("pat 的 Google 邮箱");
    await userEvent.clear(box);
    await userEvent.type(box, "p2@g.com");
    const row = box.closest("li")!;
    await userEvent.click(within(row).getByRole("button", { name: "保存邮箱" }));
    await userEvent.click(within(row).getByRole("button", { name: "停用" }));
    await waitFor(() => expect(posted("/api/v2/admin/users/pat")).toHaveLength(2));
    expect(posted("/api/v2/admin/users/pat")[0]?.body).toEqual({ email: "p2@g.com" });
    expect(posted("/api/v2/admin/users/pat")[1]?.body).toEqual({ active: false });
    const me = (await screen.findByLabelText("local 的 Google 邮箱")).closest("li")!;
    expect(within(me).queryByRole("button", { name: "停用" })).toBeNull();
  });
});

describe("投委会阶段投票", () => {
  it("在投委会阶段可赞成 / 反对 / 弃权，意见随票提交", async () => {
    const fx = (await import("@/test/fixtures.json")).default as unknown as Record<string, [number, { deal: Record<string, unknown> }]>;
    const ov = structuredClone(fx["GET /api/v2/deals/1"]![1]);
    ov.deal = { ...ov.deal, stage: "committee", stage_label: "投委会" };
    override("GET /api/v2/deals/1", 200, ov);
    at("#/deals/1/committee");
    await heading("投委会表决");
    await userEvent.type(await screen.findByLabelText("意见"), "价格需议");
    for (const name of ["赞成", "反对", "弃权"]) await userEvent.click(screen.getByRole("button", { name }));
    await waitFor(() => expect(posted("/api/v2/deals/1/committee/vote").map((c) => (c.body as { vote: string }).vote)).toEqual(["approve", "reject", "abstain"]));
    expect(posted("/api/v2/deals/1/committee/vote")[0]!.body).toMatchObject({ comment: "价格需议" });
  });
});

describe("流水线淘汰条件标签", () => {
  it("已承销但没写淘汰条件时写“未设淘汰条件”，没有版本时写“未承销”", async () => {
    const { killText } = await import("@/pages/Pipeline");
    const base = { kill: { triggered: [], unknown: [], clear: false }, kill_criteria: [] } as never as Parameters<typeof killText>[0];
    expect(killText({ ...base, current_version_id: 3 })).toBe("未设淘汰条件");
    expect(killText({ ...base, current_version_id: null })).toBe("未承销");
    expect(killText({ ...base, current_version_id: 3, kill: { triggered: [{}], unknown: [], clear: false } } as never)).toBe("触发淘汰");
  });
});

describe("后台操作台", () => {
  it("系统：版本、数据库、认证、Google 登录、运行时长、最近错误", async () => {
    override("GET /api/v2/admin/errors", 200, [{ at: "2026-10-23T01:00:00Z", request_id: "abcdef123456", path: "/api/v2/deals/9", method: "GET", error: "KeyError: 'x'" }]);
    at("#/settings/system");
    const status = await screen.findByRole("region", { name: "运行状态" });
    expect(await within(status).findByText("2.0.0")).toBeInTheDocument();
    expect(within(status).getByText(/sqlite · 迁移版本 0002/)).toBeInTheDocument();
    expect(within(status).getByText("本机模式")).toBeInTheDocument();
    expect(within(status).getByText("5 分钟")).toBeInTheDocument();
    const errs = screen.getByRole("region", { name: "最近的服务器错误" });
    expect(await within(errs).findByText("KeyError: 'x'")).toBeInTheDocument();
    expect(within(errs).getByText("abcdef12")).toBeInTheDocument();
  });
  it("审计日志：列出改前 → 改后，按对象类型重新查询、按操作人筛", async () => {
    override("GET /api/v2/admin/audit", 200, [
      { id: 2, entity: "user", entity_id: "3", action: "update", actor: "owner", before: { email: null, role: "viewer" }, after: { email: "p@g.com", role: "viewer" }, request_id: "r2", at: "2026-10-23T02:00:00Z" },
      { id: 1, entity: "deal", entity_id: "1", action: "create", actor: "pat", before: null, after: { name: "A" }, request_id: "r1", at: "2026-10-23T01:00:00Z" }]);
    at("#/settings/audit");
    expect(await screen.findByText("email: — → p@g.com")).toBeInTheDocument();
    expect(screen.queryByText(/role:/)).toBeNull();                      // 没变的字段不列
    await userEvent.type(screen.getByLabelText("操作人"), "pat");
    expect(screen.queryByText("email: — → p@g.com")).toBeNull();
    expect(screen.getByText("共 1 条（最近 500 条内）")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("对象类型"), "user");
    await waitFor(() => expect(calls.some((c) => c.path.startsWith("/api/v2/admin/audit") && c.path.includes("entity=user"))).toBe(true));
  });
  it("changes()：非对象整体显示、两边都空不列", async () => {
    const { changes } = await import("@/pages/Settings");
    expect(changes(null, null)).toEqual([]);
    expect(changes(null, "x")).toEqual(["x"]);
    expect(changes("a", "b")).toEqual(["a → b"]);
    expect(changes({ a: 1, b: [1] }, { a: 1, b: [2], c: "" })).toEqual(["b: [1] → [2]"]);
  });
  it("新建机构级交易可从示例开始：建交易后直接存第一版承销，名称与要价按示例带出", async () => {
    const fx = (await import("@/test/fixtures.json")).default as unknown as Record<string, [number, { kill_criteria_defaults: Record<string, unknown> }]>;
    const cat = structuredClone(fx["GET /api/v2/catalog"]![1]);
    cat.kill_criteria_defaults.institutional = [{ metric: "dscr", op: "<", threshold: 1.25 }];
    override("GET /api/v2/catalog", 200, cat);
    override("GET /api/v2/cre/example?kind=multifamily", 200, { purchase_price: 48000000, hold_years: 5 });
    override("POST /api/v2/deals", 201, { id: 1, name: "示例：多户公寓", track: "institutional" });
    override("POST /api/v2/deals/1/versions", 201, { id: 9, version_no: 1 });
    at("#/");
    await screen.findByText("4 笔交易");
    await userEvent.click(screen.getAllByRole("button", { name: /新建交易/ })[0]!);
    const dlg = await screen.findByRole("dialog", { name: "新建交易" });
    await userEvent.click(within(dlg).getByRole("button", { name: "机构级" }));
    await userEvent.click(within(dlg).getByRole("button", { name: "示例：多户公寓" }));
    await userEvent.click(within(dlg).getByRole("button", { name: "创建并开始承销" }));
    await waitFor(() => expect(posted("/api/v2/deals/1/versions")).toHaveLength(1));
    expect(posted("/api/v2/deals")[0]?.body).toMatchObject({ name: "示例：多户公寓", track: "institutional", asking_price: 48000000 });
    expect(posted("/api/v2/deals/1/versions")[0]?.body).toMatchObject({ inputs: { purchase_price: 48000000 }, label: "示例数据" });
  });
});
