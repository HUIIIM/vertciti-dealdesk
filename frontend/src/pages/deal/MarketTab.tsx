// 市场与可比（CoStar / Reonomy 学来的布局）：可比成交表 + 价格/距离散点、产权穿透、卖方动机分。
// 依赖外部数据源（TopHap 等）：按需拉取，失败诚实降级并说明原因，绝不编数字。
import { T } from "@/i18n";
import { useState } from "react";
import { rawJson } from "@/api/client";
import { Empty, ErrorBox, NumCell, Skeleton, Status } from "@/components/ui";
import { fmtShort } from "@/lib/format";
import { useDeal } from "./Deal";

interface Comp { address: string; price: number; sf: number | null; sale_date: string; distance_miles: number | null; source: string }
interface CompsOut { ok: boolean; rows?: Comp[]; error?: string; source?: string; fetched_at?: string; note?: string }
interface TreeNode { id: string; level: number; display: string; confidence: string; relation: string; sources: { source: string }[] }
interface TreeOut { ok: boolean; owner_resolved: boolean; nodes: TreeNode[]; caveats: string[] }
interface Signal { id: string; label: string; status: string; earned: number; points: number; value: string; source: string }
interface SellOut { ok: boolean; score: number; max_score: number; tier_note: string; signals: Signal[]; caveats: string[] }
interface Mention { title: string; url: string; source: string; published_at: string | null }
interface EvDim { dim: string; label: string; query: string; items: Mention[]; error?: string }
interface EvidenceOut { ok: boolean; reason?: string; source?: string; window?: string; dims: EvDim[] }

const DIM_LABEL: Record<string, string> = {
  supply: T("供给"), demand: T("需求"), vacancy: T("空置率"), rent_trend: T("租金趋势"), population: T("人口"), employment: T("就业"),
};

/** City guess for the EchoWatch query: "123 Main St, Tampa, FL 33602" -> "Tampa"; "39-09 Main St Flushing NY 11354" -> "Flushing". */
export function guessArea(address: string): string {
  const parts = address.split(",").map((p) => p.trim()).filter(Boolean);
  if (parts.length >= 3) return parts[parts.length - 2] ?? "";
  const m = address.match(/([A-Za-z][A-Za-z .'-]*?)\s+[A-Z]{2}\s+\d{5}/);
  if (!m?.[1]) return "";
  const words = m[1].trim().split(/\s+/);
  return words[words.length - 1] ?? "";
}

function useOnDemand<T>(fn: () => Promise<T>) {
  const [st, set] = useState<{ data?: T; error?: Error; loading: boolean }>({ loading: false });
  const run = async () => { set({ loading: true }); try { set({ data: await fn(), loading: false }); } catch (e) { set({ error: e as Error, loading: false }); } };
  return { ...st, run };
}

export function MarketTab() {
  const { ov } = useDeal();
  const addr = ov.deal.address;
  const comps = useOnDemand(() => rawJson<CompsOut>("/api/wb/comps/pull", { address: addr }));
  const tree = useOnDemand(() => rawJson<TreeOut>("/api/wb/ownership/tree", { address: addr }));
  const sell = useOnDemand(() => rawJson<SellOut>("/api/wb/sell-readiness/score", { address: addr }));
  const [area, setArea] = useState(() => guessArea(addr ?? ""));
  const ev = useOnDemand(() => rawJson<EvidenceOut>(`/api/wb/research/evidence?area=${encodeURIComponent(area.slice(0, 120))}`));
  if (!addr) return <Empty title={T("先填地址")}>{T("市场数据按地址检索。")}</Empty>;
  const rows = comps.data?.rows ?? [];
  return (
    <>
      <section className="card" aria-label={T("可比成交")}>
        <div className="row" style={{ justifyContent: "space-between" }}><h2 style={{ margin: 0 }}>{T("可比成交")}</h2>
          <span className="row"><a className="btn ghost sm" href={`https://www.openstreetmap.org/search?query=${encodeURIComponent(addr)}`} target="_blank" rel="noopener noreferrer">{T("在地图中查看 ↗")}</a>
            <button className="btn sm primary" type="button" onClick={comps.run} disabled={comps.loading}>{comps.loading ? T("拉取中…") : T("拉取可比成交")}</button></span></div>
        <p className="sub">{T("来源：TopHap 公共记录（recorded sales）。未启用或额度用尽时如实显示原因。")}</p>
        {comps.loading ? <Skeleton rows={4} /> : null}
        {comps.error ? <ErrorBox error={comps.error} /> : null}
        {comps.data && !comps.data.ok ? <div className="banner warn">{T("没拉到：")}{comps.data.error}{T("。这不是“没有可比成交”，是数据源暂不可用；可在“文件与证据”里手动登记可比。")}</div> : null}
        {rows.length ? (<>
          <CompsPlot rows={rows} />
          <div className="table-wrap"><table className="t"><thead><tr><th scope="col">{T("地址")}</th><th scope="col">{T("成交日")}</th><th scope="col" className="num">{T("成交价")}<span className="unit">{T("（$）")}</span></th>
            <th scope="col" className="num">{T("面积")}<span className="unit">{T("（SF）")}</span></th><th scope="col" className="num">$/SF</th><th scope="col" className="num">{T("距离")}<span className="unit">{T("（英里）")}</span></th><th scope="col">{T("来源")}</th></tr></thead>
            <tbody>{rows.map((c, i) => <tr key={i}><td>{c.address}</td><td>{c.sale_date}</td><NumCell v={c.price} unit="usd" /><NumCell v={c.sf} unit="int" />
              <NumCell v={c.sf ? c.price / c.sf : null} unit="usd" /><NumCell v={c.distance_miles} unit="x" /><td className="muted">{c.source}</td></tr>)}</tbody></table></div></>) : null}
      </section>
      <section className="card" aria-label={T("舆情证据")}>
        <div className="row" style={{ justifyContent: "space-between" }}><h2 style={{ margin: 0 }}>{T("舆情证据（EchoWatch）")}</h2>
          <span className="row"><input aria-label={T("检索区域")} value={area} onChange={(e) => setArea(e.target.value)} placeholder={T("城市，如 Tampa")} style={{ width: 160 }} />
            <button className="btn sm" type="button" onClick={ev.run} disabled={ev.loading || !area.trim()}>{ev.loading ? T("拉取中…") : T("拉取证据")}</button></span></div>
        <p className="sub">{T("按区域检索近 30 天带出处的公开提及：供给 / 需求 / 空置 / 租金 / 人口 / 就业。提及确实存在，但不等于它说的数字已核实——引用前请点开原文。")}</p>
        {ev.loading ? <Skeleton rows={3} /> : null}
        {ev.error ? <ErrorBox error={ev.error} /> : null}
        {ev.data && !ev.data.ok ? <div className="banner warn">{T("没拉到：")}{ev.data.reason}{T("。未覆盖的维度请手动登记，不要猜。")}</div> : null}
        {ev.data?.dims.length ? (<ul className="checks">{ev.data.dims.map((d) => <li key={d.dim}>
          <Status s={d.items.length ? "verified" : "planned"}>{DIM_LABEL[d.dim] ?? d.dim}</Status>
          <span>{d.items.length ? d.items.map((m) => <div key={m.url}><a href={m.url} target="_blank" rel="noopener noreferrer">{m.title || m.url}</a>
            <div className="d">{m.source}{m.published_at ? ` · ${m.published_at.slice(0, 10)}` : ""}</div></div>)
            : <span className="muted">{d.error ?? T("无匹配提及")}</span>}<div className="d">{T("检索：")}{d.query}</div></span></li>)}</ul>) : null}
        {ev.data?.source ? <p className="sub">{T("来源：")}{ev.data.source}</p> : null}
      </section>
      <div className="split">
        <section className="card" aria-label={T("产权穿透")}>
          <div className="row" style={{ justifyContent: "space-between" }}><h2 style={{ margin: 0 }}>{T("产权与业主")}</h2>
            <button className="btn sm" type="button" onClick={tree.run} disabled={tree.loading}>{tree.loading ? T("穿透中…") : T("穿透产权")}</button></div>
          <p className="sub">{T("LLC → 真实决策人；推断节点一律标“待验证”。")}</p>
          {tree.error ? <ErrorBox error={tree.error} /> : null}
          {tree.data ? (<ul className="checks">{tree.data.nodes.map((n) => <li key={n.id} style={{ paddingLeft: n.level * 16 }}>
            <Status s={n.confidence === "verified" ? "verified" : "building"}>{n.confidence === "verified" ? T("已验证") : T("待验证")}</Status>
            <span>{n.display}<div className="d">{n.relation} · {n.sources.map((s) => s.source).join(T("、"))}</div></span></li>)}
            {tree.data.caveats.map((c) => <li key={c}><Status s="planned">{T("说明")}</Status><span className="muted">{c}</span></li>)}</ul>) : null}
        </section>
        <section className="card" aria-label={T("卖方动机")}>
          <div className="row" style={{ justifyContent: "space-between" }}><h2 style={{ margin: 0 }}>{T("卖方动机分")}</h2>
            <button className="btn sm" type="button" onClick={sell.run} disabled={sell.loading}>{sell.loading ? T("计算中…") : T("计算")}</button></div>
          <p className="sub">{T("规则分（非黑箱）：持有年限、贷款到期、再融资、留置权、区域热度；无数据的信号不计分。")}</p>
          {sell.error ? <ErrorBox error={sell.error} /> : null}
          {sell.data ? (<><p><strong style={{ fontSize: 28, fontWeight: 300 }}>{sell.data.score}</strong> / {sell.data.max_score} · {sell.data.tier_note}</p>
            <ul className="checks">{sell.data.signals.map((s) => <li key={s.id}><Status s={s.status === "hit" ? "verified" : s.status === "unavailable" ? "planned" : "building"}>
              {s.status === "hit" ? `+${s.earned}` : s.status === "unavailable" ? T("无数据") : T("未命中")}</Status><span>{s.label}<div className="d">{s.value} · {s.source}</div></span></li>)}</ul></>) : null}
        </section>
      </div>
    </>
  );
}

function CompsPlot({ rows }: { rows: Comp[] }) {
  const pts = rows.filter((r) => r.sf && r.distance_miles != null).map((r) => ({ x: r.distance_miles!, y: r.price / r.sf!, r }));
  if (pts.length < 2) return null;
  const W = 760, H = 220, P = 40, mx = Math.max(...pts.map((p) => p.x)) || 1, ys = pts.map((p) => p.y), lo = Math.min(...ys), hi = Math.max(...ys);
  const X = (x: number) => P + (x / mx) * (W - P * 2), Y = (y: number) => H - P - ((y - lo) / (hi - lo || 1)) * (H - P * 2);
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={T("可比成交：$/SF 与距离")}>
      <line className="axis" x1={P} x2={W - P} y1={H - P} y2={H - P} /><line className="axis" x1={P} x2={P} y1={P} y2={H - P} />
      <text x={W / 2} y={H - 8} textAnchor="middle">{T("距离（英里）")}</text><text x={8} y={P - 12}>$/SF</text>
      <text x={P} y={H - P + 14}>0</text><text x={W - P} y={H - P + 14} textAnchor="end">{mx.toFixed(1)}</text>
      <text x={P - 4} y={Y(hi)} textAnchor="end">{fmtShort(hi).replace("$", "")}</text><text x={P - 4} y={Y(lo)} textAnchor="end">{fmtShort(lo).replace("$", "")}</text>
      {pts.map((p, i) => <rect key={i} x={X(p.x) - 4} y={Y(p.y) - 4} width={8} height={8} className="base"><title>{T("{0}：${1}/SF，{2} 英里", [p.r.address, p.y.toFixed(0), p.x])}</title></rect>)}
    </svg>
  );
}
