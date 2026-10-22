// 外壳：与 vertciti.com 一致的黑色品牌条 + 产品栏（导航 / 命令栏入口 / 密度与主题 / 当前身份）。
import type { ReactNode } from "react";
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
      <a href="#main" className="sr-only">跳到主内容</a>
      <div className="brandbar" role="navigation" aria-label="vertciti">
        <a className="logo" href="https://vertciti.com" aria-label="vertciti 官网">vertciti<i /></a>
        <a href="#/" aria-current="page">DealDesk</a>
        <span className="sp" />
        <a className="hide-sm" href="https://vertciti.com/trust/">仿冒预警</a>
        <a className="hide-sm" href="https://vertciti.com/business/">vertciti 业务版图</a>
        <a href="/" title="v1 单页决策（旧版入口）">v1</a>
      </div>
      <header className="appbar">
        <span className="prod">交易工作台</span>
        <nav aria-label="主导航">
          <a href="#/" aria-current={cur("pipeline")}>流水线</a>
          <a href="#/compare" aria-current={cur("compare")}>比较</a>
          <a href="#/settings/templates" aria-current={cur("settings")}>设置</a>
        </nav>
        <span className="sp" />
        <button type="button" className="cmdk-trigger" onClick={onCmdk} aria-label="打开命令栏（⌘K）">
          <span className="label">搜交易、跳转、执行命令</span><span className="sp" style={{ flex: 1 }} /><Kbd k="⌘ K" />
        </button>
        <div className="seg desktop-only" role="group" aria-label="密度">
          <button type="button" aria-pressed={density === "comfortable"} onClick={() => setDensity("comfortable")}>舒适</button>
          <button type="button" aria-pressed={density === "compact"} onClick={() => setDensity("compact")}>紧凑</button>
        </div>
        <button type="button" className="btn ghost sm desktop-only" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          aria-label={theme === "dark" ? "切换到浅色" : "切换到深色（长时间建模）"}>{theme === "dark" ? "浅色" : "深色"}</button>
        <span className="who" title={me.permissions.join("、")}><span className="name">{me.display_name || me.username}</span><span className="chip">{me.role_label}</span></span>
      </header>
      <main id="main" className="page" tabIndex={-1}>{children}</main>
    </>
  );
}
