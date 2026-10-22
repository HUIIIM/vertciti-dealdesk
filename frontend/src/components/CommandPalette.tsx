// ⌘K 命令栏（Bloomberg 式）：输入地址、交易名或命令直达。↑↓ 选择、Enter 执行、Esc 关闭。
import { T } from "@/i18n";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, call, type DealListItem } from "@/api/client";
import { navigate } from "@/lib/router";

export interface Command { id: string; group: string; label: string; hint?: string; run: () => void }

function score(q: string, text: string): number {
  if (!q) return 1;
  const t = text.toLowerCase(), s = q.toLowerCase();
  if (t.includes(s)) return 100 - t.indexOf(s);
  let i = 0;
  for (const ch of t) if (ch === s[i]) i++;
  return i === s.length ? 10 : 0;
}

export function CommandPalette({ onClose, commands }: { onClose: () => void; commands: Command[] }) {
  const [q, setQ] = useState("");
  const [deals, setDeals] = useState<DealListItem[]>([]);
  const [sel, setSel] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { input.current?.focus(); call(api.GET("/api/v2/deals")).then(setDeals).catch(() => setDeals([])); }, []);
  const items = useMemo<Command[]>(() => {
    const dealCmds: Command[] = deals.map((d) => ({ id: `deal-${d.id}`, group: T("交易"), label: d.name,
      hint: `${d.stage_label} · ${d.address || "—"}`, run: () => navigate({ name: "deal", id: d.id, tab: "overview" }) }));
    return [...dealCmds, ...commands]
      .map((c) => ({ c, s: Math.max(score(q, c.label), score(q, c.hint ?? "") * 0.8) }))
      .filter((x) => x.s > 0).sort((a, b) => b.s - a.s).slice(0, 30).map((x) => x.c);
  }, [q, deals, commands]);
  const run = (c: Command | undefined) => { if (c) { onClose(); c.run(); } };
  return (
    <div className="overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="cmdk" role="dialog" aria-modal="true" aria-label={T("命令栏")}>
        <input ref={input} value={q} onChange={(e) => { setQ(e.target.value); setSel(0); }} placeholder={T("搜交易名 / 地址，或输入命令（新建、比较、设置、密度、深色…）")}
          aria-label={T("命令栏搜索")} role="combobox" aria-expanded="true" aria-controls="cmdk-list" aria-activedescendant={items[sel] ? `cmd-${items[sel]!.id}` : undefined}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, items.length - 1)); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
            else if (e.key === "Enter") { e.preventDefault(); run(items[sel]); }
            else if (e.key === "Escape") { e.preventDefault(); onClose(); }
          }} />
        <ul id="cmdk-list" role="listbox">
          {items.length === 0 ? <li aria-disabled="true"><span className="muted">{T("没有匹配项")}</span></li> : items.map((c, i) => (
            <li key={c.id} id={`cmd-${c.id}`} role="option" aria-selected={i === sel} onMouseEnter={() => setSel(i)} onClick={() => run(c)}>
              <span className="grp">{c.group}</span><span>{c.label}</span><span className="sp" /><span className="muted" style={{ fontSize: 12 }}>{c.hint}</span>
            </li>))}
        </ul>
      </div>
    </div>
  );
}
