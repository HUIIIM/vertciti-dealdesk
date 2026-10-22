// 测试用后端替身：按 “方法 路径?查询” 返回录制的真实响应（tools/record_web_fixtures.py），写操作记录下来供断言。
import fixtures from "./fixtures.json";

type Fx = Record<string, [number, unknown]>;
const FX = fixtures as unknown as Fx;
export interface Call { method: string; path: string; body: unknown }
export const calls: Call[] = [];
const overrides = new Map<string, [number, unknown]>();

export function override(key: string, status: number, body: unknown): void { overrides.set(key, [status, body]); }
export function reset(): void { calls.length = 0; overrides.clear(); }

function json(status: number, body: unknown, extra: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "x-request-id": "test-rid", ...extra } });
}

export function install(): void {
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(new URL(String(input), "http://localhost"), init);
    const url = new URL(req.url, "http://localhost");
    const method = req.method.toUpperCase();
    let body: unknown = null;
    if (method !== "GET") { const t = await req.clone().text().catch(() => ""); try { body = t ? JSON.parse(t) : null; } catch { body = t; } }
    const search = decodeURIComponent(url.search);
    calls.push({ method, path: url.pathname + search, body });
    const full = `${method} ${url.pathname}${search}`, bare = `${method} ${url.pathname}`;
    const hit = overrides.get(full) ?? overrides.get(bare) ?? FX[full] ?? FX[bare];
    if (hit) return json(hit[0], hit[1]);
    if (url.pathname.endsWith(".pdf") || url.pathname.endsWith(".xlsx")) return new Response("PK", { status: 200, headers: { "x-content-sha256": "ab".repeat(32), "x-run-id": "Rtest" } });
    if (method !== "GET") return json(200, { ok: true });
    return json(404, { detail: `测试夹具缺失：${full}`, request_id: "test-rid" });
  }) as typeof fetch;
}
