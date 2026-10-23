// 设置：淘汰条件 / 假设 / 市场默认值模板、数据源状态、用户（董事长）、外观与快捷键。
import { T } from "@/i18n";
import { useState } from "react";
import { api, call } from "@/api/client";
import { useApi } from "@/api/useApi";
import { useApp } from "@/app-context";
import { KillEditor, type Crit } from "@/components/KillEditor";
import { ErrorBox, Kbd, Status, useToast } from "@/components/ui";
import { trackLabel } from "@/domain/fields";
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

type UserRow = { username: string; display_name: string; role: string; active: boolean; email?: string | null };
type RoleKey = "chairman" | "analyst" | "viewer";
const ROLE_TEXT: Record<string, string> = { chairman: T("董事长"), analyst: T("分析"), viewer: T("只读") };

/** 用户：按 Google 邮箱邀请（邀请制，无公开注册）；可改邮箱、角色、停用。访问令牌只给脚本 / 管理员用。 */
function Users() {
  const toast = useToast();
  const { me } = useApp();
  const u = useApi(() => call(api.GET("/api/v2/admin/users")), []);
  const [form, setForm] = useState<{ username: string; role: RoleKey; display_name: string; email: string }>({ username: "", role: "analyst", display_name: "", email: "" });
  const [token, setToken] = useState<string | null>(null);
  const create = async () => {
    try {
      const r = await call(api.POST("/api/v2/admin/users", { body: { ...form, email: form.email.trim() || null } }));
      setToken(String((r as { token: string }).token));
      setForm({ username: "", role: "analyst", display_name: "", email: "" });
      toast.ok(form.email.trim() ? T("已邀请：对方用这个 Google 账号打开 DealDesk 即可登录") : T("用户已创建"));
      await u.reload();
    } catch (e) { toast.err(e); }
  };
  const patch = async (username: string, body: { email?: string; role?: RoleKey; active?: boolean }) => {
    try { await call(api.PATCH("/api/v2/admin/users/{username}", { params: { path: { username } }, body })); toast.ok(T("已保存")); await u.reload(); }
    catch (e) { toast.err(e); }
  };
  const rows = (u.data ?? []) as unknown as UserRow[];
  return (
    <div className="split">
      <section className="card"><h2>{T("用户")}</h2>{u.error ? <ErrorBox error={u.error} /> : null}
        <p className="sub">{T("登记了 Google 邮箱的人，打开 DealDesk 点“使用 Google 账号登录”即可进入；清空邮箱即撤销。")}</p>
        <ul className="checks">{rows.map((x) => <UserItem key={x.username} x={x} self={x.username === me.username} onPatch={(b) => void patch(x.username, b)} />)}</ul></section>
      <section className="card"><h2>{T("邀请用户")}</h2>
        <form style={{ display: "grid", gap: 12 }} onSubmit={(e) => { e.preventDefault(); void create(); }}>
          <label className="field">{T("Google 邮箱")}<input className="input" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="name@gmail.com" autoComplete="off" /></label>
          <label className="field">{T("用户名")}<input className="input" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} pattern="[A-Za-z0-9._-]{2,80}" required /></label>
          <label className="field">{T("显示名")}<input className="input" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} /></label>
          <label className="field">{T("角色")}<select className="input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as RoleKey })}>
            <option value="chairman">{T("董事长")}</option><option value="analyst">{T("分析")}</option><option value="viewer">{T("只读")}</option></select></label>
          <div><button className="btn primary" type="submit">{T("邀请")}</button></div></form>
        {token ? <details style={{ marginTop: 12 }}><summary className="muted">{T("访问令牌（脚本 / 管理员用，只显示这一次）")}</summary>
          <div className="mono" style={{ wordBreak: "break-all", marginTop: 8 }}>{token}</div></details> : null}</section>
    </div>
  );
}

function UserItem({ x, self, onPatch }: { x: UserRow; self: boolean; onPatch: (b: { email?: string; role?: RoleKey; active?: boolean }) => void }) {
  const [email, setEmail] = useState(x.email ?? "");
  return (
    <li style={{ alignItems: "start" }}>
      <span className="chip">{ROLE_TEXT[x.role] ?? x.role}</span>
      <span style={{ display: "grid", gap: 6, flex: 1 }}>
        <span>{x.display_name}<span className="d">{x.username}{x.active ? "" : T(" · 已停用")}</span></span>
        <span style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input className="input" type="email" aria-label={T("{0} 的 Google 邮箱", [x.username])} value={email} onChange={(e) => setEmail(e.target.value)} placeholder={T("未登记 Google 邮箱")} style={{ flex: "1 1 200px" }} />
          <button type="button" className="btn sm" disabled={email.trim() === (x.email ?? "")} onClick={() => onPatch({ email: email.trim() })}>{T("保存邮箱")}</button>
          {self ? null : <button type="button" className="btn sm ghost" onClick={() => onPatch({ active: !x.active })}>{x.active ? T("停用") : T("启用")}</button>}
        </span>
      </span>
    </li>
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
        <tbody>{list.data.map((p) => <tr key={`${p.kind}:${p.id}`}><td>{p.name || "—"}</td><td>{trackLabel(p.track)}</td>
          <td>{p.address || "—"}</td><td>{p.updated_at ? fmtDate(new Date(p.updated_at * 1000).toISOString()) : "—"}</td>
          <td>{p.imported_deal_id ? <a className="btn ghost sm" href={`#/deals/${p.imported_deal_id}`}>{T("已导入 · 打开")}</a>
            : <button className="btn sm" type="button" disabled={!can("deal.write") || busy !== null} onClick={() => void imp(p)}>{busy === `${p.kind}:${p.id}` ? T("导入中…") : T("导入")}</button>}</td></tr>)}</tbody></table></div> : null}
    </section>
  );
}
