// 机构级赛道的三个页面：逐租约租金表（含到期续租假设、WALT）、市场租赁假设与运营费用、模型（债务 / 退出 / 瀑布 + 逐年现金流）。
import { T } from "@/i18n";
import { useApp } from "@/app-context";
import { FieldInput, NumberInput } from "@/components/FieldInput";
import { passportStatus } from "@/components/Passport";
import { Metric, MetricGrid, NumCell } from "@/components/ui";
import { INST_DEAL, INST_DEBT, INST_MARKET, INST_MF_OPEX, INST_MF_RENO, INST_MF_REVENUE, INST_OPEX, INST_WATERFALL, MF_DEFAULTS,
  blankInstitutional, blankUnit, type FieldSpec } from "@/domain/fields";
import { fmt, type Unit } from "@/lib/format";
import { getPath, type JsonObj } from "@/lib/paths";
import { useDeal } from "./Deal";

interface Lease { tenant?: string; suite?: string; sf?: number; start?: string; end?: string; rent_psf_yr?: number; escalation_pct?: number;
  free_rent_months?: number; recovery?: "nnn" | "gross" | "base_year" }
interface UnitRow { name?: string; units?: number; avg_sf?: number; in_place_rent?: number; market_rent?: number; renovate_units?: number;
  reno_cost_per_unit?: number; reno_premium?: number }
interface Seg { tenant: string; suite: string; sf: number; start: number; end: number; rent_psf: number; speculative: boolean;
  downtime_before: number; ti: number; lc: number }
interface Cre { metrics: Record<string, number | null>; annual: Record<string, number[]>; rent_roll: Seg[];
  waterfall: { lp_irr_pct: number | null; gp_irr_pct: number | null; lp_multiple: number | null; gp_multiple: number | null; gp_promote: number } | null;
  exit: { sale_price: number; selling_costs: number; loan_payoff: number; net_proceeds_levered: number } }

/** 多户公寓（按户型）还是按租约（写字楼 / 零售 / 工业）。 */
export function useIsMf(): boolean {
  const { draft } = useDeal();
  return draft.property_type === "multifamily";
}

/** 物业类型切换：多户公寓不填逐份租约（有租约时先确认清掉）；按租约物业缺市场租赁假设时补默认值。 */
function PropertyType() {
  const { draft, set } = useDeal();
  const mf = draft.property_type === "multifamily";
  const leases = (draft.leases as Lease[] | undefined) ?? [];
  const toMf = () => {
    if (mf) return;
    if (leases.length && !window.confirm(T("多户公寓按户型建模，会清掉现有 {0} 份租约。继续？", [leases.length]))) return;
    set("leases", []);
    if (!Array.isArray(draft.unit_mix) || !(draft.unit_mix as UnitRow[]).length) set("unit_mix", [{ ...blankUnit(), name: "1B1B" }]);
    if (!draft.multifamily) set("multifamily", { ...MF_DEFAULTS });
    set("property_type", "multifamily");
  };
  const toCommercial = () => {
    if (!mf) return;
    if (!draft.market) set("market", blankInstitutional().market);
    set("property_type", "commercial");
  };
  return (
    <div className="seg" role="group" aria-label={T("物业类型")} style={{ marginBottom: 12 }}>
      <button type="button" aria-pressed={!mf} onClick={toCommercial}>{T("按租约（写字楼 / 零售 / 工业）")}</button>
      <button type="button" aria-pressed={mf} onClick={toMf}>{T("多户公寓（按户型）")}</button>
    </div>
  );
}

/** 按户数加权的平均在租月租与市场月租。 */
export function unitAverages(units: UnitRow[]): { units: number; inPlace: number | null; market: number | null } {
  const n = units.reduce((a, u) => a + (u.units ?? 0), 0);
  if (!n) return { units: 0, inPlace: null, market: null };
  const w = (k: "in_place_rent" | "market_rent") => units.reduce((a, u) => a + (u.units ?? 0) * (u[k] ?? 0), 0) / n;
  return { units: n, inPlace: w("in_place_rent"), market: w("market_rent") };
}

function UnitMix() {
  const { draft, set, passports, openPassport } = useDeal();
  const cre = useCre();
  const units = (draft.unit_mix as UnitRow[] | undefined) ?? [];
  const upd = (i: number, k: keyof UnitRow, v: unknown) => set(`unit_mix.${i}.${k}`, v);
  const avg = unitAverages(units);
  const ltl = avg.market && avg.inPlace != null ? ((avg.market - avg.inPlace) / avg.market) * 100 : null;
  const reno = units.reduce((a, u) => a + (u.renovate_units ?? 0), 0);
  const num = (i: number, k: keyof UnitRow, label: string, unit: "int" | "usd") => (
    <NumberInput value={units[i]![k] as number | undefined} unit={unit} label={T("第 {0} 个户型{1}", [i + 1, label])}
      onChange={(v) => upd(i, k, k === "units" || k === "renovate_units" ? Math.round(v ?? 0) : v ?? 0)} />);
  return (
    <section className="card" aria-label={T("户型表")}>
      <div className="row" style={{ justifyContent: "space-between" }}><h2 style={{ margin: 0 }}>{T("户型表")}</h2>
        <button className="btn sm" type="button" onClick={() => set("unit_mix", [...units, blankUnit()])}>{T("+ 加户型")}</button></div>
      <p className="sub">{T("租金按每户每月。在租租约在租期内均匀到期、调到市场租金；翻新户停用后按市场租金 + 溢价出租。")}</p>
      <MetricGrid count={4} style={{ marginBottom: 12 }}>
        <Metric label={T("总户数")} value={avg.units} unit="int" />
        <Metric label={T("平均在租月租")} value={avg.inPlace} unit="usd" />
        <Metric label="Loss-to-lease" value={ltl} unit="pct" />
        <Metric label={T("翻新户数")} value={reno} unit="int" />
      </MetricGrid>
      <div className="table-wrap" style={{ maxHeight: "none" }}><table className="t">
        <thead><tr><th scope="col">{T("户型")}</th><th scope="col" className="num">{T("户数")}</th><th scope="col" className="num">{T("户均面积")}<span className="unit">SF</span></th>
          <th scope="col" className="num">{T("在租月租")}<span className="unit">$</span></th><th scope="col" className="num">{T("市场月租")}<span className="unit">$</span></th>
          <th scope="col" className="num">{T("翻新户数")}</th><th scope="col" className="num">{T("每户翻新成本")}<span className="unit">$</span></th>
          <th scope="col" className="num">{T("翻新溢价")}<span className="unit">{T("$/月")}</span></th><th scope="col"><span className="sr-only">{T("操作")}</span></th></tr></thead>
        <tbody>{units.map((u, i) => (
          <tr key={i}>
            <td className="cell-input"><input className="input" style={{ width: 90 }} value={u.name ?? ""} aria-label={T("第 {0} 个户型名称", [i + 1])} onChange={(e) => upd(i, "name", e.target.value)} /></td>
            <td className="cell-input">{num(i, "units", T("户数"), "int")}</td>
            <td className="cell-input">{num(i, "avg_sf", T("户均面积"), "int")}</td>
            <td className="cell-input"><div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>{num(i, "in_place_rent", T("在租月租"), "usd")}
              <button type="button" className="btn ghost sm" aria-label={T("第 {0} 个户型在租月租的数字护照", [i + 1])} onClick={() => openPassport(`unit_mix.${i}.in_place_rent`, T("第 {0} 个户型在租月租", [i + 1]))}>
                <span className={`status ${passportStatus(passports[`unit_mix.${i}.in_place_rent`])}`} style={{ padding: "0 4px" }}><i aria-hidden="true" />{T("源")}</span></button></div></td>
            <td className="cell-input">{num(i, "market_rent", T("市场月租"), "usd")}</td>
            <td className="cell-input">{num(i, "renovate_units", T("翻新户数"), "int")}</td>
            <td className="cell-input">{num(i, "reno_cost_per_unit", T("每户翻新成本"), "usd")}</td>
            <td className="cell-input">{num(i, "reno_premium", T("翻新溢价"), "usd")}</td>
            <td><button type="button" className="btn ghost sm" aria-label={T("删除第 {0} 个户型", [i + 1])} disabled={units.length <= 1}
              onClick={() => set("unit_mix", units.filter((_, j) => j !== i))}>×</button></td>
          </tr>))}</tbody></table></div>
      {cre && cre.metrics.capex_total ? <p className="muted" style={{ marginTop: 8 }}>{T("持有期翻新支出 {0}；每户价格 {1}", [fmt(cre.metrics.capex_total, "usd"), fmt(cre.metrics.price_per_unit, "usd")])}</p> : null}
    </section>
  );
}

const RECOVERY: [string, string][] = [["nnn", "NNN"], ["gross", T("毛租约")], ["base_year", T("基年")]];

/** 分析月下标 → YYYY-MM（以交割月为 0）。 */
export function monthLabel(start: string, idx: number): string {
  const [y, m] = start.split("-").map(Number);
  if (!y || !m) return String(idx);
  const t = y * 12 + (m - 1) + idx;
  return `${Math.floor(t / 12)}-${String((t % 12) + 1).padStart(2, "0")}`;
}

function monthsBetween(a: string, b: string): number | null {
  const pa = a.split("-").map(Number), pb = b.split("-").map(Number);
  if (pa.length !== 2 || pb.length !== 2 || pa.some((x) => !x) || pb.some((x) => !x)) return null;
  return (pb[0]! - pa[0]!) * 12 + (pb[1]! - pa[1]!);
}

/** 加权平均剩余租期（年，按面积加权，从交割月算到到期月）：机构看租约稳定性的第一指标。 */
export function walt(leases: Lease[], start: string): number | null {
  let w = 0, sf = 0;
  for (const l of leases) {
    const left = l.end ? monthsBetween(start, l.end) : null;
    if (left == null || !l.sf) continue;
    w += Math.max(0, left + 1) * l.sf; sf += l.sf;
  }
  return sf ? w / sf / 12 : null;
}

function useCre(): Cre | null {
  const { preview } = useDeal();
  return ((preview?.detail as { cre?: Cre } | undefined)?.cre) ?? null;
}

function Fields({ specs }: { specs: FieldSpec[] }) {
  const { draft, set, passports, openPassport } = useDeal();
  return <div className="grid-form">{specs.map((f) => <FieldInput key={f.path} spec={f} value={getPath(draft, f.path)} onChange={(v) => set(f.path, v)}
    onPassport={(p) => openPassport(p, f.label)} passportState={passportStatus(passports[f.path])} />)}</div>;
}

export function InstRentRoll() {
  const mf = useIsMf();
  return <><PropertyType />{mf ? <UnitMix /> : <LeaseRentRoll />}</>;
}

function LeaseRentRoll() {
  const { draft, set, passports, openPassport } = useDeal();
  const cre = useCre();
  const leases = (draft.leases as Lease[] | undefined) ?? [];
  const start = String(draft.analysis_start ?? "");
  const area = Number(draft.area_sf ?? 0);
  const leased = leases.reduce((a, l) => a + (l.sf ?? 0), 0);
  const upd = (i: number, k: keyof Lease, v: unknown) => set(`leases.${i}.${k}`, v);
  const add = () => set("leases", [...leases, { tenant: "", suite: "", sf: 0, start, end: start, rent_psf_yr: Number(getPath(draft, "market.rent_psf_yr") ?? 0),
    escalation_pct: 3, free_rent_months: 0, recovery: "nnn" }]);
  const spec = cre?.rent_roll.filter((s) => s.speculative) ?? [];
  const w = walt(leases, start);
  return (
    <>
      <section className="card" aria-label={T("租约")}>
        <div className="row" style={{ justifyContent: "space-between" }}><h2 style={{ margin: 0 }}>{T("租约（逐份）")}</h2>
          <button className="btn sm" type="button" onClick={add}>{T("+ 加租约")}</button></div>
        <p className="sub">{T("租金按每个租约周年日递增；到期后按“市场与费用”页的续租概率与市场条件自动续上。未出租面积按新租招租。")}</p>
        <MetricGrid count={4} style={{ marginBottom: 12 }}>
          <Metric label={T("已出租面积")} value={leased} unit="int" />
          <Metric label={T("交割时出租率")} value={area ? (leased / area) * 100 : null} unit="pct" />
          <Metric label="WALT" value={w} unit="x" />
          <Metric label={T("租约数")} value={leases.length} unit="int" />
        </MetricGrid>
        <div className="table-wrap" style={{ maxHeight: "none" }}><table className="t">
          <thead><tr><th scope="col">{T("租户")}</th><th scope="col">{T("单元")}</th><th scope="col" className="num">{T("面积")}<span className="unit">SF</span></th>
            <th scope="col">{T("起租")}</th><th scope="col">{T("到期")}</th><th scope="col" className="num">{T("租金")}<span className="unit">{T("$/SF/年")}</span></th>
            <th scope="col" className="num">{T("年递增")}<span className="unit">%</span></th><th scope="col" className="num">{T("免租月")}</th><th scope="col">{T("回收")}</th>
            <th scope="col"><span className="sr-only">{T("操作")}</span></th></tr></thead>
          <tbody>{leases.map((l, i) => (
            <tr key={i}>
              <td className="cell-input"><input className="input" value={l.tenant ?? ""} aria-label={T("第 {0} 份租约租户", [i + 1])} onChange={(e) => upd(i, "tenant", e.target.value)} /></td>
              <td className="cell-input"><input className="input" style={{ width: 64 }} value={l.suite ?? ""} aria-label={T("第 {0} 份租约单元", [i + 1])} onChange={(e) => upd(i, "suite", e.target.value)} /></td>
              <td className="cell-input"><NumberInput value={l.sf} unit="int" label={T("第 {0} 份租约面积", [i + 1])} onChange={(v) => upd(i, "sf", v ?? 0)} /></td>
              <td className="cell-input"><input className="input mono" style={{ width: 88 }} value={l.start ?? ""} placeholder="YYYY-MM" aria-label={T("第 {0} 份租约起租", [i + 1])} onChange={(e) => upd(i, "start", e.target.value)} /></td>
              <td className="cell-input"><input className="input mono" style={{ width: 88 }} value={l.end ?? ""} placeholder="YYYY-MM" aria-label={T("第 {0} 份租约到期", [i + 1])} onChange={(e) => upd(i, "end", e.target.value)} /></td>
              <td className="cell-input"><div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                <NumberInput value={l.rent_psf_yr} unit="x" label={T("第 {0} 份租约租金", [i + 1])} onChange={(v) => upd(i, "rent_psf_yr", v ?? 0)} />
                <button type="button" className="btn ghost sm" aria-label={T("第 {0} 份租约租金的数字护照", [i + 1])} onClick={() => openPassport(`leases.${i}.rent_psf_yr`, T("第 {0} 份租约租金", [i + 1]))}>
                  <span className={`status ${passportStatus(passports[`leases.${i}.rent_psf_yr`])}`} style={{ padding: "0 4px" }}><i aria-hidden="true" />{T("源")}</span></button></div></td>
              <td className="cell-input"><NumberInput value={l.escalation_pct} unit="pct" label={T("第 {0} 份租约年递增", [i + 1])} onChange={(v) => upd(i, "escalation_pct", v ?? 0)} /></td>
              <td className="cell-input"><NumberInput value={l.free_rent_months} unit="int" label={T("第 {0} 份租约免租月", [i + 1])} onChange={(v) => upd(i, "free_rent_months", Math.round(v ?? 0))} /></td>
              <td className="cell-input"><select className="input" value={l.recovery ?? "nnn"} aria-label={T("第 {0} 份租约回收方式", [i + 1])} onChange={(e) => upd(i, "recovery", e.target.value)}>
                {RECOVERY.map(([v, lbl]) => <option key={v} value={v}>{lbl}</option>)}</select></td>
              <td><button type="button" className="btn ghost sm" aria-label={T("删除第 {0} 份租约", [i + 1])} onClick={() => set("leases", leases.filter((_, j) => j !== i))}>×</button></td>
            </tr>))}
            {leases.length === 0 ? <tr><td colSpan={10} className="muted">{T("还没有租约：全部面积按空置招租计算。")}</td></tr> : null}</tbody></table></div>
      </section>
      <section className="card" aria-label={T("到期续租假设")}>
        <h2>{T("到期与续租假设")}</h2>
        <p className="sub">{T("引擎按续租概率把“续租”与“换新租户”加权成一条路径：空置月、免租、TI / LC 都按概率加权。这些是假设，不是签约事实。")}</p>
        {spec.length ? <div className="table-wrap" style={{ maxHeight: "none" }}><table className="t">
          <thead><tr><th scope="col">{T("面积")}</th><th scope="col">{T("起租")}</th><th scope="col">{T("到期")}</th><th scope="col" className="num">{T("空置月")}</th>
            <th scope="col" className="num">{T("租金")}<span className="unit">{T("$/SF/年")}</span></th><th scope="col" className="num">TI<span className="unit">$</span></th><th scope="col" className="num">LC<span className="unit">$</span></th></tr></thead>
          <tbody>{spec.map((s, i) => <tr key={i}><td>{s.tenant}{s.suite ? ` · ${s.suite}` : ""}<div className="d">{fmt(s.sf, "int")} SF</div></td>
            <td className="mono">{monthLabel(start, s.start)}</td><td className="mono">{monthLabel(start, s.end)}</td><NumCell v={s.downtime_before} unit="int" />
            <NumCell v={s.rent_psf} unit="x" /><NumCell v={s.ti} unit="usd" /><NumCell v={s.lc} unit="usd" /></tr>)}</tbody></table></div>
          : <p className="muted">{cre ? T("持有期内没有到期租约。") : T("填好租约和市场假设后，这里列出每次到期续上的假设段。")}</p>}
      </section>
    </>
  );
}

export function InstMarketOpex() {
  if (useIsMf()) return (
    <div className="split">
      <section className="card" aria-label={T("收入假设")}><h2>{T("收入假设")}</h2>
        <p className="sub">{T("空置率与坏账在“模型”页的“一般空置率 / 信用损失”里填。")}</p><Fields specs={INST_MF_REVENUE} /></section>
      <div>
        <section className="card" aria-label={T("运营费用")}><h2>{T("运营费用")}</h2><Fields specs={INST_MF_OPEX} /></section>
        <section className="card" aria-label={T("翻新计划")}><h2>{T("翻新计划")}</h2>
          <p className="sub">{T("按户型顺序开工；各户型翻新户数、成本与溢价在“租金表”页的户型表里填。")}</p><Fields specs={INST_MF_RENO} /></section>
      </div>
    </div>
  );
  return (
    <div className="split">
      <section className="card" aria-label={T("市场租赁假设")}><h2>{T("市场租赁假设（MLA）")}</h2>
        <p className="sub">{T("到期后续租与新租按续租概率加权；新段租金取起租当月的市场租金，市场租金按年增长。")}</p><Fields specs={INST_MARKET} /></section>
      <section className="card" aria-label={T("运营费用")}><h2>{T("运营费用")}</h2>
        <p className="sub">{T("NNN 租约按面积占比回收可回收费用；基年租约只回收超过基年的部分；毛租约不回收。管理费不回收。")}</p><Fields specs={INST_OPEX} /></section>
    </div>
  );
}

const ROWS: [string, string, boolean][] = [
  ["base_rent", T("基本租金"), false], ["free_rent", T("免租"), false], ["recoveries", T("费用回收"), false],
  ["general_vacancy", T("一般空置"), false], ["credit_loss", T("信用损失"), false], ["egr", T("有效总收入 EGR"), true],
  ["opex_recoverable", T("可回收费用"), false], ["opex_non_recoverable", T("不可回收费用"), false], ["mgmt_fee", T("管理费"), false],
  ["noi", "NOI", true], ["ti", "TI", false], ["lc", "LC", false], ["reserves", T("资本储备"), false],
  ["cf_before_debt", T("债前现金流"), true], ["debt_service", T("还本付息"), false], ["cf_after_debt", T("债后现金流"), true],
];

const ROWS_MF: [string, string, boolean][] = [
  ["potential_rent", T("潜在租金 GPR"), false], ["loss_to_lease", "Loss-to-lease", false], ["premium", T("翻新溢价"), false],
  ["turnover_vacancy", T("翻新停用"), false], ["non_revenue", T("不产生租金的户"), false], ["base_rent", T("在租租金"), true],
  ["free_rent", T("租金优惠"), false], ["general_vacancy", T("空置"), false], ["credit_loss", T("坏账"), false],
  ["recoveries", T("其他收入"), false], ["egr", T("有效总收入 EGR"), true], ["opex_recoverable", T("房产税与保险"), false],
  ["opex_non_recoverable", T("运营费用"), false], ["mgmt_fee", T("管理费"), false], ["noi", "NOI", true],
  ["capex", T("翻新支出"), false], ["reserves", T("资本储备"), false],
  ["cf_before_debt", T("债前现金流"), true], ["debt_service", T("还本付息"), false], ["cf_after_debt", T("债后现金流"), true],
];

export function InstModel() {
  const { draft, set, preview, previewing } = useDeal();
  const mf = draft.property_type === "multifamily";
  const { catalog } = useApp();
  const cre = useCre();
  const hold = Number(draft.hold_years ?? 0);
  const floating = getPath(draft, "debt.rate_type") === "floating";
  const curve = (getPath(draft, "debt.sofr_curve_pct") as number[] | undefined) ?? [];
  const tiers = ((getPath(draft, "waterfall.tiers") as { irr_pct: number; lp_share_pct: number }[] | undefined) ?? []);
  const m = preview?.metrics ?? {};
  const keys = ["irr_pct", "unlevered_irr_pct", "cap_rate_pct", "dscr", "debt_yield_pct", "equity_multiple", "coc_pct", "cash_to_close", "avg_occupancy_pct"];
  const cm = cre?.metrics ?? {};
  const years = Array.from({ length: Math.max(0, hold) }, (_, i) => i);
  const val = (k: string, y: number) => { const v = cre?.annual[k]?.[y]; return k === "debt_service" && typeof v === "number" ? -v : v; };
  return (
    <div className="split">
      <div>
        <section className="card" aria-label={T("交易与退出")}><h2>{T("交易与退出")}</h2><Fields specs={INST_DEAL} /></section>
        <section className="card" aria-label={T("债务")}><h2>{T("债务")}</h2><Fields specs={INST_DEBT} />
          {floating ? <label className="field" style={{ marginTop: 12 }}>{T("SOFR 曲线（逐年，%）")}<span className="hint">{T("逗号分隔，最后一年向后沿用")}</span>
            <input className="input mono" defaultValue={curve.join(", ")} aria-label={T("SOFR 曲线")}
              onBlur={(e) => set("debt.sofr_curve_pct", e.target.value.split(/[,\s]+/).map(Number).filter((x) => Number.isFinite(x)))} /></label> : null}
        </section>
        <section className="card" aria-label={T("分配瀑布")}><h2>{T("分配瀑布（GP / LP）")}</h2>
          <p className="sub">{T("按 LP IRR 门槛：优先回报以内按出资比例分；每过一档 LP 份额下降、GP 拿 promote。")}</p>
          <Fields specs={INST_WATERFALL} />
          <h3 style={{ fontSize: 15, marginTop: 12 }}>{T("中间各档")}</h3>
          {tiers.map((t, i) => <div className="row" key={i} style={{ alignItems: "end", marginBottom: 8 }}>
            <label className="field" style={{ width: 150 }}>{T("LP IRR 到")}<NumberInput value={t.irr_pct} unit="pct" label={T("第 {0} 档门槛", [i + 1])} onChange={(v) => set(`waterfall.tiers.${i}.irr_pct`, v ?? 0)} /></label>
            <label className="field" style={{ width: 150 }}>{T("此前 LP 份额")}<NumberInput value={t.lp_share_pct} unit="pct" label={T("第 {0} 档 LP 份额", [i + 1])} onChange={(v) => set(`waterfall.tiers.${i}.lp_share_pct`, v ?? 0)} /></label>
            <button type="button" className="btn ghost sm" aria-label={T("删除第 {0} 档", [i + 1])} onClick={() => set("waterfall.tiers", tiers.filter((_, j) => j !== i))}>×</button></div>)}
          {tiers.length < 5 ? <button type="button" className="btn sm" onClick={() => set("waterfall.tiers", [...tiers, { irr_pct: (tiers.at(-1)?.irr_pct ?? Number(getPath(draft, "waterfall.pref_pct") ?? 8)) + 4, lp_share_pct: 70 }])}>{T("+ 加一档")}</button> : null}
        </section>
      </div>
      <section className="card" aria-label={T("结果")} aria-busy={previewing}>
        <h2>{T("结果")}{previewing ? <span className="muted" style={{ fontSize: 13, marginLeft: 8 }}><span className="live-dot" aria-hidden="true" />{T("计算中…")}</span> : null}</h2>
        {preview?.error ? <div className="banner risk" role="alert" style={{ marginTop: 12 }}>{preview.error}</div> : null}
        <MetricGrid count={keys.length} style={{ marginTop: 12 }}>
          {keys.map((k) => <Metric key={k} label={catalog.metrics[k]?.label ?? k} value={m[k] ?? null} unit={(catalog.metrics[k]?.unit ?? "pct") as Unit} />)}
        </MetricGrid>
        {cre ? <ul className="checks" style={{ marginTop: 12 }}>
          <li><span className="chip">IRR</span><span>{T("按月现金流年化：有杠杆 {0} · 无杠杆 {1}", [fmt(cm.levered_irr_monthly_pct, "pct"), fmt(cm.unlevered_irr_monthly_pct, "pct")])}</span></li>
          <li><span className="chip">NPV</span><span>{T("有杠杆 {0} · 无杠杆 {1}", [fmt(cm.levered_npv, "usd"), fmt(cm.unlevered_npv, "usd")])}</span></li>
          <li><span className="chip">{T("退出")}</span><span>{T("售价 {0}（下一年 NOI {1} ÷ {2}）· 偿还贷款 {3} · 有杠杆净所得 {4}", [fmt(cre.exit.sale_price, "usd"), fmt(cm.forward_noi, "usd"),
            fmt(cm.exit_cap_pct, "pct"), fmt(cre.exit.loan_payoff, "usd"), fmt(cre.exit.net_proceeds_levered, "usd")])}</span></li>
          {cre.waterfall ? <li><span className="chip">{T("瀑布")}</span><span>{T("LP IRR {0}（{1}）· GP IRR {2}（{3}）· GP promote {4}", [fmt(cre.waterfall.lp_irr_pct, "pct"), fmt(cre.waterfall.lp_multiple, "x"),
            fmt(cre.waterfall.gp_irr_pct, "pct"), fmt(cre.waterfall.gp_multiple, "x"), fmt(cre.waterfall.gp_promote, "usd")])}</span></li> : null}
        </ul> : null}
        <h3 style={{ marginTop: 20, fontSize: 15 }}>{T("逐年现金流（$）")}</h3>
        {cre ? <div className="table-wrap" tabIndex={0} role="region" aria-label={T("逐年现金流（$）")}><table className="t">
          <thead><tr><th scope="col" style={{ whiteSpace: "nowrap" }}>{T("科目")}</th>{years.map((y) => <th key={y} scope="col" className="num">{T("第 {0} 年", [y + 1])}</th>)}</tr></thead>
          <tbody>{(mf ? ROWS_MF : ROWS).map(([k, label, total]) => <tr key={k} className={total ? "total" : undefined}><td style={{ whiteSpace: "nowrap" }}>{label}</td>{years.map((y) => <NumCell key={y} v={val(k, y)} unit="usd" />)}</tr>)}
            <tr><td style={{ whiteSpace: "nowrap" }}>{T("平均出租率")}</td>{years.map((y) => <NumCell key={y} v={cre.annual.occupancy_pct?.[y]} unit="pct" />)}</tr></tbody></table></div>
          : <p className="muted">{T("填好交易、租约与市场假设后，这里出逐年现金流。")}</p>}
      </section>
    </div>
  );
}

/** 商业 PDF 提取出的租约表行 → 机构级租约（起止按交割月 + 新租期估，必须人工核对）。 */
export function tenantsToLeases(rows: { suite?: string | null; tenant?: string | null; sf?: number | null; monthly_rent?: number | null }[],
  draft: JsonObj): Lease[] {
  const start = String(draft.analysis_start ?? "");
  const term = Number(getPath(draft, "market.lease_term_years") ?? 5);
  return rows.map((r) => ({ tenant: r.tenant ?? "", suite: r.suite ?? "", sf: r.sf ?? 0, start, end: monthLabel(start, term * 12 - 1),
    rent_psf_yr: r.sf && r.monthly_rent ? (r.monthly_rent * 12) / r.sf : 0, escalation_pct: 3, free_rent_months: 0, recovery: "nnn" }));
}
