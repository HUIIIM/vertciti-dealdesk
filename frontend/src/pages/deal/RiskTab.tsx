// 敏感性与红队：龙卷风图（最可能出错的 5 个假设）、实时滑块（DealCheck 式压力测试）、概率加权情景、反推最高出价。
import { T } from "@/i18n";
import { useEffect, useState } from "react";
import { api, call } from "@/api/client";
import type { DevilsMemo, Metrics, RedTeam, ScenarioIn } from "@/api/types";
import { useApi } from "@/api/useApi";
import { useApp } from "@/app-context";
import { Tornado } from "@/components/Charts";
import { Empty, ErrorBox, NumCell, Skeleton, Status, useToast } from "@/components/ui";
import { fmt } from "@/lib/format";
import { scaleNum, updateWild, type JsonObj } from "@/lib/paths";
import { useDeal } from "./Deal";

export function RiskTab() {
  const { id, ov, reload } = useDeal();
  const toast = useToast();
  const { can } = useApp();
  const hasV = Boolean(ov.version);
  const rt = useApi(() => (hasV ? call(api.GET("/api/v2/deals/{deal_id}/redteam", { params: { path: { deal_id: id } } })) : Promise.resolve(null)), [id, hasV, ov.deal.current_version_id]);
  if (!hasV) return <Empty title={T("还没有承销版本")}>{T("保存第一版后，这里自动列出最可能出错的假设。")}</Empty>;
  const markRead = async () => {
    try { await call(api.POST("/api/v2/deals/{deal_id}/redteam/read", { params: { path: { deal_id: id } } })); toast.ok(T("已标记红队面板已读（当前版本）"));
      await Promise.all([rt.reload(), reload()]); } catch (e) { toast.err(e); }
  };
  return (
    <>
      <DevilsCard id={id} version={ov.deal.current_version_id ?? 0} />
      <section className="card risk" aria-label={T("红队面板")}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 style={{ margin: 0 }}>{T("红队面板：最可能出错的 5 个假设")}</h2>
          {rt.data ? (rt.data.read ? <Status s="verified">{T("已读")}</Status> : can("deal.write") ? <button className="btn primary sm" type="button" onClick={markRead}>{T("我已读完（进投委会关卡）")}</button> : <Status s="planned">{T("未读")}</Status>) : null}
        </div>
        {rt.error ? <ErrorBox error={rt.error} /> : null}
        {rt.loading && !rt.data ? <Skeleton rows={5} /> : null}
        {rt.data ? (<>
          <p className="sub">{rt.data.note}</p>
          <Tornado rows={rt.data.top} base={rt.data.base} label={rt.data.metric_label} shock={rt.data.shock_pct} />
          <div className="table-wrap" style={{ maxHeight: "none", marginTop: 12 }}>
            <table className="t"><thead><tr><th scope="col">{T("假设")}</th><th scope="col" className="num">−{rt.data.shock_pct}{T("% 后")}<span className="unit">{T("（%）")}</span></th>
              <th scope="col" className="num">+{rt.data.shock_pct}{T("% 后")}<span className="unit">{T("（%）")}</span></th><th scope="col" className="num">{T("波动")}<span className="unit">{T("（bp）")}</span></th><th scope="col">{T("关键数字")}</th></tr></thead>
              <tbody>{rt.data.all.map((r) => <tr key={r.key}><td>{r.label}</td><NumCell v={r.minus.value} unit="pct" /><NumCell v={r.plus.value} unit="pct" />
                <NumCell v={r.swing_bps} unit="int" /><td>{r.material ? <Status s="building">{T("关键 · 需复核")}</Status> : <span className="muted">{T("否")}</span>}</td></tr>)}</tbody></table>
          </div>
          {rt.data.skipped.length ? <p className="muted" style={{ fontSize: 13 }}>{T("未扰动：")}{rt.data.skipped.map((s) => T("{0}（{1}）", [s.label, s.reason])).join(T("；"))}</p> : null}
        </>) : null}
      </section>
      {rt.data ? <Sliders rt={rt.data} /> : null}
      <div className="split">
        <ScenariosCard />
        <MaxBidCard />
      </div>
    </>
  );
}

function Sliders({ rt }: { rt: RedTeam }) {
  const { track, version } = useDeal();
  const [shocks, setShocks] = useState<Record<string, number>>({});
  const [res, setRes] = useState<Metrics | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const base = (version?.inputs ?? {}) as JsonObj;
  useEffect(() => {
    let x = base;
    for (const r of rt.top) { const s = shocks[r.key] ?? 0; if (s) for (const p of r.paths) x = updateWild(x, p, (v) => scaleNum(v, 1 + s / 100)); }
    let alive = true;  // 拖得快时旧请求可能晚到：只认最新一次的结果
    const t = window.setTimeout(() => {
      call(api.POST("/api/v2/model/{track}", { params: { path: { track } }, body: x as never }))
        .then((r) => { if (alive) { setRes((r as { metrics: Metrics }).metrics); setErr(null); } })
        .catch((e: Error) => { if (alive) setErr(e.message); });
    }, 200);
    return () => { alive = false; window.clearTimeout(t); };
  }, [JSON.stringify(shocks), version?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const v = res?.[rt.metric] ?? null;
  return (
    <section className="card" aria-label={T("压力测试滑块")}>
      <div className="row" style={{ justifyContent: "space-between" }}><h2 style={{ margin: 0 }}>{T("压力测试：拖动看回报实时变化")}</h2>
        <button className="btn ghost sm" type="button" onClick={() => setShocks({})}>{T("复位")}</button></div>
      <p className="sub">{T("在已保存版本上叠加变动，不改草稿。结果：")}{rt.metric_label} <strong className={typeof v === "number" && v < 0 ? "neg" : undefined}>{fmt(v, "pct")}</strong>
        {T("（基准")}{" "}{fmt(rt.base, "pct")}{T("）· DSCR")}{" "}{fmt(res?.dscr, "x")}{err ? <span className="neg"> · {err}</span> : null}</p>
      {rt.top.map((r) => (
        <div className="slider-row" key={r.key}>
          <label htmlFor={`s-${r.key}`}>{r.label}</label>
          <input id={`s-${r.key}`} type="range" min={-30} max={30} step={1} value={shocks[r.key] ?? 0} onChange={(e) => setShocks({ ...shocks, [r.key]: Number(e.target.value) })}
            aria-valuetext={`${shocks[r.key] ?? 0}%`} />
          <span className="num">{(shocks[r.key] ?? 0) > 0 ? "+" : ""}{shocks[r.key] ?? 0}%</span>
          <span className="muted" style={{ fontSize: 12 }}>{T("±10% 波动")}{" "}{Math.round(r.swing_bps)}bp</span>
        </div>))}
    </section>
  );
}

function ScenariosCard() {
  const { id, track, ov } = useDeal();
  const { catalog } = useApp();
  const aLabel = (k: string | null | undefined) => catalog.assumptions[track]?.find((a) => a.key === k)?.label ?? k ?? "";
  const [sc, setSc] = useState<ScenarioIn[]>(() => catalog.scenario_defaults[track] ?? []);
  const out = useApi(() => call(api.POST("/api/v2/deals/{deal_id}/scenarios", { params: { path: { deal_id: id } }, body: { scenarios: sc as never } })), [id, ov.deal.current_version_id, JSON.stringify(sc)]);
  const total = sc.reduce((a, s) => a + s.probability, 0);
  return (
    <section className="card" aria-label={T("概率加权结果")}>
      <h2>{T("概率加权结果")}</h2>
      <p className="sub">{T("三情景加概率，看期望回报与亏损概率，而不只是一个点估计。概率合计须为 100。")}</p>
      <div className="table-wrap" style={{ maxHeight: "none" }}>
        <table className="t"><thead><tr><th scope="col">{T("情景")}</th><th scope="col" className="num">{T("概率")}<span className="unit">{T("（%）")}</span></th>
          <th scope="col" className="num">{out.data?.metric_label ?? T("主回报")}<span className="unit">{T("（%）")}</span></th><th scope="col">{T("亏损")}</th></tr></thead>
          <tbody>{sc.map((s, i) => { const row = out.data?.scenarios[i];
            return (<tr key={s.name}><td>{s.name}<div className="muted" style={{ fontSize: 12 }}>{(s.changes ?? []).map((c) => `${c.assumption ? aLabel(c.assumption) : c.path} ${c.pct != null ? `${c.pct > 0 ? "+" : ""}${c.pct}%` : c.add != null ? `${c.add > 0 ? "+" : ""}${c.add}` : ""}`).join(T("，")) || T("按当前版本")}</div></td>
              <td className="cell-input"><input className="input num" style={{ width: 80 }} type="number" min={0} max={100} value={s.probability} aria-label={T("{0}概率", [s.name])}
                onChange={(e) => setSc(sc.map((x, j) => (j === i ? { ...x, probability: Number(e.target.value) } : x)))} /></td>
              <NumCell v={row?.primary ?? null} unit="pct" /><td>{row?.loss == null ? "—" : row.loss ? <Status s="risk">{T("亏损")}</Status> : <Status s="verified">{T("否")}</Status>}</td></tr>); })}</tbody>
          <tfoot><tr className="total"><td>{T("期望")}</td><td className={`num${total !== 100 ? " neg" : ""}`}>{total}</td><NumCell v={out.data?.expected ?? null} unit="pct" />
            <td>{out.data?.loss_probability_pct == null ? "—" : T("亏损概率 {0}%", [out.data.loss_probability_pct])}</td></tr></tfoot></table>
      </div>
      {out.error ? <p className="neg" role="alert">{out.error.message}</p> : null}
    </section>
  );
}

function MaxBidCard() {
  const { id, track, ov } = useDeal();
  const { catalog } = useApp();
  const primary = catalog.primary_metric[track] ?? "irr_pct";
  const [t1, setT1] = useState(track === "residential" ? 8 : 12);
  const [t2, setT2] = useState(1.25);
  const [run, setRun] = useState(0);
  const mb = useApi(() => call(api.POST("/api/v2/deals/{deal_id}/max-bid", { params: { path: { deal_id: id } },
    body: { targets: [{ metric: primary, min: t1 }, { metric: "dscr", min: t2 }], include_kill_criteria: true } })), [id, run, ov.deal.current_version_id]);
  return (
    <section className="card" aria-label={T("反推最高出价")}>
      <h2>{T("反推最高出价")}</h2>
      <p className="sub">{T("同时满足每个目标与淘汰条件；取各约束允许价中的最低者，并写明是哪条卡住了价格。")}</p>
      <form className="row" onSubmit={(e) => { e.preventDefault(); setRun((x) => x + 1); }}>
        <label className="field" style={{ width: 150 }}>{T("目标")}{" "}{catalog.metrics[primary]?.label} ≥ %<input className="input num" type="number" step="0.1" value={t1} onChange={(e) => setT1(Number(e.target.value))} /></label>
        <label className="field" style={{ width: 130 }}>{T("目标 DSCR ≥")}<input className="input num" type="number" step="0.05" value={t2} onChange={(e) => setT2(Number(e.target.value))} /></label>
        <button className="btn primary" type="submit" style={{ alignSelf: "end" }}>{T("反算")}</button>
      </form>
      {mb.error ? <ErrorBox error={mb.error} /> : null}
      {mb.data ? (<>
        <div className="maxbid"><span className="v">{fmt(mb.data.max_bid, "usd")}</span>
          <span className="muted">{T("要价")}{" "}{fmt(mb.data.asking, "usd")}{mb.data.headroom_pct != null ? T(" · 相对要价 {0}{1}%", [mb.data.headroom_pct > 0 ? "+" : "", mb.data.headroom_pct.toFixed(1)]) : ""}</span></div>
        <ul className="checks">{mb.data.constraints.map((c, i) => <li key={i}><Status s={c.status === "ok" || c.status === "above_range" ? (mb.data!.binding?.label === c.label ? "building" : "verified") : "risk"}>
          {mb.data!.binding?.label === c.label ? T("卡住价格") : c.status === "ok" ? T("可满足") : c.status === "above_range" ? T("宽松") : c.status === "infeasible" ? T("达不到") : T("无法计算")}</Status>
          <span>{c.label}<div className="d">{c.price != null ? T("允许最高 {0}", [fmt(c.price, "usd")]) : c.reason}{c.source === "kill_criteria" ? T(" · 来自淘汰条件") : ""}</div></span></li>)}</ul>
        <p className="muted" style={{ fontSize: 12 }}>{mb.data.note}{track === "residential" ? T(" 住宅改价时按原 LTV 等比调整首付与贷款。") : ""}</p></>) : <Skeleton />}
    </section>
  );
}


const TAB_HREF: Record<string, string> = { overview: "", risk: "/risk", files: "/files", model: "/model", rentroll: "/rentroll" };

/** 反方备忘录：上会前先读“这笔交易最可能怎么失败”。规则生成、不经 AI；每条带去处理的入口。 */
function DevilsCard({ id, version }: { id: number; version: number }) {
  const memo = useApi<DevilsMemo>(() => call(api.GET("/api/v2/deals/{deal_id}/devils-memo", { params: { path: { deal_id: id } } })), [id, version]);
  if (memo.error) return <ErrorBox error={memo.error} onRetry={memo.reload} />;
  if (!memo.data) return <section className="card"><Skeleton rows={3} /></section>;
  const d = memo.data;
  return (
    <section className={`card devils${d.high ? " risk" : ""}`} aria-label={T("反方备忘录")}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>{T("反方备忘录：这笔交易最可能怎么失败")}</h2>
        <span className="chip" title={d.note}>{T("不经 AI · 运行")}{" "}{d.run_id.slice(0, 12)}</span>
      </div>
      {d.headline ? <p className="headline">{d.headline}</p> : <p className="muted">{T("没有可由数据支持的反方论点（数据不足的论点不写）。")}</p>}
      {d.points.length ? (
        <ol className="devils-list">
          {d.points.map((p) => (
            <li key={p.key}>
              <Status s={p.severity === "high" ? "risk" : "building"}>{p.severity === "high" ? T("高") : T("中")} · {p.title}</Status>
              <span>{p.text}</span>
              <a className="btn sm ghost" href={`#/deals/${id}${TAB_HREF[p.tab] ?? ""}`}>{T("去看")}</a>
            </li>))}
        </ol>) : null}
      <p className="sub" style={{ margin: "8px 0 0" }}>{d.note}</p>
    </section>
  );
}
