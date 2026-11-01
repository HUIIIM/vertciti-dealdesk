// useApi 失败口径（台账第 30 项）：重取失败时保留上一次成功的数据，不清空界面；恢复后重试可达。
import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "./client";
import { useApi } from "./useApi";

describe("useApi 失败保留数据", () => {
  it("换键重取失败：error 给出、旧 data 保留；再重取成功后恢复", async () => {
    let mode: "ok1" | "fail" | "ok2" = "ok1";
    const fetcher = () => (mode === "fail"
      ? Promise.reject(new ApiError(0, "无法连接服务器：网络中断或后端暂不可用，请稍后重试", null))
      : Promise.resolve(mode === "ok1" ? "第一版数据" : "第二版数据"));
    const { result, rerender } = renderHook(({ deps }: { deps: unknown[] }) => useApi(fetcher, deps), {
      initialProps: { deps: [0] },
    });
    await waitFor(() => expect(result.current.data).toBe("第一版数据"));

    mode = "fail";
    rerender({ deps: [1] });
    await waitFor(() => expect(result.current.error).toBeInstanceOf(ApiError));
    expect(result.current.data).toBe("第一版数据");  // 已加载数据不清空
    expect(result.current.error?.message).toContain("无法连接服务器");

    mode = "ok2";
    rerender({ deps: [2] });
    await waitFor(() => expect(result.current.data).toBe("第二版数据"));
    expect(result.current.error).toBeUndefined();
  });

  it("同键 reload 失败同样保留数据", async () => {
    let fail = false;
    const fetcher = () => (fail ? Promise.reject(new Error("boom")) : Promise.resolve("数据"));
    const { result } = renderHook(() => useApi(fetcher, []));
    await waitFor(() => expect(result.current.data).toBe("数据"));
    fail = true;
    act(() => { void result.current.reload(); });
    await waitFor(() => expect(result.current.error).toBeInstanceOf(Error));
    expect(result.current.data).toBe("数据");
  });
});
