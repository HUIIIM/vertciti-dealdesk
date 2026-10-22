// 导出（老版功能）：按当前承销版本生成投资备忘录 PDF、核保明细 Excel；商业另有一页纸与经典核保报告。
import { T } from "@/i18n";
import { useState } from "react";
import { raw } from "@/api/client";
import { useToast } from "@/components/ui";
import { saveResponse } from "@/lib/download";
import { useDeal } from "./Deal";

type Kind = "memo" | "model" | "tearsheet" | "report";

export function ExportCard() {
  const { id, track, ov } = useDeal();
  const toast = useToast();
  const [busy, setBusy] = useState<Kind | null>(null);
  const kinds: [Kind, string][] = [["memo", T("投资备忘录 PDF")], ["model", T("核保明细 Excel")],
    ...(track === "commercial" ? [["tearsheet", T("一页纸 Tear Sheet")], ["report", T("经典核保报告 PDF")]] as [Kind, string][] : [])];
  const go = async (k: Kind) => {
    setBusy(k);
    try { const name = await saveResponse(await raw(`/api/v2/deals/${id}/export/${k}`), `dealdesk-${id}-${k}`); toast.ok(T("已导出：{0}", [name])); }
    catch (e) { toast.err(e); } finally { setBusy(null); }
  };
  return (
    <section className="card flat" aria-label={T("导出")}>
      <h2>{T("导出")}</h2>
      <p className="sub">{ov.version ? T("按当前版本（第 {0} 版）现算；缺的数显示“—”，不估算。", [ov.version.version_no]) : T("先保存一版承销才能导出。")}</p>
      <div className="row">{kinds.map(([k, l]) => (
        <button key={k} className={k === "memo" ? "btn primary" : "btn"} type="button" disabled={!ov.version || busy !== null} onClick={() => void go(k)}>
          {busy === k ? T("生成中…") : l}</button>))}</div>
    </section>
  );
}
