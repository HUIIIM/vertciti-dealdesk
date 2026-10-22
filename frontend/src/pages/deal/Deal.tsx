// 交易页：顶部结论卡（F 型阅读起点）+ 核对进度 + 关卡；下方 10 个标签页。
// 草稿：在模型类标签页改假设 → 右侧实时重算（防抖 300ms，不保存）；⌘S 保存为新承销版本（必填“本版改了什么”）。
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, call, type OverviewOut, type PassportOut, type VersionOut } from "@/api/client";
import type { KillEval, MaxBid, Metrics } from "@/api/types";
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
import { CommitteeTab } from "./CommitteeTab";
import { FilesTab } from "./FilesTab";
import { HoldingTab } from "./HoldingTab";
import { LogTab } from "./LogTab";
import { MarketTab } from "./MarketTab";
import { ModelTab } from "./ModelTab";
import { OverviewTab } from "./OverviewTab";
import { RentRollTab } from "./RentRollTab";
import { RiskTab } from "./RiskTab";
import { T12Tab } from "./T12Tab";

export interface Preview { metrics: Metrics; detail: Record<string, unknown>; error?: string }
export interface DealCtxValue {
  id: number; track: Track; ov: OverviewOut; version: VersionOut | null; draft: JsonObj; dirty: boolean;
  set: (path: string, value: unknown) => void; replaceDraft: (d: JsonObj) => void; preview: Preview | null; previewing: boolean;
  passports: Record<string, PassportOut>; openPassport: (path: string, label: string) => void; reload: () => Promise<void>; save: () => void;
}
const DealCtx = createContext<DealCtxValue | null>(null);
export function useDeal(): DealCtxValue {
  const v = useContext(DealCtx);
  if (!v) throw new Error("useDeal 必须在交易页内使用");
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
      toast.ok(`已保存第 ${v.version_no} 版 · 运行编号 ${v.run_id}`);
      setLabel(""); setSaving(false); setEdit(null);
      await ov.reload();
    } catch (e) { toast.err(e); setSaving(false); }
  };
  const [askSave, setAskSave] = useState(false);
  const save = () => { if (!can("deal.write")) { toast.err("只读角色不能保存"); return; } if (dirty || !vid) setAskSave(true); else toast.info("没有未保存的改动"); };
  useHotkeys([
    { combo: "mod+s", label: "保存", group: "交易", allowInInput: true, run: save },
    { combo: "e", label: "编辑模型", group: "交易", run: () => navigate({ name: "deal", id, tab: "model" }) },
    ...DEAL_TABS.map(([k], i) => ({ combo: String((i + 1) % 10), label: k, group: "标签", run: () => navigate({ name: "deal", id, tab: k }) })),
  ], !askSave && !passport);
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const mb = useMaxBid(id, Boolean(ov.data?.version), ov.data?.kill as unknown as KillEval | undefined);
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
        <section className={`verdict-card ${kill.triggered.length ? "risk" : kill.clear ? "ok" : ""}`} aria-label="结论卡">
          <p className="eyebrow">{d.track === "commercial" ? "商业" : "住宅"} · {d.stage_label}{o.version ? ` · 第 ${(o.version as { version_no: number }).version_no} 版` : " · 尚未承销"}</p>
          <h1>{d.name}</h1>
          <div className="muted" style={{ fontSize: 14 }}>{d.address || "地址未填"}</div>
          <div className="maxbid">
            <span className="muted" style={{ fontWeight: 800, fontSize: 13 }}>结论</span>
            <Status s={killStatus(kill)}>{kill.triggered.length ? `触发淘汰 ${kill.triggered.length} 条` : kill.unknown.length ? "淘汰条件无法判定" : kill.clear ? "淘汰条件未触发" : "未承销"}</Status>
            {o.last_verdict ? <span className="chip">最近决策 {o.last_verdict}</span> : null}
            <MaxBidInline mb={mb} hasVersion={Boolean(o.version)} dirty={dirty} />
          </div>
          <MetricGrid count={metricKeys.length} style={{ marginTop: 8 }}>
            {metricKeys.map((k) => { const meta = catalog.metrics[k]!;
              return <Metric key={k} label={meta.label} value={m[k] ?? null} unit={meta.unit as Unit} testId={`metric-${k}`}
                note={dirty ? "草稿重算" : undefined} onOpen={() => setPassport({ path: `metric:${k}`, label: meta.label })} />; })}
          </MetricGrid>
          {kill.items.length ? (
            <ul className="checks" style={{ marginTop: 12 }} aria-label="淘汰条件">
              {kill.items.map((k, i) => <li key={i}><Status s={k.state === "triggered" ? "risk" : k.state === "unknown" ? "building" : "verified"}>
                {k.state === "triggered" ? "触发" : k.state === "unknown" ? "未知" : "未触发"}</Status><span>{k.text}<span className="muted"> · 当前 {fmt(k.value, (catalog.metrics[k.metric]?.unit ?? "x") as Unit)}</span></span></li>)}
            </ul>) : <div className="banner warn" style={{ marginTop: 12 }}>还没写淘汰条件：进入承销前必须先写“什么情况下放弃”。</div>}
          {mb.data && o.version ? <PriceLadder mb={mb.data} /> : null}
          <ol className="stepper" aria-label="阶段" style={{ marginTop: "auto", paddingTop: 16 }}>
            {STAGES.map(([s, l], i) => <li key={s} className={i < stageIdx ? "done" : i === stageIdx ? "current" : ""} aria-current={i === stageIdx ? "step" : undefined}>{l}</li>)}
          </ol>
        </section>
        <section className="card" aria-label="核对进度">
          <h2>核对进度</h2>
          <p className="sub">关键数字由红队面板的敏感性客观定义（±10% 让主回报移动 ≥ 100bp）</p>
          <div className="row" style={{ justifyContent: "space-between" }}><span>关键数字已复核</span><strong className="num">{ver_.key_reviewed} / {ver_.key_total}</strong></div>
          <div className="progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="关键数字复核进度"><span style={{ width: `${pct}%` }} /></div>
          <ul className="checks" style={{ marginTop: 8 }}>
            <li><Status s={ver_.open_conflicts ? "risk" : "verified"}>{ver_.open_conflicts ? `${ver_.open_conflicts} 条` : "无"}</Status><span>未裁决的跨来源矛盾</span></li>
            <li><Status s={ver_.stale_evidence ? "risk" : ver_.review_due ? "building" : "verified"}>{ver_.stale_evidence ? `${ver_.stale_evidence} 条停用` : ver_.review_due ? `${ver_.review_due} 条待复核` : "新鲜"}</Status><span>证据新鲜度（14 天待复核 / 30 天停用）</span></li>
            <li><Status s={ver_.redteam_read ? "verified" : "planned"}>{ver_.redteam_read ? "已读" : "未读"}</Status><span>红队面板（当前版本）</span></li>
          </ul>
          {o.next_gate ? (<>
            <h3 style={{ marginTop: 16, fontSize: 15 }}>进入「{STAGES.find(([s]) => s === o.next_stage)?.[1]}」的关卡</h3>
            <ul className="checks">{(o.next_gate.checks ?? []).map((c) => <li key={c.key}><Status s={c.status}>{c.status_label}</Status><span>{c.label}{c.detail ? <div className="d">{c.detail}</div> : null}</span></li>)}</ul>
          </>) : null}
          {can("deal.advance") ? <div style={{ marginTop: 12 }}><a className="btn sm" href={`#/deals/${id}`}>去推进阶段 →</a></div> : null}
        </section>
      </div>
      <nav className="tabs" role="tablist" aria-label="交易标签页">
        {DEAL_TABS.map(([k, l], i) => <a key={k} role="tab" aria-selected={tab === k} href={k === "overview" ? `#/deals/${id}` : `#/deals/${id}/${k}`}
          title={`快捷键 ${(i + 1) % 10}`}>{l}</a>)}
      </nav>
      <div role="tabpanel" aria-label={DEAL_TABS.find(([k]) => k === tab)?.[1]}>
        {tab === "overview" ? <OverviewTab /> : tab === "rentroll" ? <RentRollTab /> : tab === "t12" ? <T12Tab /> : tab === "model" ? <ModelTab />
          : tab === "risk" ? <RiskTab /> : tab === "market" ? <MarketTab /> : tab === "files" ? <FilesTab /> : tab === "committee" ? <CommitteeTab />
          : tab === "holding" ? <HoldingTab /> : <LogTab />}
      </div>
      {dirty ? (
        <div className="draftbar" role="region" aria-label="未保存的草稿">
          <span>{previewing ? <span className="live-dot" aria-hidden="true" /> : null}草稿有改动 · 结果为实时重算{previewing ? "（计算中…）" : ""}{preview?.error ? ` · ${preview.error}` : ""}</span>
          <span style={{ flex: 1 }} />
          <button className="btn sm" type="button" onClick={() => setEdit(null)}>放弃改动</button>
          {can("deal.write") ? <button className="btn sm primary" type="button" onClick={save}>保存为新版本 <Kbd k="⌘ S" /></button> : null}
        </div>) : !vid && can("deal.write") ? (
        <div className="draftbar"><span>还没有承销版本：在“租金表 / T12 / 模型”填好假设后保存第一版</span><span style={{ flex: 1 }} />
          <button className="btn sm primary" type="button" onClick={save}>保存第一版 <Kbd k="⌘ S" /></button></div>) : null}
      {askSave ? (
        <Dialog title="保存承销版本" onClose={() => setAskSave(false)} footer={<>
          <button className="btn ghost" type="button" onClick={() => setAskSave(false)}>取消</button>
          <button className="btn primary" type="button" disabled={saving} onClick={async () => { await doSave(); setAskSave(false); }}>{saving ? "保存中…" : "保存"}</button></>}>
          <label className="field">本版改了什么、为什么<span className="hint">写进投委会包“自上一版起改了什么”</span>
            <input className="input" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="如：退出 cap 按可比上调 50bp" maxLength={200}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void doSave().then(() => setAskSave(false)); } }} /></label>
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
function useMaxBid(id: number, hasVersion: boolean, kill: KillEval | undefined) {
  const targets = (kill?.items ?? []).filter((k) => k.op === "<" || k.op === "<=").map((k) => ({ metric: k.metric, min: k.threshold }));
  return useApi<MaxBid | null>(() => (hasVersion && targets.length ? call(api.POST("/api/v2/deals/{deal_id}/max-bid", {
    params: { path: { deal_id: id } }, body: { targets: [], include_kill_criteria: true } })) : Promise.resolve(null)),
  [id, hasVersion, JSON.stringify(targets)]);
}

function MaxBidInline({ mb, hasVersion, dirty }: { mb: ReturnType<typeof useMaxBid>; hasVersion: boolean; dirty: boolean }) {
  if (!hasVersion) return null;
  if (mb.loading && !mb.data) return <span className="muted">最高出价计算中…</span>;
  if (!mb.data) return <span className="muted">最高出价：需下限型淘汰条件</span>;
  return (
    <span style={{ display: "inline-flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }} data-testid="max-bid">
      <span className="muted" style={{ fontWeight: 800, fontSize: 13 }}>最高出价</span>
      <TweenUsd value={mb.data.max_bid} />
      <span className="muted" style={{ fontSize: 13 }}>{mb.data.binding ? `卡在：${mb.data.binding.label}` : ""}{dirty ? " · 按已保存版本" : ""}</span>
    </span>
  );
}

/**
 * 出价空间（vertciti 独有）：每条约束各自允许的最高价画成一个点，竖线是要价，点与竖线之间的段是差额。
 * 坐标轴为放大的价格区间（不从 0 开始），所以用点与差额段而不用从 0 起的长条——避免夸大差异。
 * 一眼看出哪条约束卡住价格（橙色）、离要价还差多少；无法满足的约束写明，不画假条。
 */
export function PriceLadder({ mb }: { mb: MaxBid }) {
  const priced = mb.constraints.map((c) => c.price).filter((v): v is number => typeof v === "number");
  if (!priced.length) return null;
  const vals = [mb.asking, ...priced];
  const lo = Math.min(...vals) * 0.85, hi = Math.max(...vals) * 1.04;
  const pos = (v: number) => Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100));
  const ask = pos(mb.asking);
  return (
    <section className="ladder" aria-label="出价空间">
      <div className="ladder-head"><strong>出价空间</strong><span className="muted">方块 = 该约束允许的最高价 · 竖线 = 要价 {fmtShort(mb.asking)} · 橙色 = 卡住价格的约束</span></div>
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
              </>) : <em className="lx">无法满足</em>}
              <b className="ask" style={{ left: `${ask}%` }} aria-hidden="true" />
            </span>
            <span className={`lv num${bind ? " bind" : ""}`}>{typeof c.price === "number" ? fmtShort(c.price) : "—"}{c.status === "above_range" ? "+" : ""}</span>
          </div>);
      })}
    </section>
  );
}

function MetricExplain({ metric, label, onClose }: { metric: string; label: string; onClose: () => void }) {
  const { ov, passports, openPassport, version } = useDeal();
  const rt = useApi(() => (ov.version ? call(api.GET("/api/v2/deals/{deal_id}/redteam", { params: { path: { deal_id: ov.deal.id } } })) : Promise.resolve(null)), [ov.deal.id, ov.version]);
  const keys = ((rt.data as { key_fields?: string[] } | null)?.key_fields ?? []);
  return (
    <Dialog title={`计算说明 · ${label}`} onClose={onClose}>
      <p style={{ marginTop: 0 }}>这是系统计算值（抽取方式：系统计算），由 v1 核保引擎按当前版本输入算出，口径由金标准测试锁定。</p>
      <p className="mono muted">指标 {metric} · 运行编号 {version?.run_id ?? "—（尚未保存版本）"}</p>
      <p>同一运行编号半年后重算结果分毫不差：“日志”标签页可一键校验。</p>
      {keys.length ? (<>
        <h3 style={{ fontSize: 15 }}>驱动它的关键输入（敏感性 ≥ 100bp）</h3>
        <ul className="checks">{keys.map((k) => <li key={k}><span className={`status ${passportStatus(passports[k])}`}><i aria-hidden="true" />{passports[k]?.review_label ?? "无来源"}</span>
          <button type="button" className="btn ghost sm" title={k} onClick={() => { onClose(); openPassport(k, fieldLabel(k)); }}>{fieldLabel(k)}</button></li>)}</ul></>) : null}
    </Dialog>
  );
}

/** 最高出价大字：滚动到终值；完整值放 title 与读屏文本。 */
function TweenUsd({ value }: { value: number | null | undefined }) {
  const shown = useTween(value, 900);
  return <span className="v" title={fmt(value, "usd")} aria-label={fmt(value, "usd")}>{fmt(shown === null || shown === undefined ? shown : Math.round(shown / 100) * 100, "usd")}</span>;
}
