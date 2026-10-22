// 新建交易：名称、赛道、地址、要价 + 淘汰条件（必填至少一条，按赛道预填默认模板）。
import { useState } from "react";
import { api, call } from "@/api/client";
import { useApp } from "@/app-context";
import { KillEditor, type Crit } from "@/components/KillEditor";
import { Dialog, useToast } from "@/components/ui";
import type { Track } from "@/domain/fields";
import { parseNum } from "@/lib/format";
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
  const switchTrack = (t: Track) => { setTrack(t); setKill((catalog.kill_criteria_defaults[t] ?? []) as Crit[]); };
  const submit = async () => {
    if (!name.trim()) { toast.err("先写交易名称"); return; }
    if (kill.length === 0) { toast.err("至少写一条淘汰条件：先想清楚什么情况下放弃"); return; }
    setBusy(true);
    try {
      const d = await call(api.POST("/api/v2/deals", { body: { name: name.trim(), track, address: address.trim(),
        asking_price: parseNum(asking), kill_criteria: kill, tags: [] } }));
      toast.ok(`已建交易：${d.name}`);
      onCreated(); onClose();
      navigate({ name: "deal", id: d.id, tab: "model" });
    } catch (e) { toast.err(e); } finally { setBusy(false); }
  };
  return (
    <Dialog title="新建交易" onClose={onClose} footer={<>
      <button className="btn ghost" type="button" onClick={onClose}>取消</button>
      <button className="btn primary" type="button" onClick={submit} disabled={busy}>{busy ? "创建中…" : "创建并开始承销"}</button></>}>
      <form onSubmit={(e) => { e.preventDefault(); void submit(); }} style={{ display: "grid", gap: 16 }}>
        <div className="seg" role="group" aria-label="赛道">
          <button type="button" aria-pressed={track === "commercial"} onClick={() => switchTrack("commercial")}>商业</button>
          <button type="button" aria-pressed={track === "residential"} onClick={() => switchTrack("residential")}>住宅</button>
        </div>
        <label className="field">交易名称<input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="如 39-09 Main St" required /></label>
        <label className="field">地址<input className="input" value={address} onChange={(e) => setAddress(e.target.value)} placeholder="街道, 城市, 州" /></label>
        <label className="field">要价<span className="hint">美元；可稍后在模型里改</span>
          <input className="input num" inputMode="decimal" value={asking} onChange={(e) => setAsking(e.target.value)} placeholder="如 4,200,000" /></label>
        <KillEditor value={kill} onChange={setKill} />
      </form>
    </Dialog>
  );
}
