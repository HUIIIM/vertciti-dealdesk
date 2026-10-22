import { useState } from "react";
import { api, ApiError, call, type GateOut } from "@/api/client";
import type { Approval, Task } from "@/api/types";
import { optimistic, useApi } from "@/api/useApi";
import { useApp } from "@/app-context";
import { Empty, Status, useToast } from "@/components/ui";
import { STAGES } from "@/domain/fields";
import { fmt, fmtDate } from "@/lib/format";
import { useDeal } from "./Deal";

export function OverviewTab() {
  const { id, ov, reload } = useDeal();
  const { can } = useApp();
  const toast = useToast();
  const [reason, setReason] = useState("");
  const [blocked, setBlocked] = useState<GateOut | null>(null);
  const d = ov.deal;
  const idx = STAGES.findIndex(([s]) => s === d.stage);
  const advance = async (target: string) => {
    try {
      await call(api.POST("/api/v2/deals/{deal_id}/stage", { params: { path: { deal_id: id } }, body: { target: target as "screening", reason } }));
      toast.ok(`已进入「${STAGES.find(([s]) => s === target)?.[1] ?? "已放弃"}」`); setBlocked(null); setReason(""); await reload();
    } catch (e) {
      if (e instanceof ApiError && e.gate) setBlocked(e.gate as GateOut);
      toast.err(e);
    }
  };
  return (
    <div className="split">
      <div>
        <section className="card" aria-label="阶段推进">
          <h2>阶段推进</h2>
          <p className="sub">只能逐级前进；每一级都有关卡。回退不设关卡，但必须写原因（记入日志）。</p>
          {ov.next_stage ? (
            <div className="row">
              {can("deal.advance") ? <button className="btn primary" type="button" onClick={() => advance(ov.next_stage!)}>
                推进到「{STAGES.find(([s]) => s === ov.next_stage)?.[1]}」</button> : null}
              {ov.next_gate && !ov.next_gate.allowed ? <Status s="building">关卡未通过</Status> : <Status s="verified">关卡已满足</Status>}
            </div>) : <p>已在最后阶段。</p>}
          {blocked ? <ul className="checks" style={{ marginTop: 12 }}>{(blocked.checks ?? []).filter((c) => !c.ok).map((c) =>
            <li key={c.key}><Status s={c.status}>{c.status_label}</Status><span>{c.label}{c.detail ? <div className="d">{c.detail}</div> : null}</span></li>)}</ul> : null}
          {can("deal.advance") ? <details style={{ marginTop: 16 }}>
            <summary style={{ cursor: "pointer", fontWeight: 700 }}>回退或放弃</summary>
            <div style={{ display: "grid", gap: 8, marginTop: 8 }}>
              <label className="field">原因（必填）<input className="input" value={reason} onChange={(e) => setReason(e.target.value)} /></label>
              <div className="row">
                {STAGES.slice(0, Math.max(idx, 0)).map(([s, l]) => <button key={s} className="btn sm" type="button" disabled={!reason.trim()} onClick={() => advance(s)}>回到{l}</button>)}
                <button className="btn sm danger" type="button" onClick={() => advance("passed")}>放弃这笔交易</button>
              </div>
              <p className="muted" style={{ fontSize: 13, margin: 0 }}>放弃前须先在右侧记一条 PASS 决策（理由 + 当时的数字快照），便于复盘。</p>
            </div>
          </details> : null}
        </section>
        <Tasks />
        <Approvals />
      </div>
      <Decisions />
    </div>
  );
}

function Decisions() {
  const { id, reload } = useDeal();
  const { can } = useApp();
  const toast = useToast();
  const list = useApi(() => call(api.GET("/api/v2/deals/{deal_id}/decisions", { params: { path: { deal_id: id } } })), [id]);
  const [verdict, setVerdict] = useState<"BUY" | "HOLD" | "PASS">("HOLD");
  const [why, setWhy] = useState("");
  const submit = async () => {
    try {
      await call(api.POST("/api/v2/deals/{deal_id}/decisions", { params: { path: { deal_id: id } }, body: { verdict, rationale: why } }));
      toast.ok(`已记 ${verdict}：数字快照与运行编号已冻结`); setWhy(""); await Promise.all([list.reload(), reload()]);
    } catch (e) { toast.err(e); }
  };
  return (
    <section className="card" aria-label="决策日志">
      <h2>决策日志</h2>
      <p className="sub">每个 BUY / HOLD / PASS 记录理由与当时的数字快照：复盘看的是当时原样，不是今天重算的结果。</p>
      {can("decision.write") ? (
        <form onSubmit={(e) => { e.preventDefault(); void submit(); }} style={{ display: "grid", gap: 8, marginBottom: 16 }}>
          <div className="seg" role="group" aria-label="结论">
            {(["BUY", "HOLD", "PASS"] as const).map((v) => <button key={v} type="button" aria-pressed={verdict === v} onClick={() => setVerdict(v)}>{v}</button>)}
          </div>
          <label className="field">理由（至少 10 个字）<textarea className="input" rows={3} value={why} onChange={(e) => setWhy(e.target.value)} /></label>
          <div><button className="btn primary" type="submit" disabled={why.trim().length < 10}>记录决策</button></div>
        </form>) : null}
      {list.data?.length ? (
        <ul className="timeline">{list.data.map((x) => {
          const snap = x.snapshot as { metrics?: Record<string, number | null>; version_no?: number };
          return (<li key={x.id}><div className="when">{fmtDate(x.created_at, true)} · {x.created_by} · {x.stage}</div>
            <strong>{x.verdict}</strong> {x.rationale}
            <div className="muted mono" style={{ fontSize: 12 }}>第 {snap.version_no ?? "—"} 版 · {x.run_id ?? "无运行"} · DSCR {fmt(snap.metrics?.dscr, "x")} · IRR {fmt(snap.metrics?.irr_pct, "pct")}</div></li>); })}</ul>
      ) : <Empty title="还没有决策记录" />}
    </section>
  );
}

function Tasks() {
  const { id, ov, reload } = useDeal();
  const { can } = useApp();
  const toast = useToast();
  const list = useApi(() => call(api.GET("/api/v2/deals/{deal_id}/tasks", { params: { path: { deal_id: id } } })), [id]);
  const [title, setTitle] = useState("");
  const toggle = (t: Task) => optimistic(
    () => list.setData((xs) => xs?.map((x) => (x.id === t.id ? { ...x, status: t.status === "done" ? "open" : "done" } : x))),
    () => list.setData((xs) => xs?.map((x) => (x.id === t.id ? t : x))),
    () => call(api.PATCH("/api/v2/deals/{deal_id}/tasks/{task_id}", { params: { path: { deal_id: id, task_id: t.id } }, body: { status: t.status === "done" ? "open" : "done" } })),
  ).then(() => reload()).catch(toast.err);
  const add = async () => {
    try { await call(api.POST("/api/v2/deals/{deal_id}/tasks", { params: { path: { deal_id: id } }, body: { title, stage: ov.deal.stage, assignee: "", due: "" } }));
      setTitle(""); await list.reload(); } catch (e) { toast.err(e); }
  };
  return (
    <section className="card flat" aria-label="任务">
      <h2>任务</h2>
      {list.data?.length ? <ul className="checks">{list.data.map((t) => (
        <li key={t.id}><input type="checkbox" checked={t.status === "done"} disabled={!can("task.write")} onChange={() => void toggle(t)} aria-label={`完成：${t.title}`} style={{ width: 20, height: 20 }} />
          <span style={{ textDecoration: t.status === "done" ? "line-through" : undefined }}>{t.title}<div className="d">{STAGES.find(([s]) => s === t.stage)?.[1] ?? t.stage}{t.due ? ` · 截止 ${t.due}` : ""}</div></span></li>))}</ul>
        : <p className="muted">还没有任务。尽调、交割阶段的任务全部完成才能推进。</p>}
      {can("task.write") ? <form className="row" style={{ marginTop: 8 }} onSubmit={(e) => { e.preventDefault(); if (title.trim()) void add(); }}>
        <input className="input" style={{ flex: 1 }} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="加任务（归入当前阶段）" aria-label="新任务" />
        <button className="btn" type="submit">添加</button></form> : null}
    </section>
  );
}

function Approvals() {
  const { id, reload } = useDeal();
  const { can, me } = useApp();
  const toast = useToast();
  const list = useApi(() => call(api.GET("/api/v2/deals/{deal_id}/approvals", { params: { path: { deal_id: id } } })), [id]);
  const [amount, setAmount] = useState("");
  const [title, setTitle] = useState("定金");
  const decide = async (a: Approval, approve: boolean) => {
    try { await call(api.POST("/api/v2/deals/{deal_id}/approvals/{approval_id}/decide", { params: { path: { deal_id: id, approval_id: a.id } }, body: { approve, note: "" } }));
      toast.ok(approve ? "已批准" : "已驳回"); await Promise.all([list.reload(), reload()]); } catch (e) { toast.err(e); }
  };
  const request = async () => {
    try { await call(api.POST("/api/v2/deals/{deal_id}/approvals", { params: { path: { deal_id: id } }, body: { kind: "payment", title, amount: Number(amount.replace(/,/g, "")), note: "" } }));
      setAmount(""); await list.reload(); } catch (e) { toast.err(e); }
  };
  return (
    <section className="card flat" aria-label="审批">
      <h2>审批</h2>
      <p className="sub">付款类动作只能由董事长批准；任何人不能审批自己发起的申请。</p>
      {list.data?.length ? <ul className="checks">{list.data.map((a) => (
        <li key={a.id}><Status s={a.status === "approved" ? "verified" : a.status === "rejected" ? "risk" : "building"}>{a.status === "approved" ? "已批准" : a.status === "rejected" ? "已驳回" : "待批"}</Status>
          <span>{a.kind === "payment" ? "付款" : "审批"} · {a.title}{a.amount ? ` · ${fmt(a.amount, "usd")}` : ""}<div className="d">发起 {a.created_by}{a.decided_by ? ` · 决定 ${a.decided_by}` : ""}</div>
            {a.status === "pending" && can(a.kind === "payment" ? "payment.approve" : "approval.decide") && (a.created_by !== me.username || me.username === "local") ? (
              <span className="row" style={{ marginTop: 4 }}><button className="btn sm primary" type="button" onClick={() => void decide(a, true)}>批准</button>
                <button className="btn sm" type="button" onClick={() => void decide(a, false)}>驳回</button></span>) : null}</span></li>))}</ul>
        : <p className="muted">暂无审批。</p>}
      {can("approval.request") ? <form className="row" style={{ marginTop: 8 }} onSubmit={(e) => { e.preventDefault(); void request(); }}>
        <input className="input" style={{ width: 140 }} value={title} onChange={(e) => setTitle(e.target.value)} aria-label="付款事项" />
        <input className="input num" style={{ width: 160 }} value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" placeholder="金额 $" aria-label="金额" required />
        <button className="btn" type="submit">申请付款</button></form> : null}
    </section>
  );
}
