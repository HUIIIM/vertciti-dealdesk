// 租金表：商业逐租户（面积、月租、承销年租），合计与出租率实时算；住宅为收入字段。
import { T } from "@/i18n";
import { useRef } from "react";
import { raw } from "@/api/client";
import { FieldInput, NumberInput } from "@/components/FieldInput";
import { passportStatus } from "@/components/Passport";
import { NumCell, useToast } from "@/components/ui";
import { saveResponse } from "@/lib/download";
import { RES_INCOME } from "@/domain/fields";
import { getPath } from "@/lib/paths";
import { useDeal } from "./Deal";

interface Tenant { suite?: string; tenant?: string; sf?: number; monthly_rent?: number; underwritten_annual?: number | null }

export function RentRollTab() {
  const { track, draft, set, preview, passports, openPassport } = useDeal();
  const toast = useToast();
  const xf = useRef<HTMLInputElement>(null);
  if (track === "residential") {
    return (
      <section className="card"><h2>{T("租金与收入")}</h2>
        <div className="grid-form">{RES_INCOME.map((f) => <FieldInput key={f.path} spec={f} value={getPath(draft, f.path)} onChange={(v) => set(f.path, v)}
          onPassport={(p) => openPassport(p, f.label)} passportState={passportStatus(passports[f.path])} />)}</div></section>);
  }
  const tenants = (draft.tenants as Tenant[] | undefined) ?? [];
  const rr = ((preview?.detail as { compute?: { rent_roll?: Record<string, number> } })?.compute?.rent_roll) ?? {};
  const totSf = tenants.reduce((a, t) => a + (t.sf ?? 0), 0);
  const totM = tenants.reduce((a, t) => a + (t.monthly_rent ?? 0), 0);
  const upd = (i: number, k: keyof Tenant, v: unknown) => set(`tenants.${i}.${k}`, v);
  const template = async () => {
    try { await saveResponse(await raw("/api/uw/rentroll/template.xlsx"), "dealdesk_rentroll_template.xlsx"); } catch (e) { toast.err(e); }
  };
  const importXlsx = async (f: File) => {
    const fd = new FormData(); fd.append("file", f);
    try {
      const r = await (await raw("/api/uw/rentroll/parse", { method: "POST", body: fd })).json() as { tenants: Tenant[]; skipped_example?: number; bad_dates?: number };
      if (!r.tenants.length) { toast.err(T("表里没有租户行（示例行已跳过）")); return; }
      if (tenants.length && !window.confirm(T("用表里的 {0} 个租户替换当前 {1} 行？", [r.tenants.length, tenants.length]))) return;
      set("tenants", r.tenants);
      toast.ok(T("已导入 {0} 个租户", [r.tenants.length]) + (r.bad_dates ? T("；{0} 行日期没认出来，已留空", [r.bad_dates]) : ""));
    } catch (e) { toast.err(e); }
  };
  return (
    <section className="card">
      <div className="row" style={{ justifyContent: "space-between" }}><h2 style={{ margin: 0 }}>{T("租金表")}</h2>
        <div className="row">
          <button className="btn ghost sm" type="button" onClick={() => void template()}>{T("下载 Excel 模板")}</button>
          <input ref={xf} type="file" accept=".xlsx" className="sr-only" aria-label={T("选择租金表 Excel")} onChange={(e) => { const f = e.target.files?.[0]; if (f) void importXlsx(f); e.target.value = ""; }} />
          <button className="btn sm" type="button" onClick={() => xf.current?.click()}>{T("从 Excel 导入")}</button>
          <button className="btn sm" type="button" onClick={() => set("tenants", [...tenants, { suite: String(tenants.length + 1), tenant: "", sf: 0, monthly_rent: 0 }])}>{T("+ 加租户")}</button></div></div>
      <p className="sub">{T("年租 = 月租 × 12；承销年租留空则按合同口径。数字旁“源”可登记来源（租约、租金表第几页）。")}</p>
      <div className="table-wrap" style={{ maxHeight: "none" }}>
        <table className="t">
          <thead><tr><th scope="col">{T("单元")}</th><th scope="col">{T("租户")}</th><th scope="col" className="num">{T("面积")}<span className="unit">{T("（SF）")}</span></th>
            <th scope="col" className="num">{T("月租")}<span className="unit">{T("（$）")}</span></th><th scope="col" className="num">{T("年租")}<span className="unit">{T("（$）")}</span></th>
            <th scope="col" className="num">{T("$/SF/年")}</th><th scope="col" className="num">{T("承销年租")}<span className="unit">{T("（$）")}</span></th><th scope="col"><span className="sr-only">{T("操作")}</span></th></tr></thead>
          <tbody>
            {tenants.map((t, i) => (
              <tr key={i}>
                <td className="cell-input"><input className="input" value={t.suite ?? ""} aria-label={T("第 {0} 行单元", [i + 1])} onChange={(e) => upd(i, "suite", e.target.value)} style={{ width: 70 }} /></td>
                <td className="cell-input"><input className="input" value={t.tenant ?? ""} aria-label={T("第 {0} 行租户", [i + 1])} onChange={(e) => upd(i, "tenant", e.target.value)} /></td>
                <td className="cell-input"><NumberInput value={t.sf} unit="int" label={T("第 {0} 行面积", [i + 1])} onChange={(v) => upd(i, "sf", v ?? 0)} /></td>
                <td className="cell-input"><NumberInput value={t.monthly_rent} unit="usd" label={T("第 {0} 行月租", [i + 1])} onChange={(v) => upd(i, "monthly_rent", v ?? 0)} /></td>
                <NumCell v={(t.monthly_rent ?? 0) * 12} unit="usd" />
                <NumCell v={t.sf ? ((t.monthly_rent ?? 0) * 12) / t.sf : null} unit="x" />
                <td className="cell-input"><NumberInput value={t.underwritten_annual ?? undefined} unit="usd" label={T("第 {0} 行承销年租", [i + 1])} onChange={(v) => upd(i, "underwritten_annual", v)} /></td>
                <td><button className="btn ghost sm" type="button" aria-label={T("删除第 {0} 行", [i + 1])} onClick={() => set("tenants", tenants.filter((_, j) => j !== i))}>{T("删除")}</button></td>
              </tr>))}
            {tenants.length === 0 ? <tr><td colSpan={8} className="muted">{T("还没有租户。整栋空置或按估算收入，可只填 T12。")}</td></tr> : null}
          </tbody>
          <tfoot><tr className="total"><td>{T("合计")}</td><td>{tenants.length} {" "}{T("户")}</td><NumCell v={totSf} unit="int" /><NumCell v={totM} unit="usd" /><NumCell v={totM * 12} unit="usd" />
            <NumCell v={totSf ? (totM * 12) / totSf : null} unit="x" /><NumCell v={rr.total_annual_uw ?? null} unit="usd" /><td /></tr></tfoot>
        </table>
      </div>
      <div className="grid" style={{ marginTop: 16 }}>
        <FieldInput spec={{ path: "vacant_sf", label: T("空置面积"), unit: "int", hint: "SF" }} value={draft.vacant_sf} onChange={(v) => set("vacant_sf", v ?? 0)} />
        <div className="metric"><div className="k">{T("出租率（按面积）")}</div><div className="v">{typeof rr.occupancy === "number" ? `${(rr.occupancy * 100).toFixed(1)}%` : "—"}</div></div>
      </div>
    </section>
  );
}
