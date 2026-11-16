// Pricing (MAPPING 10.3): per material, the rate each site and vendor pays, the spread and twelve months of trend, the last price against its budget
// and the latest quote, PV lines against their index. A spread's reasons are not in the records: each site above the median names its buyer.
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Button, SectionTitle, StateChip, Tile, Tiles } from "../../ds";
import { DataTable, TitleCell, type Col } from "../../ds/DataTable";
import { FilterBar, type FilterValue } from "../../ds/FilterBar";
import { useAskContext } from "../../shell/AskContext";
import { inr, monthShort, monthYear, shortDate } from "../../ui/format";
import { insights, type PricingDetail, type PricingRow } from "./api";
import { Frame } from "./Frame";
import { Bar, Empty, Fig, ReadFailed, Sources, Spark, useReadError, Vert } from "./ui";

const per = (uom: string) => (uom === "NO" ? "each" : `per ${uom}`);

function pricingCols(): Col<PricingRow>[] {
  return [
    { id: "m", head: "Material", width: "minmax(200px,1fr)", cell: (r) => <TitleCell title={<Link to={`/insights/pricing/${encodeURIComponent(r.code)}`}>{r.description}</Link>} sub={`${r.code} · ${r.category} · ${per(r.uom)}`} /> },
    { id: "s", head: "Sites", width: "64px", end: true, label: "sites", cell: (r) => r.sites || "—" },
    { id: "sp", head: "Spread", width: "150px", end: true, label: "spread", cell: (r) => r.spread ? <span className="ins-stack1"><Fig f={r.spread} title={`${r.description}: spread`} sub={`${r.low?.rate.text} – ${r.high?.rate.text}`} />{r.flagged ? <Link className="ins-tag" to={`/items/${encodeURIComponent(r.flagged)}`}>On Today</Link> : r.unexplained ? <span className="ins-tag quiet" title="A site pays materially above the median; the records do not say why">ask why</span> : null}</span> : <span className="ins-fig none">one site</span> },
    { id: "l", head: "Last price", width: "120px", end: true, label: "last", cell: (r) => <Fig f={r.last} title={`${r.description}: last PO rate`} sub={r.last_budget ? <>budget <Fig f={r.last_budget} title="Budget rate of that project" quiet /></> : "no budget rate"} /> },
    { id: "q", head: "Latest quote", width: "110px", end: true, label: "quote", hide: "narrow", cell: (r) => <Fig f={r.latest_quote} title={`${r.description}: latest quote`} /> },
    { id: "t", head: "12 months", width: "150px", label: "trend", hide: "mid", cell: (r) => <span className="ins-trend"><Spark values={r.trend.map((t) => t.rate?.value ?? null)} />{r.trend_change ? <Fig f={r.trend_change} title={`${r.description}: change over the months bought`} quiet /> : null}</span> },
    { id: "pv", head: "PV lines", width: "72px", end: true, label: "PV lines", hide: "narrow", cell: (r) => r.pv_lines || "—" },
  ];
}

/** /insights/pricing */
export function Pricing() {
  const r = useReadError(() => insights.pricing(), []);
  const [q, setQ] = useState("");
  const [f, setF] = useState<FilterValue>({});
  const d = r.data;
  const cats = useMemo(() => [...new Set((d?.rows ?? []).map((x) => x.category))].sort(), [d]);
  const rows = useMemo(() => (d?.rows ?? []).filter((x) => (!f.c || x.category === f.c)
    && (!f.s || (f.s === "today" ? !!x.flagged : f.s === "ask" ? x.unexplained : f.s === "pv" ? x.pv_lines > 0 : (x.sites ?? 0) > 1))
    && (!q.trim() || `${x.description} ${x.code} ${x.group}`.toLowerCase().includes(q.trim().toLowerCase()))), [d, f, q]);
  return (
    <Sources>
      <Frame title="Pricing" meta={d ? <><span>{d.rows.length} materials bought</span><span className="sep">·</span><span>trend {monthYear(d.months[0])} – {monthYear(d.months[d.months.length - 1])}</span></> : undefined}>
        {r.loading ? <div className="ins-sk" aria-busy="true" aria-label="Loading prices"><i /><i /><i /><i /></div>
          : r.error || !d ? <ReadFailed e={r.error!} what="prices" notFound={{ title: "Pricing", line: "No prices on file." }} />
          : (
            <>
              <FilterBar label="materials" search={q} onSearch={setQ} placeholder="Search materials" value={f} onChange={setF} filters={[
                { id: "c", label: "Category", options: cats.map((c) => ({ value: c, label: c, count: d.rows.filter((x) => x.category === c).length })) },
                { id: "s", label: "Show", options: [
                  { value: "many", label: "Bought at several sites", count: d.rows.filter((x) => x.sites > 1).length },
                  { value: "ask", label: "A site above the median", count: d.rows.filter((x) => x.unexplained).length },
                  { value: "today", label: "Spread on Today", count: d.rows.filter((x) => x.flagged).length },
                  { value: "pv", label: "With PV lines", count: d.rows.filter((x) => x.pv_lines > 0).length },
                ] },
              ]} />
              <div className="ins-body">
                {rows.length === 0 ? <Empty>No material matches.</Empty> : <DataTable label="Prices by material" cols={pricingCols()} rows={rows} rowKey={(x) => x.code} two />}
              </div>
              <ul className="ins-notes">{d.notes.map((x) => <li key={x}>{x}</li>)}</ul>
            </>
          )}
      </Frame>
    </Sources>
  );
}

/** /insights/pricing/:material */
export function PricingMaterial() {
  const { material = "" } = useParams();
  const r = useReadError(() => insights.material(material), [material]);
  const d = r.data;
  useAskContext(d ? { type: "material", id: d.code, label: d.description } : null);
  return (
    <Sources>
      <Frame back={{ to: "/insights/pricing", label: "Pricing" }} title={d?.description ?? "Material"}
        meta={d ? <><span>{d.code}</span><span className="sep">·</span><span>{d.category}</span><span className="sep">·</span><span>{per(d.uom)}</span>{d.index && <><span className="sep">·</span><span>moves with {d.index}</span></>}</> : undefined}
        actions={d ? <Button to={`/materials/${encodeURIComponent(d.code)}`}>Material record</Button> : undefined}>
        {r.loading ? <div className="ins-sk" aria-busy="true" aria-label="Loading prices"><i /><i /><i /><i /></div>
          : r.error || !d ? <ReadFailed e={r.error!} what="this material's prices" notFound={{ title: "No prices", line: `No PO on file for material ${material}.` }} />
          : <MaterialBody d={d} />}
      </Frame>
    </Sources>
  );
}

function MaterialBody({ d }: { d: PricingDetail }) {
  const max = Math.max(1, ...d.by_site.map((s) => s.rate.value ?? 0));
  const bought = d.trend.filter((t) => t.rate);
  const tmax = Math.max(1, ...bought.map((t) => t.rate!.value ?? 0));
  return (
    <div className="ins-body">
      <Tiles>
        <Tile figure={d.spread ? <Fig f={d.spread} title="Spread" /> : "—"} label={d.spread ? `spread over ${d.sites} sites` : "bought at one site"} />
        <Tile figure={d.median != null ? inr(d.median) : "—"} label={`median site rate ${per(d.uom)}`} />
        <Tile figure={<Fig f={d.last} title="Last PO rate" />} label={d.last_budget ? `last price · budget ${d.last_budget.text}` : "last price · no budget rate"} />
        <Tile figure={<Fig f={d.latest_quote} title="Latest quote" />} label="latest quote" />
      </Tiles>

      <section className="ins-sec">
        <SectionTitle>Rate by site</SectionTitle>
        {d.by_site.length === 0 ? <Empty>No PO line names a project.</Empty> : (
          <DataTable label="Rate by site" rows={d.by_site} rowKey={(s) => s.project} two cols={[
            { id: "p", head: "Project", width: "minmax(150px,1fr)", cell: (s) => <TitleCell title={<span className="ins-pv">{s.vertical && <Vert id={s.vertical} short />}<Link to={`/insights/projects/${encodeURIComponent(s.project)}`}>{s.project_name}</Link></span>} sub={`${s.vendor_name} · ${shortDate(s.date)}`} /> },
            { id: "b", head: "", width: "minmax(80px,160px)", phone: "hide", cell: (s) => <Bar value={s.rate.value ?? 0} max={max} tone={(s.vs_median_pct ?? 0) > 0 ? "accent" : "muted"} /> },
            { id: "r", head: "Last rate", width: "110px", end: true, label: "rate", cell: (s) => <Fig f={s.rate} title={`${s.project_name}: last PO rate`} sub={s.vs_median_pct != null ? `${s.vs_median_pct > 0 ? "+" : ""}${Math.round(s.vs_median_pct)}% on median` : undefined} /> },
            { id: "bu", head: "Budget", width: "100px", end: true, label: "budget", hide: "narrow", cell: (s) => <Fig f={s.budget} title={`${s.project_name}: budget rate`} /> },
            { id: "q", head: "Latest quote", width: "100px", end: true, label: "quote", hide: "mid", cell: (s) => <Fig f={s.quote} title={`${s.project_name}: latest quote`} /> },
            { id: "w", head: "Buyer", width: "130px", label: "buyer", hide: "narrow", cell: (s) => s.buyer_name ?? "—" },
          ]} />
        )}
      </section>

      {d.unknowns.length > 0 && (
        <section className="ins-sec">
          <SectionTitle>What the spread leaves unknown</SectionTitle>
          <ul className="ins-unk">
            {d.unknowns.map((u) => (
              <li key={u.project}>
                <p>{u.what}</p>
                <p className="ins-ask"><StateChip tone="unknown">unknown</StateChip> Ask {u.ask_name ? <Link to={`/insights/team/${encodeURIComponent(u.ask ?? "")}`}>{u.ask_name}</Link> : "the site's buyer"}, who buys {u.project_name}'s lines · <Link to={`/pos/${u.refs[0]?.split(":")[1]?.split("/")[0] ?? ""}`}>the last PO</Link></p>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="ins-sec">
        <SectionTitle>Twelve months</SectionTitle>
        {bought.length === 0 ? <Empty>Not bought in the last twelve months.</Empty> : (
          <div className="ins-cols" role="table" aria-label="Monthly average rate">
            {d.trend.map((t) => (
              <div key={t.month} className="ins-col" role="row">
                <span className="ins-colbar" aria-hidden><i style={{ height: `${t.rate ? Math.max(4, (100 * (t.rate.value ?? 0)) / tmax) : 0}%` }} /></span>
                <span role="cell" className="ins-colv">{t.rate ? <Fig f={t.rate} title={`Average rate, ${monthYear(t.month)}`} quiet /> : <span className="ins-fig none">—</span>}</span>
                <span role="cell" className="ins-coll">{monthShort(t.month)}</span>
              </div>
            ))}
          </div>
        )}
        {d.index && d.index_series.length > 1 && <p className="ins-note">{d.index}: {d.index_series[0].value.toLocaleString("en-IN")} in {monthYear(d.index_series[0].month)}, {d.index_series[d.index_series.length - 1].value.toLocaleString("en-IN")} in {monthYear(d.index_series[d.index_series.length - 1].month)}.</p>}
        {d.trend_change && <p className="ins-note">The monthly average moved <Fig f={d.trend_change} title="Change over the year" quiet /> between the first and the last month it was bought (every site together, so a month's mix of sites moves it too).</p>}
      </section>

      <section className="ins-sec">
        <SectionTitle>Rate by vendor</SectionTitle>
        <DataTable label="Rate by vendor" rows={d.by_vendor} rowKey={(v) => v.vendor} cols={[
          { id: "v", head: "Vendor", width: "minmax(180px,1fr)", cell: (v) => <TitleCell title={<Link to={`/vendors/${encodeURIComponent(v.vendor)}`}>{v.vendor_name}</Link>} sub={`${v.lines} PO ${v.lines === 1 ? "line" : "lines"} · last ${shortDate(v.last_date)}`} /> },
          { id: "l", head: "Last rate", width: "110px", end: true, label: "last", cell: (v) => <Fig f={v.last} title={`${v.vendor_name}: last rate`} /> },
          { id: "r", head: "Low – high", width: "160px", end: true, label: "range", cell: (v) => (v.low === v.high ? inr(v.low) : `${inr(v.low)} – ${inr(v.high)}`) },
          { id: "p", head: "Projects", width: "80px", end: true, label: "projects", hide: "narrow", cell: (v) => v.projects.length },
        ]} />
      </section>

      {d.pv.length > 0 && (
        <section className="ins-sec">
          <SectionTitle>Price variation against the index</SectionTitle>
          <DataTable label="PV items" rows={d.pv} rowKey={(x) => x.ref} cols={[
            { id: "i", head: "Line", width: "minmax(180px,1fr)", cell: (x) => <TitleCell title={x.kind === "po" ? <Link to={`/pos/${x.ref.split(":")[1].split("/")[0]}`}>PO {x.ref.split(":")[1]}</Link> : "Look-ahead item, not ordered"} sub={[x.project_name, x.vendor_name].filter(Boolean).join(" · ")} /> },
            { id: "x", head: "Index", width: "150px", label: "index", cell: (x) => <span className="ins-stack1">{x.index}<small>{x.base_month ? `base ${monthYear(x.base_month)}` : x.change_pct != null ? `${x.change_pct}% a month` : ""}</small></span> },
            { id: "c", head: "Since base", width: "100px", end: true, label: "since base", cell: (x) => (x.kind === "po" && x.change_pct != null ? `${x.change_pct > 0 ? "+" : ""}${x.change_pct}%` : "—") },
            { id: "pv", head: "PV", width: "130px", end: true, label: "PV", cell: (x) => <Fig f={x.pv} title={x.kind === "po" ? "PV the clause moves" : "A month's wait"} sub={x.kind === "po" ? "on the ordered qty" : "a month's wait"} /> },
          ]} />
        </section>
      )}

      <section className="ins-sec">
        <SectionTitle>Quotes</SectionTitle>
        {d.quotes.length === 0 ? <Empty>No priced quote on file for this material.</Empty> : (
          <DataTable label="Quotes" rows={d.quotes} rowKey={(x) => x.ref} cols={[
            { id: "v", head: "Vendor", width: "minmax(180px,1fr)", cell: (x) => <TitleCell title={x.vendor_name} sub={[x.project_name, x.cs ?? (x.source === "mail" ? "mail only" : null), x.basis].filter(Boolean).join(" · ")} /> },
            { id: "d", head: "Date", width: "90px", label: "date", cell: (x) => shortDate(x.date) },
            { id: "r", head: "Rate", width: "130px", end: true, label: "rate", cell: (x) => (x.rate_base != null ? <span className="ins-stack1">{inr(x.rate_base)}{x.uom && x.rate_base !== x.rate ? <small>{inr(x.rate)} per {x.uom}</small> : null}</span> : `${inr(x.rate)} per ${x.uom}`) },
          ]} />
        )}
      </section>
    </div>
  );
}
