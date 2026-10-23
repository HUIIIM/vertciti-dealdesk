// 外壳：与 vertciti.com 一致的黑色品牌条 + 产品栏（导航 / 命令栏入口 / 密度与主题 / 当前身份）。
import { lang, setLang, T } from "@/i18n";
import type { ReactNode } from "react";
import { api, setToken } from "@/api/client";
import { useApp } from "@/app-context";
import { Kbd } from "@/components/ui";
import type { Density, Theme } from "@/lib/prefs";
import type { Route } from "@/lib/router";

export function AppShell({ route, children, onCmdk, density, setDensity, theme, setTheme }: {
  route: Route; children: ReactNode; onCmdk: () => void; density: Density; setDensity: (d: Density) => void; theme: Theme; setTheme: (t: Theme) => void;
}) {
  const { me } = useApp();
  const cur = (n: string) => (route.name === n || (n === "pipeline" && route.name === "deal") ? "page" : undefined);
  return (
    <>
      <a href="#main" className="sr-only">{T("跳到主内容")}</a>
      <div className="brandbar" role="navigation" aria-label="vertciti">
        <a className="logo" href="https://vertciti.com" aria-label={T("vertciti 官网")}>vertciti<i /></a>
        <a href="#/" aria-current="page">DealDesk</a>
        <span className="sp" />
        <a className="hide-sm" href="https://vertciti.com/trust/">{T("仿冒预警")}</a>
        <a className="hide-sm" href="https://vertciti.com/business/">{T("vertciti 业务版图")}</a>
        <button type="button" className="langsw" onClick={() => setLang(lang() === "en" ? "zh" : "en")}
          aria-label={lang() === "en" ? "切换到中文" : "Switch to English"} lang={lang() === "en" ? "zh-CN" : "en"}> {/* i18n-exempt：切换按钮用目标语言标注 */}
          {lang() === "en" ? "中文" : "EN"}</button>{/* i18n-exempt：同上 */}
      </div>
      <header className="appbar">
        <span className="prod">{T("交易工作台")}</span>
        <nav aria-label={T("主导航")}>
          <a href="#/" aria-current={cur("pipeline")}>{T("流水线")}</a>
          <a href="#/compare" aria-current={cur("compare")}>{T("比较")}</a>
          <a href="#/settings/templates" aria-current={cur("settings")}>{T("设置")}</a>
        </nav>
        <span className="sp" />
        <button type="button" className="cmdk-trigger" onClick={onCmdk} aria-label={T("搜交易、跳转、执行命令（命令栏 ⌘K）")}>
          <span className="label">{T("搜交易、跳转、执行命令")}</span><span className="sp" style={{ flex: 1 }} /><Kbd k="⌘ K" />
        </button>
        <div className="seg desktop-only" role="group" aria-label={T("密度")}>
          <button type="button" aria-pressed={density === "comfortable"} onClick={() => setDensity("comfortable")}>{T("舒适")}</button>
          <button type="button" aria-pressed={density === "compact"} onClick={() => setDensity("compact")}>{T("紧凑")}</button>
        </div>
        <button type="button" className="btn ghost sm desktop-only" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          aria-label={theme === "dark" ? T("切换到浅色") : T("切换到深色（长时间建模）")}>{theme === "dark" ? T("浅色") : T("深色")}</button>
        <span className="who" title={me.permissions.join(T("、"))}><span className="name">{me.display_name || me.username}</span><span className="chip">{me.role_label}</span></span>
        {me.auth ? <button type="button" className="btn ghost sm" onClick={() => void signOut()}>{T("退出登录")}</button> : null}
      </header>
      <main id="main" className="page" tabIndex={-1}>{children}</main>
    </>
  );
}

/** 退出：作废服务端会话令牌（Google 登录那种）、清掉本地令牌，回到登录页。 */
async function signOut(): Promise<void> {
  try { await api.POST("/api/v2/auth/logout"); } catch { /* 离线也照样清本地 */ }
  setToken(null);
  window.location.replace(window.location.pathname + "#/");
  window.location.reload();
}
