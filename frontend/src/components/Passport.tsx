// 数字护照：点开任一数字，看到来源文件第几页、抽取方式、可信度、复核、新鲜度、谁在何时改过；可登记新来源、标复核。
import { useState } from "react";
import { api, ApiError, call, type PassportDetail } from "@/api/client";
import { useApi } from "@/api/useApi";
import { useApp } from "@/app-context";
import { Dialog, ErrorBox, Skeleton, Status, useToast, type StatusKey } from "@/components/ui";
import { fmtDate } from "@/lib/format";

export function passportStatus(p: { review_status?: string; confidence?: string; freshness?: { state?: string } } | undefined): StatusKey {
  if (!p) return "planned";
  if (p.freshness?.state === "stale") return "risk";
  if (p.review_status === "pending" || p.freshness?.state === "review") return "building";
  return p.confidence === "low" ? "building" : "verified";
}

export function PassportDialog({ dealId, field, label, currentValue, onClose, onChanged }: {
  dealId: number; field: string; label: string; currentValue: unknown; onClose: () => void; onChanged: () => void;
}) {
  const { can } = useApp();
  const toast = useToast();
  const p = useApi<PassportDetail | null>(async () => {
    try { return await call(api.GET("/api/v2/deals/{deal_id}/passport", { params: { path: { deal_id: dealId }, query: { field } } })); }
    catch (e) { if (e instanceof ApiError && e.status === 404) return null; throw e; }
  }, [dealId, field]);
  const [form, setForm] = useState({ source: "", page: "", method: "pdf", confidence: "high", assumption_source: "document", evidence_at: "", market_data: false, note: "" });
  const submit = async () => {
    try {
      const r = await call(api.POST("/api/v2/deals/{deal_id}/evidence", { params: { path: { deal_id: dealId } }, body: {
        field, value: currentValue as never, source: form.source, method: form.method as "pdf", confidence: form.confidence as "high",
        page: form.page ? Number(form.page) : null, evidence_at: form.evidence_at || null, market_data: form.market_data,
        assumption_source: form.assumption_source as "document", note: form.note } }));
      toast.ok(r.conflict ? "已登记；与另一来源数值不一致，已开一条矛盾待裁决" : "来源已登记");
      await p.reload(); onChanged();
    } catch (e) { toast.err(e); }
  };
  const review = async () => {
    try { await call(api.POST("/api/v2/deals/{deal_id}/review", { params: { path: { deal_id: dealId } }, body: { field, note: "" } }));
      toast.ok("已标记复核"); await p.reload(); onChanged(); } catch (e) { toast.err(e); }
  };
  const cur = p.data?.current;
  return (
    <Dialog title={`数字护照 · ${label}`} onClose={onClose} wide>
      <p className="mono muted" style={{ marginTop: 0 }}>{field}</p>
      {p.error ? <ErrorBox error={p.error} /> : null}
      {p.loading && p.data === undefined ? <Skeleton /> : null}
      {p.data === null ? <div className="banner warn">这个数字还没有来源记录。未知保持未知：请登记它来自哪份文件第几页，或标明是分析师判断。</div> : null}
      {cur ? (
        <div className="card flat">
          <div className="row" style={{ marginBottom: 8 }}>
            <Status s={passportStatus(cur)}>{cur.review_label}</Status>
            <span className="chip">可信度 {cur.confidence_label}</span><span className="chip">{cur.method_label}</span>
            <span className="chip">{cur.assumption_source_label as string}</span>
            <span className="chip">{(cur.freshness as { label: string }).label}</span>
          </div>
          <p style={{ margin: 0 }}><strong>来源：</strong>{cur.source}{cur.page ? ` · 第 ${cur.page} 页` : ""} · 值 {String(cur.value)}</p>
          <p className="muted" style={{ margin: "4px 0 0", fontSize: 13 }}>登记 {cur.created_by} · {fmtDate(cur.created_at, true)}
            {cur.reviewed_by ? ` · 复核 ${String(cur.reviewed_by)} ${fmtDate(cur.reviewed_at as string, true)}` : ""}</p>
          {can("deal.write") && cur.review_status === "pending" ? <button className="btn sm" type="button" style={{ marginTop: 8 }} onClick={review}>标记已复核</button> : null}
        </div>) : null}
      {p.data && p.data.history.length > 1 ? (<>
        <h3 style={{ fontSize: 15 }}>修改历史</h3>
        <ul className="timeline">{p.data.history.map((h) => (
          <li key={h.id}><div className="when">{fmtDate(h.created_at, true)} · {h.created_by}</div>{String(h.value)} ← {h.source}{h.page ? ` p.${h.page}` : ""}（{h.method_label} · {h.confidence_label}）</li>))}</ul></>) : null}
      {p.data && p.data.conflicts.length ? (<>
        <h3 style={{ fontSize: 15 }}>跨来源矛盾</h3>
        {p.data.conflicts.map((c) => { const x = c as { id: number; source_a: string; value_a: unknown; source_b: string; value_b: unknown; status: string; resolution_note: string };
          return <div key={x.id} className={`banner ${x.status === "open" ? "warn" : "ok"}`}>{x.source_a}：{String(x.value_a)} vs {x.source_b}：{String(x.value_b)} · {x.status === "open" ? "待裁决" : `已裁决：${x.resolution_note}`}</div>; })}</>) : null}
      {can("deal.write") ? (
        <form className="card flat" onSubmit={(e) => { e.preventDefault(); void submit(); }} style={{ display: "grid", gap: 12 }}>
          <h3 style={{ margin: 0, fontSize: 15 }}>登记来源（当前值 {String(currentValue ?? "—")}）</h3>
          <div className="grid-form">
            <label className="field">来源<input className="input" required value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} placeholder="如 OM、T12、经纪人邮件" /></label>
            <label className="field">页码<input className="input num" inputMode="numeric" value={form.page} onChange={(e) => setForm({ ...form, page: e.target.value })} /></label>
            <label className="field">抽取方式<select className="input" value={form.method} onChange={(e) => setForm({ ...form, method: e.target.value })}>
              <option value="pdf">PDF 抽取</option><option value="ocr">OCR 识别</option><option value="api">接口拉取</option><option value="manual">人工录入</option><option value="import">导入</option></select></label>
            <label className="field">可信度<select className="input" value={form.confidence} onChange={(e) => setForm({ ...form, confidence: e.target.value })}>
              <option value="high">高</option><option value="medium">中</option><option value="low">低</option></select></label>
            <label className="field">假设来源<select className="input" value={form.assumption_source} onChange={(e) => setForm({ ...form, assumption_source: e.target.value })}>
              <option value="document">文件抽取</option><option value="historical">历史数据</option><option value="benchmark">市场基准</option><option value="comps">可比交易</option><option value="analyst">分析师判断</option></select></label>
            <label className="field">证据日期<input className="input" type="date" value={form.evidence_at} onChange={(e) => setForm({ ...form, evidence_at: e.target.value })} /></label>
          </div>
          <label className="row" style={{ fontSize: 14 }}><input type="checkbox" checked={form.market_data} onChange={(e) => setForm({ ...form, market_data: e.target.checked })} />市场数据（超过 14 天标黄待复核，30 天停用）</label>
          <div><button className="btn primary" type="submit">登记</button></div>
        </form>) : null}
    </Dialog>
  );
}
