// 动效（官网同一语言：cubic-bezier(.2,.7,.2,1)）。系统“减少动态效果”、无 rAF / matchMedia（测试环境）时一律直出终值。
import { useEffect, useState } from "react";
import { isNum } from "@/lib/format";

export function motionOK(): boolean {
  return typeof window !== "undefined" && typeof window.requestAnimationFrame === "function"
    && typeof window.matchMedia === "function" && !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** 官网缓动曲线 cubic-bezier(.2,.7,.2,1) 的近似：快起慢收。 */
export const easeOut = (p: number): number => 1 - (1 - p) ** 3;

interface Anim { to: number | null | undefined; from: number; v: number | null }

/**
 * 数字滚动：首次出现从 0 滚到终值，之后每次变化（如假设草稿实时重算）从当前显示值滚到新值。
 * 返回“此刻该显示的数”；动画结束即精确等于终值。未知（null）不滚动，直接显示“—”。
 */
export function useTween(target: number | null | undefined, ms = 700): number | null | undefined {
  const ok = motionOK();
  const [anim, setAnim] = useState<Anim>(() => ({ to: target, from: 0, v: ok && isNum(target) && target !== 0 ? 0 : null }));
  if (anim.to !== target) {
    // 渲染期按 prop 调整 state（React 官方推荐模式，避免 effect 里同步 setState 造成闪一帧终值）
    const cur = anim.v ?? (isNum(anim.to) ? anim.to : null);
    setAnim({ to: target, from: cur ?? 0, v: ok && isNum(target) && cur !== null && cur !== target ? cur : null });
  }
  const running = anim.v !== null;
  const from = anim.from;
  useEffect(() => {
    if (!running || !isNum(target)) return;
    let raf = 0;
    const t0 = performance.now();
    const step = (t: number) => {
      const p = Math.min(1, (t - t0) / ms);
      setAnim((a) => (a.to === target ? { ...a, v: p < 1 ? from + (target - from) * easeOut(p) : null } : a));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [running, target, from, ms]);
  return anim.v ?? target;
}
