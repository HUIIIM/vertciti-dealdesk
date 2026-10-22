// 根组件：加载身份与目录 → 外壳 → 路由；全局快捷键（⌘K / ? / N / G+字母）。
import { useCallback, useMemo, useState } from "react";
import { api, ApiError, call, rawJson } from "@/api/client";
import type { Catalog, Me } from "@/api/types";
import { useApi } from "@/api/useApi";
import { Ctx } from "@/app-context";
import { AppShell } from "@/components/AppShell";
import { CommandPalette, type Command } from "@/components/CommandPalette";
import { ShortcutHelp } from "@/components/ShortcutHelp";
import { ErrorBox, Skeleton } from "@/components/ui";
import { useHotkeys } from "@/lib/hotkeys";
import { useAppearance } from "@/lib/prefs";
import { navigate, useRoute } from "@/lib/router";
import { Compare } from "@/pages/Compare";
import { DealPage } from "@/pages/deal/Deal";
import { Login } from "@/pages/Login";
import { NewDeal } from "@/pages/NewDeal";
import { Pipeline } from "@/pages/Pipeline";
import { Settings } from "@/pages/Settings";

export function App() {
  const route = useRoute();
  const { density, setDensity, theme, setTheme } = useAppearance();
  const [authTick, setAuthTick] = useState(0);
  const boot = useApi(async () => {
    const me = (await call(api.GET("/api/v2/me"))) as unknown as Me;
    if (me.auth && me.username === "anonymous") return { me, catalog: null };
    const catalog = (await rawJson<Catalog>("/api/v2/catalog"));
    return { me, catalog };
  }, [authTick]);
  const [cmdk, setCmdk] = useState(false);
  const [help, setHelp] = useState(false);
  const [creating, setCreating] = useState(false);
  const [dealsVersion, setDealsVersion] = useState(0);
  const refreshDeals = useCallback(() => setDealsVersion((v) => v + 1), []);
  const commands = useMemo<Command[]>(() => [
    { id: "new", group: "命令", label: "新建交易", hint: "N", run: () => setCreating(true) },
    { id: "pipeline", group: "跳转", label: "流水线", hint: "G P", run: () => navigate({ name: "pipeline" }) },
    { id: "compare", group: "跳转", label: "比较页", hint: "G C", run: () => navigate({ name: "compare", ids: [] }) },
    { id: "settings", group: "跳转", label: "设置 · 模板", hint: "G S", run: () => navigate({ name: "settings", section: "templates" }) },
    { id: "sources", group: "跳转", label: "设置 · 数据源状态", run: () => navigate({ name: "settings", section: "sources" }) },
    { id: "dense", group: "外观", label: density === "compact" ? "切换到舒适密度" : "切换到紧凑密度", run: () => setDensity(density === "compact" ? "comfortable" : "compact") },
    { id: "theme", group: "外观", label: theme === "dark" ? "切换到浅色" : "切换到深色（长时间建模）", run: () => setTheme(theme === "dark" ? "light" : "dark") },
    { id: "help", group: "帮助", label: "显示全部快捷键", hint: "?", run: () => setHelp(true) },
    { id: "v1", group: "跳转", label: "v1 单页决策（旧版入口）", run: () => { window.location.href = "/"; } },
  ], [density, theme, setDensity, setTheme]);
  const overlay = cmdk || help || creating;
  useHotkeys([
    { combo: "mod+k", label: "命令栏", group: "全局", allowInInput: true, run: () => setCmdk((v) => !v) },
    { combo: "?", label: "快捷键", group: "全局", run: () => setHelp(true) },
    { combo: "g p", label: "流水线", group: "全局", run: () => navigate({ name: "pipeline" }) },
    { combo: "g c", label: "比较", group: "全局", run: () => navigate({ name: "compare", ids: [] }) },
    { combo: "g s", label: "设置", group: "全局", run: () => navigate({ name: "settings", section: "templates" }) },
  ], !overlay);

  if (boot.error && !(boot.error instanceof ApiError && boot.error.status === 401)) return <main className="page"><ErrorBox error={boot.error} onRetry={boot.reload} /></main>;
  if (boot.loading && !boot.data) return <main className="page"><Skeleton rows={6} h={32} /></main>;
  if (!boot.data?.catalog || (boot.error instanceof ApiError && boot.error.status === 401)) return <Login onDone={() => setAuthTick((t) => t + 1)} />;
  const { me, catalog } = boot.data;
  const can = (p: string) => me.permissions.includes(p);
  return (
    <Ctx.Provider value={{ me, catalog, can, refreshDeals, dealsVersion }}>
      <AppShell route={route} onCmdk={() => setCmdk(true)} density={density} setDensity={setDensity} theme={theme} setTheme={setTheme}>
        {route.name === "pipeline" ? <Pipeline /> : route.name === "deal" ? <DealPage key={route.id} id={route.id} tab={route.tab} />
          : route.name === "compare" ? <Compare ids={route.ids} /> : route.name === "settings" ? <Settings section={route.section} />
          : <ErrorBox error={new Error(`页面不存在：${route.path}`)} />}
      </AppShell>
      {cmdk ? <CommandPalette onClose={() => setCmdk(false)} commands={commands} /> : null}
      {help ? <ShortcutHelp onClose={() => setHelp(false)} /> : null}
      {creating ? <NewDeal onClose={() => setCreating(false)} onCreated={refreshDeals} /> : null}
    </Ctx.Provider>
  );
}
