// 设置：淘汰条件 / 假设 / 市场默认值模板、数据源状态、用户（董事长）、外观与快捷键。
import { T } from "@/i18n";
import { useState } from "react";
import { api, call } from "@/api/client";
import { useApi } from "@/api/useApi";
import { useApp } from "@/app-context";
import { KillEditor, type Crit } from "@/components/KillEditor";
import { ErrorBox, Kbd, Status, useToast } from "@/components/ui";
import { fmtDate } from "@/lib/format";
import { GLOBAL_HELP } from "@/lib/hotkeys";
import { navigate } from "@/lib/router";
import type { LegacyProject } from "@/api/types";

const SECTIONS = [["templates", T("模板")], ["sources", T("数据源")], ["legacy", T("老版项目")], ["users", T("用户")], ["shortcuts", T("快捷键")]] as const;

export function Settings({ section }: { section: string }) {
  const { can } = useApp();
  return (
    <>
      <div className="page-head"><div><p className="eyebrow">{T("设置")}</p><h1>{SECTIONS.find(([k]) => k === section)?.[1] ?? T("设置")}</h1></div></div>
      <nav className="tabs" aria-label={T("设置分区")}>{SECTIONS.filter(([k]) => k !== "users" || can("users.manage")).map(([k, l]) =>
        <a key={k} href={`#/settings/${k}`} aria-current={section === k ? "page" : undefined}>{l}</a>)}</nav>
      {section === "sources" ? <Sources /> : section === "legacy" ? <Legacy /> : section === "users" ? <Users /> : section === "shortcuts" ? (
        <section className="card"><table className="t"><tbody>{GLOBAL_HELP.map((h) => <tr key={h.combo}><td><Kbd k={h.combo} /></td><td>{h.label}</td></tr>)}</tbody></table></section>) : <Templates />}
    </>
  );
}

function Templates() {
  const { can } = useApp();
  const toast = useToast();
  const t = useApi(() => call(api.GET("/api/v2/settings/templates", { params: { query: { kind: "kill_criteria" } } })), []);
  const [name, setName] = useState(T("保守"));
  const [crit, setCrit] = useState<Crit[]>([{ metric: "dscr", op: "<", threshold: 1.35 }, { metric: "irr_pct", op: "<", threshold: 14 }]);
  const save = async () => {
    try { await call(api.PUT("/api/v2/settings/templates", { body: { kind: "kill_criteria", name, payload: { criteria: crit } } })); toast.ok(T("模板已保存")); await t.reload(); }
    catch (e) { toast.err(e); }
  };
  return (
    <div className="split">
      <section className="card"><h2>{T("淘汰条件模板")}</h2>
        {t.error ? <ErrorBox error={t.error} /> : null}
        <ul className="checks">{(t.data ?? []).map((x) => { const p = x.payload as { criteria?: Crit[]; track?: string };
          return <li key={String(x.name)}><Status s={x.builtin ? "planned" : "verified"}>{x.builtin ? T("内置") : T("自定义")}</Status>
            <span><strong>{String(x.label || x.name)}</strong><div className="d">{(p.criteria ?? []).map((c) => `${c.metric} ${c.op} ${c.threshold}`).join(T("；"))}</div></span></li>; })}</ul></section>
      <section className="card"><h2>{T("新建 / 覆盖模板")}</h2>
        {can("settings.write") ? (<form style={{ display: "grid", gap: 12 }} onSubmit={(e) => { e.preventDefault(); void save(); }}>
          <label className="field">{T("模板名")}<input className="input" value={name} onChange={(e) => setName(e.target.value)} required /></label>
          <KillEditor value={crit} onChange={setCrit} /><div><button className="btn primary" type="submit">{T("保存模板")}</button></div></form>)
          : <p className="muted">{T("只有董事长可以修改模板。")}</p>}</section>
    </div>
  );
}

function Sources() {
  const s = useApi(() => call(api.GET("/api/v2/settings/data-sources")), []);
  const h = useApi(() => call(api.GET("/api/v2/health")), []);
  const hd = h.data as { db?: { kind: string; revision: string; ok: boolean }; engine_version?: string; auth?: string } | undefined;
  return (
    <div className="split">
      <section className="card"><h2>{T("数据源")}</h2><ul className="checks">{(s.data ?? []).map((x) => <li key={String(x.key)}>
        <Status s={x.configured ? "verified" : "planned"}>{x.configured ? T("已配置") : T("未配置")}</Status><span>{String(x.label)}<div className="d">{String(x.detail)}</div></span></li>)}</ul></section>
      <section className="card"><h2>{T("系统")}</h2>{hd ? <ul className="checks">
        <li><Status s={hd.db?.ok ? "verified" : "risk"}>{hd.db?.ok ? T("正常") : T("异常")}</Status><span>{T("数据库")}{" "}{hd.db?.kind} {" "}{T("· 迁移版本")}{" "}{hd.db?.revision}</span></li>
        <li><Status s="verified">{T("版本")}</Status><span className="mono">{hd.engine_version}</span></li>
        <li><Status s={hd.auth === "on" ? "verified" : "building"}>{hd.auth === "on" ? T("已开启") : T("本机模式")}</Status><span>{T("访问认证（生产请设 DEALDESK_AUTH=on）")}</span></li></ul> : null}</section>
    </div>
  );
}

function Users() {
  const toast = useToast();
  const u = useApi(() => call(api.GET("/api/v2/admin/users")), []);
  const [form, setForm] = useState<{ username: string; role: "chairman" | "analyst" | "viewer"; display_name: string }>({ username: "", role: "analyst", display_name: "" });
  const [token, setToken] = useState<string | null>(null);
  const create = async () => {
    try { const r = await call(api.POST("/api/v2/admin/users", { body: form })); setToken(String((r as { token: string }).token)); await u.reload(); }
    catch (e) { toast.err(e); }
  };
  return (
    <div className="split">
      <section className="card"><h2>{T("用户")}</h2>{u.error ? <ErrorBox error={u.error} /> : null}
        <ul className="checks">{(u.data ?? []).map((x) => <li key={String(x.username)}><span className="chip">{String(x.role)}</span><span>{String(x.display_name)}<div className="d">{String(x.username)}</div></span></li>)}</ul></section>
      <section className="card"><h2>{T("创建用户")}</h2>
        <form style={{ display: "grid", gap: 12 }} onSubmit={(e) => { e.preventDefault(); void create(); }}>
          <label className="field">{T("用户名")}<input className="input" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} pattern="[A-Za-z0-9._-]{2,80}" required /></label>
          <label className="field">{T("显示名")}<input className="input" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} /></label>
          <label className="field">{T("角色")}<select className="input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as typeof form.role })}>
            <option value="chairman">{T("董事长")}</option><option value="analyst">{T("分析")}</option><option value="viewer">{T("只读")}</option></select></label>
          <div><button className="btn primary" type="submit">{T("创建并生成令牌")}</button></div></form>
        {token ? <div className="banner warn" role="alert" style={{ marginTop: 12 }}><strong>{T("访问令牌（只显示这一次）：")}</strong><div className="mono" style={{ wordBreak: "break-all" }}>{token}</div></div> : null}</section>
    </div>
  );
}

/** 老版（v1）保存过的项目：一键导入成新交易，输入原样带成第一版承销；导入过的直接跳过去。 */
function Legacy() {
  const { can } = useApp();
  const toast = useToast();
  const list = useApi(() => call(api.GET("/api/v2/legacy/projects")), []);
  const [busy, setBusy] = useState<string | null>(null);
  const imp = async (p: LegacyProject) => {
    setBusy(`${p.kind}:${p.id}`);
    try {
      const r = await call(api.POST("/api/v2/legacy/projects/{kind}/{pid}/import", { params: { path: { kind: p.kind, pid: p.id } } }));
      if (r.warning) toast.err(T("已建交易，但老版输入不全，没能生成承销版本：{0}", [r.warning])); else toast.ok(T("已导入：{0}", [r.deal.name]));
      navigate({ name: "deal", id: r.deal.id, tab: r.version ? "overview" : "model" });
    } catch (e) { toast.err(e); } finally { setBusy(null); }
  };
  return (
    <section className="card"><h2>{T("老版项目")}</h2>
      <p className="sub">{T("老版单页界面保存过的项目。导入后成为一笔新交易，输入原样带成第一版承销；同一项目只导入一次。")}</p>
      {list.error ? <ErrorBox error={list.error} /> : null}
      {list.data && list.data.length === 0 ? <p className="muted">{T("没有老版项目。")}</p> : null}
      {list.data?.length ? <div className="table-wrap" style={{ maxHeight: "none" }}><table className="t">
        <thead><tr><th scope="col">{T("名称")}</th><th scope="col">{T("赛道")}</th><th scope="col">{T("地址")}</th><th scope="col">{T("最后修改")}</th><th scope="col"><span className="sr-only">{T("操作")}</span></th></tr></thead>
        <tbody>{list.data.map((p) => <tr key={`${p.kind}:${p.id}`}><td>{p.name || "—"}</td><td>{p.track === "commercial" ? T("商业") : T("住宅")}</td>
          <td>{p.address || "—"}</td><td>{p.updated_at ? fmtDate(new Date(p.updated_at * 1000).toISOString()) : "—"}</td>
          <td>{p.imported_deal_id ? <a className="btn ghost sm" href={`#/deals/${p.imported_deal_id}`}>{T("已导入 · 打开")}</a>
            : <button className="btn sm" type="button" disabled={!can("deal.write") || busy !== null} onClick={() => void imp(p)}>{busy === `${p.kind}:${p.id}` ? T("导入中…") : T("导入")}</button>}</td></tr>)}</tbody></table></div> : null}
    </section>
  );
}
