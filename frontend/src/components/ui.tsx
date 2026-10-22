// DNA 基础组件。状态词全系统统一：已验证 / 建设中 / 计划中 / 风险（颜色 + 图标 + 文字三重表意）。
import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiError } from "@/api/client";
import { fmt, fmtCell, fmtShort, isNeg, isNum, type Unit } from "@/lib/format";

export type StatusKey = "verified" | "building" | "planned" | "risk";
export const STATUS_LABEL: Record<StatusKey, string> = { verified: "已验证", building: "建设中", planned: "计划中", risk: "风险" };

export function Status({ s, children }: { s: StatusKey; children?: ReactNode }) {
  return <span className={`status ${s}`}><i aria-hidden="true" />{children ?? STATUS_LABEL[s]}</span>;
}

export function Kbd({ k }: { k: string }) {
  return <>{k.split(" ").map((x, i) => <kbd key={i}>{x}</kbd>)}</>;
}

/** 指标卡：数字可点（打开数字护照 / 计算说明）。 */
export function Metric({ label, value, unit, note, onOpen, testId }: {
  label: string; value: number | null | undefined; unit: Unit; note?: ReactNode; onOpen?: () => void; testId?: string;
}) {
  const full = fmt(value, unit);
  // 百万级金额在卡片里用紧凑写法（$36.00M），完整数放 title 与读屏文本，避免截断
  const text = (unit === "usd" || unit === "usd_month") && isNum(value) && Math.abs(value) >= 1e6 ? fmtShort(value) : full;
  return (
    <div className="metric" data-testid={testId}>
      <div className="k">{label}</div>
      <div className={`v${isNeg(value) ? " neg" : ""}`} title={full}>
        {onOpen ? <button type="button" onClick={onOpen} aria-label={`${label} ${full}，查看来源与计算`}>{text}</button> : text}
      </div>
      {note ? <div className="note">{note}</div> : null}
    </div>
  );
}

/** 表格数字单元格：右对齐、等宽、负数括号 + 红色。单位写在表头。 */
export function NumCell({ v, unit }: { v: unknown; unit: Unit }) {
  return <td className={`num${isNeg(v) ? " neg" : ""}`}>{fmtCell(v, unit)}</td>;
}

export function Skeleton({ rows = 3, h = 18 }: { rows?: number; h?: number }) {
  return (
    <div aria-busy="true" aria-label="加载中" style={{ display: "grid", gap: 8 }}>
      {Array.from({ length: rows }, (_, i) => <div key={i} className="skeleton" style={{ height: h, width: `${90 - i * 12}%` }} />)}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="empty"><p style={{ fontWeight: 800, color: "var(--text-2)", margin: 0 }}>{title}</p>{children}</div>;
}

export function ErrorBox({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  const rid = error instanceof ApiError ? error.requestId : null;
  return (
    <div className="banner risk" role="alert">
      <strong>出错了：</strong>{error.message}
      {rid ? <span className="muted mono"> · 请求编号 {rid}</span> : null}
      {onRetry ? <> <button className="btn sm" type="button" onClick={onRetry}>重试</button></> : null}
    </div>
  );
}

// ---------------------------------------------------------------- 对话框：焦点陷阱、Esc 关闭、关闭后焦点归还
export function Dialog({ title, onClose, children, footer, wide }: {
  title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    const el = ref.current!;
    const focusables = () => Array.from(el.querySelectorAll<HTMLElement>(
      "button,[href],input,select,textarea,[tabindex]:not([tabindex='-1'])")).filter((x) => !x.hasAttribute("disabled"));
    (focusables().find((x) => x.tagName === "INPUT" || x.tagName === "SELECT" || x.tagName === "TEXTAREA") ?? focusables()[0])?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); onClose(); }
      if (e.key === "Tab") {
        const f = focusables();
        if (!f.length) return;
        const first = f[0]!, last = f[f.length - 1]!;
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    el.addEventListener("keydown", onKey);
    return () => { el.removeEventListener("keydown", onKey); prev?.focus?.(); };
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} ref={ref} style={wide ? { width: "min(960px,100%)" } : undefined}>
        <header><h2 id={titleId}>{title}</h2><button className="btn ghost sm" type="button" onClick={onClose} aria-label="关闭">Esc</button></header>
        <div className="body">{children}</div>
        {footer ? <footer>{footer}</footer> : null}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Toast
interface ToastItem { id: number; text: string; kind: "ok" | "err" | "info" }
const ToastCtx = createContext<(text: string, kind?: ToastItem["kind"]) => void>(() => {});

export function ToastHost({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const push = useCallback((text: string, kind: ToastItem["kind"] = "info") => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs, { id, text, kind }]);
    window.setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), kind === "err" ? 8000 : 3500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toast-host" role="status" aria-live="polite">
        {items.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.text}</div>)}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast() {
  const push = useContext(ToastCtx);
  return useMemo(() => ({
    ok: (t: string) => push(t, "ok"),
    info: (t: string) => push(t, "info"),
    err: (e: unknown) => {
      const msg = e instanceof Error ? e.message : String(e);
      const rid = e instanceof ApiError && e.requestId ? `（请求编号 ${e.requestId.slice(0, 8)}）` : "";
      push(msg + rid, "err");
    },
  }), [push]);
}
