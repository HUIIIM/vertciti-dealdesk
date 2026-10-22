// 淘汰条件编辑器：先写“什么情况下放弃”（如 DSCR < 1.25、IRR < 12%），模型一碰线就红标。
import { useApp } from "@/app-context";

export interface Crit { metric: string; op: "<" | "<=" | ">" | ">="; threshold: number }

export function KillEditor({ value, onChange }: { value: Crit[]; onChange: (v: Crit[]) => void }) {
  const { catalog } = useApp();
  const metrics = Object.entries(catalog.metrics);
  const upd = (i: number, patch: Partial<Crit>) => onChange(value.map((c, j) => (i === j ? { ...c, ...patch } : c)));
  return (
    <fieldset style={{ border: 0, padding: 0, margin: 0, display: "grid", gap: 8 }}>
      <legend className="field" style={{ marginBottom: 8 }}>淘汰条件 <span className="hint">满足任一条即放弃；先写后算，防止“越算越想买”</span></legend>
      {value.map((c, i) => (
        <div className="row" key={i}>
          <select className="input" style={{ width: 180 }} aria-label="指标" value={c.metric} onChange={(e) => upd(i, { metric: e.target.value })}>
            {metrics.map(([k, m]) => <option key={k} value={k}>{m.label}</option>)}
          </select>
          <select className="input" style={{ width: 90 }} aria-label="比较" value={c.op} onChange={(e) => upd(i, { op: e.target.value as Crit["op"] })}>
            <option value="<">低于</option><option value="<=">不高于</option><option value=">">高于</option><option value=">=">不低于</option>
          </select>
          <input className="input num" style={{ width: 130 }} aria-label="阈值" type="number" step="any" value={c.threshold}
            onChange={(e) => upd(i, { threshold: Number(e.target.value) })} />
          <span className="muted" style={{ fontSize: 13 }}>{catalog.metrics[c.metric]?.unit === "pct" ? "%" : catalog.metrics[c.metric]?.unit === "x" ? "×" : "$"} 即放弃</span>
          <button type="button" className="btn ghost sm" onClick={() => onChange(value.filter((_, j) => j !== i))} aria-label="删除这条">删除</button>
        </div>))}
      <div><button type="button" className="btn sm" onClick={() => onChange([...value, { metric: "dscr", op: "<", threshold: 1.25 }])}>+ 加一条</button></div>
    </fieldset>
  );
}
