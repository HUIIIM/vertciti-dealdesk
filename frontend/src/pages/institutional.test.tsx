// 机构级赛道前端：日期 / WALT 工具函数、PDF 租约行转租约；交易页三张机构页用真实引擎输出（inst-fixture.json）渲染。
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "@/App";
import { ToastHost } from "@/components/ui";
import { blankInputs, fieldLabel, trackLabel } from "@/domain/fields";
import fixtures from "@/test/fixtures.json";
import inst from "@/test/inst-fixture.json";
import { calls, override } from "@/test/server";
import { monthLabel, tenantsToLeases, walt } from "./deal/InstTabs";

const FX = fixtures as unknown as Record<string, [number, unknown]>;

/** 把 1 号交易的录制响应克隆成 9 号机构级交易：赛道、版本输入、试算结果换成机构引擎的真实输出。 */
function seedInstitutionalDeal(): void {
  for (const [key, [status, body]] of Object.entries(FX)) {
    if (!key.includes("/api/v2/deals/1")) continue;
    override(key.replace("/api/v2/deals/1", "/api/v2/deals/9"), status, JSON.parse(JSON.stringify(body).replaceAll('"deal_id":1', '"deal_id":9')));
  }
  const ov = JSON.parse(JSON.stringify(FX["GET /api/v2/deals/1"]![1])) as { deal: Record<string, unknown>; version: Record<string, unknown>; metrics: unknown };
  ov.deal = { ...ov.deal, id: 9, track: "institutional", name: "Suburban Office" };
  ov.version = { ...ov.version, deal_id: 9, inputs: inst.inputs, outputs: inst.preview };
  ov.metrics = inst.preview.metrics;
  override("GET /api/v2/deals/9", 200, ov);
  override("GET /api/v2/deals/9/versions/2", 200, ov.version);
  override("POST /api/v2/model/institutional", 200, inst.preview);
  override("GET /api/v2/catalog", 200, inst.catalog);  // 含机构级赛道的指标与默认淘汰条件
}
const at = (hash: string) => { window.location.hash = hash; return render(<ToastHost><App /></ToastHost>); };

describe("机构级工具函数", () => {
  it("月下标 → 年月；WALT 按面积加权；PDF 租约行按市场租期估起止", () => {
    expect(monthLabel("2026-01", 0)).toBe("2026-01");
    expect(monthLabel("2026-11", 3)).toBe("2027-02");
    expect(walt([{ sf: 100, end: "2026-12" }, { sf: 300, end: "2030-12" }], "2026-01")).toBeCloseTo((100 * 12 + 300 * 60) / 400 / 12);
    expect(walt([], "2026-01")).toBeNull();
    const ls = tenantsToLeases([{ suite: "2", tenant: "Cafe", sf: 1200, monthly_rent: 5000 }], { analysis_start: "2026-01", market: { lease_term_years: 5 } });
    expect(ls[0]).toMatchObject({ tenant: "Cafe", start: "2026-01", end: "2030-12", rent_psf_yr: 50, recovery: "nnn" });
    expect(trackLabel("institutional")).toBe("机构级");
    expect(fieldLabel("leases.0.rent_psf_yr")).toBe("第 1 份租约 · 租金 $/SF");
    expect(blankInputs("institutional", "", "", 5e6)).toMatchObject({ purchase_price: 5e6, hold_years: 7 });
  });
});

describe("机构级交易页", () => {
  it("租金表：逐份租约、WALT、到期续租假设；改租金进草稿并触发重算", async () => {
    seedInstitutionalDeal();
    at("#/deals/9/rentroll");
    expect(await screen.findByRole("heading", { name: "租约（逐份）" }, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.getByLabelText("第 1 份租约租户")).toHaveValue("Northwind Legal");
    expect(screen.getByText("WALT")).toBeInTheDocument();
    const roll = screen.getByRole("region", { name: "到期续租假设" });
    expect((await within(roll).findAllByText(/Contoso Health/, undefined, { timeout: 3000 })).length).toBeGreaterThan(0);
    const rent = screen.getByLabelText("第 2 份租约租金");
    fireEvent.focus(rent); fireEvent.change(rent, { target: { value: "36" } }); fireEvent.blur(rent);
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/api/v2/model/institutional"
      && (c.body as { leases: { rent_psf_yr: number }[] }).leases[1]!.rent_psf_yr === 36)).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "+ 加租约" }));
    expect(screen.getByLabelText("第 4 份租约租户")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("删除第 4 份租约"));
    expect(screen.queryByLabelText("第 4 份租约租户")).toBeNull();
  });
  it("市场与费用页、模型页：逐年现金流、退出、瀑布、SOFR 曲线与档位编辑", async () => {
    seedInstitutionalDeal();
    at("#/deals/9/t12");
    expect(await screen.findByRole("heading", { name: "市场租赁假设（MLA）" }, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "市场与费用" })).toBeInTheDocument();
    await act(async () => { window.location.hash = "#/deals/9/model"; window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(await screen.findByRole("heading", { name: "逐年现金流（$）" })).toBeInTheDocument();
    expect(screen.getByText("有效总收入 EGR")).toBeInTheDocument();
    expect(screen.getByText(/LP IRR 15\.64%/)).toBeInTheDocument();
    const curve = screen.getByLabelText("SOFR 曲线");
    fireEvent.change(curve, { target: { value: "4, 3.5" } }); fireEvent.blur(curve);
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/api/v2/model/institutional"
      && JSON.stringify((c.body as { debt: { sofr_curve_pct: number[] } }).debt.sofr_curve_pct) === "[4,3.5]")).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "+ 加一档" }));
    expect(screen.getByLabelText("第 3 档门槛")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("删除第 3 档"));
    expect(screen.queryByLabelText("第 3 档门槛")).toBeNull();
  });
  it("导出卡给出机构投委会备忘录与带公式的 Excel", async () => {
    seedInstitutionalDeal();
    at("#/deals/9");
    expect(await screen.findByRole("button", { name: "机构投委会备忘录 PDF" }, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "承销模型 Excel（带公式）" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "一页纸 Tear Sheet" })).toBeNull();
  });
});
