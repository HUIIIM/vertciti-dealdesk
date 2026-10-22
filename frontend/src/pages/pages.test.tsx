import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { App } from "@/App";
import { ToastHost } from "@/components/ui";
import { calls, override } from "@/test/server";

function at(hash: string) {
  window.location.hash = hash;
  return render(<ToastHost><App /></ToastHost>);
}
const go = async (hash: string) => { await act(async () => { window.location.hash = hash; window.dispatchEvent(new HashChangeEvent("hashchange")); }); };

describe("流水线", () => {
  it("看板按阶段分列、淘汰状态三重表意；切表格可排序", async () => {
    at("#/");
    expect(await screen.findByText("4 笔交易")).toBeInTheDocument();
    const col = screen.getByRole("listitem", { name: /承销 1 笔/ });
    expect(within(col).getByText("39-09 Main St")).toBeInTheDocument();
    expect(within(col).getByText("触发淘汰")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "表格" }));
    expect(screen.getByRole("table", { name: "交易列表" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /收购价/ }));
    expect(screen.getAllByRole("row")[1]!.textContent).toContain("Queens");
  });
  it("筛选与键盘：J/K 移动、Enter 打开", async () => {
    at("#/");
    await screen.findByText("4 笔交易");
    await userEvent.type(screen.getByLabelText("筛选名称或地址"), "Main");
    expect(screen.getByText("1 笔交易")).toBeInTheDocument();
    (document.activeElement as HTMLElement).blur();
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(window.location.hash).toBe("#/deals/1"));
  });
  it("N 新建交易：必须先写淘汰条件；创建后进模型页", async () => {
    override("POST /api/v2/deals", 201, { id: 9, name: "新交易", track: "commercial", stage: "sourcing" });
    at("#/");
    await screen.findByText("4 笔交易");
    await userEvent.keyboard("n");
    const dlg = await screen.findByRole("dialog", { name: "新建交易" });
    await userEvent.type(within(dlg).getByLabelText("交易名称"), "新交易");
    await userEvent.type(within(dlg).getByLabelText(/要价/), "1,000,000");
    await userEvent.click(within(dlg).getByRole("button", { name: "创建并开始承销" }));
    await waitFor(() => expect(window.location.hash).toBe("#/deals/9/model"));
    const post = calls.find((c) => c.method === "POST" && c.path === "/api/v2/deals")!;
    expect(post.body).toMatchObject({ name: "新交易", asking_price: 1000000 });
    expect((post.body as { kill_criteria: unknown[] }).kill_criteria.length).toBeGreaterThan(0);
  });
});

describe("交易页", () => {
  it("结论卡：最高出价与卡住价格的约束、淘汰条件、核对进度", async () => {
    at("#/deals/1");
    expect(await screen.findByRole("heading", { name: "39-09 Main St" })).toBeInTheDocument();
    expect(await screen.findByTestId("max-bid")).toHaveTextContent(/最高出价\$34,289,000.*卡在：IRR低于 12%/);
    expect(screen.getByLabelText("淘汰条件")).toHaveTextContent("IRR低于 12% 即放弃");
    expect(screen.getByRole("progressbar", { name: "关键数字复核进度" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /IRR 8\.94%/ }));
    expect(await screen.findByRole("dialog", { name: /计算说明/ })).toHaveTextContent("运行编号");
  });
  it("每个标签页都能渲染（数字键切换）", async () => {
    at("#/deals/1");
    await screen.findByRole("heading", { name: "39-09 Main St" });
    const expectations: [string, string][] = [["rentroll", "租金表"], ["t12", "T12 · 现金流"], ["model", "假设"], ["risk", "红队面板：最可能出错的 5 个假设"],
      ["market", "可比成交"], ["files", "跨来源矛盾登记"], ["committee", "投委会表决"], ["holding", "事后归因复盘：当时错在哪条假设"], ["log", "时间线"], ["overview", "阶段推进"]];
    for (const [tab, name] of expectations) {
      await go(tab === "overview" ? "#/deals/1" : `#/deals/1/${tab}`);
      expect(await screen.findByRole("heading", { name }, { timeout: 3000 })).toBeInTheDocument();
    }
  });
  it("模型页改假设 → 实时重算请求带草稿；⌘S 弹出保存并带改动说明", async () => {
    at("#/deals/1/model");
    const price = await screen.findByLabelText("收购价");
    fireEvent.focus(price);
    fireEvent.change(price, { target: { value: "30000000" } });
    fireEvent.blur(price);
    await waitFor(() => expect(calls.some((c) => c.path === "/api/v2/model/commercial" && (c.body as { analysis: { purchase_price: number } }).analysis.purchase_price === 30000000)).toBe(true), { timeout: 3000 });
    expect(screen.getByRole("region", { name: "未保存的草稿" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "s", metaKey: true });
    const dlg = await screen.findByRole("dialog", { name: "保存承销版本" });
    await userEvent.type(within(dlg).getByRole("textbox"), "降价到 3000 万{Enter}");
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/api/v2/deals/1/versions")).toBe(true));
    const v = calls.find((c) => c.path === "/api/v2/deals/1/versions" && c.method === "POST")!;
    expect(v.body).toMatchObject({ label: "降价到 3000 万" });
  });
  it("数字护照：打开、查看矛盾与历史、登记来源", async () => {
    at("#/deals/1/model");
    fireEvent.click(await screen.findByRole("button", { name: "退出 Cap Rate 的数字护照" }));
    const dlg = await screen.findByRole("dialog", { name: /数字护照 · 退出 Cap Rate/ });
    expect(await within(dlg).findByText("修改历史")).toBeInTheDocument();
    expect(within(dlg).getByText(/待裁决/)).toBeInTheDocument();
    await userEvent.type(within(dlg).getByLabelText("来源"), "评估报告");
    await userEvent.click(within(dlg).getByRole("button", { name: "登记" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/v2/deals/1/evidence")).toBe(true));
  });
  it("关卡未过：推进返回 409 时逐项列出原因", async () => {
    override("POST /api/v2/deals/1/stage", 409, { detail: "关卡未通过：淘汰条件未触发", request_id: "r1",
      gate: { allowed: false, checks: [{ key: "kill_clear", label: "淘汰条件未触发", status: "risk", status_label: "风险", detail: "已触发：IRR", ok: false }] } });
    at("#/deals/1");
    fireEvent.click(await screen.findByRole("button", { name: /推进到「投委会」/ }));
    expect(await screen.findByText("已触发：IRR")).toBeInTheDocument();
  });
  it("住宅交易：模型页没有 IRR，现金回报为主", async () => {
    at("#/deals/2/model");
    expect(await screen.findByText("月度构成")).toBeInTheDocument();
    expect(await screen.findByText(/deal 评分/, { selector: "p" })).toBeInTheDocument();
  });
});

describe("命令栏与全局快捷键", () => {
  it("⌘K 搜交易并跳转；? 显示快捷键", async () => {
    at("#/");
    await screen.findByText("4 笔交易");
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    const box = await screen.findByRole("combobox", { name: "命令栏搜索" });
    await userEvent.type(box, "Queens");
    expect(await screen.findByRole("option", { name: /Queens 两家庭/ })).toBeInTheDocument();
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(window.location.hash).toBe("#/deals/2"));
    fireEvent.keyDown(window, { key: "?" });
    expect(await screen.findByRole("dialog", { name: "键盘快捷键" })).toBeInTheDocument();
  });
});

describe("比较与设置", () => {
  it("比较页逐行最优", async () => {
    at("#/compare?ids=1,2");
    expect(await screen.findByText("交易并排")).toBeInTheDocument();
    expect((await screen.findAllByLabelText(/（最优）/)).length).toBeGreaterThanOrEqual(5);
    expect(screen.getByRole("columnheader", { name: /Queens 两家庭/ })).toBeInTheDocument();
  });
  it("设置：模板、数据源、快捷键", async () => {
    at("#/settings/templates");
    expect(await screen.findByText("商业默认")).toBeInTheDocument();
    await go("#/settings/sources");
    expect(await screen.findByText(/迁移版本/)).toBeInTheDocument();
    await go("#/settings/shortcuts");
    expect(await screen.findByText("打开命令栏：搜交易、跳页面、执行命令")).toBeInTheDocument();
  });
  it("认证开启且未登录 → 令牌登录页", async () => {
    override("GET /api/v2/me", 200, { username: "anonymous", role: "viewer", role_label: "只读", display_name: "匿名", auth: true, permissions: [] });
    at("#/");
    expect(await screen.findByRole("heading", { name: "输入访问令牌" })).toBeInTheDocument();
  });
});
