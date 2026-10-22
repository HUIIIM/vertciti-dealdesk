// T12：历史（在手）与预测（pro forma）两列并排；收入 → 空置 → 费用 → NOI，实时重算。
import { T } from "@/i18n";
import { FieldInput, NumberInput } from "@/components/FieldInput";
import { passportStatus } from "@/components/Passport";
import { NumCell } from "@/components/ui";
import { COM_BELOW_LINE, COM_EXPENSES, COM_INCOME, RES_EXPENSES } from "@/domain/fields";
import { getPath } from "@/lib/paths";
import { useDeal } from "./Deal";

export function T12Tab() {
  const { track, draft, set, preview, passports, openPassport } = useDeal();
  if (track === "residential") {
    return (
      <section className="card"><h2>{T("运营费用")}</h2>
        <div className="grid-form">{RES_EXPENSES.map((f) => <FieldInput key={f.path} spec={f} value={getPath(draft, f.path)} onChange={(v) => set(f.path, v)}
          onPassport={(p) => openPassport(p, f.label)} passportState={passportStatus(passports[f.path])} />)}</div></section>);
  }
  const c = (preview?.detail as { compute?: Record<string, Record<string, number>> })?.compute ?? {};
  const h = c.historical ?? {}, p = c.proforma ?? {};
  const line = (k: string, label: string) => (
    <tr key={k}><th scope="row" style={{ fontWeight: 600 }}>{label}
      <button type="button" className="btn ghost sm" style={{ minHeight: 22, padding: "0 4px", marginLeft: 6 }} aria-label={T("{0} 预测值的数字护照", [label])}
        onClick={() => openPassport(`proforma.${k}`, T("{0}（预测）", [label]))}><span className={`status ${passportStatus(passports[`proforma.${k}`])}`} style={{ padding: "0 4px" }}><i aria-hidden="true" />{T("源")}</span></button></th>
      <td className="cell-input"><NumberInput value={getPath(draft, `historical.${k}`)} unit="usd" label={T("{0} 历史", [label])} onChange={(v) => set(`historical.${k}`, v ?? 0)} /></td>
      <td className="cell-input"><NumberInput value={getPath(draft, `proforma.${k}`)} unit="usd" label={T("{0} 预测", [label])} onChange={(v) => set(`proforma.${k}`, v ?? 0)} /></td></tr>);
  return (
    <section className="card">
      <h2>{T("T12 · 现金流")}</h2><p className="sub">{T("左“历史”= 在手口径，右“预测”= pro forma；NOI、EGI 等合计由引擎实时算出。")}</p>
      <div className="table-wrap" style={{ maxHeight: "none" }}>
        <table className="t">
          <thead><tr><th scope="col">{T("科目")}</th><th scope="col" className="num">{T("历史")}<span className="unit">{T("（$/年）")}</span></th><th scope="col" className="num">{T("预测")}<span className="unit">{T("（$/年）")}</span></th></tr></thead>
          <tbody>
            <tr className="total"><td>{T("基础租金（来自租金表）")}</td><NumCell v={h.base_rents ?? null} unit="usd" /><NumCell v={p.base_rents ?? null} unit="usd" /></tr>
            {COM_INCOME.map(([k, l]) => line(k, l))}
            <tr><th scope="row" style={{ fontWeight: 600 }}>{T("空置率（%）")}</th>
              <td className="cell-input"><NumberInput value={getPath(draft, "historical.vacancy_pct")} unit="pct" label={T("历史空置率")} onChange={(v) => set("historical.vacancy_pct", v ?? 0)} /></td>
              <td className="cell-input"><NumberInput value={getPath(draft, "proforma.vacancy_pct")} unit="pct" label={T("预测空置率")} onChange={(v) => set("proforma.vacancy_pct", v ?? 0)} /></td></tr>
            <tr className="total"><td>{T("有效总收入 EGI")}</td><NumCell v={h.egi ?? null} unit="usd" /><NumCell v={p.egi ?? null} unit="usd" /></tr>
            {COM_EXPENSES.map(([k, l]) => line(k, l))}
            <tr className="total"><td>{T("总费用")}</td><NumCell v={h.total_expenses ?? null} unit="usd" /><NumCell v={p.total_expenses ?? null} unit="usd" /></tr>
            <tr className="total"><td>NOI</td><NumCell v={h.noi ?? null} unit="usd" /><NumCell v={p.noi ?? null} unit="usd" /></tr>
            {COM_BELOW_LINE.map(([k, l]) => line(k, l))}
            <tr className="total"><td>{T("可用于还贷现金流")}</td><NumCell v={h.cash_flow_avail ?? null} unit="usd" /><NumCell v={p.cash_flow_avail ?? null} unit="usd" /></tr>
          </tbody>
        </table>
      </div>
    </section>
  );
}
