// 数据表：表头与首列冻结、点表头排序、列宽可拖动并记住（本机偏好）、悬停整行高亮、键盘选中行。
import { T } from "@/i18n";
import { useRef, useState, type ReactNode } from "react";
import { load, save } from "@/lib/prefs";
import { unitSuffix, type Unit } from "@/lib/format";

export interface Column<T> { key: string; header: string; unit?: Unit; numeric?: boolean; width?: number;
  render: (row: T) => ReactNode; sortValue?: (row: T) => number | string | null }

export function DataTable<T>({ id, columns, rows, rowKey, selected, onRowClick, caption, footer }: {
  id: string; columns: Column<T>[]; rows: T[]; rowKey: (r: T) => string | number; selected?: number;
  onRowClick?: (r: T) => void; caption?: string; footer?: ReactNode;
}) {
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(() => load(`sort.${id}`, null));
  const [widths, setWidths] = useState<Record<string, number>>(() => load(`cols.${id}`, {}));
  const drag = useRef<{ key: string; x: number; w: number } | null>(null);
  const col = columns.find((c) => c.key === sort?.key);
  const sorted = col?.sortValue ? [...rows].sort((a, b) => {
    const va = col.sortValue!(a), vb = col.sortValue!(b);
    if (va == null) return 1;
    if (vb == null) return -1;
    return (va < vb ? -1 : va > vb ? 1 : 0) * sort!.dir;
  }) : rows;
  const toggle = (k: string) => {
    const next = sort?.key === k ? (sort.dir === 1 ? { key: k, dir: -1 as const } : null) : { key: k, dir: 1 as const };
    setSort(next); save(`sort.${id}`, next);
  };
  const startResize = (e: React.PointerEvent, key: string) => {
    e.preventDefault(); e.stopPropagation();
    const th = (e.target as HTMLElement).parentElement!;
    drag.current = { key, x: e.clientX, w: th.getBoundingClientRect().width };
    const move = (ev: PointerEvent) => {
      const d = drag.current; if (!d) return;
      setWidths((w) => ({ ...w, [d.key]: Math.max(64, Math.round(d.w + ev.clientX - d.x)) }));
    };
    const up = () => {
      window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up);
      drag.current = null; setWidths((w) => { save(`cols.${id}`, w); return w; });
    };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
  };
  return (
    <div className="table-wrap">
      <table className="t">
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        <colgroup>{columns.map((c) => <col key={c.key} style={{ width: widths[c.key] ?? c.width }} />)}</colgroup>
        <thead>
          <tr>{columns.map((c) => {
            const s = sort?.key === c.key ? (sort.dir === 1 ? "ascending" : "descending") : "none";
            return (
              <th key={c.key} scope="col" className={`${c.numeric || c.unit ? "num" : ""} ${c.sortValue ? "sortable" : ""}`} aria-sort={c.sortValue ? s : undefined}
                style={{ position: "sticky" }}>
                {c.sortValue ? <button type="button" onClick={() => toggle(c.key)} style={{ all: "unset", cursor: "pointer" }}>
                  {c.header}{c.unit && unitSuffix(c.unit) ? <span className="unit">{T("（")}{unitSuffix(c.unit)}{T("）")}</span> : null}
                  {s === "ascending" ? " ↑" : s === "descending" ? " ↓" : ""}</button>
                  : <>{c.header}{c.unit && unitSuffix(c.unit) ? <span className="unit">{T("（")}{unitSuffix(c.unit)}{T("）")}</span> : null}</>}
                <span className="resize desktop-only" role="separator" aria-orientation="vertical" aria-label={T("调整“{0}”列宽", [c.header])} onPointerDown={(e) => startResize(e, c.key)} />
              </th>);
          })}</tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => (
            <tr key={rowKey(r)} data-selected={selected === i ? "" : undefined} onClick={onRowClick ? () => onRowClick(r) : undefined}
              style={onRowClick ? { cursor: "pointer" } : undefined}>
              {columns.map((c) => <td key={c.key} className={c.numeric || c.unit ? "num" : undefined}>{c.render(r)}</td>)}
            </tr>))}
        </tbody>
        {footer}
      </table>
    </div>
  );
}
