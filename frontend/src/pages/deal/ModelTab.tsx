// 模型（ARGUS 式）：左侧假设、右侧结果；改假设右侧实时更新；现金流按年 / 按月切换。
import { T } from "@/i18n";
import { useState } from "react";
import { useApp } from "@/app-context";
import { FieldInput } from "@/components/FieldInput";
import { passportStatus } from "@/components/Passport";
import { Metric, MetricGrid, NumCell } from "@/components/ui";
import { COM_ANALYSIS, COM_PROPERTY, RES_DEAL, RES_EXIT } from "@/domain/fields";
import type { Unit } from "@/lib/format";
import { getPath } from "@/lib/paths";
import { useDeal } from "./Deal";
import { InstModel } from "./InstTabs";

export function ModelTab() {
  const { track } = useDeal();
  return track === "institutional" ? <InstModel /> : <ClassicModel />;
}

function ClassicModel() {
  const { track, draft, set, preview, previewing, passports, openPassport } = useDeal();
  const { catalog } = useApp();
  const [period, setPeriod] = useState<"year" | "month">("year");
  const specs = track === "commercial" ? [...COM_ANALYSIS, ...COM_PROPERTY] : [...RES_DEAL, ...RES_EXIT];
  const m = preview?.metrics ?? {};
  const shownMetrics = Object.entries(catalog.metrics).filter(([k]) => m[k] !== undefined
    && !(track === "residential" && (k === "irr_pct" || k === "equity_multiple" || k === "breakeven_occupancy_pct")));
  const det = (preview?.detail ?? {}) as { compute?: { analysis?: { exit?: { cash_flows?: number[]; sale_proceeds?: number | null } } };
    score?: { metrics?: Record<string, number>; total?: number; grade?: string; vetoes?: { message: string }[] } };
  const flows = det.compute?.analysis?.exit?.cash_flows ?? [];
  const div = period === "month" ? 12 : 1;
  return (
    <div className="split">
      <section className="card" aria-label={T("假设")}>
        <h2>{T("假设")}</h2><p className="sub">{T("改动只进草稿；右侧实时重算。⌘S 保存为新版本。")}</p>
        <div className="grid-form">
          {specs.map((f) => <FieldInput key={f.path} spec={f} value={getPath(draft, f.path)} onChange={(v) => set(f.path, v)}
            onPassport={(p) => openPassport(p, f.label)} passportState={passportStatus(passports[f.path])} />)}
        </div>
      </section>
      <section className="card" aria-label={T("结果")} aria-busy={previewing}>
        <div className="row" style={{ justifyContent: "space-between" }}><h2 style={{ margin: 0 }}>{T("结果")}{previewing ? <span className="muted" style={{ fontSize: 13, marginLeft: 8 }}><span className="live-dot" aria-hidden="true" />{T("计算中…")}</span> : null}</h2>
          <div className="seg" role="group" aria-label={T("现金流周期")}><button type="button" aria-pressed={period === "year"} onClick={() => setPeriod("year")}>{T("按年")}</button>
            <button type="button" aria-pressed={period === "month"} onClick={() => setPeriod("month")}>{T("按月")}</button></div></div>
        {preview?.error ? <div className="banner risk" role="alert" style={{ marginTop: 12 }}>{preview.error}</div> : null}
        <MetricGrid count={shownMetrics.length} style={{ marginTop: 12 }}>
          {shownMetrics.map(([k, meta]) => <Metric key={k} label={meta.label} value={m[k] ?? null} unit={meta.unit as Unit} />)}
        </MetricGrid>
        {track === "commercial" ? (<>
          <h3 style={{ marginTop: 20, fontSize: 15 }}>{T("持有期现金流（")}{period === "year" ? T("年") : T("月均")}{T("）")}</h3>
          <div className="table-wrap" style={{ maxHeight: "none" }}>
            <table className="t"><thead><tr><th scope="col">{T("期")}</th><th scope="col" className="num">{T("现金流")}<span className="unit">{T("（$）")}</span></th><th scope="col">{T("说明")}</th></tr></thead>
              <tbody>{flows.map((v, i) => <tr key={i}><td>{period === "year" ? T("第 {0} 年", [i]) : i === 0 ? T("期初") : T("第 {0} 年（月均）", [i])}</td>
                <NumCell v={i === 0 ? v : v / div} unit="usd" /><td className="muted">{i === 0 ? T("初始投入") : i === flows.length - 1 ? T("含退出净所得") : ""}</td></tr>)}
                {flows.length === 0 ? <tr><td colSpan={3} className="muted">{T("数据不足，暂无现金流（收购价、NOI 或退出 cap 缺失）。")}</td></tr> : null}</tbody></table>
          </div></>) : (<>
          <h3 style={{ marginTop: 20, fontSize: 15 }}>{T("月度构成")}</h3>
          <div className="table-wrap" style={{ maxHeight: "none" }}><table className="t"><thead><tr><th scope="col">{T("项目")}</th><th scope="col" className="num">{period === "year" ? T("年") : T("月")}<span className="unit">{T("（$）")}</span></th></tr></thead>
            <tbody>{([["egi", T("有效租金收入")], ["opex", T("运营费用")], ["noi_monthly", "NOI"], ["monthly_pi", T("月供 P&I")], ["piti", "PITI"], ["cash_flow_monthly", T("净现金流")]] as const).map(([k, l]) => {
              const v = det.score?.metrics?.[k]; return <tr key={k}><td>{l}</td><NumCell v={typeof v === "number" ? v * (period === "year" ? 12 : 1) : null} unit="usd" /></tr>; })}</tbody></table></div>
          {det.score ? <p style={{ marginTop: 12 }}>{T("deal 评分")}{" "}<strong>{det.score.total}</strong>{T("（")}{det.score.grade}{T("）")}{det.score.vetoes?.length ? <span className="neg"> {" "}{T("· 一票否决：")}{det.score.vetoes.map((x) => x.message).join(T("；"))}</span> : null}</p> : null}
        </>)}
      </section>
    </div>
  );
}
