// 点路径读写（与后端 app/domain/v2/paths.py 同语义）：'analysis.rate'、'tenants.0.monthly_rent'。
export type Json = null | boolean | number | string | Json[] | { [k: string]: Json };
export type JsonObj = { [k: string]: Json };

export function getPath(obj: unknown, path: string): unknown {
  let cur: unknown = obj;
  for (const k of path.split(".")) {
    if (cur == null) return undefined;
    if (Array.isArray(cur)) cur = cur[Number(k)];
    else if (typeof cur === "object") cur = (cur as Record<string, unknown>)[k];
    else return undefined;
  }
  return cur;
}

/** 不可变更新：返回新对象，沿途复制；中间缺失的对象自动补。 */
export function setPath<T>(obj: T, path: string, value: unknown): T {
  const keys = path.split(".");
  const walk = (node: unknown, i: number): unknown => {
    const k = keys[i]!;
    const isIdx = /^\d+$/.test(k);
    const base: Record<string, unknown> | unknown[] = Array.isArray(node)
      ? [...node]
      : node && typeof node === "object"
        ? { ...(node as Record<string, unknown>) }
        : isIdx ? [] : {};
    const child = Array.isArray(base) ? base[Number(k)] : base[k];
    const next = i === keys.length - 1 ? value : walk(child, i + 1);
    if (Array.isArray(base)) base[Number(k)] = next;
    else base[k] = next;
    return base;
  };
  return walk(obj, 0) as T;
}

/** 带 * 通配（每一项）的不可变更新；与后端 update_path 同语义。 */
export function updateWild<T>(obj: T, path: string, fn: (v: unknown) => unknown): T {
  const i = path.indexOf("*");
  if (i < 0) return setPath(obj, path, fn(getPath(obj, path)));
  const head = path.slice(0, i - 1), rest = path.slice(i + 2);
  const arr = getPath(obj, head);
  if (!Array.isArray(arr)) return obj;
  const next = arr.map((item) => (rest ? updateWild(item, rest, fn) : fn(item)));
  return setPath(obj, head, next);
}

export function scaleNum(v: unknown, f: number): unknown {
  return typeof v === "number" && Number.isFinite(v) ? v * f : v;
}
