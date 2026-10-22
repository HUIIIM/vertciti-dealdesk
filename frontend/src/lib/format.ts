import { T } from "@/i18n";
// 数字口径（蓝图 §6）：等宽数字、千分位、单位放表头不放单元格；负数括号 + 红色双重标示（色盲友好）；
// 未知一律 “—”，绝不编数字（AGENTS.md）。百分比为“百分比数”（6.5 表示 6.5%）。
export type Unit = "usd" | "usd_month" | "pct" | "x" | "int" | "pts" | "text";

const usd0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const dec2 = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const DASH = "—";

export function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** 表格单元格用：不带单位符号（单位在表头），负数加括号。 */
export function fmtCell(v: unknown, unit: Unit): string {
  if (!isNum(v)) return v == null || v === "" || typeof v === "number" ? DASH : String(v);
  const a = Math.abs(v);
  const body = unit === "usd" || unit === "usd_month" || unit === "int" ? usd0.format(a) : dec2.format(a);
  return v < 0 ? `(${body})` : body;
}

/** 独立展示用（指标卡、句子里）：带单位符号。 */
export function fmt(v: unknown, unit: Unit): string {
  if (!isNum(v)) return v == null || v === "" || typeof v === "number" ? DASH : String(v);
  const a = Math.abs(v);
  let s: string;
  switch (unit) {
    case "usd":
    case "usd_month":
      s = `$${usd0.format(a)}`;
      break;
    case "pct":
      s = `${dec2.format(a)}%`;
      break;
    case "x":
      s = `${dec2.format(a)}×`;
      break;
    case "pts":
      s = dec2.format(a).replace(/\.?0+$/, "") || "0";
      break;
    case "int":
      s = usd0.format(a);
      break;
    default:
      s = String(v);
  }
  return v < 0 ? `(${s})` : s;
}

export function unitSuffix(unit: Unit): string {
  return { usd: "$", usd_month: T("$/月"), pct: "%", x: "×", int: "", pts: T("分"), text: "" }[unit];
}

export function isNeg(v: unknown): boolean {
  return isNum(v) && v < 0;
}

/** 紧凑金额：$37.98M / $196.2K（看板卡片等窄位置）。 */
export function fmtShort(v: unknown): string {
  if (!isNum(v)) return DASH;
  const a = Math.abs(v);
  const s = a >= 1e9 ? `${(a / 1e9).toFixed(2)}B` : a >= 1e6 ? `${(a / 1e6).toFixed(2)}M` : a >= 1e3 ? `${(a / 1e3).toFixed(1)}K` : a.toFixed(0);
  return v < 0 ? `($${s})` : `$${s}`;
}

export function fmtDate(iso: string | null | undefined, withTime = false): string {
  if (!iso) return DASH;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return DASH;
  const p = (n: number) => String(n).padStart(2, "0");
  const day = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  return withTime ? `${day} ${p(d.getHours())}:${p(d.getMinutes())}` : day;
}

/** 解析用户输入的数字：允许千分位、$、%、括号负数；空串 → null（未知）。 */
export function parseNum(raw: string): number | null {
  const t = raw.trim();
  if (t === "") return null;
  const neg = /^\(.*\)$/.test(t) || t.startsWith("-");
  const n = Number(t.replace(/[(),$%\s×x-]/g, ""));
  if (!Number.isFinite(n)) return null;
  return neg ? -n : n;
}
