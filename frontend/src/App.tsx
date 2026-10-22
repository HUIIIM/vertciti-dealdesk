// 根组件：加载身份与目录 → 外壳 → 路由；全局快捷键（⌘K / ? / N / G+字母）。
import { T } from "@/i18n";
import { lazy, Suspense, useCallback, useMemo, useState } from "react";
import { api, ApiError, call, rawJson } from "@/api/client";
import type { Catalog, Me } from "@/api/types";
import { useApi } from "@/api/useApi";
import { Ctx } from "@/app-context";
import { AppShell } from "@/components/AppShell";
import { CommandPalette, type Command } from "@/components/CommandPalette";
import { ShortcutHelp } from "@/components/ShortcutHelp";
import { ErrorBox, Skeleton } from "@/components/ui";
import { useHotkeys } from "@/lib/hotkeys";
import { effectivePermissions, PHONE_QUERY, useMediaQuery } from "@/lib/media";
import { useAppearance } from "@/lib/prefs";
import { navigate, useRoute } from "@/lib/router";
import { Login } from "@/pages/Login";
import { NewDeal } from "@/pages/NewDeal";
import { Pipeline } from "@/pages/Pipeline";

// 按页面拆包：首屏（流水线）只带必需代码，其余页面进入时再取
const DealPage = lazy(() => import("@/pages/deal/Deal").then((m) => ({ default: m.DealPage })));
const Compare = lazy(() => import("@/pages/Compare").then((m) => ({ default: m.Compare })));
const Settings = lazy(() => import("@/pages/Settings").then((m) => ({ default: m.Settings })));

export function App() {
  const route = useRoute();
  const { density, setDensity, theme, setTheme } = useAppearance();
  const phone = useMediaQuery(PHONE_QUERY);
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
  const canWrite = effectivePermissions(boot.data?.me.permissions ?? [], phone).includes("deal.write");
  const commands = useMemo<Command[]>(() => [
    // 没有写权限（只读角色 / 手机端）不出现“新建交易”：入口与服务端权限一致
    ...(canWrite ? [{ id: "new", group: T("命令"), label: T("新建交易"), hint: "N", run: () => setCreating(true) }] : []),
    { id: "pipeline", group: T("跳转"), label: T("流水线"), hint: "G P", run: () => navigate({ name: "pipeline" }) },
    { id: "compare", group: T("跳转"), label: T("比较页"), hint: "G C", run: () => navigate({ name: "compare", ids: [] }) },
    { id: "settings", group: T("跳转"), label: T("设置 · 模板"), hint: "G S", run: () => navigate({ name: "settings", section: "templates" }) },
    { id: "sources", group: T("跳转"), label: T("设置 · 数据源状态"), run: () => navigate({ name: "settings", section: "sources" }) },
    { id: "dense", group: T("外观"), label: density === "compact" ? T("切换到舒适密度") : T("切换到紧凑密度"), run: () => setDensity(density === "compact" ? "comfortable" : "compact") },
    { id: "theme", group: T("外观"), label: theme === "dark" ? T("切换到浅色") : T("切换到深色（长时间建模）"), run: () => setTheme(theme === "dark" ? "light" : "dark") },
    { id: "help", group: T("帮助"), label: T("显示全部快捷键"), hint: "?", run: () => setHelp(true) },
    { id: "v1", group: T("跳转"), label: T("v1 单页决策（旧版入口）"), run: () => { window.location.href = "/"; } },
  ], [density, theme, setDensity, setTheme, canWrite]);
  const overlay = cmdk || help || creating;
  useHotkeys([
    { combo: "mod+k", label: T("命令栏"), group: T("全局"), allowInInput: true, run: () => setCmdk((v) => !v) },
    { combo: "?", label: T("快捷键"), group: T("全局"), run: () => setHelp(true) },
    { combo: "g p", label: T("流水线"), group: T("全局"), run: () => navigate({ name: "pipeline" }) },
    { combo: "g c", label: T("比较"), group: T("全局"), run: () => navigate({ name: "compare", ids: [] }) },
    { combo: "g s", label: T("设置"), group: T("全局"), run: () => navigate({ name: "settings", section: "templates" }) },
  ], !overlay);

  if (boot.error && !(boot.error instanceof ApiError && boot.error.status === 401)) return <main className="page"><ErrorBox error={boot.error} onRetry={boot.reload} /></main>;
  if (boot.loading && !boot.data) return <main className="page"><Skeleton rows={6} h={32} /></main>;
  if (!boot.data?.catalog || (boot.error instanceof ApiError && boot.error.status === 401)) return <Login onDone={() => setAuthTick((t) => t + 1)} />;
  const { me, catalog } = boot.data;
  const perms = effectivePermissions(me.permissions, phone);
  const can = (p: string) => perms.includes(p);
  return (
    <Ctx.Provider value={{ me, catalog, can, refreshDeals, dealsVersion }}>
      <AppShell route={route} onCmdk={() => setCmdk(true)} density={density} setDensity={setDensity} theme={theme} setTheme={setTheme}>
        {phone ? <p className="phone-note" role="note">{T("手机端为只读视图：看数字、进度与记录；编辑、审批、投票请用电脑。")}</p> : null}
        <Suspense fallback={<Skeleton rows={6} h={28} />}>
        {route.name === "pipeline" ? <Pipeline /> : route.name === "deal" ? <DealPage key={route.id} id={route.id} tab={route.tab} />
          : route.name === "compare" ? <Compare ids={route.ids} /> : route.name === "settings" ? <Settings section={route.section} />
          : <ErrorBox error={new Error(T("页面不存在：{0}", [route.path]))} />}
        </Suspense>
      </AppShell>
      {cmdk ? <CommandPalette onClose={() => setCmdk(false)} commands={commands} /> : null}
      {help ? <ShortcutHelp onClose={() => setHelp(false)} /> : null}
      {creating ? <NewDeal onClose={() => setCreating(false)} onCreated={refreshDeals} /> : null}
    </Ctx.Provider>
  );
}
