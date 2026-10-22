// 日志：时间线（阶段、版本、证据、矛盾、投票、决策、文件）+ 版本对比（像代码 diff）+ 运行编号校验。
import { useState } from "react";
import { api, call } from "@/api/client";
import type { Event } from "@/api/types";
import { useApi } from "@/api/useApi";
import { Status, useToast } from "@/components/ui";
import { fieldLabel } from "@/domain/fields";
import { fmtDate } from "@/lib/format";
import { useDeal } from "./Deal";

const KIND: Record<string, string> = { created: "建交易", version_saved: "保存承销版本", stage_changed: "阶段变化", conflict_opened: "发现矛盾", conflict_resolved: "裁决矛盾",
  redteam_read: "红队面板已读", vote: "投票", committee_pack: "生成投委会包", decision: "决策", approval_requested: "申请审批", approval_decided: "审批决定",
  document_uploaded: "上传文件", task_done: "完成任务", kill_criteria_changed: "修改淘汰条件" };

function summary(e: Event): string {
  const p = e.payload as Record<string, unknown>;
  switch (e.kind) {
    case "stage_changed": return `${String(p.from)} → ${String(p.to)}${p.reason ? `（${String(p.reason)}）` : ""}`;
    case "version_saved": return `第 ${String(p.version_no)} 版 · ${String(p.run_id)}`;
    case "vote": return `${String(p.voter)}：${String(p.vote)}`;
    case "decision": return String(p.verdict);
    case "committee_pack": return `${String(p.kind).toUpperCase()} · sha256 ${String(p.sha256).slice(0, 12)}…`;
    case "conflict_opened": case "conflict_resolved": return String(p.field);
    case "document_uploaded": return String(p.filename);
    case "task_done": return String(p.title);
    default: return "";
  }
}

export function LogTab() {
  const { id, ov } = useDeal();
  const toast = useToast();
  const ev = useApi(() => call(api.GET("/api/v2/deals/{deal_id}/events", { params: { path: { deal_id: id }, query: { limit: 300 } } })), [id, ov.deal.updated_at]);
  const vs = useApi(() => call(api.GET("/api/v2/deals/{deal_id}/versions", { params: { path: { deal_id: id } } })), [id, ov.deal.current_version_id]);
  const [a, setA] = useState<number | null>(null);
  const [b, setB] = useState<number | null>(null);
  const diff = useApi(() => (a && b && a !== b ? call(api.GET("/api/v2/deals/{deal_id}/diff", { params: { path: { deal_id: id }, query: { a, b } } })) : Promise.resolve(null)), [id, a, b]);
  const verify = async (rid: string) => {
    try { const r = await call(api.POST("/api/v2/runs/{run_id}/verify", { params: { path: { run_id: rid } } }));
      if (r.identical) toast.ok(`运行 ${rid}：重算结果分毫不差${r.same_engine ? "" : "（引擎已升级，结果仍一致）"}`); else toast.err(new Error(`运行 ${rid}：重算结果与登记不一致（引擎 ${r.stored_engine} → ${r.current_engine}）`)); }
    catch (e) { toast.err(e); }
  };
  return (
    <div className="split">
      <section className="card" aria-label="时间线"><h2>时间线</h2>
        <ul className="timeline">{(ev.data ?? []).map((e) => <li key={e.id}><div className="when">{fmtDate(e.created_at, true)} · {e.created_by}</div>
          <strong>{KIND[e.kind] ?? e.kind}</strong> <span className="muted">{summary(e)}</span></li>)}</ul></section>
      <section className="card" aria-label="版本"><h2>承销版本</h2>
        <p className="sub">选两版看差异（假设逐项、结果随之变化）；运行编号可一键重算校验。</p>
        <div className="table-wrap" style={{ maxHeight: 360 }}><table className="t"><thead><tr><th scope="col">版</th><th scope="col">说明</th><th scope="col">A</th><th scope="col">B</th><th scope="col">运行编号</th></tr></thead>
          <tbody>{(vs.data ?? []).map((v) => <tr key={v.id}><td>{v.version_no}</td><td>{v.label}</td>
            <td><input type="radio" name="va" aria-label={`A：第 ${v.version_no} 版`} checked={a === v.id} onChange={() => setA(v.id)} /></td>
            <td><input type="radio" name="vb" aria-label={`B：第 ${v.version_no} 版`} checked={b === v.id} onChange={() => setB(v.id)} /></td>
            <td><button className="btn ghost sm mono" type="button" onClick={() => void verify(v.run_id)} title="重算校验">{v.run_id}</button></td></tr>)}</tbody></table></div>
        {diff.data ? (<>
          <h3 style={{ marginTop: 16, fontSize: 15 }}>第 {diff.data.a.version_no} 版 → 第 {diff.data.b.version_no} 版：{diff.data.changed_inputs} 项假设、{diff.data.changed_metrics} 项结果</h3>
          <div className="table-wrap" style={{ maxHeight: 360 }}><table className="t"><thead><tr><th scope="col">路径</th><th scope="col">类型</th><th scope="col" className="num">之前</th><th scope="col" className="num">之后</th></tr></thead>
            <tbody>{[...diff.data.inputs, ...diff.data.metrics.map((r) => ({ ...r, path: `结果 · ${r.path}` }))].map((r) => (
              <tr key={r.path}><td title={r.path}>{r.path.startsWith("结果 · ") ? r.path : fieldLabel(r.path)}</td><td><Status s={r.kind === "added" ? "verified" : r.kind === "removed" ? "risk" : "building"}>{r.kind === "added" ? "新增" : r.kind === "removed" ? "删除" : "修改"}</Status></td>
                <td className="num">{typeof r.before === "object" ? JSON.stringify(r.before)?.slice(0, 40) : String(r.before ?? "—")}</td>
                <td className="num">{typeof r.after === "object" ? JSON.stringify(r.after)?.slice(0, 40) : String(r.after ?? "—")}</td></tr>))}</tbody></table></div></>) : null}
      </section>
    </div>
  );
}
