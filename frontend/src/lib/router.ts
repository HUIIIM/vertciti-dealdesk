// hash 路由（#/deals/12/model）：静态托管无需服务端重写规则。
import { useEffect, useState } from "react";

export type Route =
  | { name: "pipeline" }
  | { name: "deal"; id: number; tab: DealTab }
  | { name: "compare"; ids: number[] }
  | { name: "settings"; section: string }
  | { name: "notfound"; path: string };

export const DEAL_TABS = [
  ["overview", "概览"], ["rentroll", "租金表"], ["t12", "T12"], ["model", "模型"], ["risk", "敏感性与红队"],
  ["market", "市场与可比"], ["files", "文件与证据"], ["committee", "投委会"], ["holding", "持有期"], ["log", "日志"],
] as const;
export type DealTab = (typeof DEAL_TABS)[number][0];
const TAB_KEYS = new Set<string>(DEAL_TABS.map(([k]) => k));

export function parse(hash: string): Route {
  const path = hash.replace(/^#/, "") || "/";
  const parts = path.split("?")[0]!.split("/").filter(Boolean);
  if (parts.length === 0 || parts[0] === "pipeline") return { name: "pipeline" };
  if (parts[0] === "deals" && parts[1] && /^\d+$/.test(parts[1])) {
    const tab = parts[2] && TAB_KEYS.has(parts[2]) ? (parts[2] as DealTab) : "overview";
    return { name: "deal", id: Number(parts[1]), tab };
  }
  if (parts[0] === "compare") {
    const q = new URLSearchParams(path.split("?")[1] ?? "");
    const ids = (q.get("ids") ?? "").split(",").filter((x) => /^\d+$/.test(x)).map(Number);
    return { name: "compare", ids };
  }
  if (parts[0] === "settings") return { name: "settings", section: parts[1] ?? "templates" };
  return { name: "notfound", path };
}

export function href(r: Route): string {
  switch (r.name) {
    case "pipeline": return "#/";
    case "deal": return r.tab === "overview" ? `#/deals/${r.id}` : `#/deals/${r.id}/${r.tab}`;
    case "compare": return `#/compare?ids=${r.ids.join(",")}`;
    case "settings": return `#/settings/${r.section}`;
    default: return "#/";
  }
}

export function navigate(r: Route | string): void {
  window.location.hash = typeof r === "string" ? r : href(r);
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parse(window.location.hash));
  useEffect(() => {
    const on = () => setRoute(parse(window.location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}
