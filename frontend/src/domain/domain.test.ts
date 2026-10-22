import { describe, expect, it } from "vitest";
import { blankInputs, fieldLabel, STAGE_LABEL } from "./fields";
import { toFilters } from "@/pages/Pipeline";

describe("fields", () => {
  it("模板带入名称地址要价", () => {
    const c = blankInputs("commercial", "A", "B", 1000) as { analysis: { purchase_price: number }; property: { name: string } };
    expect(c.analysis.purchase_price).toBe(1000);
    expect(c.property.name).toBe("A");
    const r = blankInputs("residential", "", "", 500) as { price: number; risk_flags: unknown[] };
    expect(r.price).toBe(500);
    expect(r.risk_flags).toEqual([]);
    expect((blankInputs("residential") as { price: number }).price).toBe(0);
  });
  it("路径转中文标签，不露内部字段名", () => {
    expect(fieldLabel("analysis.exit_cap_rate")).toBe("退出 Cap Rate");
    expect(fieldLabel("proforma.property_tax")).toBe("房产税（预测）");
    expect(fieldLabel("tenants.*.monthly_rent")).toContain("租金水平");
    expect(fieldLabel("tenants.2.sf")).toBe("第 3 户 · 面积");
    expect(fieldLabel("unknown.path")).toBe("unknown.path");
    expect(STAGE_LABEL.passed).toBe("已放弃");
  });
  it("保存视图的任意 JSON 被逐字段收窄", () => {
    expect(toFilters({ track: "commercial", q: "x", kill: "clear", view: "table" })).toEqual({ filters: { track: "commercial", q: "x", kill: "clear" }, view: "table" });
    expect(toFilters({ track: "hotel", q: 5, kill: "nope", view: 1 })).toEqual({ filters: { track: "", q: "", kill: "" }, view: null });
  });
});
