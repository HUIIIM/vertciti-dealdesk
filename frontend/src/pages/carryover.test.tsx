// 老版功能搬进 v2 的前端入口：导出、从 PDF 提取字段并采用（登记来源）、租金表 Excel、新建时自动搜集、导入老版项目。
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { App } from "@/App";
import { ToastHost } from "@/components/ui";
import { filenameOf } from "@/lib/download";
import { prefillKey } from "@/lib/prefill";
import { calls, override } from "@/test/server";

const at = (hash: string) => { window.location.hash = hash; return render(<ToastHost><App /></ToastHost>); };
const posts = (path: string) => calls.filter((c) => c.method === "POST" && c.path.startsWith(path));
const cand = (o: Record<string, unknown>) => ({ key: "asking_price", label: "售价/要价", path: "analysis.purchase_price", value: 41_000_000,
  display: "$41,000,000", page: 2, source: "om.pdf", source_url: "", confidence: "low", confidence_label: "卖方口径", seller_claimed: true,
  note: "", method: "pdf", ...o });

describe("导出", () => {
  it("商业交易四种导出都在，点了按当前版本下载", async () => {
    override("GET /api/v2/deals/1/export/memo", 200, {});
    at("#/deals/1");
    const card = await screen.findByRole("region", { name: "导出" }, { timeout: 3000 });
    expect(within(card).getByRole("button", { name: "一页纸 Tear Sheet" })).toBeInTheDocument();
    await userEvent.click(within(card).getByRole("button", { name: "投资备忘录 PDF" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/v2/deals/1/export/memo")).toBe(true));
    expect(await screen.findByText(/已导出：dealdesk-1-memo/)).toBeInTheDocument();
  });
  it("文件名取服务端给的（中文也行），取不到用兜底名", () => {
    const r = (cd: string) => new Response("", { headers: { "content-disposition": cd } });
    expect(filenameOf(r("attachment; filename=a.pdf; filename*=UTF-8''%E5%A4%87%E5%BF%98.pdf"), "x")).toBe("备忘.pdf");
    expect(filenameOf(r('attachment; filename="b.xlsx"'), "x")).toBe("b.xlsx");
    expect(filenameOf(r(""), "fallback.pdf")).toBe("fallback.pdf");
  });
});

describe("从 PDF 提取字段", () => {
  it("勾选采用 → 写进草稿并逐条登记来源；只作参考的项不能勾；租约表行可加入租金表", async () => {
    override("GET /api/v2/deals/1/documents", 200, [{ id: 5, deal_id: 1, filename: "om.pdf", content_type: "application/pdf", size: 2048,
      sha256: "ab".repeat(32), category: "om", created_at: "2026-10-20T00:00:00Z", created_by: "local" }]);
    override("POST /api/v2/deals/1/documents/5/extract", 200, { document_id: 5, filename: "om.pdf", track: "commercial", notice: "全部是卖方口径",
      candidates: [cand({}), cand({ key: "beds", label: "卧室数", path: null, value: 3, display: "3" })],
      tenants: [{ suite: "2", tenant: "Cafe", sf: 1200, monthly_rent: 5000, page: 3 }] });
    at("#/deals/1/files");
    await userEvent.click(await screen.findByRole("button", { name: "提取字段" }, { timeout: 3000 }));
    const box = await screen.findByRole("region", { name: "提取结果" });
    expect(within(box).getByText("仅参考")).toBeInTheDocument();
    expect(within(box).getAllByRole("checkbox")).toHaveLength(1);
    await userEvent.click(within(box).getByRole("button", { name: "加入租金表（1）" }));
    expect(await screen.findByText(/已加入 1 个租户/)).toBeInTheDocument();
    await userEvent.click(within(box).getByRole("button", { name: "采用所选（1）" }));
    await waitFor(() => expect(posts("/api/v2/deals/1/evidence")[0]?.body).toMatchObject({
      field: "analysis.purchase_price", value: 41_000_000, method: "pdf", confidence: "low", page: 2, document_id: 5, note: "卖方口径、待验证" }));
    expect(await screen.findByText(/已采用 1 项并登记来源/)).toBeInTheDocument();
  });
});

describe("租金表 Excel", () => {
  it("下载模板；导入时先确认替换，日期没认出来的照实说", async () => {
    override("POST /api/uw/rentroll/parse", 200, { tenants: [{ suite: "A", tenant: "X", sf: 100, monthly_rent: 1000 }, { suite: "B", tenant: "Y", sf: 200, monthly_rent: 2000 }], bad_dates: 1 });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    at("#/deals/1/rentroll");
    await screen.findByRole("heading", { name: "租金表" }, { timeout: 3000 });
    await userEvent.click(screen.getByRole("button", { name: "下载 Excel 模板" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/uw/rentroll/template.xlsx")).toBe(true));
    const input = screen.getByLabelText("选择租金表 Excel");
    await act(async () => { fireEvent.change(input, { target: { files: [new File(["x"], "rr.xlsx")] } }); });
    expect(await screen.findByText(/已导入 2 个租户；1 行日期没认出来/)).toBeInTheDocument();
    expect(confirm).toHaveBeenCalled();
    expect(screen.getByLabelText("第 2 行租户")).toHaveValue("Y");
    confirm.mockRestore();
  });
});

describe("新建时自动搜集", () => {
  it("搜到的要价带进表单，其余候选建好交易后暂存，交易页打开时采用", async () => {
    override("POST /api/v2/research", 200, { track: "commercial", mode: "address", address: "1 Main St, Austin, TX", manual_needed: ["月租金"], error: "",
      candidates: [cand({ method: "api", source: "redfin.com", page: null, value: 510000, display: "$510,000", confidence: "medium", seller_claimed: false })] });
    override("POST /api/v2/deals", 201, { id: 9, name: "1 Main St", track: "commercial", stage: "sourcing" });
    at("#/");
    await screen.findByText("4 笔交易");
    await userEvent.keyboard("n");
    const dlg = await screen.findByRole("dialog", { name: "新建交易" });
    await userEvent.type(within(dlg).getByLabelText(/地址/), "1 Main St, Austin, TX");
    await userEvent.click(within(dlg).getByRole("button", { name: "自动搜集公开信息" }));
    expect(await within(dlg).findByText(/需要手动补：月租金/)).toBeInTheDocument();
    await userEvent.click(within(dlg).getByRole("button", { name: "带入新交易（1）" }));
    expect(within(dlg).getByLabelText(/要价/)).toHaveValue("510000");
    expect(within(dlg).getByLabelText("交易名称")).toHaveValue("1 Main St");
    await userEvent.click(within(dlg).getByRole("button", { name: "创建并开始承销" }));
    await waitFor(() => expect(window.location.hash).toBe("#/deals/9/model"));
    expect(JSON.parse(localStorage.getItem(prefillKey(9)) ?? "[]")).toHaveLength(1);
    expect(posts("/api/v2/research")[0]?.body).toMatchObject({ track: "commercial", mode: "address" });
  });
  it("交易页打开时把暂存的候选采用掉，并删掉暂存", async () => {
    localStorage.setItem(prefillKey(1), JSON.stringify([cand({ method: "api" })]));
    at("#/deals/1");
    await waitFor(() => expect(posts("/api/v2/deals/1/evidence")[0]?.body).toMatchObject({ field: "analysis.purchase_price", method: "api" }), { timeout: 3000 });
    expect(localStorage.getItem(prefillKey(1))).toBeNull();
  });
});

describe("导入老版项目", () => {
  it("列出老版项目；导入过的直接给链接；导入后跳到新交易", async () => {
    override("GET /api/v2/legacy/projects", 200, [
      { kind: "uw", id: 3, track: "commercial", name: "老商业", address: "9 Elm", updated_at: 1_760_000_000, imported_deal_id: null },
      { kind: "project", id: 4, track: "residential", name: "老住宅", address: "", updated_at: null, imported_deal_id: 2 }]);
    override("POST /api/v2/legacy/projects/uw/3/import", 201, { deal: { id: 7, name: "老商业" }, version: { id: 1, version_no: 1 }, warning: "" });
    at("#/settings/legacy");
    expect(await screen.findByRole("link", { name: "已导入 · 打开" })).toHaveAttribute("href", "#/deals/2");
    await userEvent.click(screen.getByRole("button", { name: "导入" }));
    await waitFor(() => expect(window.location.hash).toBe("#/deals/7"));
  });
});
