import { describe, expect, it } from "vitest";
import { ApiError, api, call, detailText, getToken, isNetworkError, raw, rawJson, setToken } from "./client";
import { optimistic } from "./useApi";
import { calls, install, override } from "@/test/server";

describe("API 客户端", () => {
  it("422 字段错误拼成中文可读的一句话", () => {
    expect(detailText([{ loc: ["body", "name"], msg: "必填" }, { msg: "x" }])).toBe("name：必填；x");
    expect(detailText("直接文本")).toBe("直接文本");
    expect(detailText(42)).toBe("请求失败");
  });
  it("失败统一抛 ApiError，带请求编号与关卡明细", async () => {
    override("GET /api/v2/deals/77", 409, { detail: "关卡未通过", request_id: "rid-9", gate: { allowed: false } });
    const e = await call(api.GET("/api/v2/deals/{deal_id}", { params: { path: { deal_id: 77 } } })).catch((x: unknown) => x);
    expect(e).toBeInstanceOf(ApiError);
    expect((e as ApiError).status).toBe(409);
    expect((e as ApiError).requestId).toBe("rid-9");
    expect((e as ApiError).gate).toEqual({ allowed: false });
    await expect(raw("/api/v2/nope")).rejects.toBeInstanceOf(ApiError);
  });
  it("令牌只存会话，并以 Bearer 头发出", async () => {
    setToken("dd_x");
    expect(getToken()).toBe("dd_x");
    await rawJson("/api/v2/me");
    await call(api.GET("/api/v2/me"));
    expect(calls.length).toBe(2);
    setToken(null);
    expect(getToken()).toBeNull();
  });
  it("网络失败（断网/后端不可达）收敛为中文 ApiError，不漏浏览器原生英文", async () => {
    const e = await call(Promise.reject(new TypeError("Failed to fetch"))).catch((x: unknown) => x);
    expect(e).toBeInstanceOf(ApiError);
    expect(isNetworkError(e)).toBe(true);
    expect((e as ApiError).status).toBe(0);
    expect((e as ApiError).message).toContain("无法连接服务器");
    expect((e as ApiError).message).not.toContain("Failed to fetch");
    globalThis.fetch = (() => Promise.reject(new TypeError("Failed to fetch"))) as typeof fetch;
    try {
      const e2 = await raw("/api/v2/me").catch((x: unknown) => x);
      expect(e2).toBeInstanceOf(ApiError);
      expect(isNetworkError(e2)).toBe(true);
      expect((e2 as ApiError).message).not.toContain("Failed to fetch");
    } finally {
      install();
    }
  });
  it("乐观更新：失败回滚并把错误抛给调用方", async () => {
    let v = 1;
    await expect(optimistic(() => { v = 2; }, () => { v = 1; }, () => Promise.reject(new Error("boom")))).rejects.toThrow("boom");
    expect(v).toBe(1);
    await expect(optimistic(() => { v = 3; }, () => { v = 1; }, () => Promise.resolve("ok"))).resolves.toBe("ok");
    expect(v).toBe(3);
  });
});

describe("报错永远是中文", () => {
  it("框架英文短语与 Pydantic 校验类型转中文", async () => {
    const { detailText } = await import("./client");
    expect(detailText("Method Not Allowed")).toMatch(/接口不存在/);
    expect(detailText("Internal Server Error")).toBe("服务器内部错误");
    expect(detailText([{ loc: ["body", "price"], msg: "Input should be greater than 0", type: "greater_than", ctx: { gt: 0 } }]))
      .toBe("price：必须大于 0");
    expect(detailText([{ loc: ["body", "verdict"], type: "literal_error", ctx: { expected: "'BUY', 'HOLD' or 'PASS'" } }]))
      .toBe("verdict：取值只能是 BUY, HOLD or PASS");
    expect(detailText("交易 9 不存在")).toBe("交易 9 不存在");  // 业务层中文原样
  });
});
