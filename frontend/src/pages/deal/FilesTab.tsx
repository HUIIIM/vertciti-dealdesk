// 文件与证据：交易文件（SHA-256 存证）、全部数字护照、跨来源矛盾登记（裁决须写理由）。
import { T } from "@/i18n";
import { useRef, useState } from "react";
import { api, call, raw } from "@/api/client";
import type { ConflictRow, Doc, Extract } from "@/api/types";
import { useApi } from "@/api/useApi";
import { useApp } from "@/app-context";
import { Candidates } from "@/components/Candidates";
import { passportStatus } from "@/components/Passport";
import { Empty, Status, useToast } from "@/components/ui";
import { fieldLabel } from "@/domain/fields";
import { fmtDate } from "@/lib/format";
import { useAdopt } from "./adopt";
import { useDeal } from "./Deal";
import { tenantsToLeases } from "./InstTabs";

export function FilesTab() {
  const { id, track, draft, set, passports, openPassport, reload } = useDeal();
  const adopt = useAdopt();
  const [ex, setEx] = useState<Extract | null>(null);
  const [extracting, setExtracting] = useState<number | null>(null);
  const { can } = useApp();
  const toast = useToast();
  const docs = useApi(() => call(api.GET("/api/v2/deals/{deal_id}/documents", { params: { path: { deal_id: id } } })), [id]);
  const cons = useApi(() => call(api.GET("/api/v2/deals/{deal_id}/conflicts", { params: { path: { deal_id: id } } })), [id]);
  const file = useRef<HTMLInputElement>(null);
  const [cat, setCat] = useState("om");
  const upload = async (f: File) => {
    const fd = new FormData(); fd.append("file", f); fd.append("category", cat);
    try { await raw(`/api/v2/deals/${id}/documents`, { method: "POST", body: fd }); toast.ok(T("已上传：{0}", [f.name])); await docs.reload(); }
    catch (e) { toast.err(e); }
  };
  const download = async (d: Doc) => {
    try { const r = await raw(`/api/v2/deals/${id}/documents/${d.id}`); const url = URL.createObjectURL(await r.blob());
      const a = document.createElement("a"); a.href = url; a.download = d.filename; a.click(); URL.revokeObjectURL(url); } catch (e) { toast.err(e); }
  };
  const extract = async (d: Doc) => {
    setExtracting(d.id);
    try { setEx(await call(api.POST("/api/v2/deals/{deal_id}/documents/{doc_id}/extract", { params: { path: { deal_id: id, doc_id: d.id } } }))); }
    catch (e) { toast.err(e); } finally { setExtracting(null); }
  };
  const adoptTenants = (rows: Extract["tenants"]) => {
    if (track === "institutional" && draft.property_type === "multifamily") {  // 多户公寓按户型建模，不收逐份租约
      toast.err(T("多户公寓按户型建模：请在“租金表”页的户型表里按户型填户数与租金，PDF 里的租约行不能直接加入"));
      return;
    }
    if (track === "institutional") {  // 机构级：转成逐份租约；起止日期只是按新租期估的，必须核对
      set("leases", [...((draft.leases as unknown[] | undefined) ?? []), ...tenantsToLeases(rows, draft)]);
      toast.ok(T("已加入 {0} 份租约草稿：起止日期是估的，务必按租约原件改", [rows.length]));
      return;
    }
    const cur = (draft.tenants as unknown[] | undefined) ?? [];
    set("tenants", [...cur, ...rows.map((t) => ({ suite: t.suite ?? "", tenant: t.tenant ?? "", sf: t.sf ?? 0, monthly_rent: t.monthly_rent ?? 0 }))]);
    toast.ok(T("已加入 {0} 个租户到租金表草稿：记得核对并保存一版", [rows.length]));
  };
  const isPdf = (d: Doc) => d.content_type.includes("pdf") || d.filename.toLowerCase().endsWith(".pdf");
  const resolve = async (c: ConflictRow, value: unknown) => {
    const note = window.prompt(T("裁决「{0}」：为什么采用 {1}？", [fieldLabel(c.field), String(value)]));
    if (!note) return;
    try { await call(api.POST("/api/v2/deals/{deal_id}/conflicts/{conflict_id}/resolve", { params: { path: { deal_id: id, conflict_id: c.id } }, body: { value: value as never, note } }));
      toast.ok(T("已裁决")); await Promise.all([cons.reload(), reload()]); } catch (e) { toast.err(e); }
  };
  const ps = Object.values(passports);
  return (
    <>
      {ex ? <section className="card" aria-label={T("提取结果")}>
        <div className="row" style={{ justifyContent: "space-between" }}><h2 style={{ margin: 0 }}>{T("从「{0}」提取", [ex.filename])}</h2>
          <button className="btn ghost sm" type="button" onClick={() => setEx(null)}>{T("关闭")}</button></div>
        <p className="sub">{ex.notice}</p>
        <Candidates key={ex.document_id} items={ex.candidates} onAdopt={(c) => void adopt(c, ex.document_id).then(() => setEx(null))} />
        {track !== "residential" && ex.tenants.length ? <div style={{ marginTop: 16 }}>
          <h3 style={{ fontSize: 15 }}>{T("租约表行（{0}）", [ex.tenants.length])}</h3>
          <ul className="checks">{ex.tenants.slice(0, 8).map((t, i) => <li key={i}><span className="chip">{t.suite}</span>
            <span>{t.tenant}<div className="d">{t.sf ?? "—"} SF · ${t.monthly_rent ?? "—"}{T("/月")}{t.page ? ` · p.${t.page}` : ""}</div></span></li>)}</ul>
          <button className="btn" type="button" onClick={() => adoptTenants(ex.tenants)}>{T("加入租金表（{0}）", [ex.tenants.length])}</button></div> : null}
      </section> : null}
      <section className="card" aria-label={T("跨来源矛盾")}>
        <h2>{T("跨来源矛盾登记")}</h2><p className="sub">{T("同一字段两个来源差异 &gt; 0.5% 自动登记；未裁决的矛盾会挡住进投委会的关卡。")}</p>
        {cons.data?.length ? <ul className="checks">{cons.data.map((c) => (
          <li key={c.id}><Status s={c.status === "open" ? "risk" : "verified"}>{c.status === "open" ? T("待裁决") : T("已裁决")}</Status>
            <span><strong title={c.field}>{fieldLabel(c.field)}</strong>{T("：")}{c.source_a} = {String(c.value_a)} vs {c.source_b} = {String(c.value_b)}{c.diff_pct != null ? T("（差 {0}%）", [c.diff_pct.toFixed(1)]) : ""}
              {c.status === "open" && can("deal.write") ? <span className="row" style={{ marginTop: 4 }}>
                <button className="btn sm" type="button" onClick={() => void resolve(c, c.value_a)}>{T("采用")}{" "}{c.source_a}</button>
                <button className="btn sm" type="button" onClick={() => void resolve(c, c.value_b)}>{T("采用")}{" "}{c.source_b}</button></span>
                : c.status === "resolved" ? <div className="d">{T("采用")}{" "}{String(c.resolved_value)} · {c.resolution_note} · {c.resolved_by}</div> : null}</span></li>))}</ul>
          : <p className="muted">{T("没有矛盾。")}</p>}
      </section>
      <div className="split">
        <section className="card" aria-label={T("数字护照")}>
          <h2>{T("数字护照（")}{ps.length}{T("）")}</h2><p className="sub">{T("每个已登记来源的数字：点开看来源页码、复核、修改历史。")}</p>
          {ps.length ? <div className="table-wrap"><table className="t"><thead><tr><th scope="col">{T("字段")}</th><th scope="col">{T("状态")}</th><th scope="col">{T("来源")}</th><th scope="col">{T("可信度")}</th><th scope="col">{T("新鲜度")}</th></tr></thead>
            <tbody>{ps.map((p) => <tr key={p.field}><td><button className="btn ghost sm" type="button" onClick={() => openPassport(p.field, fieldLabel(p.field))} title={p.field}>{fieldLabel(p.field)}</button></td>
              <td><Status s={passportStatus(p)}>{p.review_label}</Status></td><td>{p.source}{p.page ? ` p.${p.page}` : ""}</td><td>{p.confidence_label}</td>
              <td>{(p.freshness as { label: string }).label}</td></tr>)}</tbody></table></div>
            : <Empty title={T("还没有登记来源")}>{T("在租金表 / T12 / 模型里点数字旁的“源”登记。")}</Empty>}
        </section>
        <section className="card" aria-label={T("文件")}>
          <h2>{T("文件")}</h2><p className="sub">{T("OM、租金表、T12、尽调报告；保存 SHA-256，可核对原件。≤ 20MB。")}</p>
          {can("document.write") ? <div className="row" style={{ marginBottom: 12 }}>
            <select className="input" style={{ width: 140 }} value={cat} onChange={(e) => setCat(e.target.value)} aria-label={T("文件类别")}>
              <option value="om">OM / Flyer</option><option value="rent_roll">{T("租金表")}</option><option value="t12">T12</option><option value="diligence">{T("尽调")}</option><option value="legal">{T("法律")}</option><option value="other">{T("其他")}</option></select>
            <input ref={file} type="file" className="sr-only" aria-label={T("选择文件")} onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); e.target.value = ""; }} />
            <button className="btn" type="button" onClick={() => file.current?.click()}>{T("上传文件")}</button></div> : null}
          {docs.data?.length ? <ul className="checks">{docs.data.map((d) => <li key={d.id}><span className="chip">{d.category}</span>
            <span><button className="btn ghost sm" type="button" onClick={() => void download(d)}>{d.filename}</button>
              <div className="d mono">{(d.size / 1024).toFixed(1)} KB · sha256 {d.sha256.slice(0, 16)}… · {d.created_by} · {fmtDate(d.created_at, true)}</div>
              {isPdf(d) && can("document.write") ? <button className="btn sm" type="button" style={{ marginTop: 4 }} disabled={extracting !== null}
                onClick={() => void extract(d)}>{extracting === d.id ? T("提取中…") : T("提取字段")}</button> : null}</span></li>)}</ul>
            : <p className="muted">{T("还没有文件。")}</p>}
        </section>
      </div>
    </>
  );
}
