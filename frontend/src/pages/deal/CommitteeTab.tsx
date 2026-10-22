// 投委会：计票（董事长一票否决）、投票、一键生成投委会包（PDF / Excel）、原件校验（哈希登记）。
import { T } from "@/i18n";
import { useRef, useState } from "react";
import { api, call, raw } from "@/api/client";
import type { Verify } from "@/api/types";
import { useApi } from "@/api/useApi";
import { useApp } from "@/app-context";
import { Empty, Status, useToast } from "@/components/ui";
import { fmtDate } from "@/lib/format";
import { useDeal } from "./Deal";

export function CommitteeTab() {
  const { id, ov, reload } = useDeal();
  const { can } = useApp();
  const toast = useToast();
  const hasV = Boolean(ov.version);
  const st = useApi(() => (hasV ? call(api.GET("/api/v2/deals/{deal_id}/committee", { params: { path: { deal_id: id } } })) : Promise.resolve(null)), [id, hasV, ov.deal.current_version_id]);
  const packs = useApi(() => call(api.GET("/api/v2/deals/{deal_id}/committee/packs", { params: { path: { deal_id: id } } })), [id]);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [verify, setVerify] = useState<Verify | null>(null);
  const vf = useRef<HTMLInputElement>(null);
  if (!hasV) return <Empty title={T("还没有承销版本")}>{T("投委会对“当前版本”表决；先保存一版承销。")}</Empty>;
  const vote = async (v: "approve" | "reject" | "abstain") => {
    try { await call(api.POST("/api/v2/deals/{deal_id}/committee/vote", { params: { path: { deal_id: id } }, body: { vote: v, comment } }));
      toast.ok(T("已投票")); setComment(""); await Promise.all([st.reload(), reload()]); } catch (e) { toast.err(e); }
  };
  const gen = async (kind: "pdf" | "xlsx") => {
    setBusy(kind);
    try {
      const r = await raw(`/api/v2/deals/${id}/committee/pack.${kind}`);
      const url = URL.createObjectURL(await r.blob());
      const a = document.createElement("a"); a.href = url; a.download = `DealDesk-IC-${id}.${kind}`; a.click(); URL.revokeObjectURL(url);
      toast.ok(T("投委会包已生成 · sha256 {0}…", [r.headers.get("x-content-sha256")?.slice(0, 12)])); await packs.reload(); await reload();
    } catch (e) { toast.err(e); } finally { setBusy(null); }
  };
  const doVerify = async (f: File) => {
    const fd = new FormData(); fd.append("file", f);
    try { setVerify(await (await raw("/api/v2/committee/verify", { method: "POST", body: fd })).json() as Verify); } catch (e) { toast.err(e); }
  };
  const t = st.data?.tally;
  return (
    <div className="split">
      <div>
        <section className={`card ${t?.result === "approved" ? "ok" : t?.result === "rejected" ? "risk" : ""}`} aria-label={T("表决")}>
          <h2>{T("投委会表决")}</h2><p className="sub">{st.data?.rules}</p>
          {t ? <p style={{ fontSize: 18 }}><Status s={t.result === "approved" ? "verified" : t.result === "rejected" ? "risk" : "building"}>{t.result === "approved" ? T("通过") : t.result === "rejected" ? T("不通过") : T("待定")}</Status>
            <span style={{ marginLeft: 8 }}>{t.why} {" "}{T("· 赞成")}{" "}{t.approve} {" "}{T("· 反对")}{" "}{t.reject} {" "}{T("· 弃权")}{" "}{t.abstain}</span></p> : null}
          {ov.deal.stage === "committee" && can("committee.vote") ? (
            <div style={{ display: "grid", gap: 8 }}>
              <label className="field">{T("意见")}<textarea className="input" rows={2} value={comment} onChange={(e) => setComment(e.target.value)} /></label>
              <div className="row"><button className="btn primary" type="button" onClick={() => void vote("approve")}>{T("赞成")}</button>
                <button className="btn danger" type="button" onClick={() => void vote("reject")}>{T("反对")}</button>
                <button className="btn" type="button" onClick={() => void vote("abstain")}>{T("弃权")}</button></div></div>)
            : <p className="muted">{ov.deal.stage === "committee" ? T("只读角色不能投票。") : T("交易进入“投委会”阶段后才能投票。")}</p>}
          {st.data?.votes.length ? <ul className="timeline" style={{ marginTop: 16 }}>{st.data.votes.map((v) => <li key={v.id}><div className="when">{fmtDate(v.created_at, true)} · {v.role_label}</div>
            <strong>{v.voter}</strong> {v.vote === "approve" ? T("赞成") : v.vote === "reject" ? T("反对") : T("弃权")}{v.comment ? T("：{0}", [v.comment]) : ""}</li>)}</ul> : null}
        </section>
      </div>
      <section className="card" aria-label={T("投委会包")}>
        <h2>{T("投委会包")}</h2><p className="sub">{T("投资备忘录 + 关键图表 + 风险清单 + 投票记录；印运行编号与内容摘要，文件哈希登记在案。")}</p>
        <div className="row">
          <button className="btn primary" type="button" disabled={!can("committee.package") || busy !== null} onClick={() => void gen("pdf")}>{busy === "pdf" ? T("生成中…") : T("生成 PDF")}</button>
          <button className="btn" type="button" disabled={!can("committee.package") || busy !== null} onClick={() => void gen("xlsx")}>{busy === "xlsx" ? T("生成中…") : T("生成 Excel")}</button>
        </div>
        <h3 style={{ marginTop: 20, fontSize: 15 }}>{T("校验一份包是不是原件")}</h3>
        <input ref={vf} type="file" className="sr-only" aria-label={T("选择要校验的文件")} onChange={(e) => { const f = e.target.files?.[0]; if (f) void doVerify(f); e.target.value = ""; }} />
        <button className="btn sm" type="button" onClick={() => vf.current?.click()}>{T("上传 PDF / Excel 校验")}</button>
        {verify ? <div className={`banner ${verify.genuine ? "ok" : "risk"}`} style={{ marginTop: 8 }} role="status">{verify.message}<div className="mono muted" style={{ fontSize: 12 }}>sha256 {verify.sha256}</div></div> : null}
        {packs.data?.length ? (<><h3 style={{ marginTop: 20, fontSize: 15 }}>{T("已生成")}</h3>
          <ul className="checks">{packs.data.map((p) => <li key={p.id}><span className="chip">{p.kind.toUpperCase()}</span>
            <span className="mono" style={{ fontSize: 12 }}>{p.sha256.slice(0, 24)}…<div className="d">{p.run_id} · {p.created_by} · {fmtDate(p.created_at, true)}</div></span></li>)}</ul></>) : null}
      </section>
    </div>
  );
}
