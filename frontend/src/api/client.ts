// 类型安全客户端：路径、参数、请求体由后端 OpenAPI 生成的 schema.d.ts 约束（npm run gen:api）。
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

export function getToken(): string | null {
  try { return window.sessionStorage.getItem(TOKEN_KEY); } catch { return null; }
}
export function setToken(t: string | null): void {
  try {
    if (t) window.sessionStorage.setItem(TOKEN_KEY, t);
    else window.sessionStorage.removeItem(TOKEN_KEY);
  } catch { /* 会话存储不可用时仅本页有效 */ }
}

export class ApiError extends Error {
  constructor(public status: number, message: string, public requestId: string | null, public gate?: unknown) {
    super(message);
    this.name = "ApiError";
  }
}

// 框架层（Starlette / Pydantic）的英文报错一律转成中文可操作的话：用户永远不该看到英文原因短语
const FRAMEWORK_TEXT: Record<string, string> = {
  "Not Found": "接口不存在：前后端版本可能不一致，请刷新页面",
  "Method Not Allowed": "接口不存在：前后端版本可能不一致，请刷新页面",
  "Internal Server Error": "服务器内部错误",
  "Unauthorized": "请先登录",
  "Forbidden": "当前角色没有这个权限",
};

interface PydErr { loc?: unknown[]; msg?: string; type?: string; ctx?: Record<string, unknown> }

/** Pydantic 校验错误按类型给中文（未知类型才退回原文）。 */
export function pydText(e: PydErr): string {
  const c = e.ctx ?? {};
  switch (e.type) {
    case "missing": return "必填";
    case "greater_than": return `必须大于 ${String(c.gt)}`;
    case "greater_than_equal": return `不能小于 ${String(c.ge)}`;
    case "less_than": return `必须小于 ${String(c.lt)}`;
    case "less_than_equal": return `不能大于 ${String(c.le)}`;
    case "string_too_long": return `最多 ${String(c.max_length)} 个字`;
    case "string_too_short": return `至少 ${String(c.min_length)} 个字`;
    case "too_long": return `最多 ${String(c.max_length)} 项`;
    case "too_short": return `至少 ${String(c.min_length)} 项`;
    case "literal_error": case "enum": return `取值只能是 ${String(c.expected ?? "").replace(/'/g, "")}`;
    case "float_parsing": case "int_parsing": case "float_type": case "int_type": return "必须是数字";
    case "bool_parsing": case "bool_type": return "必须是 是 / 否";
    case "extra_forbidden": return "不认识的字段";
    default: return e.msg ?? "输入无效";
  }
}

/** FastAPI 的 detail 可能是数组（字段校验）：拼成一句中文可读的话。 */
export function detailText(detail: unknown): string {
  if (typeof detail === "string") return FRAMEWORK_TEXT[detail] ?? detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => {
      const item = d as PydErr;
      const loc = Array.isArray(item.loc) ? item.loc.filter((x) => x !== "body").join(".") : "";
      return loc ? `${loc}：${pydText(item)}` : pydText(item);
    }).join("；");
  }
  return "请求失败";
}

const auth: Middleware = {
  onRequest({ request }) {
    const t = getToken();
    if (t) request.headers.set("Authorization", `Bearer ${t}`);
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
