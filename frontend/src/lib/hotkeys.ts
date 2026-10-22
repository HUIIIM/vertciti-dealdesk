// 全局快捷键（蓝图 §6）：⌘K 命令栏、J/K 上下、Enter 打开、E 编辑、⌘S 保存、? 显示全部、G 然后字母跳转、Esc 关浮层。
// 焦点在输入框时只响应带修饰键的组合（⌘S / ⌘K），单字母不抢输入。
import { useEffect, useLayoutEffect, useRef } from "react";

export interface Hotkey { combo: string; label: string; group: string; run: (e: KeyboardEvent) => void; allowInInput?: boolean }

export const GLOBAL_HELP: { combo: string; label: string }[] = [
  { combo: "⌘ K", label: "打开命令栏：搜交易、跳页面、执行命令" },
  { combo: "J / K", label: "列表中下移 / 上移" },
  { combo: "Enter", label: "打开选中的交易" },
  { combo: "E", label: "编辑当前交易的模型" },
  { combo: "⌘ S", label: "保存承销版本" },
  { combo: "N", label: "新建交易" },
  { combo: "G P", label: "跳到流水线" },
  { combo: "G C", label: "跳到比较页" },
  { combo: "G S", label: "跳到设置" },
  { combo: "1 – 9 / 0", label: "交易页切换标签" },
  { combo: "?", label: "显示全部快捷键" },
  { combo: "Esc", label: "关闭浮层" },
];

function isTyping(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

export function matches(e: KeyboardEvent, combo: string): boolean {
  const parts = combo.toLowerCase().split("+");
  const key = parts.pop()!;
  const mod = parts.includes("mod");
  const shift = parts.includes("shift");
  if (mod !== (e.metaKey || e.ctrlKey)) return false;
  if (shift && !e.shiftKey) return false;
  return e.key.toLowerCase() === key;
}

/** 注册一组快捷键；组件卸载自动注销。支持 “g p” 这种两段式。 */
export function useHotkeys(keys: Hotkey[], enabled = true): void {
  const ref = useRef(keys);
  useLayoutEffect(() => { ref.current = keys; });
  useEffect(() => {
    if (!enabled) return;
    let pendingG = false;
    let timer: number | undefined;
    const on = (e: KeyboardEvent) => {
      const typing = isTyping(e.target);
      for (const hk of ref.current) {
        if (hk.combo.startsWith("g ")) {
          if (typing || e.metaKey || e.ctrlKey) continue;
          if (pendingG && e.key.toLowerCase() === hk.combo.slice(2)) {
            e.preventDefault(); pendingG = false; hk.run(e); return;
          }
          continue;
        }
        if (typing && !hk.allowInInput) continue;
        if (matches(e, hk.combo)) { e.preventDefault(); hk.run(e); return; }
      }
      if (!typing && !e.metaKey && !e.ctrlKey && e.key.toLowerCase() === "g") {
        pendingG = true;
        window.clearTimeout(timer);
        timer = window.setTimeout(() => { pendingG = false; }, 1200);
      }
    };
    window.addEventListener("keydown", on);
    return () => { window.removeEventListener("keydown", on); window.clearTimeout(timer); };
  }, [enabled]);
}
