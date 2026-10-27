// 登录：Google 登录为主（服务端 OAuth + 会话 cookie，关标签页不丢）；令牌粘贴为过渡应急入口，
// 仅在开关开启（me.token_login）或 Google 尚未配置（防锁死回退）时出现。
import { T } from "@/i18n";
import { useState } from "react";
import { setToken } from "@/api/client";
import type { Me } from "@/api/types";

const ERROR_TEXT: Record<string, string> = {
  not_provisioned: T("该 Google 账号未建档：请先让董事长在“设置 → 用户”创建同邮箱用户后再登录。"),
  disabled: T("该账号已被停用：请联系董事长。"),
  email_unverified: T("邮箱未验证：请先在 Google 账号中验证邮箱后重试。"),
  verify_failed: T("登录校验未通过：请重试；持续失败请联系董事长。"),
  state_mismatch: T("登录状态已过期：请重新登录。"),
  not_configured: T("Google 登录尚未配置：请使用下方访问令牌应急登录，或联系董事长完成配置。"),
};

function readError(): string | null {
  try {
    const q = new URLSearchParams(window.location.search);
    const code = q.get("login_error");
    if (!code) return null;
    q.delete("login_error");
    const rest = q.toString();
    window.history.replaceState(null, "", window.location.pathname + (rest ? `?${rest}` : "") + window.location.hash);
    return ERROR_TEXT[code] ?? ERROR_TEXT.verify_failed ?? code;
  } catch { return null; }
}

export function Login({ onDone, me }: { onDone: () => void; me: Me | null }) {
  const [t, setT] = useState("");
  const [error] = useState<string | null>(readError);
  const google = me?.google_login === true;
  const showToken = me?.token_login === true || !google;
  return (
    <main className="page" style={{ maxWidth: 520 }}>
      <p className="eyebrow">{T("DealDesk · 登录")}</p>
      <h1 style={{ fontSize: 32, margin: "0 0 8px" }}>{T("登录")}</h1>
      {error ? <div className="banner warn" role="alert" style={{ marginBottom: 16 }}>{error}</div> : null}
      {google ? (
        <div className="card" style={{ display: "grid", gap: 16 }}>
          <p className="muted" style={{ margin: 0 }}>{T("用已建档的 Google 账号登录。账号须先由董事长在“设置 → 用户”创建（用户名为邮箱），未建档的账号无法登录。登录后 30 天内免重新登录。")}</p>
          <a className="btn primary" href="/auth/google/login" style={{ textAlign: "center" }}>{T("使用 Google 登录")}</a>
        </div>
      ) : null}
      {showToken ? (
        <form onSubmit={(e) => { e.preventDefault(); setToken(t.trim()); onDone(); }} className="card" style={{ display: "grid", gap: 16, marginTop: google ? 16 : 0 }}>
          {google ? <p className="muted" style={{ margin: 0 }}>{T("应急令牌登录（仅在 Google 登录不可用时使用）")}</p> : null}
          <label className="field">{T("访问令牌")}<input className="input mono" value={t} onChange={(e) => setT(e.target.value)} autoComplete="off" placeholder="dd_…" required /></label>
          <button className="btn primary" type="submit">{T("进入")}</button>
        </form>
      ) : null}
    </main>
  );
}
