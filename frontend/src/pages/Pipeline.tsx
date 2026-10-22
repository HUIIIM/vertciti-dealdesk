// 流水线（首页）：看板 / 表格两种视图，按阶段分列；可筛选、排序、保存视图；J/K 移动、Enter 打开、N 新建。
import { T } from "@/i18n";
import { useMemo, useState } from "react";
import { api, call, type DealListItem } from "@/api/client";
import { useApi } from "@/api/useApi";
import { useApp } from "@/app-context";
import { DataTable, type Column } from "@/components/DataTable";
import { Empty, ErrorBox, Kbd, Skeleton, Status, useToast } from "@/components/ui";
import { STAGES } from "@/domain/fields";
import { fmt, fmtShort } from "@/lib/format";
import { useHotkeys } from "@/lib/hotkeys";
import { usePref } from "@/lib/prefs";
import { navigate } from "@/lib/router";
import { NewDeal } from "./NewDeal";

type View = "board" | "table";
interface Filters { track: "" | "residential" | "commercial"; q: string; kill: "" | "triggered" | "clear" | "unknown" }
const NONE: Filters = { track: "", q: "", kill: "" };

/** 服务端保存的视图配置是任意 JSON：逐字段收窄，不信任形状。 */
export function toFilters(c: Record<string, unknown>): { filters: Filters; view: View | null } {
  const pick = <T extends string>(v: unknown, ok: readonly T[]): T | "" => (typeof v === "string" && (ok as readonly string[]).includes(v) ? (v as T) : "");
  return { filters: { track: pick(c.track, ["residential", "commercial"] as const), q: typeof c.q === "string" ? c.q : "",
    kill: pick(c.kill, ["triggered", "clear", "unknown"] as const) }, view: c.view === "board" || c.view === "table" ? c.view : null };
}

export function killState(d: DealListItem): "risk" | "verified" | "building" | "planned" {
  const k = d.kill as { triggered?: unknown[]; unknown?: unknown[]; clear?: boolean } | null;
  if (!k) return "planned";
  if (k.triggered?.length) return "risk";
  if (k.unknown?.length) return "building";
  return k.clear ? "verified" : "planned";
}
const KILL_TEXT = { risk: T("触发淘汰"), verified: T("未触发"), building: T("指标未知"), planned: T("未承销") } as const;

export function Pipeline() {
  const { catalog, can, dealsVersion, refreshDeals } = useApp();
  const toast = useToast();
  const deals = useApi(() => call(api.GET("/api/v2/deals")), [dealsVersion]);
  const views = useApi(() => call(api.GET("/api/v2/settings/views")), []);
  const [view, setView] = usePref<View>("pipeline.view", "board");
  const [f, setF] = usePref<Filters>("pipeline.filters", NONE);
  const [sel, setSel] = useState(0);
  const [creating, setCreating] = useState(false);
  const rows = useMemo(() => (deals.data ?? []).filter((d) => (!f.track || d.track === f.track)
    && (!f.q || `${d.name} ${d.address}`.toLowerCase().includes(f.q.toLowerCase()))
    && (!f.kill || ({ triggered: "risk", clear: "verified", unknown: "building" } as const)[f.kill] === killState(d))), [deals.data, f]);
  const ordered = useMemo(() => view === "board"
    ? STAGES.flatMap(([s]) => rows.filter((d) => d.stage === s)).concat(rows.filter((d) => d.stage === "passed")) : rows, [rows, view]);
  const selIdx = Math.min(sel, Math.max(ordered.length - 1, 0));
  useHotkeys([
    { combo: "j", label: T("下移"), group: T("列表"), run: () => setSel(Math.min(selIdx + 1, ordered.length - 1)) },
    { combo: "k", label: T("上移"), group: T("列表"), run: () => setSel(Math.max(selIdx - 1, 0)) },
    { combo: "enter", label: T("打开"), group: T("列表"), run: () => { const d = ordered[selIdx]; if (d) navigate({ name: "deal", id: d.id, tab: "overview" }); } },
    { combo: "e", label: T("编辑模型"), group: T("列表"), run: () => { const d = ordered[selIdx]; if (d) navigate({ name: "deal", id: d.id, tab: "model" }); } },
    { combo: "n", label: T("新建"), group: T("列表"), run: () => { if (can("deal.write")) setCreating(true); } },
  ], !creating);
  const primary = (d: DealListItem) => catalog.primary_metric[d.track] ?? "irr_pct";
  const m = (d: DealListItem, k: string) => (d.metrics as Record<string, number | null>)[k] ?? null;
  const columns: Column<DealListItem>[] = [
    { key: "name", header: T("交易"), width: 240, render: (d) => <a className="rowlink" href={`#/deals/${d.id}`}>{d.name}</a>, sortValue: (d) => d.name },
    { key: "stage", header: T("阶段"), width: 90, render: (d) => d.stage_label, sortValue: (d) => d.stage_index },
    { key: "track", header: T("赛道"), width: 70, render: (d) => (d.track === "commercial" ? T("商业") : T("住宅")), sortValue: (d) => d.track },
    { key: "price", header: T("收购价"), unit: "usd", width: 130, render: (d) => fmt(m(d, "price") ?? d.asking_price, "int"), sortValue: (d) => m(d, "price") ?? d.asking_price ?? null },
    { key: "primary", header: T("主回报"), unit: "pct", width: 100, render: (d) => fmt(m(d, primary(d)), "pct").replace("%", ""), sortValue: (d) => m(d, primary(d)) },
    { key: "dscr", header: "DSCR", unit: "x", width: 80, render: (d) => fmt(m(d, "dscr"), "x").replace("×", ""), sortValue: (d) => m(d, "dscr") },
    { key: "cap", header: "Cap Rate", unit: "pct", width: 90, render: (d) => fmt(m(d, "cap_rate_pct"), "pct").replace("%", ""), sortValue: (d) => m(d, "cap_rate_pct") },
    { key: "kill", header: T("淘汰条件"), width: 120, render: (d) => <Status s={killState(d)}>{KILL_TEXT[killState(d)]}</Status>, sortValue: (d) => killState(d) },
    { key: "updated", header: T("更新"), width: 110, render: (d) => d.updated_at.slice(0, 10), sortValue: (d) => d.updated_at },
  ];
  const saveView = async () => {
    const name = window.prompt(T("视图名称"), f.track === "commercial" ? T("只看商业") : T("我的视图"));
    if (!name) return;
    try { await call(api.PUT("/api/v2/settings/views", { body: { name, config: { ...f, view } } })); await views.reload(); toast.ok(T("视图已保存")); }
    catch (e) { toast.err(e); }
  };
  return (
    <>
      <div className="page-head">
        <div><p className="eyebrow">{T("流水线")}</p><h1>{rows.length} {" "}{T("笔交易")}</h1></div>
        <span className="sp" />
        <div className="seg" role="group" aria-label={T("视图")}>
          <button type="button" aria-pressed={view === "board"} onClick={() => setView("board")}>{T("看板")}</button>
          <button type="button" aria-pressed={view === "table"} onClick={() => setView("table")}>{T("表格")}</button>
        </div>
        {can("deal.write") ? <button className="btn primary" type="button" onClick={() => setCreating(true)}>{T("新建交易")}{" "}<Kbd k="N" /></button> : null}
      </div>
      <div className="row" style={{ marginBottom: 16 }} role="search">
        <input className="input" style={{ maxWidth: 280 }} placeholder={T("筛选：名称 / 地址")} aria-label={T("筛选名称或地址")} value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} />
        <select className="input" style={{ width: 120 }} aria-label={T("赛道")} value={f.track} onChange={(e) => setF({ ...f, track: e.target.value as Filters["track"] })}>
          <option value="">{T("全部赛道")}</option><option value="commercial">{T("商业")}</option><option value="residential">{T("住宅")}</option>
        </select>
        <select className="input" style={{ width: 150 }} aria-label={T("淘汰条件")} value={f.kill} onChange={(e) => setF({ ...f, kill: e.target.value as Filters["kill"] })}>
          <option value="">{T("淘汰条件：全部")}</option><option value="triggered">{T("触发淘汰")}</option><option value="clear">{T("未触发")}</option><option value="unknown">{T("指标未知")}</option>
        </select>
        {(views.data ?? []).map((v) => { const cfg = toFilters(v.config);
          return <button key={v.id} className="btn sm" type="button" onClick={() => { setF(cfg.filters); if (cfg.view) setView(cfg.view); }}>{v.name}</button>; })}
        <button className="btn ghost sm" type="button" onClick={saveView}>{T("保存当前视图")}</button>
        {f !== NONE && (f.q || f.track || f.kill) ? <button className="btn ghost sm" type="button" onClick={() => setF(NONE)}>{T("清除筛选")}</button> : null}
      </div>
      {deals.error ? <ErrorBox error={deals.error} onRetry={deals.reload} /> : null}
      {deals.loading && !deals.data ? <Skeleton rows={5} h={44} /> : null}
      {deals.data && deals.data.length === 0 ? (
        <Empty title={T("还没有交易")}>
          <p>{T("新建第一笔交易：先写淘汰条件，再开始承销。")}</p>
          {can("deal.write") ? <button className="btn primary" type="button" onClick={() => setCreating(true)}>{T("新建交易")}</button> : null}
        </Empty>) : null}
      {deals.data && deals.data.length > 0 && view === "table" ? (
        <DataTable id="pipeline" caption={T("交易列表")} columns={columns} rows={ordered} rowKey={(d) => d.id} selected={selIdx}
          onRowClick={(d) => navigate({ name: "deal", id: d.id, tab: "overview" })} />) : null}
      {deals.data && deals.data.length > 0 && view === "board" ? (
        <div className="kanban" role="list" aria-label={T("按阶段分列")}>
          {[...STAGES, ["passed", T("已放弃")] as [string, string]].map(([s, label]) => {
            const col = rows.filter((d) => d.stage === s);
            if (s === "passed" && col.length === 0) return null;
            return (
              <section key={s} className="kcol" role="listitem" aria-label={T("{0} {1} 笔", [label, col.length])}>
                <h2><span>{label}</span><span className="muted">{col.length}</span></h2>
                {col.map((d) => { const st = killState(d); const idx = ordered.indexOf(d);
                  return (
                    <a key={d.id} href={`#/deals/${d.id}`} className={`kcard ${st === "risk" ? "risk" : st === "verified" ? "ok" : st === "building" ? "warn" : ""}`}
                      aria-current={idx === selIdx ? "true" : undefined} onFocus={() => setSel(idx)}>
                      <div className="name" title={d.name}>{d.name}</div>
                      <div className="addr" title={d.address || undefined}>{d.address || "—"} · {d.track === "commercial" ? T("商业") : T("住宅")}</div>
                      <div className="kv"><span className="muted">{T("价格")}</span><span>{fmtShort(m(d, "price") ?? d.asking_price)}</span></div>
                      <div className="kv"><span className="muted">{catalog.metrics[primary(d)]?.label}</span><span>{fmt(m(d, primary(d)), "pct")}</span></div>
                      <div className="kv"><span className="muted">DSCR</span><span>{fmt(m(d, "dscr"), "x")}</span></div>
                      <div className="foot"><Status s={st}>{KILL_TEXT[st]}</Status></div>
                    </a>); })}
              </section>);
          })}
        </div>) : null}
      {creating ? <NewDeal onClose={() => setCreating(false)} onCreated={refreshDeals} /> : null}
    </>
  );
}
