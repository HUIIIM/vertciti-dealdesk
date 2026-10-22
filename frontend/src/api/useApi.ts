// 极简数据钩子：加载 / 错误 / 重载；mutate 支持乐观更新（先改界面，失败回滚并提示）。
// 状态按“请求键”派生：loading = 当前键还没有结果；effect 里只在异步回调中 setState（React 19 规则）。
import { useCallback, useEffect, useRef, useState } from "react";

export interface ApiState<T> { data: T | undefined; error: Error | undefined; loading: boolean; reload: () => Promise<void>;
  setData: (fn: (d: T | undefined) => T | undefined) => void }

interface Slot<T> { key: string; tick: number; data?: T; error?: Error }

export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[]): ApiState<T> {
  const key = JSON.stringify(deps);
  const [tick, setTick] = useState(0);
  const [slot, setSlot] = useState<Slot<T>>({ key: "\u0000", tick: -1 });
  const fetchRef = useRef(fetcher);
  const waiters = useRef<(() => void)[]>([]);
  useEffect(() => { fetchRef.current = fetcher; });
  useEffect(() => {
    let alive = true;
    const settle = () => { const w = waiters.current; waiters.current = []; w.forEach((f) => f()); };
    fetchRef.current().then(
      (data) => { if (alive) { setSlot({ key, tick, data }); settle(); } },
      (error: Error) => { if (alive) { setSlot((s) => ({ key, tick, data: s.key === key ? s.data : undefined, error })); settle(); } },
    );
    return () => { alive = false; };
  }, [key, tick]);
  const reload = useCallback(() => new Promise<void>((res) => { waiters.current.push(res); setTick((t) => t + 1); }), []);
  const setData = useCallback((fn: (d: T | undefined) => T | undefined) => setSlot((s) => ({ ...s, data: fn(s.data) })), []);
  const same = slot.key === key;
  return { data: same ? slot.data : undefined, error: same ? slot.error : undefined, loading: !same || slot.tick !== tick, reload, setData };
}

/** 乐观更新：apply 立即生效；commit 失败时 rollback 并把错误抛给调用方（由 toast 提示）。 */
export async function optimistic<T>(apply: () => void, rollback: () => void, commit: () => Promise<T>): Promise<T> {
  apply();
  try {
    return await commit();
  } catch (e) {
    rollback();
    throw e;
  }
}
