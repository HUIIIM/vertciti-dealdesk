// 市场与可比（CoStar / Reonomy 学来的布局）：可比成交表 + 价格/距离散点、产权穿透、卖方动机分。
// 依赖外部数据源（TopHap 等）：按需拉取，失败诚实降级并说明原因，绝不编数字。
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
  if (!addr) return <Empty title="先填地址">市场数据按地址检索。</Empty>;
  const rows = comps.data?.rows ?? [];
  return (
    <>
      <section className="card" aria-label="可比成交">
        <div className="row" style={{ justifyContent: "space-between" }}><h2 style={{ margin: 0 }}>可比成交</h2>
          <span className="row"><a className="btn ghost sm" href={`https://www.openstreetmap.org/search?query=${encodeURIComponent(addr)}`} target="_blank" rel="noopener noreferrer">在地图中查看 ↗</a>
            <button className="btn sm primary" type="button" onClick={comps.run} disabled={comps.loading}>{comps.loading ? "拉取中…" : "拉取可比成交"}</button></span></div>
        <p className="sub">来源：TopHap 公共记录（recorded sales）。未启用或额度用尽时如实显示原因。</p>
        {comps.loading ? <Skeleton rows={4} /> : null}
        {comps.error ? <ErrorBox error={comps.error} /> : null}
        {comps.data && !comps.data.ok ? <div className="banner warn">没拉到：{comps.data.error}。这不是“没有可比成交”，是数据源暂不可用；可在“文件与证据”里手动登记可比。</div> : null}
        {rows.length ? (<>
          <CompsPlot rows={rows} />
          <div className="table-wrap"><table className="t"><thead><tr><th scope="col">地址</th><th scope="col">成交日</th><th scope="col" className="num">成交价<span className="unit">（$）</span></th>
            <th scope="col" className="num">面积<span className="unit">（SF）</span></th><th scope="col" className="num">$/SF</th><th scope="col" className="num">距离<span className="unit">（英里）</span></th><th scope="col">来源</th></tr></thead>
            <tbody>{rows.map((c, i) => <tr key={i}><td>{c.address}</td><td>{c.sale_date}</td><NumCell v={c.price} unit="usd" /><NumCell v={c.sf} unit="int" />
              <NumCell v={c.sf ? c.price / c.sf : null} unit="usd" /><NumCell v={c.distance_miles} unit="x" /><td className="muted">{c.source}</td></tr>)}</tbody></table></div></>) : null}
      </section>
      <div className="split">
        <section className="card" aria-label="产权穿透">
          <div className="row" style={{ justifyContent: "space-between" }}><h2 style={{ margin: 0 }}>产权与业主</h2>
            <button className="btn sm" type="button" onClick={tree.run} disabled={tree.loading}>{tree.loading ? "穿透中…" : "穿透产权"}</button></div>
          <p className="sub">LLC → 真实决策人；推断节点一律标“待验证”。</p>
          {tree.error ? <ErrorBox error={tree.error} /> : null}
          {tree.data ? (<ul className="checks">{tree.data.nodes.map((n) => <li key={n.id} style={{ paddingLeft: n.level * 16 }}>
            <Status s={n.confidence === "verified" ? "verified" : "building"}>{n.confidence === "verified" ? "已验证" : "待验证"}</Status>
            <span>{n.display}<div className="d">{n.relation} · {n.sources.map((s) => s.source).join("、")}</div></span></li>)}
            {tree.data.caveats.map((c) => <li key={c}><Status s="planned">说明</Status><span className="muted">{c}</span></li>)}</ul>) : null}
        </section>
        <section className="card" aria-label="卖方动机">
          <div className="row" style={{ justifyContent: "space-between" }}><h2 style={{ margin: 0 }}>卖方动机分</h2>
            <button className="btn sm" type="button" onClick={sell.run} disabled={sell.loading}>{sell.loading ? "计算中…" : "计算"}</button></div>
          <p className="sub">规则分（非黑箱）：持有年限、贷款到期、再融资、留置权、区域热度；无数据的信号不计分。</p>
          {sell.error ? <ErrorBox error={sell.error} /> : null}
          {sell.data ? (<><p><strong style={{ fontSize: 28, fontWeight: 300 }}>{sell.data.score}</strong> / {sell.data.max_score} · {sell.data.tier_note}</p>
            <ul className="checks">{sell.data.signals.map((s) => <li key={s.id}><Status s={s.status === "hit" ? "verified" : s.status === "unavailable" ? "planned" : "building"}>
              {s.status === "hit" ? `+${s.earned}` : s.status === "unavailable" ? "无数据" : "未命中"}</Status><span>{s.label}<div className="d">{s.value} · {s.source}</div></span></li>)}</ul></>) : null}
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
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="可比成交：$/SF 与距离">
      <line className="axis" x1={P} x2={W - P} y1={H - P} y2={H - P} /><line className="axis" x1={P} x2={P} y1={P} y2={H - P} />
      <text x={W / 2} y={H - 8} textAnchor="middle">距离（英里）</text><text x={8} y={P - 12}>$/SF</text>
      <text x={P} y={H - P + 14}>0</text><text x={W - P} y={H - P + 14} textAnchor="end">{mx.toFixed(1)}</text>
      <text x={P - 4} y={Y(hi)} textAnchor="end">{fmtShort(hi).replace("$", "")}</text><text x={P - 4} y={Y(lo)} textAnchor="end">{fmtShort(lo).replace("$", "")}</text>
      {pts.map((p, i) => <rect key={i} x={X(p.x) - 4} y={Y(p.y) - 4} width={8} height={8} className="base"><title>{`${p.r.address}：$${p.y.toFixed(0)}/SF，${p.x} 英里`}</title></rect>)}
    </svg>
  );
}
