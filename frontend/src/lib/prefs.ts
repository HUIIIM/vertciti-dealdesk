// 本机偏好（密度、主题、列宽、视图）：localStorage 只存便利项，读写全部 try/catch（隐私模式下可能不可用）。
import { useCallback, useEffect, useState } from "react";

export function load<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(`dd.${key}`);
    return raw == null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

export function save(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(`dd.${key}`, JSON.stringify(value));
  } catch {
    /* 存不了就算了：偏好不是业务数据 */
  }
}

export function usePref<T>(key: string, fallback: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => load(key, fallback));
  const set = useCallback((nv: T) => { setV(nv); save(key, nv); }, [key]);
  return [v, set];
}

export type Density = "comfortable" | "compact";
export type Theme = "light" | "dark" | "auto";

export function useAppearance(): { density: Density; setDensity: (d: Density) => void; theme: Theme; setTheme: (t: Theme) => void } {
  const [density, setDensity] = usePref<Density>("density", "comfortable");
  const [theme, setTheme] = usePref<Theme>("theme", "light");
  useEffect(() => {
    const el = document.documentElement;
    el.dataset.density = density;
    if (theme === "auto") { delete el.dataset.theme; el.dataset.themeAuto = "1"; }
    else { el.dataset.theme = theme; delete el.dataset.themeAuto; }
  }, [density, theme]);
  return { density, setDensity, theme, setTheme };
}
