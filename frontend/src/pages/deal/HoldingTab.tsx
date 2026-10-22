// 持有期（Juniper Square / Yardi 式）：录实际数、实际 vs 承销偏差，以及 vertciti 独有的事后归因复盘。
import { T } from "@/i18n";
import { useState } from "react";
import { api, ApiError, call } from "@/api/client";
import { useApi } from "@/api/useApi";
import { useApp } from "@/app-context";
import { Waterfall } from "@/components/Charts";
import { NumberInput } from "@/components/FieldInput";
import { Empty, ErrorBox, NumCell, Skeleton, useToast } from "@/components/ui";
import { fmt } from "@/lib/format";
import { useDeal } from "./Deal";

export function HoldingTab() {
  const { id, ov } = useDeal();
  const { can } = useApp();
  const toast = useToast();
  const hasV = Boolean(ov.version);
  const h = useApi(() => (hasV ? call(api.GET("/api/v2/deals/{deal_id}/holding", { params: { path: { deal_id: id } } })) : Promise.resolve(null)), [id, hasV]);
  const [row, setRow] = useState<{ period: string; noi: number | null; occupancy_pct: number | null; cash_flow: number | null }>({ period: String(new Date().getFullYear()), noi: null, occupancy_pct: null, cash_flow: null });
  if (!hasV) return <Empty title={T("还没有承销版本")} />;
  const save = async () => {
    try { await call(api.PUT("/api/v2/deals/{deal_id}/actuals", { params: { path: { deal_id: id } }, body: row })); toast.ok(T("已录入 {0}", [row.period])); await h.reload(); }
    catch (e) { toast.err(e instanceof ApiError ? e : new Error(String(e))); }
  };
  const a = h.data?.attribution;
  return (
    <>
      {ov.deal.stage !== "holding" ? <div className="banner">{T("交易尚未进入持有期；可以先录入以试算，正式复盘以 BUY 决策时冻结的版本为基准。")}</div> : null}
      {h.error ? <ErrorBox error={h.error} /> : null}
      {!h.data ? <Skeleton /> : (<>
        <section className="card" aria-label={T("事后归因")}>
          <h2>{T("事后归因复盘：当时错在哪条假设")}</h2>
          <p className="sub">{T("对照基准：第")}{" "}{h.data.basis.version_no} {" "}{T("版 ·")}{" "}{h.data.basis.run_id}{h.data.basis.from_buy_decision ? T("（BUY 决策时冻结）") : T("（当前版，尚无 BUY 决策）")}</p>
          {a?.available && a.steps ? (<>
            <Waterfall label="IRR" start={a.underwritten ?? 0} end={a.actual_implied ?? 0} steps={a.steps.map((s) => ({ label: s.label, v: s.contribution_pct_points ?? 0 }))} />
            <p>{T("承销 IRR")}{" "}{fmt(a.underwritten, "pct")} {" "}{T("→ 按实际推算")}{" "}{fmt(a.actual_implied, "pct")}{T("，合计偏差")}{" "}<strong className={(a.total_pct_points ?? 0) < 0 ? "neg" : undefined}>{fmt(a.total_pct_points, "pct")}</strong>{T("（百分点）。")}</p>
            <p className="muted" style={{ fontSize: 13 }}>{a.note}</p></>) : <p className="muted">{a?.reason}</p>}
        </section>
        <section className="card" aria-label={T("偏差表")}>
          <h2>{T("实际 vs 承销")}</h2>
          <div className="table-wrap" style={{ maxHeight: "none" }}><table className="t"><thead><tr><th scope="col">{T("期间")}</th><th scope="col" className="num">{T("实际 NOI")}<span className="unit">{T("（$）")}</span></th>
            <th scope="col" className="num">{T("承销 NOI")}<span className="unit">{T("（$）")}</span></th><th scope="col" className="num">{T("偏差")}<span className="unit">{T("（$）")}</span></th><th scope="col" className="num">{T("偏差")}<span className="unit">{T("（%）")}</span></th>
            <th scope="col" className="num">{T("出租率")}<span className="unit">{T("（%）")}</span></th></tr></thead>
            <tbody>{h.data.variance.map((v) => <tr key={v.period}><td>{v.period}{T("（第")}{" "}{v.year} {" "}{T("年）")}</td><NumCell v={v.noi.actual} unit="usd" /><NumCell v={v.noi.underwritten} unit="usd" />
              <NumCell v={v.noi.variance} unit="usd" /><NumCell v={v.noi.variance_pct} unit="pct" /><NumCell v={v.occupancy_pct} unit="pct" /></tr>)}
              {h.data.variance.length === 0 ? <tr><td colSpan={6} className="muted">{T("还没有实际数。")}</td></tr> : null}</tbody></table></div>
          {can("holding.write") ? (
            <form className="row" style={{ marginTop: 12, alignItems: "end" }} onSubmit={(e) => { e.preventDefault(); void save(); }}>
              <label className="field" style={{ width: 120 }}>{T("期间")}<input className="input" value={row.period} onChange={(e) => setRow({ ...row, period: e.target.value })} pattern="\d{4}(-\d{2})?" required /></label>
              <label className="field" style={{ width: 170 }}>{T("实际 NOI（$）")}<NumberInput value={row.noi} unit="usd" label={T("实际 NOI")} onChange={(v) => setRow({ ...row, noi: v })} /></label>
              <label className="field" style={{ width: 130 }}>{T("出租率（%）")}<NumberInput value={row.occupancy_pct} unit="pct" label={T("出租率")} onChange={(v) => setRow({ ...row, occupancy_pct: v })} /></label>
              <label className="field" style={{ width: 170 }}>{T("净现金流（$）")}<NumberInput value={row.cash_flow} unit="usd" label={T("净现金流")} onChange={(v) => setRow({ ...row, cash_flow: v })} /></label>
              <button className="btn primary" type="submit">{T("录入")}</button></form>) : null}
        </section></>)}
    </>
  );
}
