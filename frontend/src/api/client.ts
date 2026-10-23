// 类型安全客户端：路径、参数、请求体由后端 OpenAPI 生成的 schema.d.ts 约束（npm run gen:api）。
import { lang, T } from "@/i18n";
import createClient, { type Middleware } from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type DealOut = Schemas["DealOut"];
export type DealListItem = Schemas["DealListItem"];
export type OverviewOut = Schemas["OverviewOut"];
export type VersionOut = Schemas["VersionOut"];
export type PassportOut = Schemas["PassportOut"];
export type PassportDetail = Schemas["PassportDetail"];
export type GateOut = Schemas["GateOut"];

const TOKEN_KEY = "dd.token";

// 手动粘贴的长期令牌只存本标签页（sessionStorage）；Google 登录换来的会话令牌（dds_，服务端 12 小时过期）
// 存 localStorage，关掉标签页再开不用重新登录
export function getToken(): string | null {
  try { return window.sessionStorage.getItem(TOKEN_KEY) ?? window.localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
export function setToken(t: string | null): void {
  try {
    window.sessionStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(TOKEN_KEY);
    if (t) (t.startsWith("dds_") ? window.localStorage : window.sessionStorage).setItem(TOKEN_KEY, t);
  } catch { /* 存储不可用时仅本页有效 */ }
}

/** Google 登录回跳：后端把结果放在 URL 片段（#auth=令牌 / #auth_error=原因），读出后立刻从地址栏抹掉。 */
export function consumeAuthFragment(): string | null {
  const h = window.location.hash;
  if (!h.startsWith("#auth=") && !h.startsWith("#auth_error=")) return null;
  window.history.replaceState(null, "", window.location.pathname + window.location.search + "#/");
  if (h.startsWith("#auth=")) { setToken(decodeURIComponent(h.slice(6))); return null; }
  return decodeURIComponent(h.slice(12));
}

export class ApiError extends Error {
  constructor(public status: number, message: string, public requestId: string | null, public gate?: unknown) {
    super(message);
    this.name = "ApiError";
  }
}

// 框架层（Starlette / Pydantic）的英文报错一律转成中文可操作的话：用户永远不该看到英文原因短语
const FRAMEWORK_TEXT: Record<string, string> = {
  "Not Found": T("接口不存在：前后端版本可能不一致，请刷新页面"),
  "Method Not Allowed": T("接口不存在：前后端版本可能不一致，请刷新页面"),
  "Internal Server Error": T("服务器内部错误"),
  "Unauthorized": T("请先登录"),
  "Forbidden": T("当前角色没有这个权限"),
};

interface PydErr { loc?: unknown[]; msg?: string; type?: string; ctx?: Record<string, unknown> }

/** Pydantic 校验错误按类型给中文（未知类型才退回原文）。 */
export function pydText(e: PydErr): string {
  const c = e.ctx ?? {};
  switch (e.type) {
    case "missing": return T("必填");
    case "greater_than": return T("必须大于 {0}", [String(c.gt)]);
    case "greater_than_equal": return T("不能小于 {0}", [String(c.ge)]);
    case "less_than": return T("必须小于 {0}", [String(c.lt)]);
    case "less_than_equal": return T("不能大于 {0}", [String(c.le)]);
    case "string_too_long": return T("最多 {0} 个字", [String(c.max_length)]);
    case "string_too_short": return T("至少 {0} 个字", [String(c.min_length)]);
    case "too_long": return T("最多 {0} 项", [String(c.max_length)]);
    case "too_short": return T("至少 {0} 项", [String(c.min_length)]);
    case "literal_error": case "enum": return T("取值只能是 {0}", [String(c.expected ?? "").replace(/'/g, "")]);
    case "float_parsing": case "int_parsing": case "float_type": case "int_type": return T("必须是数字");
    case "bool_parsing": case "bool_type": return T("必须是 是 / 否");
    case "extra_forbidden": return T("不认识的字段");
    default: return e.msg ?? T("输入无效");
  }
}

/** FastAPI 的 detail 可能是数组（字段校验）：拼成一句中文可读的话。 */
export function detailText(detail: unknown): string {
  if (typeof detail === "string") return FRAMEWORK_TEXT[detail] ?? detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => {
      const item = d as PydErr;
      const loc = Array.isArray(item.loc) ? item.loc.filter((x) => x !== "body").join(".") : "";
      return loc ? T("{0}：{1}", [loc, pydText(item)]) : pydText(item);
    }).join(T("；"));
  }
  return T("请求失败");
}

const auth: Middleware = {
  onRequest({ request }) {
    const t = getToken();
    if (t) request.headers.set("Authorization", `Bearer ${t}`);
    if (lang() === "en") request.headers.set("X-DD-Lang", "en");  // 后端只认这个头，不认浏览器的 Accept-Language
    return request;
  },
};

export const api = createClient<paths>({ baseUrl: typeof window === "undefined" ? "" : window.location.origin });
api.use(auth);

/** 统一取数：成功返回 data，失败抛 ApiError（带后端 request_id，便于对账日志）。 */
export async function call<T>(p: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await p;
  if (error !== undefined || !response.ok) {
    const body = (error ?? {}) as { detail?: unknown; request_id?: string; gate?: unknown };
    throw new ApiError(response.status, detailText(body.detail) || `HTTP ${response.status}`,
      body.request_id ?? response.headers.get("x-request-id"), body.gate);
  }
  return data as T;
}

/** 非 v2 / 二进制端点（v1 接口、下载、上传）。 */
export async function raw(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const t = getToken();
  if (t) headers.set("Authorization", `Bearer ${t}`);
  if (lang() === "en") headers.set("X-DD-Lang", "en");
  const r = await fetch(path, { ...init, headers });
  if (!r.ok) {
    let body: { detail?: unknown; request_id?: string; gate?: unknown } = {};
    try { body = await r.json(); } catch { /* 非 JSON */ }
    throw new ApiError(r.status, detailText(body.detail) || `HTTP ${r.status}`, body.request_id ?? r.headers.get("x-request-id"), body.gate);
  }
  return r;
}

export async function rawJson<T>(path: string, body?: unknown): Promise<T> {
  const r = await raw(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  return (await r.json()) as T;
}
