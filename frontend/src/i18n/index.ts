// 中英切换（与 v1 static/i18n.js 同一约定）：默认中文；?lang=en 深链优先，其次 localStorage('dd_lang')。
// T(中文原文, [参数])：英文时查 EN 词典，{0}{1} 占位替换；缺词回退中文原文（测试保证不缺）。
// 语言在页面加载时确定；切换 = 写入偏好并刷新（模块级常量、日期与数字格式一次到位，不会半中半英）。
import { EN } from "./en";

export type Lang = "zh" | "en";
const KEY = "dd_lang";

function detect(): Lang {
  if (typeof window === "undefined") return "zh";
  const q = new URLSearchParams(window.location.search).get("lang");
  if (q === "en" || q === "zh") {
    try { window.localStorage.setItem(KEY, q); } catch { /* 隐私模式：仅本次有效 */ }
    return q;
  }
  try { return window.localStorage.getItem(KEY) === "en" ? "en" : "zh"; } catch { return "zh"; }
}

let current: Lang = detect();
if (typeof document !== "undefined") document.documentElement.lang = current === "en" ? "en" : "zh-CN";

export function lang(): Lang {
  return current;
}

export function T(zh: string, args?: readonly unknown[]): string {
  const tpl = current === "en" ? (EN[zh] ?? zh) : zh;
  return args ? tpl.replace(/\{(\d+)\}/g, (_, i: string) => String(args[Number(i)] ?? "")) : tpl;
}

/** 切换语言：写偏好、去掉深链参数、刷新。 */
export function setLang(l: Lang): void {
  try { window.localStorage.setItem(KEY, l); } catch { /* 忽略 */ }
  const u = new URL(window.location.href);
  if (u.searchParams.has("lang")) {
    u.searchParams.delete("lang");
    window.location.replace(u.toString());  // search 变了 → 整页重载
  } else {
    window.location.reload();  // 只有 hash 时 replace 不会重载
  }
}

/** 仅测试用：不刷新地切换。 */
export function __setLangForTest(l: Lang): void {
  current = l;
}
