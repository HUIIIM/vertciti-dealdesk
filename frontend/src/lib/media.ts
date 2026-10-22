// 视口媒体查询（useSyncExternalStore：无 effect 内 setState，SSR / 测试环境无 matchMedia 时恒为 false）。
import { useSyncExternalStore } from "react";

export const PHONE_QUERY = "(max-width: 640px)";

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (cb) => {
      if (typeof window.matchMedia !== "function") return () => {};
      const m = window.matchMedia(query);
      m.addEventListener("change", cb);
      return () => m.removeEventListener("change", cb);
    },
    () => typeof window.matchMedia === "function" && window.matchMedia(query).matches,
    () => false,
  );
}

/** 手机端只读（蓝图 §5）：只保留 *.read 权限；写操作请用电脑。 */
export function effectivePermissions(perms: readonly string[], phone: boolean): string[] {
  return phone ? perms.filter((p) => p.endsWith(".read")) : [...perms];
}
