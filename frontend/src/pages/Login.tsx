// 认证开启（DEALDESK_AUTH=on）且未登录：首选 Google 登录（邀请制，董事长在“设置 → 用户”登记邮箱）；
// 访问令牌留给脚本与管理员，折叠在下面。令牌以 Bearer 头发送，不用 cookie（无 CSRF 面）。
import { T } from "@/i18n";
import { useState } from "react";
import { api, call, setToken } from "@/api/client";
import { useApi } from "@/api/useApi";

const ERRORS: Record<string, string> = {
  not_invited: T("这个 Google 账号还没有被邀请。请让董事长在“设置 → 用户”里登记你的邮箱后再试。"),
  not_configured: T("Google 登录尚未配置，请联系管理员。"),
  failed: T("Google 登录没有完成，请重试。"),
};

export function Login({ onDone, error = null }: { onDone: () => void; error?: string | null }) {
  const [t, setT] = useState("");
  const providers = useApi(() => call(api.GET("/api/v2/auth/providers")), []);
  const google = Boolean((providers.data as { google?: boolean } | undefined)?.google);
  const tokenForm = (
    <form onSubmit={(e) => { e.preventDefault(); setToken(t.trim()); onDone(); }} style={{ display: "grid", gap: 16 }}>
      <label className="field">{T("访问令牌")}<input className="input mono" value={t} onChange={(e) => setT(e.target.value)} autoComplete="off" placeholder="dd_…" required /></label>
      <button className={google ? "btn" : "btn primary"} type="submit">{T("进入")}</button>
    </form>
  );
  return (
    <main className="page" style={{ maxWidth: 520 }}>
      <p className="eyebrow">{T("DealDesk · 登录")}</p>
      <h1 style={{ fontSize: 32, margin: "0 0 8px" }}>{google ? T("登录") : T("输入访问令牌")}</h1>
      <p className="muted">{google ? T("仅限受邀用户：用董事长登记过的 Google 账号登录。") : T("令牌由董事长在“设置 → 用户”创建，只显示一次。关闭浏览器标签页后需重新输入。")}</p>
      {error ? <div className="banner warn" role="alert" style={{ marginBottom: 16 }}>{ERRORS[error] ?? ERRORS.failed}</div> : null}
      <div className="card" style={{ display: "grid", gap: 16 }}>
        {google ? <>
          <a className="btn primary" href="/api/v2/auth/google/start" style={{ justifyContent: "center" }}>{T("使用 Google 账号登录")}</a>
          <details><summary className="muted">{T("用访问令牌登录（脚本 / 管理员）")}</summary><div style={{ marginTop: 12 }}>{tokenForm}</div></details>
        </> : tokenForm}
      </div>
    </main>
  );
}
