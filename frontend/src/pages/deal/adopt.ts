// 采用候选值：写进草稿（保存一版才生效），同时逐条登记数字护照——谁、从哪份文件第几页、什么可信度。
import { T } from "@/i18n";
import { api, call } from "@/api/client";
import type { Candidate } from "@/api/types";
import { useToast } from "@/components/ui";
import { useDeal } from "./Deal";

export function useAdopt(): (items: Candidate[], documentId?: number) => Promise<void> {
  const { id, set, reload } = useDeal();
  const toast = useToast();
  return async (items, documentId) => {
    const usable = items.filter((c): c is Candidate & { path: string } => Boolean(c.path) && c.value !== null);
    for (const c of usable) set(c.path, c.value);
    try {
      await Promise.all(usable.map((c) => call(api.POST("/api/v2/deals/{deal_id}/evidence", { params: { path: { deal_id: id } }, body: {
        field: c.path, value: c.value as never, source: (c.source_url ? `${c.source} · ${c.source_url}` : c.source).slice(0, 300),
        method: c.method, confidence: c.confidence, page: c.page, document_id: documentId ?? null,
        assumption_source: "document", market_data: false, evidence_at: new Date().toISOString().slice(0, 10),
        note: c.seller_claimed ? T("卖方口径、待验证") : c.note } }))));
      toast.ok(T("已采用 {0} 项并登记来源：记得保存一版", [usable.length]));
      await reload();
    } catch (e) { toast.err(e); }
  };
}
