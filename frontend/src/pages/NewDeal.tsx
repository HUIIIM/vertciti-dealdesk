// 新建交易：名称、赛道、地址、要价 + 淘汰条件（必填至少一条，按赛道预填默认模板）。
import { T } from "@/i18n";
import { useState } from "react";
import { api, call } from "@/api/client";
import type { Candidate, Research } from "@/api/types";
import { useApp } from "@/app-context";
import { Candidates } from "@/components/Candidates";
import { KillEditor, type Crit } from "@/components/KillEditor";
import { Dialog, useToast } from "@/components/ui";
import type { Track } from "@/domain/fields";
import { parseNum } from "@/lib/format";
import { prefillKey } from "@/lib/prefill";
import { navigate } from "@/lib/router";

export function NewDeal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { catalog } = useApp();
  const toast = useToast();
  const [track, setTrack] = useState<Track>("commercial");
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [asking, setAsking] = useState("");
  const [kill, setKill] = useState<Crit[]>(() => (catalog.kill_criteria_defaults.commercial ?? []) as Crit[]);
  const [busy, setBusy] = useState(false);
  const [found, setFound] = useState<Research | null>(null);
  const [researching, setResearching] = useState(false);
  const [carry, setCarry] = useState<Candidate[]>([]);
  const research = async () => {
    const text = address.trim();
    if (!text) { toast.err(T("先填地址或贴房源链接")); return; }
    setResearching(true); setFound(null);
    try { setFound(await call(api.POST("/api/v2/research", { body: { track, mode: /^https?:\/\//i.test(text) ? "url" : "address", text } }))); }
    catch (e) { toast.err(e); } finally { setResearching(false); }
  };
  const take = (picked: Candidate[]) => {
    const price = picked.find((c) => c.key === "asking_price" && typeof c.value === "number");
    if (price) setAsking(String(price.value));
    if (found?.address && /^https?:\/\//i.test(address.trim())) setAddress(found.address);
    if (!name.trim() && found?.address) setName(found.address.split(",")[0] ?? found.address);
    setCarry(picked); setFound(null);
    toast.ok(T("已带入 {0} 项：建好交易后写进承销草稿并登记来源", [picked.length]));
  };
  const switchTrack = (t: Track) => { setTrack(t); setKill((catalog.kill_criteria_defaults[t] ?? []) as Crit[]); };
  const submit = async () => {
    if (!name.trim()) { toast.err(T("先写交易名称")); return; }
    if (kill.length === 0) { toast.err(T("至少写一条淘汰条件：先想清楚什么情况下放弃")); return; }
    setBusy(true);
    try {
      const d = await call(api.POST("/api/v2/deals", { body: { name: name.trim(), track, address: address.trim(),
        asking_price: parseNum(asking), kill_criteria: kill, tags: [] } }));
      if (carry.length) { try { localStorage.setItem(prefillKey(d.id), JSON.stringify(carry)); } catch { /* 存不了就只建交易，不带入 */ } }
      toast.ok(T("已建交易：{0}", [d.name]));
      onCreated(); onClose();
      navigate({ name: "deal", id: d.id, tab: "model" });
    } catch (e) { toast.err(e); } finally { setBusy(false); }
  };
  return (
    <Dialog title={T("新建交易")} onClose={onClose} footer={<>
      <button className="btn ghost" type="button" onClick={onClose}>{T("取消")}</button>
      <button className="btn primary" type="submit" form="new-deal-form" disabled={busy}>{busy ? T("创建中…") : T("创建并开始承销")}</button></>}>
      {/* 提交按钮在底栏，用 form 属性关联：表单内按 Enter 即可提交（键盘用户） */}
      <form id="new-deal-form" onSubmit={(e) => { e.preventDefault(); void submit(); }} style={{ display: "grid", gap: 16 }}>
        <div className="seg" role="group" aria-label={T("赛道")}>
          <button type="button" aria-pressed={track === "commercial"} onClick={() => switchTrack("commercial")}>{T("商业")}</button>
          <button type="button" aria-pressed={track === "residential"} onClick={() => switchTrack("residential")}>{T("住宅")}</button>
        </div>
        <label className="field">{T("交易名称")}<input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder={T("如 39-09 Main St")} required /></label>
        <label className="field">{T("地址")}<span className="hint">{T("也可以贴房源链接")}</span>
          <input className="input" value={address} onChange={(e) => setAddress(e.target.value)} placeholder={T("街道, 城市, 州")} /></label>
        <div className="row">
          <button className="btn sm" type="button" disabled={researching || !address.trim()} onClick={() => void research()}>
            {researching ? T("搜集中…（约 30–90 秒）") : T("自动搜集公开信息")}</button>
          {carry.length ? <span className="muted" style={{ fontSize: 13 }}>{T("已带入 {0} 项", [carry.length])}</span> : null}
        </div>
        {found ? <div className="card flat" style={{ margin: 0 }}>
          {found.error ? <p className="banner warn">{found.error}</p> : null}
          <Candidates items={found.candidates} onAdopt={take} adoptLabel={T("带入新交易")} />
          {found.manual_needed.length ? <p className="muted" style={{ fontSize: 13 }}>{T("没找到、需要手动补：{0}", [found.manual_needed.join(T("、"))])}</p> : null}
        </div> : null}
        <label className="field">{T("要价")}<span className="hint">{T("美元；可稍后在模型里改")}</span>
          <input className="input num" inputMode="decimal" value={asking} onChange={(e) => setAsking(e.target.value)} placeholder={T("如 4,200,000")} /></label>
        <KillEditor value={kill} onChange={setKill} />
      </form>
    </Dialog>
  );
}
