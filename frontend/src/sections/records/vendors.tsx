// Vendors (MAPPING 8.2, 8.3): the SAP master tied to the approved library, one row per company; and one vendor's page.
import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { useAskContext } from "../../shell/AskContext";
import { invalidate, useResource } from "../../api/useResource";
import type { MessageSummary, PoLine, VendorDetail, VendorQuote, VendorRow } from "../../api/types";
import { EmptyState, Notice, PageHeader, Section, Tile, Tiles, type SectionDef } from "../../ds";
import { DataTable, TitleCell, type Col } from "../../ds/DataTable";
import { FilterBar, type FilterDef } from "../../ds/FilterBar";
import { LoadError } from "../../ds/LoadError";
import { VERTICALS } from "../../components/domain/Vertical";
import { enIn, humanize, qty } from "../../ui/format";
import { Block, Facts, ListTitle, LoadingRows, PageState, RecordsTabs, RefLink, Showing, Vertical, day, days, lineTo, plural, rate, refTo, rs, useAsOf, useMore, useUrl, verticalId } from "./shared";

/** An LC or bank guarantee on file (the LC/BG tracker), as the vendor and PO pages read it. */
export type Guarantee = { kind: string; number: string | null; po: string | null; amount: number; to_open_by: string | null; issued_on: string | null; expiry: string | null;
  status: string | null; remarks: string | null; days_left?: number | null; unrecovered?: number | null };

const n = (x: string | number | null | undefined) => Number(x ?? 0);

/** Vendors: who the company buys from, what the library approves each for, how each delivers, and what is open with it. */
export function Vendors() {
  useAsOf();
  const r = useResource(api.vendors);
  const u = useUrl();
  const q = (u.get("q") ?? "").trim().toLowerCase();
  const all = r.data ?? [];
  const f = { vertical: u.get("vertical"), library: u.get("library"), msme: u.get("msme"), show: u.get("show") };
  const verts = (v: VendorRow) => v.verticals.map(verticalId);
  const filters: FilterDef[] = [
    { id: "vertical", label: "Vertical", options: VERTICALS.map((x) => ({ value: x.id, label: x.name, count: all.filter((v) => verts(v).includes(x.id)).length })).filter((o) => o.count) },
    { id: "library", label: "Library", options: [{ value: "in", label: "In the approved library", count: all.filter((v) => v.in_library).length }, { value: "out", label: "Not in the library", count: all.filter((v) => !v.in_library).length }] },
    { id: "msme", label: "MSME", options: [{ value: "yes", label: "MSME", count: all.filter((v) => v.msme).length }, { value: "no", label: "Not MSME", count: all.filter((v) => !v.msme).length }] },
    { id: "show", label: "Show", options: [
      { value: "case", label: "In a case", count: all.filter((v) => v.cases?.length).length },
      { value: "open", label: "With open POs", count: all.filter((v) => v.open_lines).length },
      { value: "streak", label: "On a late streak", count: all.filter((v) => v.streak).length },
      { value: "renamed", label: "Renamed (two codes)", count: all.filter((v) => v.renamed).length },
    ] },
  ];
  const rows = all.filter((v) =>
    (!q || `${v.name} ${v.codes.join(" ")} ${v.gstin ?? ""} ${v.city ?? ""} ${v.region ?? ""} ${v.verticals.join(" ")}`.toLowerCase().includes(q))
    && (!f.vertical || verts(v).includes(f.vertical))
    && (!f.library || (f.library === "in") === v.in_library)
    && (!f.msme || (f.msme === "yes") === v.msme)
    && (!f.show || (f.show === "case" ? !!v.cases?.length : f.show === "open" ? v.open_lines > 0 : f.show === "streak" ? v.streak > 0 : v.renamed)));
  const { shown, more } = useMore(rows, 150, `${q}|${JSON.stringify(f)}`);
  const cols: Col<VendorRow>[] = [
    { id: "name", head: "Vendor", width: "minmax(0,1fr)", cell: (v) => <TitleCell title={v.name} tip={v.name}
      sub={<>{v.codes.join(" · ")}{v.renamed ? " (renamed: both codes linked)" : ""}{v.city ? ` · ${v.city}` : ""}</>} /> },
    { id: "lib", head: "Library", width: "150px", label: "Library", cell: (v) => (v.in_library
      ? (v.verticals.length ? <span className="rc-verts">{v.verticals.map((x) => <Vertical key={x} id={verticalId(x)} />)}</span> : "In the library, not approved")
      : <span className="rc-warn">Not in the library</span>) },
    { id: "ontime", head: "On time", width: "96px", end: true, label: "On time", cell: (v) => (v.on_time_pct == null ? <span className="none">—</span>
      : <span title={`${v.receipts} receipts against a dated line`}>{v.on_time_pct}%<small>{v.streak ? `${v.streak} late in a row` : `of ${enIn(v.receipts)}`}</small></span>) },
    { id: "open", head: "Open POs", width: "104px", end: true, label: "Open", cell: (v) => (v.open_lines ? <span>{rs(v.open_value)}<small>{plural(v.open_lines, "line")}</small></span> : <span className="none">—</span>) },
    { id: "msme", head: "MSME", width: "64px", hide: "mid", label: "MSME", phone: "hide", cell: (v) => (v.msme ? "MSME" : <span className="none">—</span>) },
    { id: "case", head: "In a case", width: "220px", label: "In a case", cell: (v) => (v.cases?.length
      ? <span className="rc-case" title={v.cases.map((c) => c.label).join("\n")}>{v.cases[0].label}{v.cases.length > 1 && <small>+{v.cases.length - 1} more</small>}</span>
      : <span className="none">—</span>) },
  ];
  return (
    <div className="rc pg-fix">
      <RecordsTabs />
      <ListTitle title="Vendors" sub="One row per company from the SAP vendor master, tied to the approved library. A renamed company keeps both codes, linked, never merged." />
      <FilterBar label="vendors" search={u.get("q") ?? ""} onSearch={(s) => u.set({ q: s })} placeholder="Name, code, GSTIN or city" filters={filters}
        value={f} onChange={(v) => u.set({ vertical: v.vertical, library: v.library, msme: v.msme, show: v.show })} />
      {r.data && <Showing n={rows.length} of={all.length} what="vendors" />}
      <div className="pg-body">
        {r.loading && !r.data ? <LoadingRows /> : r.error ? <LoadError what="vendors" retry={invalidate} />
          : rows.length === 0 ? <EmptyState>{all.length ? "No vendor matches." : "No vendors on file."}</EmptyState>
          : <><DataTable label="Vendors" cols={cols} rows={shown} rowKey={(v) => v.ref.id} to={(v) => `/vendors/${encodeURIComponent(v.ref.id)}`} two />{more}</>}
      </div>
    </div>
  );
}

/** One vendor: profile, library rows, delivery record, POs, quotes, payments due, guarantees, messages and cases. */
export function VendorPage() {
  const { id = "" } = useParams();
  useAsOf();
  const u = useUrl();
  const v = useResource(() => api.vendor(id), [id]);
  const ident = v.data?.ref.id;
  useAskContext(v.data ? { type: "supplier", id: v.data.ref.id, label: v.data.name } : null);
  const pos = useResource(() => (ident ? api.pos({ vendor: ident }) : Promise.resolve([] as PoLine[])), [ident]);
  const quotes = useResource(() => (ident ? api.vendorQuotes(ident) : Promise.resolve([] as VendorQuote[])), [ident]);
  const msgs = useResource(() => api.messages().catch(() => [] as MessageSummary[]));
  if (!v.data) return <PageState what={`vendor ${id}`} error={v.error} kind="vendor" />;
  const d = v.data;
  const sections: SectionDef[] = [
    { id: "overview", label: "Overview", render: () => <Overview d={d} /> },
    { id: "delivery", label: "Delivery", count: d.delivery.n, render: () => <DeliveryBlock d={d} /> },
    { id: "pos", label: "POs", count: d.po_lines.length, render: () => <VendorPos r={pos} /> },
    { id: "quotes", label: "Quotes", count: d.quotes.length, render: () => <VendorQuotes r={quotes} /> },
    { id: "payments", label: "Payments", count: d.msme_due.length + d.guarantees.length || undefined, render: () => <Payments d={d} /> },
    { id: "messages", label: "Messages", count: d.messages.length, render: () => <Messages d={d} all={msgs.data ?? []} /> },
  ];
  return (
    <div className="rc rc-page">
      <RecordsTabs />
      <PageHeader flow back={{ to: "/vendors", label: "Vendors" }} title={d.name}
        meta={<>
          <span>{d.codes.join(" · ")}</span>
          {(d.city || d.region) && <><span className="sep">·</span><span>{[d.city, d.region].filter(Boolean).join(", ")}</span></>}
          <span className="sep">·</span><span>{d.in_library ? (d.verticals.length ? `Approved for ${d.verticals.join(", ")}` : "In the library, not approved") : "Not in the approved library"}</span>
          {d.msme && <><span className="sep">·</span><span>MSME</span></>}
        </>} />
      <Section sections={sections} current={u.get("s") ?? "overview"} onSelect={(s) => u.set({ s: s === "overview" ? undefined : s })} />
    </div>
  );
}

function Overview({ d }: { d: VendorDetail }) {
  const recs = [...d.records].sort((a, b) => (a.created_on ?? "").localeCompare(b.created_on ?? ""));
  const renamed = recs.length > 1 ? recs : null;
  return (
    <>
      <Tiles>
        <Tile figure={d.delivery.on_time_pct == null ? "—" : `${d.delivery.on_time_pct}%`} label={d.delivery.n ? `on time · ${d.delivery.on_time} of ${d.delivery.n} receipts` : "on time · no dated receipts"} tone={d.streak ? "caution" : undefined} />
        <Tile figure={rs(d.open_value)} label={`open · ${plural(d.open_lines, "PO line")}`} />
        <Tile figure={rs(d.po_value)} label={`every PO line on file · ${plural(d.po_lines.length, "line")}`} />
        <Tile figure={d.msme_due.length ? rs(d.msme_due.reduce((s, m) => s + n(m.amount.base ?? m.amount.amount), 0)) : "—"} label={d.msme ? `MSME invoices due within 45 days · ${d.msme_due.length}` : "not an MSME (no 45-day rule)"} />
      </Tiles>
      {d.cases?.length ? (
        <Block title="In a case" count={d.cases.length}>
          <ul className="rc-list">{d.cases.map((c) => <li key={c.id}><Link to={refTo(c)!}>{c.label ?? c.id}</Link></li>)}</ul>
        </Block>
      ) : null}
      {renamed && (
        <Notice>
          {renamed[0].name} ({renamed[0].code}) is now {renamed[renamed.length - 1].name} ({renamed[renamed.length - 1].code}), a new legal entity with its own GSTIN. Both codes are kept, linked, never merged{d.open_lines ? "; check which code each open line is on" : ""}.
        </Notice>
      )}
      <Block title={recs.length > 1 ? "Vendor codes" : "Profile"} count={recs.length > 1 ? recs.length : undefined}>
        <div className="rc-cards">
          {recs.map((c) => (
            <Facts key={c.code} rows={[
              ["Code", <>{c.code}{c.blocked && <span className="rc-warn"> · blocked</span>}</>],
              ["Name", c.name],
              ["GSTIN", c.gstin],
              ["MSME", c.msme ? <>Yes{c.udyam && <> · {c.udyam}</>}</> : "No"],
              ["Bank account", c.bank_masked],
              ["City", [c.city, c.region].filter(Boolean).join(", ")],
              ["Created in SAP", c.created_on ? day(c.created_on) : null],
              ["Linked by", c.link === "stated" ? "its own record" : <span title={c.evidence ?? undefined}>a person, with evidence{c.evidence && <small className="rc-sub">{humanize(c.evidence)}</small>}</span>],
            ]} />
          ))}
        </div>
        <Facts rows={[["Contact on file", d.contact.name || d.contact.email ? <>{d.contact.name}{d.contact.email && <small className="rc-sub">{d.contact.email}</small>}</> : null]]} />
      </Block>
      <Block title="Approved library" count={d.library.length} note={d.library.length ? undefined : "Not in the approved vendor library: a PO to it needs a reason on file."}>
        {d.library.length > 0 && (
          <DataTable label="Library rows" rows={d.library} rowKey={(x) => `${x.vertical}|${x.sub_vertical}|${x.category}`} cols={[
            { id: "v", head: "Vertical", width: "minmax(0,1fr)", cell: (x) => <TitleCell title={<Vertical id={verticalId(x.vertical)} />} sub={[x.sub_vertical, x.category].filter(Boolean).join(" · ")} /> },
            { id: "s", head: "Status", width: "120px", label: "Status", cell: (x) => x.status },
            { id: "a", head: "Approved on", width: "110px", label: "Approved", cell: (x) => day(x.approved_on) },
            { id: "l", head: "Tied by", width: "100px", label: "Tied by", phone: "hide", cell: (x) => ({ sap_code: "SAP code", gstin: "GSTIN", name: "name" }[x.link] ?? x.link) },
          ]} />
        )}
      </Block>
    </>
  );
}

function DeliveryBlock({ d }: { d: VendorDetail }) {
  const x = d.delivery;
  return (
    <Block title="Delivery record" note={humanize(x.line)}>
      <Facts rows={[
        ["Receipts against a dated line", enIn(x.n)],
        ["On time", x.n ? `${x.on_time} of ${x.n} (${x.on_time_pct}%)` : null],
        ["Late", x.late ? `${x.late}, ${x.avg_days_late} days late on average` : "none"],
        ["Late streak", x.streak ? `last ${x.streak} receipts late, ${day(x.streak_from)} to ${day(x.streak_to)}${x.streak_days ? ` (+${x.streak_days[0]} to +${x.streak_days[1]} days)` : ""}` : "none"],
        ["Before the streak", x.streak && x.before_pct != null ? `on time on ${x.before_pct}% of receipts${x.turned ? ": the run is new, not its usual" : ""}` : null],
      ]} />
      {x.last.length > 0 && (
        <>
          <h3 className="rc-h3">Last receipts</h3>
          <DataTable label="Last receipts" rows={x.last} rowKey={(a) => a.receipt} to={(a) => lineTo("po", a.po_line)} cols={[
            { id: "po", head: "PO line", width: "minmax(0,1fr)", cell: (a) => <TitleCell title={`PO ${a.po_line}`} sub={`receipt ${a.receipt}`} /> },
            { id: "p", head: "Received", width: "110px", label: "Received", cell: (a) => day(a.posted) },
            { id: "d", head: "Due", width: "110px", label: "Due", cell: (a) => day(a.due) },
            { id: "l", head: "Late", width: "90px", end: true, label: "Late", cell: (a) => (a.days_late == null ? "—" : a.days_late > 0 ? <span className="rc-warn">+{days(a.days_late)}</span> : a.days_late < 0 ? `${days(-a.days_late)} early` : "on the day") },
            { id: "q", head: "Quantity", width: "120px", end: true, label: "Qty", cell: (a) => qty(a.qty, a.uom) },
          ]} />
        </>
      )}
    </Block>
  );
}

/** PO lines with one vendor, open first. */
function VendorPos({ r }: { r: { data?: PoLine[]; loading: boolean; error?: string } }) {
  const rows = useMemo(() => [...(r.data ?? [])].sort((a, b) => (a.status === b.status ? b.doc_date.localeCompare(a.doc_date) : a.status === "open" ? -1 : 1)), [r.data]);
  if (r.loading && !r.data) return <LoadingRows n={4} />;
  if (r.error) return <LoadError what="this vendor's PO lines" retry={invalidate} />;
  if (!rows.length) return <EmptyState>No PO lines with this vendor on file.</EmptyState>;
  return <PoTable rows={rows} label="PO lines" vendor={false} />;
}

/** A short PO-line table for a record page (vendor, material): line, vendor or project, open quantity and value, delivery, status. */
export function PoTable({ rows, label, vendor = true }: { rows: PoLine[]; label: string; vendor?: boolean }) {
  const { shown, more } = useMore(rows, 50, `${rows.length}|${rows[0]?.ref.id}`);
  return (
    <>
      <DataTable label={label} rows={shown} rowKey={(l) => l.ref.id} to={(l) => lineTo("po", l.ref.id)} two cols={[
        { id: "l", head: "PO line", width: "minmax(0,1fr)", cell: (l) => <TitleCell title={l.text || l.material?.label || l.ref.id} sub={`PO ${l.ref.id} · ${day(l.doc_date)}${l.doc_type !== "Purchase order" ? ` · ${l.doc_type}` : ""}`} /> },
        vendor
          ? { id: "v", head: "Vendor", width: "180px", label: "Vendor", cell: (l) => <span title={`${l.vendor.label} · ${l.vendor_code}`}>{l.vendor.label}</span> }
          : { id: "p", head: "Project", width: "130px", label: "Project", cell: (l) => l.project?.label ?? <span className="none">no project</span> },
        { id: "q", head: "Open qty", width: "120px", end: true, label: "Open", cell: (l) => <span>{qty(l.open_qty, l.uom)}<small>of {qty(l.qty)}</small></span> },
        { id: "v2", head: "Open value", width: "96px", end: true, label: "₹", cell: (l) => (l.status === "open" ? rs(l.open_value) : <span className="none">—</span>) },
        { id: "d", head: "Delivery", width: "120px", label: "Delivery", cell: (l) => <Delivery l={l} /> },
        { id: "s", head: "Status", width: "96px", label: "Status", phone: "hide", cell: (l) => (l.status === "open" ? "Open" : "Received") },
      ]} />
      {more}
    </>
  );
}

/** A PO line's delivery date, the vendor's revised date beside it where its mail moved it, and days past due. */
export function Delivery({ l }: { l: PoLine }) {
  const rev = l.revised?.length ? l.revised[l.revised.length - 1] : null;
  return (
    <span>
      {day(l.delivery_date)}
      {rev ? <small className="rc-warn" title={`The vendor's mail moved it (message ${rev.message}${rev.line ? `, ${rev.line}` : ""}); SAP still says ${day(l.delivery_date)}`}>vendor: {day(rev.date)}</small>
        : l.days_past_due ? <small className="rc-warn">{days(l.days_past_due)} past due</small> : null}
    </span>
  );
}

function VendorQuotes({ r }: { r: { data?: VendorQuote[]; loading: boolean; error?: string } }) {
  if (r.loading && !r.data) return <LoadingRows n={4} />;
  if (r.error) return <LoadError what="this vendor's quotes" retry={invalidate} />;
  const rows = r.data ?? [];
  if (!rows.length) return <EmptyState>No quotes from this vendor on file.</EmptyState>;
  return <QuoteTable rows={rows} />;
}

function QuoteTable({ rows }: { rows: VendorQuote[] }) {
  const { shown, more } = useMore(rows, 50);
  return (
    <>
      <DataTable label="Quotes" rows={shown} rowKey={(x) => x.ref.id} two cols={[
        { id: "m", head: "For", width: "minmax(0,1fr)", cell: (x) => <TitleCell title={x.material ? <RefLink r={x.material} id={false} /> : "—"}
          sub={<>{x.cs ?? "no CS"}{x.project ? ` · ${x.project.label}` : ""}{x.source === "mail" && x.message ? <> · <Link to={refTo(x.message)!}>from mail</Link></> : ""}</>} /> },
        { id: "d", head: "Quoted", width: "96px", label: "Quoted", cell: (x) => day(x.quote_date) },
        { id: "r", head: "Rate", width: "124px", end: true, label: "Rate", cell: (x) => (x.rate ? <span>{rate(x.rate.base ?? x.rate.amount, x.uom)}<small>{x.l1 ? "L1" : x.price_basis ?? ""}</small></span> : <span className="none">no price yet</span>) },
        { id: "v", head: "Valid to", width: "96px", label: "Valid to", phone: "hide", cell: (x) => day(x.validity) },
        { id: "c", head: "CS outcome", width: "170px", label: "CS", cell: (x) => (x.cs_status ? <span title={x.cs_status}>{x.cs_status}{x.cs_approved_on && <small>{day(x.cs_approved_on)}</small>}</span> : <span className="none">—</span>) },
      ]} />
      {more}
    </>
  );
}

function Payments({ d }: { d: VendorDetail }) {
  const g = d.guarantees as unknown as Guarantee[];
  return (
    <>
      <Block title="Payment terms" note={d.payment_terms.length ? undefined : "No open PO lines, so no terms in force."}>
        {d.payment_terms.length > 0 && <ul className="rc-list">{d.payment_terms.map((t) => <li key={t}>{t}</li>)}</ul>}
      </Block>
      <Block title="MSME invoices falling due" count={d.msme ? d.msme_due.length : undefined}
        note={!d.msme ? "Not an MSME: the 45-day rule does not apply." : d.msme_due.length ? "Unpaid invoices whose 45-day limit falls within 45 days of the data date, or has passed." : "No unpaid invoice falls due within 45 days."}>
        {d.msme_due.length > 0 && (
          <DataTable label="MSME invoices falling due" rows={d.msme_due} rowKey={(m) => m.invoice} cols={[
            { id: "i", head: "Invoice", width: "minmax(0,1fr)", cell: (m) => <TitleCell title={m.invoice} sub={m.po ? <Link to={lineTo("po", m.po)}>PO {m.po}</Link> : "no PO"} /> },
            { id: "d", head: "Invoiced", width: "100px", label: "Invoiced", cell: (m) => day(m.invoice_date) },
            { id: "b", head: "Due by", width: "120px", label: "Due by", cell: (m) => <span>{day(m.due_by)}<small className={m.days_left < 0 ? "rc-warn" : undefined}>{m.days_left < 0 ? `${days(-m.days_left)} overdue` : `${days(m.days_left)} left`}</small></span> },
            { id: "a", head: "Amount", width: "110px", end: true, label: "₹", cell: (m) => rs(m.amount, true) },
          ]} />
        )}
      </Block>
      <Block title="LCs and guarantees" count={g.length} note={g.length ? undefined : "No LC or bank guarantee on file."}>
        {g.length > 0 && <GuaranteeTable rows={g} />}
      </Block>
    </>
  );
}

/** LCs and bank guarantees: what each is, against which PO, how much, and the date that matters now (open by, or expiry). */
export function GuaranteeTable({ rows }: { rows: Guarantee[] }) {
  return (
    <DataTable label="LCs and guarantees" rows={rows} rowKey={(x) => `${x.kind}|${x.number}|${x.po}`} two cols={[
      { id: "k", head: "Instrument", width: "minmax(0,1fr)", cell: (x) => <TitleCell title={`${x.kind}${x.number ? ` ${x.number}` : " (not yet opened)"}`} sub={<>{x.po ? <Link to={lineTo("po", x.po)}>PO {x.po}</Link> : "no PO"}{x.remarks ? ` · ${x.remarks}` : ""}</>} tip={x.remarks ?? undefined} /> },
      { id: "a", head: "Amount", width: "100px", end: true, label: "₹", cell: (x) => rs(x.amount) },
      { id: "w", head: "Date", width: "150px", label: "Date", cell: (x) => (x.kind === "LC" && !x.issued_on
        ? <span>open by {day(x.to_open_by)}{x.days_left != null && <small className={x.days_left <= 15 ? "rc-warn" : undefined}>{days(x.days_left)} left</small>}</span>
        : <span>expires {day(x.expiry)}{x.issued_on && <small>issued {day(x.issued_on)}</small>}</span>) },
      { id: "s", head: "Status", width: "96px", label: "Status", cell: (x) => x.status ?? "—" },
    ]} />
  );
}

function Messages({ d, all }: { d: VendorDetail; all: MessageSummary[] }) {
  const by = new Map(all.map((m) => [m.ref.id, m]));
  if (!d.messages.length) return <EmptyState>No messages from this vendor.</EmptyState>;
  return (
    <DataTable label="Messages" rows={d.messages} rowKey={(m) => m.id} to={(m) => refTo(m)!} two cols={[
      { id: "s", head: "Message", width: "minmax(0,1fr)", cell: (m) => { const x = by.get(m.id); return <TitleCell title={m.label ?? m.id} sub={x ? [x.from, x.kind].filter(Boolean).join(" · ") : undefined} />; } },
      { id: "d", head: "Received", width: "110px", label: "Received", cell: (m) => day(by.get(m.id)?.date) },
      { id: "t", head: "Trust", width: "100px", label: "Trust", phone: "hide", cell: (m) => { const t = by.get(m.id)?.trust; return t === "ok" ? "On file" : t ? <span className="rc-warn">{t}</span> : "—"; } },
    ]} />
  );
}

