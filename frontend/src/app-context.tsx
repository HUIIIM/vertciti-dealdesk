// 全局只读上下文：当前用户（角色与权限）、指标/假设目录（后端唯一来源）。
import { createContext, useContext } from "react";
import type { Catalog, Me } from "@/api/types";

export interface AppCtx { me: Me; catalog: Catalog; can: (perm: string) => boolean; refreshDeals: () => void; dealsVersion: number }
export const Ctx = createContext<AppCtx | null>(null);

export function useApp(): AppCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp 必须在 <App> 内使用");
  return v;
}
