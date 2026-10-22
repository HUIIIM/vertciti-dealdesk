// 候选值清单（从 PDF 提取 / 按地址搜集）：逐条勾选采用；只作参考的项（不是承销输入）列出但不能勾。
import { T } from "@/i18n";
import { useState } from "react";
import type { Candidate } from "@/api/types";
import { Status } from "@/components/ui";
import { fieldLabel } from "@/domain/fields";

const CONF: Record<Candidate["confidence"], string> = { high: T("高"), medium: T("中"), low: T("低") };

export function Candidates({ items, onAdopt, busy = false, adoptLabel = T("采用所选") }: {
  items: Candidate[]; onAdopt: (picked: Candidate[]) => void; busy?: boolean; adoptLabel?: string;
}) {
  const [picked, setPicked] = useState<Set<number>>(() => new Set(items.flatMap((c, i) => (c.path ? [i] : []))));
  if (items.length === 0) return <p className="muted">{T("没有找到可用的字段。")}</p>;
  const toggle = (i: number) => setPicked((s) => { const n = new Set(s); if (n.has(i)) n.delete(i); else n.add(i); return n; });
  return (
    <>
      <div className="table-wrap" style={{ maxHeight: "none" }}><table className="t">
        <thead><tr><th scope="col"><span className="sr-only">{T("采用")}</span></th><th scope="col">{T("字段")}</th><th scope="col">{T("值")}</th>
          <th scope="col">{T("来源")}</th><th scope="col">{T("可信度")}</th></tr></thead>
        <tbody>{items.map((c, i) => (
          <tr key={`${c.key}-${i}`}>
            <td>{c.path ? <input type="checkbox" checked={picked.has(i)} onChange={() => toggle(i)} aria-label={T("采用：{0}", [c.label])} />
              : <span className="muted" title={T("不是承销输入，只作参考")}>—</span>}</td>
            <td>{c.path ? <span title={c.path}>{fieldLabel(c.path)}</span> : c.label}{c.path ? null : <div className="d">{T("仅参考")}</div>}</td>
            <td className="mono">{c.display || "—"}</td>
            <td>{c.source}{c.page ? ` p.${c.page}` : ""}{c.seller_claimed ? <div className="d">{T("卖方口径、待验证")}</div> : null}</td>
            <td><Status s={c.confidence === "high" ? "verified" : c.confidence === "medium" ? "building" : "planned"}>{CONF[c.confidence]}</Status></td>
          </tr>))}</tbody></table></div>
      <div className="row" style={{ marginTop: 12 }}>
        <button className="btn primary" type="button" disabled={busy || picked.size === 0} onClick={() => onAdopt(items.filter((_, i) => picked.has(i)))}>
          {adoptLabel}{T("（{0}）", [picked.size])}</button>
        <span className="muted" style={{ fontSize: 13 }}>{T("采用后写进草稿并登记数字护照；保存一版才生效。")}</span>
      </div>
    </>
  );
}
