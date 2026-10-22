// 原生 SVG 图表（零依赖，深浅色自适应）：龙卷风图（红队）、归因瀑布图（持有期复盘）。
import { T } from "@/i18n";
import type { RedTeamRow } from "@/api/types";
import { fmt } from "@/lib/format";

export function Tornado({ rows, base, label, shock }: { rows: RedTeamRow[]; base: number | null; label: string; shock: number }) {
  const W = 760, rowH = 34, top = 30, labelW = 170, H = top + rows.length * rowH + 20;
  const span = Math.max(1e-9, ...rows.flatMap((r) => [Math.abs(r.minus.delta_pct_points), Math.abs(r.plus.delta_pct_points)]));
  const RIGHT = 96, mid = labelW + (W - labelW - RIGHT) / 2, scale = (W - labelW - RIGHT) / 2 / span;
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} width="100%" role="img"
      aria-label={T("红队面板龙卷风图：每个假设上下浮动 {0}% 对{1}的影响", [shock, label])}>
      <text x={mid} y={16} textAnchor="middle">{T("基准")}{" "}{label} {fmt(base, "pct")}</text>
      <line className="axis" x1={mid} x2={mid} y1={22} y2={H - 14} />
      {rows.map((r, i) => {
        const y = top + i * rowH;
        const bar = (d: number, k: string) => {
          const w = Math.abs(d) * scale;
          // 从中轴向外生长（官网“条形生长”同一节奏），逐行错开
          return <rect key={k} x={d >= 0 ? mid : mid - w} y={y + 6} width={Math.max(w, 1)} height={rowH - 14}
            className={`${d < 0 ? "negbar grow-l" : "pos grow-r"}`} style={{ animationDelay: `${i * 70}ms` }}>
            <title>{T("{0} {1}{2}%：{3} {4}{5} 个百分点", [r.label, k === "m" ? "-" : "+", shock, label, d >= 0 ? "+" : "", d.toFixed(2)])}</title></rect>;
        };
        return (
          <g key={r.key}>
            <text x={0} y={y + rowH / 2 + 4}>{r.label}</text>
            {bar(r.minus.delta_pct_points, "m")}{bar(r.plus.delta_pct_points, "p")}
            <text x={W} y={y + rowH / 2 + 4} textAnchor="end" className={r.material ? "key" : undefined}>{Math.round(r.swing_bps)} bp{r.material ? T(" · 关键") : ""}</text>
          </g>);
      })}
    </svg>
  );
}

export function Waterfall({ start, steps, end, label }: { start: number; steps: { label: string; v: number }[]; end: number; label: string }) {
  const W = 760, H = 260, pad = 36, n = steps.length + 2, bw = (W - pad * 2) / n * 0.6, gap = (W - pad * 2) / n;
  const cum = steps.reduce<number[]>((acc, s) => [...acc, acc[acc.length - 1]! + s.v], [start]);
  const pts = [...cum, end];
  const lo = Math.min(0, ...pts), hi = Math.max(0, ...pts), y = (v: number) => H - pad - ((v - lo) / (hi - lo || 1)) * (H - pad * 2);
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={T("{0}归因瀑布图", [label])}>
      <line className="grid" x1={pad} x2={W - pad} y1={y(0)} y2={y(0)} />
      <rect className="base grow-up" x={pad + (gap - bw) / 2} y={Math.min(y(start), y(0))} width={bw} height={Math.abs(y(start) - y(0))} />
      <text x={pad + gap / 2} y={H - 10} textAnchor="middle">{T("承销")}</text>
      <text x={pad + gap / 2} y={Math.min(y(start), y(0)) - 6} textAnchor="middle">{fmt(start, "pct")}</text>
      {steps.map((s, i) => {
        const a = cum[i]!, b = cum[i + 1]!, x = pad + gap * (i + 1) + (gap - bw) / 2;
        return (<g key={s.label}>
          <rect className={s.v < 0 ? "negbar grow-down" : "pos grow-up"} x={x} y={Math.min(y(a), y(b))} width={bw}
            height={Math.max(1, Math.abs(y(a) - y(b)))} style={{ animationDelay: `${(i + 1) * 140}ms` }} />
          <text className="fade-in" style={{ animationDelay: `${(i + 1) * 140 + 300}ms` }} x={x + bw / 2} y={Math.min(y(a), y(b)) - 6}
            textAnchor="middle">{s.v >= 0 ? "+" : ""}{s.v.toFixed(2)}</text>
          <text x={x + bw / 2} y={H - 10} textAnchor="middle">{s.label.length > 8 ? s.label.slice(0, 8) + "…" : s.label}</text></g>);
      })}
      <rect className="base grow-up" style={{ animationDelay: `${(n - 1) * 140}ms` }} x={pad + gap * (n - 1) + (gap - bw) / 2} y={Math.min(y(end), y(0))} width={bw} height={Math.abs(y(end) - y(0))} />
      <text x={pad + gap * (n - 1) + gap / 2} y={H - 10} textAnchor="middle">{T("实际推算")}</text>
      <text x={pad + gap * (n - 1) + gap / 2} y={Math.min(y(end), y(0)) - 6} textAnchor="middle">{fmt(end, "pct")}</text>
    </svg>
  );
}
