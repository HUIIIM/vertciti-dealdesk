// 表单字段：数字按千分位显示、失焦解析；旁边“源”按钮打开该字段的数字护照（来源 / 页码 / 复核 / 历史）。
import { useId, useState } from "react";
import type { FieldSpec } from "@/domain/fields";
import { fmtCell, parseNum, type Unit } from "@/lib/format";

export function NumberInput({ value, onChange, unit, label, invalid, step }: {
  value: unknown; onChange: (v: number | null) => void; unit: Unit; label: string; invalid?: boolean; step?: number;
}) {
  const shown = typeof value === "number" ? (unit === "pct" || unit === "x" ? String(value) : fmtCell(value, unit)) : "";
  // 编辑中显示原始输入；失焦后显示格式化值（派生，无需 effect 同步）
  const [editing, setEditing] = useState<string | null>(null);
  return (
    <input className="input num" inputMode="decimal" aria-label={label} aria-invalid={invalid || undefined} value={editing ?? shown} data-step={step}
      onFocus={() => setEditing(typeof value === "number" ? String(value) : "")}
      onChange={(e) => { setEditing(e.target.value); const n = parseNum(e.target.value); if (n !== null || e.target.value.trim() === "") onChange(n); }}
      onBlur={() => setEditing(null)} />
  );
}

export function FieldInput({ spec, value, onChange, onPassport, passportState }: {
  spec: FieldSpec; value: unknown; onChange: (v: unknown) => void; onPassport?: (path: string) => void;
  passportState?: "verified" | "building" | "planned" | "risk";
}) {
  const id = useId();
  const unitTxt = spec.unit === "pct" ? "%" : spec.unit === "usd" ? "$" : spec.unit === "usd_month" ? "$/月" : spec.unit === "x" ? "×" : "";
  return (
    <div className="field">
      <label htmlFor={id} style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <span>{spec.label}{unitTxt ? <span className="hint">（{unitTxt}）</span> : null}</span>
        {onPassport ? (
          <button type="button" className="btn ghost sm" style={{ minHeight: 24, padding: "0 6px", marginLeft: "auto" }}
            onClick={() => onPassport(spec.path)} aria-label={`${spec.label} 的数字护照`} title="来源 · 复核 · 修改历史">
            <span className={`status ${passportState ?? "planned"}`} style={{ padding: "0 4px" }}><i aria-hidden="true" />源</span>
          </button>) : null}
      </label>
      {spec.unit === "select" ? (
        <select id={id} className="input" value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
          {spec.options!.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      ) : spec.unit === "text" ? (
        <input id={id} className="input" value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />
      ) : spec.unit === "bool" ? (
        <input id={id} type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} style={{ width: 24, height: 24 }} />
      ) : (
        <span id={id} style={{ display: "contents" }}>
          <NumberInput value={value} onChange={onChange} unit={spec.unit as Unit} label={spec.label} step={spec.step} />
        </span>
      )}
      {spec.hint ? <span className="hint">{spec.hint}</span> : null}
    </div>
  );
}
