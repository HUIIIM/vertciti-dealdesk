// 比较页：2–4 笔交易并排；每行最优者标绿（按指标“越高越好 / 越低越好”）。
import { api, call } from "@/api/client";
import { useApi } from "@/api/useApi";
import { useApp } from "@/app-context";
import { Empty, ErrorBox, Skeleton, Status } from "@/components/ui";
import { fmtCell, isNeg, unitSuffix, type Unit } from "@/lib/format";
import { navigate } from "@/lib/router";

export function Compare({ ids }: { ids: number[] }) {
  const { catalog } = useApp();
  const all = useApi(() => call(api.GET("/api/v2/deals")), []);
  const cmp = useApi(() => (ids.length >= 2 ? call(api.GET("/api/v2/compare", { params: { query: { ids: ids.join(",") } } })) : Promise.resolve(null)), [ids.join(",")]);
  const toggle = (id: number) => {
    const next = ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id].slice(-4);
    navigate({ name: "compare", ids: next });
  };
  return (
    <>
      <div className="page-head"><div><p className="eyebrow">比较</p><h1>交易并排</h1></div></div>
      <section className="card flat" aria-label="选择交易">
        <p className="sub">选 2–4 笔（超过 4 笔自动替换最早选的）。</p>
        <div className="row">{(all.data ?? []).map((d) => <label key={d.id} className="chip" style={{ cursor: "pointer", minHeight: 32 }}>
          <input type="checkbox" checked={ids.includes(d.id)} onChange={() => toggle(d.id)} /> {d.name}</label>)}</div>
      </section>
      {cmp.error ? <ErrorBox error={cmp.error} /> : null}
      {ids.length < 2 ? <Empty title="至少选 2 笔交易" /> : !cmp.data ? <Skeleton rows={6} /> : (
        <div className="table-wrap" style={{ maxHeight: "none" }}>
          <table className="t">
            <thead><tr><th scope="col">指标</th>{cmp.data.deals.map((x) => <th key={x.deal.id} scope="col" className="num">
              <a href={`#/deals/${x.deal.id}`} className="rowlink">{x.deal.name}</a><div className="muted" style={{ fontWeight: 400 }}>{x.deal.stage_label}</div></th>)}</tr></thead>
            <tbody>
              {Object.entries(catalog.metrics).map(([k, meta]) => (
                <tr key={k}><th scope="row" style={{ fontWeight: 600 }}>{meta.label}{unitSuffix(meta.unit as Unit) ? <span className="muted">（{unitSuffix(meta.unit as Unit)}）</span> : null}</th>
                  {cmp.data!.deals.map((x) => { const v = x.metrics[k]; const best = cmp.data!.best[k] === x.deal.id;
                    return <td key={x.deal.id} className={`num${isNeg(v) ? " neg" : ""}`} style={best ? { boxShadow: "inset 4px 0 0 var(--ok)", fontWeight: 800 } : undefined}
                      aria-label={best ? `${fmtCell(v, meta.unit as Unit)}（最优）` : undefined}>{fmtCell(v, meta.unit as Unit)}</td>; })}</tr>))}
              <tr><th scope="row">淘汰条件</th>{cmp.data.deals.map((x) => <td key={x.deal.id} className="num">{!x.kill ? "—" : x.kill.triggered.length
                ? <Status s="risk">触发 {x.kill.triggered.length}</Status> : x.kill.unknown.length ? <Status s="building">未知</Status> : <Status s="verified">未触发</Status>}</td>)}</tr>
            </tbody>
          </table>
        </div>)}
    </>
  );
}
