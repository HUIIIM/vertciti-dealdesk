// 设置：淘汰条件 / 假设 / 市场默认值模板、数据源状态、用户（董事长）、外观与快捷键。
import { T } from "@/i18n";
import { useMemo, useState } from "react";
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

const SECTIONS = [["templates", T("模板")], ["sources", T("数据源")], ["legacy", T("老版项目")], ["users", T("用户")], ["system", T("系统")], ["audit", T("审计日志")], ["shortcuts", T("快捷键")]] as const;
// 只有董事长看得到的分区：用户管理、系统状态、审计日志
const NEEDS: Record<string, string> = { users: "users.manage", system: "audit.read", audit: "audit.read" };

export function Settings({ section }: { section: string }) {
  const { can } = useApp();
  return (
    <>
      <div className="page-head"><div><p className="eyebrow">{T("设置")}</p><h1>{SECTIONS.find(([k]) => k === section)?.[1] ?? T("设置")}</h1></div></div>
      <nav className="tabs" aria-label={T("设置分区")}>{SECTIONS.filter(([k]) => !NEEDS[k] || can(NEEDS[k])).map(([k, l]) =>
        <a key={k} href={`#/settings/${k}`} aria-current={section === k ? "page" : undefined}>{l}</a>)}</nav>
      {section === "sources" ? <Sources /> : section === "legacy" ? <Legacy /> : section === "users" ? <Users />
        : section === "system" ? <System /> : section === "audit" ? <Audit /> : section === "shortcuts" ? (
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

/** 用户：建号即准入（Google 登录以邮箱 == username 匹配既有用户）；访问令牌只给脚本 / 管理员用。 */
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
          <label className="field">{T("用户名")}<input className="input" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} pattern="[A-Za-z0-9._%+@-]{2,80}" required /></label>
          <p className="muted" style={{ margin: 0 }}>{T("Google 登录以邮箱匹配用户：受邀用户把用户名填其 Google 邮箱，之后即可用 Google 登录，不再需要令牌。")}</p>
          <label className="field">{T("显示名")}<input className="input" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} /></label>
          <label className="field">{T("角色")}<select className="input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as typeof form.role })}>
            <option value="chairman">{T("董事长")}</option><option value="analyst">{T("分析")}</option><option value="viewer">{T("只读")}</option></select></label>
          <div><button className="btn primary" type="submit">{T("创建并生成令牌")}</button></div></form>
        {token ? <div className="banner warn" role="alert" style={{ marginTop: 12 }}><strong>{T("访问令牌（只显示这一次）：")}</strong><div className="mono" style={{ wordBreak: "break-all" }}>{token}</div></div> : null}</section>
    </div>
  );
}

type Health = { version: string; engine_version: string; auth: string; uptime_s: number; db: { ok: boolean; kind: string; revision: string; error?: string } };
type ErrRow = { at: string; request_id: string; path: string; method?: string; error: string };

function uptime(s: number): string {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? T("{0} 小时 {1} 分", [h, m]) : T("{0} 分钟", [Math.max(1, m)]);
}

/** 系统状态（董事长）：版本、数据库、认证与 Google 登录、数据源、最近的服务器错误。 */
function System() {
  const { me } = useApp();
  const h = useApi(() => call(api.GET("/api/v2/health")), []);
  const src = useApi(() => call(api.GET("/api/v2/settings/data-sources")), []);
  const errs = useApi(() => call(api.GET("/api/v2/admin/errors", { params: { query: { limit: 20 } } })), []);
  const hd = h.data as Health | undefined;
  const google = (src.data ?? []).find((x) => x.key === "google_login");
  const rows = (errs.data ?? []) as unknown as ErrRow[];
  return (
    <>
      {h.error ? <ErrorBox error={h.error} onRetry={h.reload} /> : null}
      <section className="card" aria-label={T("运行状态")}><h2>{T("运行状态")}</h2>
        {hd ? <div className="sys-grid">
          <div className="sys-tile"><span className="k">{T("版本")}</span><span className="v">{hd.version}</span><span className="d mono">{hd.engine_version}</span></div>
          <div className="sys-tile"><span className="k">{T("数据库")}</span><span className="v"><Status s={hd.db.ok ? "verified" : "risk"}>{hd.db.ok ? T("正常") : T("异常")}</Status></span>
            <span className="d">{hd.db.kind}{" "}{T("· 迁移版本")}{" "}{hd.db.revision}{hd.db.error ? ` · ${hd.db.error}` : ""}</span></div>
          <div className="sys-tile"><span className="k">{T("访问认证")}</span><span className="v"><Status s={hd.auth === "on" ? "verified" : "building"}>{hd.auth === "on" ? T("已开启") : T("本机模式")}</Status></span>
            <span className="d">{hd.auth === "on" ? T("未登录不能读写") : T("生产请设 DEALDESK_AUTH=on")}</span></div>
          <div className="sys-tile"><span className="k">{T("Google 登录")}</span><span className="v"><Status s={google?.configured ? "verified" : "planned"}>{google?.configured ? T("已配置") : T("未配置")}</Status></span>
            <span className="d">{google?.configured ? T("既有用户可用 Google 账号登录") : T("未配置时登录页回退令牌登录")}</span></div>
          <div className="sys-tile"><span className="k">{T("当前身份")}</span><span className="v">{me.display_name || me.username}</span><span className="d">{me.role_label}{" · "}{me.username}</span></div>
          <div className="sys-tile"><span className="k">{T("已运行")}</span><span className="v">{uptime(hd.uptime_s)}</span><span className="d">{T("本实例自启动起")}</span></div>
        </div> : null}</section>
      <section className="card" aria-label={T("最近的服务器错误")}><div className="row" style={{ justifyContent: "space-between" }}><h2>{T("最近的服务器错误")}</h2>
        <button type="button" className="btn sm ghost" onClick={() => void errs.reload()}>{T("刷新")}</button></div>
        {errs.error ? <ErrorBox error={errs.error} /> : rows.length === 0 ? <p className="muted">{T("最近没有未捕获的服务器错误。")}</p> : (
          <div className="table-wrap"><table className="t"><thead><tr><th>{T("时间")}</th><th>{T("请求")}</th><th>{T("错误")}</th><th>{T("请求编号")}</th></tr></thead>
            <tbody>{rows.map((r) => <tr key={r.request_id + r.at}><td className="nowrap">{fmtDate(r.at, true)}</td><td className="mono">{r.method ?? ""} {r.path}</td>
              <td>{r.error}</td><td className="mono">{r.request_id.slice(0, 8)}</td></tr>)}</tbody></table></div>)}
        <p className="sub">{T("只保留本实例内存里最近 100 条；报障时把请求编号发给维护者即可定位。")}</p></section>
    </>
  );
}

type AuditRow = { id: number; entity: string; entity_id: string; action: string; actor: string; before?: unknown; after?: unknown; request_id: string; at: string };

const NOISE = new Set(["id", "created_at", "updated_at", "created_by", "archived", "stage_label", "status", "kill_criteria", "tags", "current_version_id"]);
const ENTITY: Record<string, string> = { deal: T("交易"), deal_version: T("承销版本"), user: T("用户"), approval: T("审批"), task: T("任务"),
  decision: T("决策"), document: T("文件"), conflict: T("来源矛盾"), field_provenance: T("数字护照"), committee_vote: T("投委会投票"),
  committee_pack: T("投委会包"), holding_actual: T("持有期实际数"), saved_view: T("保存的视图"), template: T("模板") };
const ACTION: Record<string, string> = { create: T("新建"), update: T("修改"), delete: T("删除"), decide: T("裁决") };

/** 改了什么：before / after 两个对象逐键对比，只列变了的；不是对象就整体显示。 */
export function changes(before: unknown, after: unknown): string[] {
  const obj = (x: unknown): x is Record<string, unknown> => typeof x === "object" && x !== null && !Array.isArray(x);
  const show = (x: unknown) => (x === null || x === undefined || x === "" ? "—" : typeof x === "object" ? JSON.stringify(x) : String(x));
  if (obj(after) && (before === null || before === undefined)) {  // 新建：只列关键字段，不倒整条记录
    const keys = Object.keys(after).filter((k) => !NOISE.has(k) && after[k] !== null && after[k] !== "" && !(Array.isArray(after[k]) && !(after[k] as unknown[]).length));
    return [...keys.slice(0, 4).map((k) => `${k}: ${show(after[k])}`), ...(keys.length > 4 ? [T("等 {0} 项", [keys.length])] : [])];
  }
  if (!obj(before) || !obj(after)) return before === undefined || before === null ? (after === undefined || after === null ? [] : [show(after)]) : [`${show(before)} → ${show(after)}`];
  return [...new Set([...Object.keys(before), ...Object.keys(after)])]
    .filter((k) => show(before[k]) !== show(after[k]))
    .map((k) => `${k}: ${show(before[k])} → ${show(after[k])}`);
}

/** 审计日志（董事长）：谁、何时、改了什么（改前 → 改后），可按对象类型与操作人筛。 */
function Audit() {
  const [entity, setEntity] = useState("");
  const [who, setWho] = useState("");
  // 不筛选的那份既用来列“对象类型”选项，也是选“全部”时的结果；选了类型再按类型向服务端查
  const base = useApi(() => call(api.GET("/api/v2/admin/audit", { params: { query: { limit: 500 } } })), []);
  const typed = useApi(() => (entity ? call(api.GET("/api/v2/admin/audit", { params: { query: { limit: 500, entity } } })) : Promise.resolve(null)), [entity]);
  const a = entity ? typed : base;
  const all = (a.data ?? []) as unknown as AuditRow[];
  const kinds = useMemo(() => [...new Set(((base.data ?? []) as unknown as AuditRow[]).map((r) => r.entity))].sort(), [base.data]);
  const rows = who.trim() ? all.filter((r) => r.actor.toLowerCase().includes(who.trim().toLowerCase())) : all;
  return (
    <section className="card" aria-label={T("审计日志")}>
      <div className="row" style={{ gap: 12, flexWrap: "wrap", marginBottom: 12 }}>
        <label className="field" style={{ minWidth: 180 }}>{T("对象类型")}<select className="input" value={entity} onChange={(e) => setEntity(e.target.value)}>
          <option value="">{T("全部")}</option>{kinds.map((k) => <option key={k} value={k}>{ENTITY[k] ?? k}</option>)}</select></label>
        <label className="field" style={{ minWidth: 180 }}>{T("操作人")}<input className="input" value={who} onChange={(e) => setWho(e.target.value)} placeholder={T("用户名")} /></label>
        <span className="muted" style={{ alignSelf: "end" }}>{T("共 {0} 条（最近 500 条内）", [rows.length])}</span>
      </div>
      {a.error ? <ErrorBox error={a.error} onRetry={a.reload} /> : rows.length === 0 ? <p className="muted">{T("没有符合条件的记录。")}</p> : (
        <div className="table-wrap"><table className="t"><thead><tr><th>{T("时间")}</th><th>{T("操作人")}</th><th>{T("对象")}</th><th>{T("操作")}</th><th>{T("改前 → 改后")}</th></tr></thead>
          <tbody>{rows.map((r) => { const c = changes(r.before, r.after); return (
            <tr key={r.id}><td className="nowrap">{fmtDate(r.at, true)}</td><td>{r.actor}</td><td>{ENTITY[r.entity] ?? r.entity} <span className="mono muted">#{r.entity_id}</span></td><td>{ACTION[r.action] ?? r.action}</td>
              <td className="audit-diff">{c.length ? c.map((x) => <div key={x}>{x}</div>) : <span className="muted">—</span>}</td></tr>); })}</tbody></table></div>)}
    </section>
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
