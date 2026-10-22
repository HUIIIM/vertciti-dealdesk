// 认证开启（DEALDESK_AUTH=on）且未登录：粘贴访问令牌。令牌只存当前会话（sessionStorage），以 Bearer 头发送，不用 cookie（无 CSRF 面）。
import { T } from "@/i18n";
import { useState } from "react";
import { setToken } from "@/api/client";

export function Login({ onDone }: { onDone: () => void }) {
  const [t, setT] = useState("");
  return (
    <main className="page" style={{ maxWidth: 520 }}>
      <p className="eyebrow">{T("DealDesk · 登录")}</p>
      <h1 style={{ fontSize: 32, margin: "0 0 8px" }}>{T("输入访问令牌")}</h1>
      <p className="muted">{T("令牌由董事长在“设置 → 用户”创建，只显示一次。关闭浏览器标签页后需重新输入。")}</p>
      <form onSubmit={(e) => { e.preventDefault(); setToken(t.trim()); onDone(); }} className="card" style={{ display: "grid", gap: 16 }}>
        <label className="field">{T("访问令牌")}<input className="input mono" value={t} onChange={(e) => setT(e.target.value)} autoComplete="off" placeholder="dd_…" required /></label>
        <button className="btn primary" type="submit">{T("进入")}</button>
      </form>
    </main>
  );
}
