// Materials (MAPPING 8.4, 8.5): the material master with what is open and the last rate paid; one material's rate history by site and by vendor,
// where it is used, what is open, and every quote beside the last PO rate and the budget rate.
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { useAskContext } from "../../shell/AskContext";
import { invalidate, useResource } from "../../api/useResource";
import type { MaterialDetail, MaterialRow, PoLine, PrLine } from "../../api/types";
import { EmptyState, PageHeader, SegmentedControl, Tile, Tiles } from "../../ds";
import { DataTable, TitleCell, type Col } from "../../ds/DataTable";
import { FilterBar, type FilterDef } from "../../ds/FilterBar";
import { LoadError } from "../../ds/LoadError";
import { enIn, qty } from "../../ui/format";
import { PrTable } from "./prs";
import { RateChart, type Pick } from "./RateChart";
import { Block, ListTitle, LoadingRows, PageState, RecordsTabs, Showing, day, pct, plural, rate, refTo, rs, useAsOf, useMore, useProjects, useUrl } from "./shared";
import { PoTable } from "./vendors";

type ByVendor = { vendor: string; id: string; lines: number; min: number; max: number; last: number; last_date: string };
type WhereUsed = { project: string; name: string; required: number; on_order: number; pr_open: number };

/** "MT (20 BAG)": the base unit, and the alternate unit with how many make one base unit. */
const units = (m: MaterialRow) => `${m.base_uom}${m.alt_uom ? ` (${m.alt_per_base ? `${enIn(m.alt_per_base, 2)} ` : ""}${m.alt_uom})` : ""}`;

/** Materials: the SAP material master, with what is open on each and the last rate paid. */
export function Materials() {
  const r = useResource(api.materials);
  const u = useUrl();
  const all = r.data ?? [];
  const q = (u.get("q") ?? "").trim().toLowerCase();
  const f = { category: u.get("category"), pv: u.get("pv"), show: u.get("show") };
  const cats = [...new Set(all.map((m) => m.category))].sort();
  const filters: FilterDef[] = [
    { id: "category", label: "Category", options: cats.map((c) => ({ value: c, label: c, count: all.filter((m) => m.category === c).length })) },
    { id: "pv", label: "Price", options: [{ value: "pv", label: "Moves with an index (PV)", count: all.filter((m) => m.pv_index).length }, { value: "firm", label: "No index on the master", count: all.filter((m) => !m.pv_index).length }] },
    { id: "show", label: "Show", options: [
      { value: "prs", label: "With open PRs", count: all.filter((m) => m.open_prs).length },
      { value: "pos", label: "With open PO lines", count: all.filter((m) => m.open_po_lines).length },
      { value: "spread", label: "Rate differs 2× or more across sites", count: all.filter((m) => (m.spread ?? 0) >= 2).length },
    ] },
  ];
  const rows = all.filter((m) =>
    (!q || `${m.code} ${m.description} ${m.group} ${m.category} ${m.pv_index ?? ""}`.toLowerCase().includes(q))
    && (!f.category || m.category === f.category) && (!f.pv || (f.pv === "pv") === !!m.pv_index)
    && (!f.show || (f.show === "prs" ? m.open_prs > 0 : f.show === "pos" ? m.open_po_lines > 0 : (m.spread ?? 0) >= 2)));
  const { shown, more } = useMore(rows, 150, `${rows.length}|${rows[0]?.code}`);
  const cols: Col<MaterialRow>[] = [
    { id: "m", head: "Material", width: "minmax(0,1fr)", cell: (m) => <TitleCell title={m.description} sub={`${m.code} · ${m.category}`} /> },
    { id: "u", head: "Unit", width: "100px", label: "Unit", cell: (m) => units(m) },
    { id: "l", head: "Lead", width: "64px", end: true, label: "Lead", hide: "narrow", cell: (m) => (m.lead_days != null ? `${m.lead_days} d` : <span className="none">—</span>) },
    { id: "pv", head: "PV index", width: "112px", label: "PV", hide: "mid", phone: "hide", cell: (m) => m.pv_index ?? <span className="none">—</span> },
    { id: "pr", head: "Open PRs", width: "80px", end: true, label: "Open PRs", cell: (m) => (m.open_prs ? enIn(m.open_prs) : <span className="none">—</span>) },
    { id: "po", head: "Open POs", width: "104px", end: true, label: "Open POs", cell: (m) => (m.open_po_lines ? <span>{rs(m.open_value)}<small>{plural(m.open_po_lines, "line")}</small></span> : <span className="none">—</span>) },
    { id: "r", head: "Last rate", width: "112px", end: true, label: "Last rate", cell: (m) => (m.last_rate != null ? `${rate(m.last_rate)}/${m.base_uom}` : <span className="none">—</span>) },
    { id: "s", head: "Spread", width: "112px", end: true, hide: "narrow", label: "Spread", cell: (m) => (m.spread != null ? <span title="The highest site's last rate over the lowest's">{m.spread.toLocaleString("en-IN", { maximumFractionDigits: 2 })}×<small>across {plural(m.projects, "project")}</small></span> : <span className="none">—</span>) },
  ];
  return (
    <div className="rc pg-fix">
      <RecordsTabs />
      <ListTitle title="Materials" sub="The SAP material master: units, planned lead time, the index a price moves with, what is open and the last rate paid (per base unit)." />
      <FilterBar label="materials" search={u.get("q") ?? ""} onSearch={(s) => u.set({ q: s })} placeholder="Code, description or group" filters={filters}
        value={f} onChange={(v) => u.set({ category: v.category, pv: v.pv, show: v.show })} />
      {r.data && <Showing n={rows.length} of={all.length} what="materials" />}
      <div className="pg-body">
        {r.loading && !r.data ? <LoadingRows /> : r.error ? <LoadError what="materials" retry={invalidate} />
          : rows.length === 0 ? <EmptyState>No material matches.</EmptyState>
          : <><DataTable label="Materials" cols={cols} rows={shown} rowKey={(m) => m.code} to={(m) => `/materials/${encodeURIComponent(m.code)}`} two />{more}</>}
      </div>
    </div>
  );
}

/** One material: master facts, rate history by site and by vendor, where it is used, open PRs and POs, and every quote. */
export function MaterialPage() {
  const { code = "" } = useParams();
  useAsOf();
  const r = useResource(() => api.material(code), [code]);
  useAskContext(r.data ? { type: "material", id: code, label: r.data.description } : null);
  const pos = useResource(() => api.pos({ material: code, status: "open" }), [code]);
  const prs = useResource(() => api.prs({ status: "open" }).then((ls) => ls.filter((l) => l.material?.id === code)), [code]);
  const pj = useProjects();
  if (!r.data) return <PageState what={`material ${code}`} error={r.error} kind="material" />;
  const m = r.data;
  const newest = m.history.length ? m.history[m.history.length - 1] : null;
  return (
    <div className="rc rc-page">
      <RecordsTabs />
      <PageHeader flow back={{ to: "/materials", label: "Materials" }} title={m.description}
        meta={<>
          <span>{m.code}</span><span className="sep">·</span><span>{m.category}</span><span className="sep">·</span><span>group {m.group}</span>
          <span className="sep">·</span><span>{units(m)}</span>
          {m.lead_days != null && <><span className="sep">·</span><span>{m.lead_days} days' planned lead</span></>}
          <span className="sep">·</span><span>{m.pv_index ? `moves with ${m.pv_index}` : "no PV index on the master"}</span>
        </>} />
      <Tiles>
        <Tile figure={newest ? rate(newest.rate, m.base_uom) : "—"} label={newest ? `last PO rate · ${day(newest.date)}, ${pj.byId.get(newest.project ?? "")?.name ?? "no project"}` : "no PO on file"} />
        <Tile figure={m.median != null ? rate(m.median, m.base_uom) : "—"} label={`median of each site's last rate · ${plural(m.by_site.length, "site")}`} />
        <Tile figure={m.spread != null ? `${m.spread.toLocaleString("en-IN", { maximumFractionDigits: 2 })}×` : "—"} label="highest site over lowest" tone={(m.spread ?? 0) >= 2 ? "caution" : undefined} />
        <Tile figure={m.open_po_lines ? rs(m.open_value) : "—"} label={`open on ${plural(m.open_po_lines, "PO line")} · ${plural(m.open_prs, "open PR line")}`} />
      </Tiles>
      <RateBlock m={m} projectName={(id) => pj.byId.get(id ?? "")?.name ?? id ?? ""} />
      <Block title="Where used" count={m.where_used.length} note="Required: the 3-month requirement sheets. On order: open PO quantity. In PRs: open PR quantity. All in the base unit.">
        {m.where_used.length ? (
          <DataTable label="Where used" rows={m.where_used as unknown as WhereUsed[]} rowKey={(w) => w.project} to={(w) => `/requirements?project=${encodeURIComponent(w.project)}`} cols={[
            { id: "p", head: "Project", width: "minmax(0,1fr)", cell: (w) => <TitleCell title={w.name} /> },
            { id: "r", head: "Required", width: "130px", end: true, label: "Required", cell: (w) => (w.required ? qty(w.required, m.base_uom) : <span className="none">—</span>) },
            { id: "o", head: "On order", width: "130px", end: true, label: "On order", cell: (w) => (w.on_order ? qty(w.on_order, m.base_uom) : <span className="none">—</span>) },
            { id: "pr", head: "In PRs", width: "130px", end: true, label: "In PRs", cell: (w) => (w.pr_open ? qty(w.pr_open, m.base_uom) : <span className="none">—</span>) },
          ]} />
        ) : <EmptyState>No project requires or buys it.</EmptyState>}
      </Block>
      <Block title="Open PO lines" count={m.open_po_refs.length}>
        {pos.loading && !pos.data ? <LoadingRows n={3} /> : pos.error ? <LoadError what="open PO lines" retry={invalidate} />
          : (pos.data ?? []).length ? <PoTable rows={sortPos(pos.data!)} label="Open PO lines" /> : <EmptyState>No open PO line.</EmptyState>}
      </Block>
      <Block title="Open PR lines" count={m.open_pr_refs.length}>
        {prs.loading && !prs.data ? <LoadingRows n={3} /> : prs.error ? <LoadError what="open PR lines" retry={invalidate} />
          : (prs.data ?? []).length ? <PrTable rows={sortPrs(prs.data!)} label="Open PR lines" /> : <EmptyState>No open PR line.</EmptyState>}
      </Block>
      <Quotes m={m} />
    </div>
  );
}

const sortPos = (ls: PoLine[]) => [...ls].sort((a, b) => (a.delivery_date ?? "9999").localeCompare(b.delivery_date ?? "9999"));
const sortPrs = (ls: PrLine[]) => [...ls].sort((a, b) => (b.age_days ?? 0) - (a.age_days ?? 0));

/** The rate history chart and, beside it as its table, the last rate by site and the rates by vendor; a row picks its dots out. */
function RateBlock({ m, projectName }: { m: MaterialDetail; projectName: (id: string | null | undefined) => string }) {
  const [by, setBy] = useState<"site" | "vendor">("site");
  const [pick, setPick] = useState<Pick>(null);
  const vendors = m.by_vendor as unknown as ByVendor[];
  const toggle = (p: NonNullable<Pick>) => setPick(pick && pick.kind === p.kind && pick.key === p.key ? null : p);
  if (!m.history.length) return <Block title="Rate history"><EmptyState>No PO line for this material on file, so no rate history.</EmptyState></Block>;
  return (
    <Block title="Rate history" count={m.history.length} note="Every PO line's rate per base unit, by its PO date.">
      <RateChart history={m.history} uom={m.base_uom} pick={pick} projectName={projectName} />
      <div className="rc-seg">
        <SegmentedControl label="Rates by" items={[{ id: "site", label: "By site", count: m.by_site.length }, { id: "vendor", label: "By vendor", count: vendors.length }]} value={by}
          onChange={(x) => { setBy(x as "site" | "vendor"); setPick(null); }} />
      </div>
      {by === "site" ? (
        <DataTable label="Last rate by site" rows={m.by_site} rowKey={(s) => s.project.id} two active={(s) => pick?.kind === "site" && pick.key === s.project.id}
          onClick={(s) => toggle({ kind: "site", key: s.project.id, label: s.project.label ?? s.project.id })} cols={[
            { id: "p", head: "Site", width: "minmax(0,1fr)", cell: (s) => <TitleCell title={s.project.label ?? s.project.id} sub={`${s.vendor} · ${plural(s.po_lines, "PO line")}`} /> },
            { id: "r", head: "Last rate", width: "124px", end: true, label: "Last", cell: (s) => <span>{rate(s.last_rate, m.base_uom)}<small>{day(s.last_date)}</small></span> },
            { id: "m", head: "vs median", width: "96px", end: true, label: "vs median", cell: (s) => pct(s.vs_median_pct) },
            { id: "b", head: "Budget", width: "124px", end: true, label: "Budget", cell: (s) => (s.budget != null ? <span>{rate(s.budget, m.base_uom)}<small>{pct(Math.round((1000 * (s.last_rate - s.budget)) / s.budget) / 10)} vs budget</small></span> : <span className="none">no budget rate</span>) },
          ]} />
      ) : (
        <DataTable label="Rates by vendor" rows={vendors} rowKey={(v) => v.id} two active={(v) => pick?.kind === "vendor" && pick.key === v.vendor}
          onClick={(v) => toggle({ kind: "vendor", key: v.vendor, label: v.vendor })} cols={[
            { id: "v", head: "Vendor", width: "minmax(0,1fr)", cell: (v) => <TitleCell title={v.vendor} sub={`${v.id} · ${plural(v.lines, "PO line")}`} /> },
            { id: "r", head: "Range", width: "180px", end: true, label: "Range", cell: (v) => (v.min === v.max ? rate(v.min, m.base_uom) : `${rate(v.min)} to ${rate(v.max, m.base_uom)}`) },
            { id: "l", head: "Last", width: "124px", end: true, label: "Last", cell: (v) => <span>{rate(v.last, m.base_uom)}<small>{day(v.last_date)}</small></span> },
          ]} />
      )}
      {pick && <p className="rc-note">{pick.label} picked out on the chart. <button type="button" className="rc-linkbtn" onClick={() => setPick(null)}>Show all equally</button> · <Link to={pick.kind === "vendor" ? `/vendors/${encodeURIComponent(vendors.find((v) => v.vendor === pick.key)?.id ?? "")}` : `/requirements?project=${encodeURIComponent(pick.key)}`}>{pick.kind === "vendor" ? "Open the vendor" : "Open the site's requirement"}</Link></p>}
    </Block>
  );
}

/** Every quote on file for the material, each beside what it last cost on a PO at that project and the project's budget rate. */
function Quotes({ m }: { m: MaterialDetail }) {
  const beside = new Map((m.beside ?? []).map((b) => [b.quote, b]));
  const { shown, more } = useMore(m.quotes, 50);
  return (
    <Block title="Quotes" count={m.quotes.length} note="Newest first. The last PO rate is at the quote's project where it has bought this material, else the newest anywhere.">
      {m.quotes.length ? (
        <>
          <DataTable label="Quotes" rows={shown} rowKey={(x) => x.ref.id} two cols={[
            { id: "v", head: "Vendor", width: "minmax(0,1fr)", cell: (x) => { const b = beside.get(x.ref.id); return <TitleCell title={x.vendor ? <Link className="rc-link" to={refTo(x.vendor)!}>{x.vendor_name}</Link> : x.vendor_name}
              sub={<>{b?.cs ?? "no CS"}{b?.project ? ` · ${b.project.label}` : ""}{!x.in_library && " · not in the library"}{x.source === "mail" && x.message ? <> · <Link to={refTo(x.message)!}>from mail</Link></> : ""}</>} />; } },
            { id: "d", head: "Quoted", width: "92px", label: "Quoted", cell: (x) => day(x.quote_date) },
            { id: "r", head: "Rate", width: "124px", end: true, label: "Rate", cell: (x) => (x.rate ? <span>{rate(x.rate.base ?? x.rate.amount, x.uom ?? m.base_uom)}<small>{[x.l1 && "L1", x.price_basis].filter(Boolean).join(" · ")}</small></span> : <span className="none">no price yet</span>) },
            { id: "l", head: "Last PO", width: "124px", end: true, label: "Last PO", cell: (x) => { const b = beside.get(x.ref.id); return b?.last_po_rate != null ? <span title={`PO ${b.last_po_line} of ${day(b.last_po_date)}${b.last_scope === "any" ? ", at any site" : ""}`}>{rate(b.last_po_rate)}<small>{pct(b.vs_last_pct)}{b.last_scope === "any" ? " · any site" : ""}</small></span> : <span className="none">none</span>; } },
            { id: "b", head: "Budget", width: "124px", end: true, label: "Budget", cell: (x) => { const b = beside.get(x.ref.id); return b?.budget != null ? <span>{rate(b.budget)}<small>{pct(b.vs_budget_pct)}</small></span> : <span className="none">none</span>; } },
            { id: "t", head: "Valid to", width: "92px", label: "Valid to", phone: "hide", hide: "narrow", cell: (x) => day(x.validity) },
          ]} />
          {more}
        </>
      ) : <EmptyState>No quote on file for this material.</EmptyState>}
    </Block>
  );
}

