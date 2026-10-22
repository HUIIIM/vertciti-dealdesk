import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Ctx, type AppCtx } from "@/app-context";
import { Tornado, Waterfall } from "./Charts";
import { DataTable } from "./DataTable";
import { NumberInput } from "./FieldInput";
import { KillEditor } from "./KillEditor";
import { Dialog, Empty, ErrorBox, Metric, Status, ToastHost, useToast } from "./ui";
import { ApiError } from "@/api/client";

const catalog = { metrics: { dscr: { label: "DSCR", label_en: "DSCR", unit: "x", better: "higher" }, irr_pct: { label: "IRR", label_en: "IRR", unit: "pct", better: "higher" } },
  primary_metric: { commercial: "irr_pct" }, assumptions: {}, kill_criteria_defaults: {}, scenario_defaults: {} } as unknown as AppCtx["catalog"];
const ctx: AppCtx = { me: { username: "local", role: "chairman", role_label: "董事长", display_name: "本机", auth: false, permissions: [] }, catalog,
  can: () => true, refreshDeals: () => {}, dealsVersion: 0 };

describe("ui", () => {
  it("状态 = 颜色 + 图标 + 文字", () => {
    render(<Status s="risk" />);
    const el = screen.getByText("风险");
    expect(el.className).toContain("risk");
    expect(el.querySelector("i")).not.toBeNull();
  });
  it("指标卡：百万级紧凑显示、完整值进 title 与读屏、负数标红、可点开", () => {
    const onOpen = vi.fn();
    render(<Metric label="收购价" value={-36000000} unit="usd" onOpen={onOpen} />);
    const btn = screen.getByRole("button", { name: /收购价 \(\$36,000,000\)/ });
    expect(btn.textContent).toBe("($36.00M)");
    expect(btn.parentElement!.className).toContain("neg");
    fireEvent.click(btn);
    expect(onOpen).toHaveBeenCalled();
  });
  it("错误框带请求编号", () => {
    render(<ErrorBox error={new ApiError(500, "坏了", "rid-123")} onRetry={() => {}} />);
    expect(screen.getByRole("alert").textContent).toContain("rid-123");
    render(<Empty title="空的" />);
    expect(screen.getByText("空的")).toBeInTheDocument();
  });
  it("对话框：Esc 关闭、焦点落在首个输入框", () => {
    const onClose = vi.fn();
    render(<Dialog title="测试" onClose={onClose}><input aria-label="名称" /></Dialog>);
    expect(document.activeElement).toBe(screen.getByLabelText("名称"));
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });
  it("Toast 显示并带请求编号", () => {
    vi.useFakeTimers();
    function Btn() { const t = useToast(); return <button onClick={() => t.err(new ApiError(400, "不行", "abcdef1234"))}>go</button>; }
    render(<ToastHost><Btn /></ToastHost>);
    fireEvent.click(screen.getByText("go"));
    expect(screen.getByText(/不行（请求编号 abcdef12）/)).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(9000); });
    expect(screen.queryByText(/不行/)).toBeNull();
    vi.useRealTimers();
  });
});

describe("DataTable", () => {
  it("点表头排序、未知值排最后、负数括号", () => {
    const rows = [{ id: 1, n: "b", v: 2 }, { id: 2, n: "a", v: null }, { id: 3, n: "c", v: -1 }];
    render(<DataTable id="t" rows={rows} rowKey={(r) => r.id} columns={[
      { key: "n", header: "名", render: (r) => r.n, sortValue: (r) => r.n },
      { key: "v", header: "值", unit: "usd", render: (r) => String(r.v), sortValue: (r) => r.v }]} />);
    fireEvent.click(screen.getByRole("button", { name: /值/ }));
    const firstCol = () => screen.getAllByRole("row").slice(1).map((tr) => tr.firstChild!.textContent);
    expect(firstCol()).toEqual(["c", "b", "a"]);
    fireEvent.click(screen.getByRole("button", { name: /值/ }));
    expect(firstCol()).toEqual(["b", "c", "a"]);
    expect(screen.getByRole("columnheader", { name: /值/ }).getAttribute("aria-sort")).toBe("descending");
  });
});

describe("表单", () => {
  it("数字输入：编辑显示原值、失焦显示千分位", () => {
    const onChange = vi.fn();
    const { rerender } = render(<NumberInput value={4200000} unit="usd" label="价" onChange={onChange} />);
    const el = screen.getByLabelText("价") as HTMLInputElement;
    expect(el.value).toBe("4,200,000");
    fireEvent.focus(el);
    expect(el.value).toBe("4200000");
    fireEvent.change(el, { target: { value: "3,900,000" } });
    expect(onChange).toHaveBeenLastCalledWith(3900000);
    fireEvent.blur(el);
    rerender(<NumberInput value={3900000} unit="usd" label="价" onChange={onChange} />);
    expect(el.value).toBe("3,900,000");
  });
  it("淘汰条件编辑：增删改", () => {
    const onChange = vi.fn();
    render(<Ctx.Provider value={ctx}><KillEditor value={[{ metric: "dscr", op: "<", threshold: 1.25 }]} onChange={onChange} /></Ctx.Provider>);
    fireEvent.change(screen.getByLabelText("阈值"), { target: { value: "1.3" } });
    expect(onChange).toHaveBeenLastCalledWith([{ metric: "dscr", op: "<", threshold: 1.3 }]);
    fireEvent.click(screen.getByText("+ 加一条"));
    expect(onChange.mock.lastCall![0]).toHaveLength(2);
    fireEvent.click(screen.getByLabelText("删除这条"));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });
});

describe("图表", () => {
  it("龙卷风图：每个假设两根条、关键标注", () => {
    const rows = [{ key: "r", label: "租金", paths: [], source_hint: "", minus: { value: 1, delta_pct_points: -7 }, plus: { value: 15, delta_pct_points: 7 }, swing_bps: 700, material: true }];
    const { container } = render(<Tornado rows={rows} base={8} label="IRR" shock={10} />);
    expect(container.querySelectorAll("rect")).toHaveLength(2);
    expect(container.textContent).toContain("关键");
  });
  it("瀑布图首尾与各步", () => {
    const { container } = render(<Waterfall label="IRR" start={8} end={5} steps={[{ label: "出租率", v: -2 }, { label: "增长", v: -1 }]} />);
    expect(container.querySelectorAll("rect")).toHaveLength(4);
    expect(container.textContent).toContain("-2.00");
  });
});
