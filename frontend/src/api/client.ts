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

/** FastAPI 422 的 detail 可能是数组（字段校验）：拼成一句中文可读的话。 */
export function detailText(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => {
      const item = d as { loc?: unknown[]; msg?: string };
      const loc = Array.isArray(item.loc) ? item.loc.filter((x) => x !== "body").join(".") : "";
      return loc ? `${loc}：${item.msg ?? "输入无效"}` : item.msg ?? "输入无效";
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

export const api = createClient<paths>({ baseUrl: "" });
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
