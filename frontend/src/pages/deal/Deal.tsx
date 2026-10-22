// 交易页：顶部结论卡（F 型阅读起点）+ 核对进度 + 关卡；下方 10 个标签页。
// 草稿：在模型类标签页改假设 → 右侧实时重算（防抖 300ms，不保存）；⌘S 保存为新承销版本（必填“本版改了什么”）。
import { T } from "@/i18n";
import { createContext, lazy, Suspense, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, call, type OverviewOut, type PassportOut, type VersionOut } from "@/api/client";
import type { KillEval, MaxBid, Metrics, PriceCheck, VerifyQueue } from "@/api/types";
import { useApi } from "@/api/useApi";
import { useApp } from "@/app-context";
import { passportStatus, PassportDialog } from "@/components/Passport";
import { Dialog, ErrorBox, Kbd, Metric, MetricGrid, Skeleton, Status, useToast, type StatusKey } from "@/components/ui";
import { blankInputs, CARD_METRICS, fieldLabel, STAGES, type Track } from "@/domain/fields";
import { fmt, fmtShort, type Unit } from "@/lib/format";
import { useHotkeys } from "@/lib/hotkeys";
import { useTween } from "@/lib/motion";
import { getPath, setPath, type JsonObj } from "@/lib/paths";
import { DEAL_TABS, navigate, type DealTab } from "@/lib/router";

// 标签页按需加载（各自一个包），概览随交易页一起预取
const CommitteeTab = lazy(() => import("./CommitteeTab").then((m) => ({ default: m.CommitteeTab })));
const FilesTab = lazy(() => import("./FilesTab").then((m) => ({ default: m.FilesTab })));
const HoldingTab = lazy(() => import("./HoldingTab").then((m) => ({ default: m.HoldingTab })));
const LogTab = lazy(() => import("./LogTab").then((m) => ({ default: m.LogTab })));
const MarketTab = lazy(() => import("./MarketTab").then((m) => ({ default: m.MarketTab })));
const ModelTab = lazy(() => import("./ModelTab").then((m) => ({ default: m.ModelTab })));
const OverviewTab = lazy(() => import("./OverviewTab").then((m) => ({ default: m.OverviewTab })));
const RentRollTab = lazy(() => import("./RentRollTab").then((m) => ({ default: m.RentRollTab })));
const RiskTab = lazy(() => import("./RiskTab").then((m) => ({ default: m.RiskTab })));
const T12Tab = lazy(() => import("./T12Tab").then((m) => ({ default: m.T12Tab })));

export interface Preview { metrics: Metrics; detail: Record<string, unknown>; error?: string }
export interface DealCtxValue {
  id: number; track: Track; ov: OverviewOut; version: VersionOut | null; draft: JsonObj; dirty: boolean;
  set: (path: string, value: unknown) => void; replaceDraft: (d: JsonObj) => void; preview: Preview | null; previewing: boolean;
  passports: Record<string, PassportOut>; openPassport: (path: string, label: string) => void; reload: () => Promise<void>; save: () => void;
}
const DealCtx = createContext<DealCtxValue | null>(null);
export function useDeal(): DealCtxValue {
  const v = useContext(DealCtx);
  if (!v) throw new Error(T("useDeal 必须在交易页内使用"));
  return v;
}

const killStatus = (k: KillEval): StatusKey => (k.triggered.length ? "risk" : k.unknown.length ? "building" : k.clear ? "verified" : "planned");

export function DealPage({ id, tab }: { id: number; tab: DealTab }) {
  const { catalog, can } = useApp();
  const toast = useToast();
  const ov = useApi(() => call(api.GET("/api/v2/deals/{deal_id}", { params: { path: { deal_id: id } } })), [id]);
  const vid = ov.data?.deal.current_version_id ?? null;
  const ver = useApi(() => (vid ? call(api.GET("/api/v2/deals/{deal_id}/versions/{version_id}", { params: { path: { deal_id: id, version_id: vid } } }))
    : Promise.resolve(null)), [id, vid]);
  const pp = useApi(() => call(api.GET("/api/v2/deals/{deal_id}/passports", { params: { path: { deal_id: id } } })), [id]);
  const [edit, setEdit] = useState<{ base: string; draft: JsonObj } | null>(null);
  const [preview, setPreview] = useState<(Preview & { key: string }) | null>(null);
  const [saving, setSaving] = useState(false);
  const [label, setLabel] = useState("");
  const [passport, setPassport] = useState<{ path: string; label: string } | null>(null);
  const track = (ov.data?.deal.track ?? "commercial") as Track;

  // 草稿 = 当前版本输入（没有版本则赛道模板）+ 本地改动。基线换了（保存了新版 / 切了交易）自动丢弃旧改动。
  const initial = useMemo<JsonObj | null>(() => {
    if (!ov.data || ver.loading) return null;
    const d = ov.data.deal;
    return (ver.data?.inputs as JsonObj | undefined) ?? blankInputs(d.track as Track, d.name, d.address, d.asking_price);
  }, [ov.data, ver.data, ver.loading]);
  const baseline = useMemo(() => (initial ? JSON.stringify(initial) : ""), [initial]);
  const draft = edit && edit.base === baseline ? edit.draft : initial;
  const setDraft = useCallback((fn: (d: JsonObj) => JsonObj) => {
    setEdit((e) => {
      const cur = e && e.base === baseline ? e.draft : initial;
      return cur ? { base: baseline, draft: fn(cur) } : e;
    });
  }, [baseline, initial]);
  const draftKey = useMemo(() => (draft ? JSON.stringify(draft) : ""), [draft]);
  const dirty = draft !== null && draftKey !== baseline;

  // 实时重算（不保存）：防抖 300ms；“计算中”由键是否对得上派生，effect 只在异步回调里 setState
  useEffect(() => {
    if (!draft) return;
    let alive = true;
    const t = window.setTimeout(async () => {
      try {
        const r = await call(api.POST("/api/v2/model/{track}", { params: { path: { track } }, body: draft as never }));
        if (alive) setPreview({ key: draftKey, metrics: r.metrics, detail: r.detail });
      } catch (e) {
        if (alive) setPreview({ key: draftKey, metrics: {}, detail: {}, error: (e as Error).message });
      }
    }, 300);
    return () => { alive = false; window.clearTimeout(t); };
  }, [draftKey, track]); // eslint-disable-line react-hooks/exhaustive-deps -- draft 由 draftKey 代表
  const previewing = Boolean(draft) && preview?.key !== draftKey;

  const reload = useCallback(async () => { await Promise.all([ov.reload(), pp.reload()]); }, [ov, pp]);
  const passports = useMemo(() => Object.fromEntries((pp.data ?? []).map((p) => [p.field, p])), [pp.data]);
  const doSave = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      const v = await call(api.POST("/api/v2/deals/{deal_id}/versions", { params: { path: { deal_id: id } }, body: { inputs: draft as never, label } }));
      toast.ok(T("已保存第 {0} 版 · 运行编号 {1}", [v.version_no, v.run_id]));
      setLabel(""); setSaving(false); setEdit(null);
      await ov.reload();
    } catch (e) { toast.err(e); setSaving(false); }
  };
  const [askSave, setAskSave] = useState(false);
  const save = () => { if (!can("deal.write")) { toast.err(T("只读角色不能保存")); return; } if (dirty || !vid) setAskSave(true); else toast.info(T("没有未保存的改动")); };
  useHotkeys([
    { combo: "mod+s", label: T("保存"), group: T("交易"), allowInInput: true, run: save },
    { combo: "e", label: T("编辑模型"), group: T("交易"), run: () => navigate({ name: "deal", id, tab: "model" }) },
    ...DEAL_TABS.map(([k], i) => ({ combo: String((i + 1) % 10), label: k, group: T("标签"), run: () => navigate({ name: "deal", id, tab: k }) })),
  ], !askSave && !passport);
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const mb = useMaxBid(id, (ov.data?.version as { id: number } | null | undefined)?.id ?? null, ov.data?.kill as unknown as KillEval | undefined);
  if (ov.error) return <ErrorBox error={ov.error} onRetry={ov.reload} />;
  if (!ov.data || !draft) return <Skeleton rows={6} h={28} />;
  const o = ov.data;
  const d = o.deal;
  const kill = o.kill as unknown as KillEval;
  const m = (dirty && preview && !preview.error ? preview.metrics : (o.metrics as Metrics)) ?? {};
  const ver_ = o.verification as { key_reviewed: number; key_total: number; open_conflicts: number; stale_evidence: number; review_due: number; redteam_read: boolean };
  const stageIdx = STAGES.findIndex(([s]) => s === d.stage);
  const ctx: DealCtxValue = { id, track, ov: o, version: ver.data ?? null, draft, dirty, set: (p, v) => setDraft((x) => setPath(x, p, v)),
    replaceDraft: (nd) => setDraft(() => nd), preview, previewing, passports, openPassport: (path, l) => setPassport({ path, label: l }), reload, save };
  const metricKeys = CARD_METRICS[track];
  const pct = ver_.key_total ? Math.round((ver_.key_reviewed / ver_.key_total) * 100) : 0;
  return (
    <DealCtx.Provider value={ctx}>
      <div className="deal-head">
        <section className={`verdict-card ${kill.triggered.length ? "risk" : kill.clear ? "ok" : ""}`} aria-label={T("结论卡")}>
          <p className="eyebrow">{d.track === "commercial" ? T("商业") : T("住宅")} · {d.stage_label}{o.version ? T(" · 第 {0} 版", [(o.version as { version_no: number }).version_no]) : T(" · 尚未承销")}</p>
          <h1>{d.name}</h1>
          <div className="muted" style={{ fontSize: 14 }}>{d.address || T("地址未填")}</div>
          <div className="maxbid">
            <span className="muted" style={{ fontWeight: 800, fontSize: 13 }}>{T("结论")}</span>
            <Status s={killStatus(kill)}>{kill.triggered.length ? T("触发淘汰 {0} 条", [kill.triggered.length]) : kill.unknown.length ? T("淘汰条件无法判定") : kill.clear ? T("淘汰条件未触发") : T("未承销")}</Status>
            {o.last_verdict ? <span className="chip">{T("最近决策")}{" "}{o.last_verdict}</span> : null}
            <MaxBidInline mb={mb} hasVersion={Boolean(o.version)} dirty={dirty} />
          </div>
          <MetricGrid count={metricKeys.length} style={{ marginTop: 8 }}>
            {metricKeys.map((k) => { const meta = catalog.metrics[k]!;
              return <Metric key={k} label={meta.label} value={m[k] ?? null} unit={meta.unit as Unit} testId={`metric-${k}`}
                note={dirty ? T("草稿重算") : undefined} onOpen={() => setPassport({ path: `metric:${k}`, label: meta.label })} />; })}
          </MetricGrid>
          {kill.items.length ? (
            <ul className="checks" style={{ marginTop: 12 }} aria-label={T("淘汰条件")}>
              {kill.items.map((k, i) => <li key={i}><Status s={k.state === "triggered" ? "risk" : k.state === "unknown" ? "building" : "verified"}>
                {k.state === "triggered" ? T("触发") : k.state === "unknown" ? T("未知") : T("未触发")}</Status><span>{k.text}<span className="muted"> {" "}{T("· 当前")}{" "}{fmt(k.value, (catalog.metrics[k.metric]?.unit ?? "x") as Unit)}</span></span></li>)}
            </ul>) : <div className="banner warn" style={{ marginTop: 12 }}>{T("还没写淘汰条件：进入承销前必须先写“什么情况下放弃”。")}</div>}
          {mb.data && o.version ? <PriceLadder mb={mb.data} dealId={id} track={track} /> : null}
          <ol className="stepper" aria-label={T("阶段")} style={{ marginTop: "auto", paddingTop: 16 }}>
            {STAGES.map(([s, l], i) => <li key={s} className={i < stageIdx ? "done" : i === stageIdx ? "current" : ""} aria-current={i === stageIdx ? "step" : undefined}>{l}</li>)}
          </ol>
        </section>
        <section className="card" aria-label={T("核对进度")}>
          <h2>{T("核对进度")}</h2>
          <p className="sub">{T("关键数字由红队面板的敏感性客观定义（±10% 让主回报移动 ≥ 100bp）")}</p>
          <div className="row" style={{ justifyContent: "space-between" }}><span>{T("关键数字已复核")}</span><strong className="num">{ver_.key_reviewed} / {ver_.key_total}</strong></div>
          <div className="progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={T("关键数字复核进度")}><span style={{ width: `${pct}%` }} /></div>
          <ul className="checks" style={{ marginTop: 8 }}>
            <li><Status s={ver_.open_conflicts ? "risk" : "verified"}>{ver_.open_conflicts ? T("{0} 条", [ver_.open_conflicts]) : T("无")}</Status><span>{T("未裁决的跨来源矛盾")}</span></li>
            <li><Status s={ver_.stale_evidence ? "risk" : ver_.review_due ? "building" : "verified"}>{ver_.stale_evidence ? T("{0} 条停用", [ver_.stale_evidence]) : ver_.review_due ? T("{0} 条待复核", [ver_.review_due]) : T("新鲜")}</Status><span>{T("证据新鲜度（14 天待复核 / 30 天停用）")}</span></li>
            <li><Status s={ver_.redteam_read ? "verified" : "planned"}>{ver_.redteam_read ? T("已读") : T("未读")}</Status><span>{T("红队面板（当前版本）")}</span></li>
          </ul>
          {o.version ? <VerifyFirst id={id} version={(o.version as { id: number }).id} stamp={JSON.stringify(ver_)} /> : null}
          {o.next_gate ? (<>
            <h3 style={{ marginTop: 16, fontSize: 15 }}>{T("进入「")}{STAGES.find(([s]) => s === o.next_stage)?.[1]}{T("」的关卡")}</h3>
            <ul className="checks">{(o.next_gate.checks ?? []).map((c) => <li key={c.key}><Status s={c.status}>{c.status_label}</Status><span>{c.label}{c.detail ? <div className="d">{c.detail}</div> : null}</span></li>)}</ul>
          </>) : null}
          {can("deal.advance") ? <div style={{ marginTop: 12 }}><a className="btn sm" href={`#/deals/${id}`}>{T("去推进阶段 →")}</a></div> : null}
        </section>
      </div>
      <nav className="tabs" role="tablist" aria-label={T("交易标签页")}>
        {DEAL_TABS.map(([k, l], i) => <a key={k} role="tab" aria-selected={tab === k} href={k === "overview" ? `#/deals/${id}` : `#/deals/${id}/${k}`}
          title={T("快捷键 {0}", [(i + 1) % 10])}>{l}</a>)}
      </nav>
      <div role="tabpanel" aria-label={DEAL_TABS.find(([k]) => k === tab)?.[1]}>
        <Suspense fallback={<Skeleton rows={5} h={28} />}>
        {tab === "overview" ? <OverviewTab /> : tab === "rentroll" ? <RentRollTab /> : tab === "t12" ? <T12Tab /> : tab === "model" ? <ModelTab />
          : tab === "risk" ? <RiskTab /> : tab === "market" ? <MarketTab /> : tab === "files" ? <FilesTab /> : tab === "committee" ? <CommitteeTab />
          : tab === "holding" ? <HoldingTab /> : <LogTab />}
        </Suspense>
      </div>
      {dirty ? (
        <div className="draftbar" role="region" aria-label={T("未保存的草稿")}>
          <span>{previewing ? <span className="live-dot" aria-hidden="true" /> : null}{T("草稿有改动 · 结果为实时重算")}{previewing ? T("（计算中…）") : ""}{preview?.error ? ` · ${preview.error}` : ""}</span>
          <span style={{ flex: 1 }} />
          <button className="btn sm" type="button" onClick={() => setEdit(null)}>{T("放弃改动")}</button>
          {can("deal.write") ? <button className="btn sm primary" type="button" onClick={save}>{T("保存为新版本")}{" "}<Kbd k="⌘ S" /></button> : null}
        </div>) : !vid && can("deal.write") ? (
        <div className="draftbar"><span>{T("还没有承销版本：在“租金表 / T12 / 模型”填好假设后保存第一版")}</span><span style={{ flex: 1 }} />
          <button className="btn sm primary" type="button" onClick={save}>{T("保存第一版")}{" "}<Kbd k="⌘ S" /></button></div>) : null}
      {askSave ? (
        <Dialog title={T("保存承销版本")} onClose={() => setAskSave(false)} footer={<>
          <button className="btn ghost" type="button" onClick={() => setAskSave(false)}>{T("取消")}</button>
          <button className="btn primary" type="button" disabled={saving} onClick={async () => { await doSave(); setAskSave(false); }}>{saving ? T("保存中…") : T("保存")}</button></>}>
          <label className="field">{T("本版改了什么、为什么")}<span className="hint">{T("写进投委会包“自上一版起改了什么”")}</span>
            <input className="input" value={label} onChange={(e) => setLabel(e.target.value)} placeholder={T("如：退出 cap 按可比上调 50bp")} maxLength={200}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); if (!saving) void doSave().then(() => setAskSave(false)); } }} /></label>
        </Dialog>) : null}
      {passport ? (passport.path.startsWith("metric:") ? (
        <MetricExplain metric={passport.path.slice(7)} label={passport.label} onClose={() => setPassport(null)} />
      ) : (
        <PassportDialog dealId={id} field={passport.path} label={passport.label} currentValue={getPath(draft, passport.path)}
          onClose={() => setPassport(null)} onChanged={() => void reload()} />)) : null}
    </DealCtx.Provider>
  );
}

/** 最高出价：结论卡的行内大字与“出价空间”梯子共用一次请求。 */
function useMaxBid(id: number, versionId: number | null, kill: KillEval | undefined) {
  // 依赖带版本号：保存新版本后必须按新版本重算（否则结论卡与出价空间停在旧版本的数）
  const crit = (kill?.items ?? []).map((k) => [k.metric, k.op, k.threshold]);
  return useApi<MaxBid | null>(() => (versionId !== null && crit.length ? call(api.POST("/api/v2/deals/{deal_id}/max-bid", {
    params: { path: { deal_id: id } }, body: { targets: [], include_kill_criteria: true } })) : Promise.resolve(null)),
  [id, versionId, JSON.stringify(crit)]);
}

function MaxBidInline({ mb, hasVersion, dirty }: { mb: ReturnType<typeof useMaxBid>; hasVersion: boolean; dirty: boolean }) {
  if (!hasVersion) return null;
  if (mb.loading && !mb.data) return <span className="muted">{T("最高出价计算中…")}</span>;
  if (!mb.data) return <span className="muted">{T("最高出价：需下限型淘汰条件")}</span>;
  return (
    <span style={{ display: "inline-flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }} data-testid="max-bid">
      <span className="muted" style={{ fontWeight: 800, fontSize: 13 }}>{T("最高出价")}</span>
      <TweenUsd value={mb.data.max_bid} />
      <span className="muted" style={{ fontSize: 13 }}>{mb.data.binding ? T("卡在：{0}", [mb.data.binding.label]) : ""}{dirty ? T(" · 按已保存版本") : ""}</span>
    </span>
  );
}

/**
 * 出价空间（vertciti 独有）：每条约束各自允许的最高价画成一个点，竖线是要价，点与竖线之间的段是差额。
 * 坐标轴为放大的价格区间（不从 0 开始），所以用点与差额段而不用从 0 起的长条——避免夸大差异。
 * 一眼看出哪条约束卡住价格（橙色）、离要价还差多少；无法满足的约束写明，不画假条。
 */
export function PriceLadder({ mb, dealId, track }: { mb: MaxBid; dealId: number; track: Track }) {
  const { catalog } = useApp();
  const [trial, setTrial] = useState<number | null>(null);
  const [check, setCheck] = useState<{ price: number; out: PriceCheck | null; err: string | null } | null>(null);
  // 拖动防抖 180ms：停手才算，避免每个像素都打一次后端；setState 只在异步回调里
  useEffect(() => {
    if (trial === null) return;
    const t = window.setTimeout(() => {
      call(api.POST("/api/v2/deals/{deal_id}/price-check", { params: { path: { deal_id: dealId } }, body: { price: trial } }))
        .then((out) => setCheck({ price: trial, out, err: null }))
        .catch((e: unknown) => setCheck({ price: trial, out: null, err: e instanceof Error ? e.message : String(e) }));
    }, 180);
    return () => window.clearTimeout(t);
  }, [trial, dealId]);
  const priced = mb.constraints.map((c) => c.price).filter((v): v is number => typeof v === "number");
  if (!priced.length) return null;
  const vals = [mb.asking, ...priced];
  const lo = Math.min(...vals) * 0.85, hi = Math.max(...vals) * 1.04;
  const pos = (v: number) => Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100));
  const ask = pos(mb.asking);
  const step = Math.max(1000, Math.round(mb.asking / 400 / 1000) * 1000);
  const shown = check && trial !== null && check.price === trial ? check : null;
  return (
    <section className="ladder" aria-label={T("出价空间")}>
      <div className="ladder-head"><strong>{T("出价空间")}</strong><span className="muted">{T("方块 = 该约束允许的最高价 · 竖线 = 要价")}{" "}{fmtShort(mb.asking)} {" "}{T("· 橙色 = 卡住价格的约束")}</span></div>
      {mb.constraints.map((c, i) => {
        const bind = mb.binding?.label === c.label;
        return (
          <div className="lrow" key={`${c.source}-${c.label}`}>
            <span className="ll" title={c.label}>{c.label}</span>
            <span className="lt">
              {typeof c.price === "number" ? (<>
                {/* 段 = 要价到允许价的差：绿 = 比要价还能多出，红 = 需要折价；从要价线向外生长 */}
                <i className={`gap ${c.price >= mb.asking ? "up" : "down"}`} style={{ left: `${Math.min(ask, pos(c.price))}%`,
                  width: `${Math.abs(pos(c.price) - ask)}%`, animationDelay: `${150 + i * 90}ms` }} />
                <s className={`mk${bind ? " bind" : ""}`} style={{ left: `${pos(c.price)}%`, animationDelay: `${150 + i * 90}ms` }} />
              </>) : <em className="lx">{T("无法满足")}</em>}
              <b className="ask" style={{ left: `${ask}%` }} aria-hidden="true" />
              {trial !== null ? <b className="trial" style={{ left: `${pos(trial)}%` }} aria-hidden="true" /> : null}
            </span>
            <span className={`lv num${bind ? " bind" : ""}`}>{typeof c.price === "number" ? fmtShort(c.price) : "—"}{c.status === "above_range" ? "+" : ""}</span>
          </div>);
      })}
      <div className="lrow try">
        <label className="ll" htmlFor={`trial-${dealId}`}>{T("试算出价")}</label>
        <input id={`trial-${dealId}`} type="range" min={Math.round(lo)} max={Math.round(hi)} step={step} value={trial ?? mb.asking}
          aria-valuetext={fmt(trial ?? mb.asking, "usd")} onChange={(e) => setTrial(Number(e.target.value))} />
        <span className="lv num">{fmtShort(trial ?? mb.asking)}</span>
      </div>
      {trial !== null ? (
        <div className="trial-out" aria-live="polite">
          <span className="row" style={{ gap: 4 }}>
            <strong className="num">{fmt(trial, "usd")}</strong>
            <span className="muted">{shown?.out?.vs_asking_pct != null ? T("相对要价 {0}{1}%", [shown.out.vs_asking_pct >= 0 ? "+" : "", shown.out.vs_asking_pct.toFixed(1)]) : ""}</span>
            {!shown ? <span className="muted"><span className="live-dot" aria-hidden="true" />{T("计算中")}</span> : null}
          </span>
          {shown?.err ? <span className="neg">{shown.err}</span> : null}
          {shown?.out ? (<>
            <span className="row" style={{ gap: 12 }}>{CARD_METRICS[track].map((k) => { const meta = catalog.metrics[k]!;
              return <span key={k}><span className="muted">{meta.label}</span> <strong className="num">{fmt(shown.out!.metrics[k] ?? null, meta.unit as Unit)}</strong></span>; })}</span>
            <span className="row" style={{ gap: 6 }}>{shown.out.kill.items.map((k, i) => <Status key={i} s={k.state === "triggered" ? "risk" : k.state === "unknown" ? "building" : "verified"}>
              {k.state === "triggered" ? T("触发") : k.state === "unknown" ? T("未知") : T("通过")} · {passText(k, catalog)}</Status>)}</span>
          </>) : null}
          <button className="btn sm ghost" type="button" onClick={() => { setTrial(null); setCheck(null); }}>{T("回到要价")}</button>
        </div>) : null}
    </section>
  );
}

function MetricExplain({ metric, label, onClose }: { metric: string; label: string; onClose: () => void }) {
  const { ov, passports, openPassport, version } = useDeal();
  const rt = useApi(() => (ov.version ? call(api.GET("/api/v2/deals/{deal_id}/redteam", { params: { path: { deal_id: ov.deal.id } } })) : Promise.resolve(null)), [ov.deal.id, ov.version]);
  const keys = ((rt.data as { key_fields?: string[] } | null)?.key_fields ?? []);
  return (
    <Dialog title={T("计算说明 · {0}", [label])} onClose={onClose}>
      <p style={{ marginTop: 0 }}>{T("这是系统计算值（抽取方式：系统计算），由 v1 核保引擎按当前版本输入算出，口径由金标准测试锁定。")}</p>
      <p className="mono muted">{T("指标")}{" "}{metric} {" "}{T("· 运行编号")}{" "}{version?.run_id ?? T("—（尚未保存版本）")}</p>
      <p>{T("同一运行编号半年后重算结果分毫不差：“日志”标签页可一键校验。")}</p>
      {keys.length ? (<>
        <h3 style={{ fontSize: 15 }}>{T("驱动它的关键输入（敏感性 ≥ 100bp）")}</h3>
        <ul className="checks">{keys.map((k) => <li key={k}><span className={`status ${passportStatus(passports[k])}`}><i aria-hidden="true" />{passports[k]?.review_label ?? T("无来源")}</span>
          <button type="button" className="btn ghost sm" title={k} onClick={() => { onClose(); openPassport(k, fieldLabel(k)); }}>{fieldLabel(k)}</button></li>)}</ul></>) : null}
    </Dialog>
  );
}

/** 最高出价大字：滚动到终值；完整值放 title 与读屏文本。 */
function TweenUsd({ value }: { value: number | null | undefined }) {
  const shown = useTween(value, 900);
  return <span className="v" title={fmt(value, "usd")} aria-label={fmt(value, "usd")}>{fmt(shown === null || shown === undefined ? shown : Math.round(shown / 100) * 100, "usd")}</span>;
}

/** 淘汰条件写成“要满足的样子”：DSCR < 1.25 即放弃 → DSCR ≥ 1.25×（试算结果里读起来不反）。 */
function passText(k: { metric: string; op: string; threshold: number }, catalog: { metrics: Record<string, { label: string; unit: string } | undefined> }): string {
  const meta = catalog.metrics[k.metric];
  const flip: Record<string, string> = { "<": "≥", "<=": ">", ">": "≤", ">=": "<" };
  return `${meta?.label ?? k.metric} ${flip[k.op] ?? k.op} ${fmt(k.threshold, (meta?.unit ?? "x") as Unit)}`;
}

/**
 * 先核哪个（vertciti 独有）：待核的矛盾与关键数字按“能让主回报指标摆动多少基点”排序，只列前 3。
 * 条从 0 起画（基点是绝对量），所以长度可以直接比。
 */
function VerifyFirst({ id, version, stamp }: { id: number; version: number; stamp: string }) {
  const q = useApi<VerifyQueue>(() => call(api.GET("/api/v2/deals/{deal_id}/verify-queue", { params: { path: { deal_id: id } } })),
    [id, version, stamp]);
  if (!q.data || !q.data.items.length) return null;
  const top = q.data.items.slice(0, 3);
  const max = Math.max(1, ...top.map((x) => x.swing_bps ?? 0));
  return (
    <section className="vfirst" aria-label={T("先核哪个")}>
      <div className="ladder-head"><strong>{T("先核哪个")}</strong>
        <span className="muted">{T("按对")}{q.data.metric_label}{T("的摆动排序")}{q.data.top_share_pct != null && q.data.items.length > 1 ? T(" · 第一处占全部不确定性的 {0}%", [Math.round(q.data.top_share_pct)]) : ""}</span></div>
      <ol>
        {top.map((x, i) => (
          <li key={`${x.kind}-${x.field}`}>
            <span className="rank num">{i + 1}</span>
            <span className="what"><strong title={x.field}>{x.label}</strong>
              <span className="muted"> · {x.kind === "conflict" ? T("矛盾") : T("未达标")}{T("：")}{x.detail}</span></span>
            <span className="bar"><i style={{ width: `${((x.swing_bps ?? 0) / max) * 100}%`, animationDelay: `${120 + i * 90}ms` }} /></span>
            <span className="bps num">{x.swing_bps == null ? "—" : `${Math.round(x.swing_bps)} bp`}</span>
            <a className="btn sm" href={`#/deals/${id}/files`}>{x.action}</a>
          </li>))}
      </ol>
    </section>
  );
}
