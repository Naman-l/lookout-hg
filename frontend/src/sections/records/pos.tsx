// POs (MAPPING 8.6, 8.10): ME2N lines netted against MB51, with the vendor's revised dates and the plain-word flags; one PO with its ladders,
// milestones, guarantees, invoices and payments.
import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { useAskContext } from "../../shell/AskContext";
import { invalidate, useResource } from "../../api/useResource";
import { useMe } from "../../api/useMe";
import type { PoDetail, PoLine } from "../../api/types";
import { EmptyState, PageHeader, Tile, Tiles } from "../../ds";
import { DataTable, TitleCell, type Col } from "../../ds/DataTable";
import { FilterBar, type FilterDef } from "../../ds/FilterBar";
import { LoadError } from "../../ds/LoadError";
import { VERTICALS } from "../../components/domain/Vertical";
import { baseOf, enIn, humanize, qty } from "../../ui/format";
import { LineLadders, LineSub, useWho } from "./prs";
import { Block, Facts, Flags, ListTitle, LoadingRows, PageState, ProjectPicker, RecordsTabs, RefLink, WhoSwitch, day, lineTo, projectMatches, rate, rs, useAsOf, useMore, useProjects, useUrl } from "./shared";
import { Delivery, GuaranteeTable, type Guarantee } from "./vendors";

const STATUS: Record<string, string> = { open: "Open", received: "Fully received" };

/** POs: every ME2N line, open ones first by delivery date (the most overdue at the top). */
export function Pos() {
  useAsOf();
  const { me } = useMe();
  const r = useResource(() => api.pos());
  const pj = useProjects();
  const u = useUrl();
  const all = r.data ?? [];
  const mine = useMemo(() => all.filter((l) => me && l.buyer === me), [all, me]);
  const { who, setWho } = useWho(u, me, mine.length > 0);
  const base = who === "mine" ? mine : all;
  const st = u.get("status") ?? "open";
  const f = { status: st === "any" ? undefined : st, type: u.get("type"), flag: u.get("flag"), vertical: u.get("vertical"), buyer: who === "all" ? u.get("buyer") : undefined };
  const project = u.get("project");
  const q = (u.get("q") ?? "").trim().toLowerCase();
  const vert = (l: PoLine) => pj.byId.get(l.project?.id ?? "")?.vertical;
  const count = (pred: (l: PoLine) => boolean) => base.filter(pred).length;
  const uniq = (xs: (string | null | undefined)[]) => [...new Set(xs.filter(Boolean) as string[])].sort();
  const filters: FilterDef[] = [
    { id: "status", label: "Status", options: Object.entries(STATUS).map(([value, label]) => ({ value, label, count: count((l) => l.status === value) })) },
    { id: "type", label: "Type", options: uniq(all.map((l) => l.doc_type)).map((x) => ({ value: x, label: x, count: count((l) => l.doc_type === x) })) },
    { id: "flag", label: "Flag", options: uniq(all.flatMap((l) => l.flags)).map((x) => ({ value: x, label: x, count: count((l) => l.flags.includes(x)) })) },
    { id: "vertical", label: "Vertical", options: VERTICALS.map((v) => ({ value: v.id, label: v.name, count: count((l) => vert(l) === v.id) })).filter((o) => o.count) },
    ...(who === "all" ? [{ id: "buyer", label: "Buyer", options: uniq(all.map((l) => l.buyer)).map((b) => ({ value: b, label: b, count: count((l) => l.buyer === b) })) }] : []),
  ];
  const rows = base.filter((l) =>
    (!f.status || l.status === f.status) && (!f.type || l.doc_type === f.type) && (!f.flag || l.flags.includes(f.flag)) && (!f.vertical || vert(l) === f.vertical)
    && (!f.buyer || l.buyer === f.buyer) && (!project || l.project?.id === project)
    && (!q || `${l.ref.id} ${l.text} ${l.vendor.label ?? ""} ${l.vendor_code} ${l.material?.id ?? ""} ${l.project?.label ?? ""} ${l.plant} ${l.pr_line?.id ?? ""}`.toLowerCase().includes(q) || projectMatches(pj.byId.get(l.project?.id ?? ""), q)));
  const due = (l: PoLine) => l.revised?.length ? l.revised[l.revised.length - 1].date : l.delivery_date ?? "9999";
  const sorted = [...rows].sort((a, b) => (a.status === "open" && b.status === "open" ? due(a).localeCompare(due(b)) : a.status === "open" ? -1 : b.status === "open" ? 1 : b.doc_date.localeCompare(a.doc_date)));
  const open = rows.reduce((s, l) => s + (l.status === "open" ? baseOf(l.open_value) ?? 0 : 0), 0);
  const late = rows.filter((l) => l.days_past_due).length;
  return (
    <div className="rc pg-fix">
      <RecordsTabs />
      <ListTitle title="POs" sub="Purchase order lines from SAP (ME2N), netted against goods receipts (MB51). A date the vendor's mail moved is shown beside the SAP date, which is not changed."
        right={<WhoSwitch me={me} value={who} onChange={setWho} mine={r.data ? mine.length : undefined} all={r.data ? all.length : undefined} />} />
      <div className="rc-bar">
        <FilterBar label="PO lines" search={u.get("q") ?? ""} onSearch={(s) => u.set({ q: s })} placeholder="PO, vendor, material, project" filters={filters}
          value={f} onChange={(v) => u.set({ status: v.status ?? "any", type: v.type, flag: v.flag, vertical: v.vertical, buyer: v.buyer })} />
        <ProjectPicker projects={pj.list} value={project} onChange={(id) => u.set({ project: id })} />
      </div>
      {r.data && (
        <p className="rc-count" role="status">
          {enIn(rows.length)} {rows.length === 1 ? "line" : "lines"}{f.status === "open" ? ", soonest delivery first" : ""}
          {open > 0 && <> · {rs(open)} open</>}{late > 0 && <> · {enIn(late)} past due</>}
          {who === "mine" && me && <> · {me}'s purchasing group</>}
        </p>
      )}
      <div className="pg-body">
        {r.loading && !r.data ? <LoadingRows /> : r.error ? <LoadError what="PO lines" retry={invalidate} />
          : rows.length === 0 ? <EmptyState>{who === "mine" && !mine.length ? "No PO lines on your purchasing group. Everyone shows the rest." : "No PO line matches."}</EmptyState>
          : <PoList rows={sorted} />}
      </div>
    </div>
  );
}

function PoList({ rows }: { rows: PoLine[] }) {
  const { shown, more } = useMore(rows, 150, `${rows.length}|${rows[0]?.ref.id}`);
  const cols: Col<PoLine>[] = [
    { id: "l", head: "PO line", width: "minmax(0,1fr)", cell: (l) => <TitleCell title={l.text || l.material?.label || l.ref.id} tip={[l.text, ...l.flags].join("\n")} sub={<LineSub id={`PO ${l.ref.id}${l.doc_type !== "Purchase order" ? ` · ${l.doc_type}` : ""}`} flags={l.flags} />} /> },
    { id: "v", head: "Vendor", width: "180px", label: "Vendor", cell: (l) => <span title={`${l.vendor.label} · ${l.vendor_code}`}>{l.vendor.label}<small>{l.vendor_code}</small></span> },
    { id: "p", head: "Project", width: "112px", label: "Project", cell: (l) => l.project?.label ?? <span className="rc-warn">no project</span> },
    { id: "q", head: "Open qty", width: "120px", end: true, label: "Open", cell: (l) => <span>{qty(l.open_qty, l.uom)}<small>of {qty(l.qty)}</small></span> },
    { id: "o", head: "Open value", width: "96px", end: true, label: "₹", cell: (l) => (l.status === "open" ? rs(l.open_value) : <span className="none">—</span>) },
    { id: "d", head: "Delivery", width: "116px", label: "Delivery", cell: (l) => <Delivery l={l} /> },
    { id: "b", head: "Buyer", width: "124px", hide: "mid", label: "Buyer", phone: "hide", cell: (l) => <span>{l.buyer ?? "—"}<small>{l.purch_group}</small></span> },
  ];
  return <><DataTable label="PO lines" rows={shown} rowKey={(l) => l.ref.id} cols={cols} to={(l) => lineTo("po", l.ref.id)} two />{more}</>;
}

type Milestone = { id: string; item: string | null; mfc_requested: string | null; mfc_issued: string | null; inspection_call: string | null; inspection_planned: string | null;
  inspection_done: string | null; dispatch: string | null; delivered: string | null; site_ready: string | null; commissioned: string | null; warranty_end: string | null; remarks: string | null };
type Ledger = { first_invoice: string | null; last_payment: string | null; invoiced: number; paid: number; advance: number; open_invoices: number };

const MS: [keyof Milestone, string][] = [["mfc_requested", "MFC asked for"], ["mfc_issued", "MFC issued"], ["inspection_call", "Inspection called"], ["inspection_planned", "Inspection planned"],
  ["inspection_done", "Inspected"], ["dispatch", "Dispatch cleared"], ["delivered", "Delivered"], ["site_ready", "Site ready (planned)"], ["commissioned", "Commissioned"], ["warranty_end", "Warranty ends"]];

/** The expediting tracker's dates for one PO line, in order; a date not on file is a dash. */
function Milestones({ m }: { m: Milestone }) {
  return (
    <div className="rc-ms">
      <p className="rc-ms-h"><b>{m.item ?? m.id}</b> <span className="rc-id">· {m.id}</span></p>
      <ol className="rc-ms-steps">
        {MS.map(([k, label]) => <li key={k} className={m[k] ? "on" : undefined}><small>{label}</small><span>{m[k] ? day(m[k]) : "—"}</span></li>)}
      </ol>
      {m.remarks && <p className="rc-note">{humanize(m.remarks)}</p>}
    </div>
  );
}

/** One PO: its lines, the ladder of each, the expediting milestones, LCs and guarantees, and the invoices and payments against it. */
export function PoPage() {
  const { no = "" } = useParams();
  useAsOf();
  const r = useResource(() => api.po(no), [no]);
  useAskContext(r.data ? { type: "po", id: no, label: `PO ${no}` } : null);
  if (!r.data) return <PageState what={`PO ${no}`} error={r.error} kind="PO" />;
  const d: PoDetail = r.data;
  const first = d.lines[0];
  const ms = d.milestones as unknown as Milestone[];
  const gs = d.guarantees as unknown as Guarantee[];
  const led = d.ledger as unknown as Ledger;
  const items = d.ledger_items ?? [];
  const value = d.lines.reduce((s, l) => s + (baseOf(l.value) ?? 0), 0);
  const open = d.lines.reduce((s, l) => s + (l.status === "open" ? baseOf(l.open_value) ?? 0 : 0), 0);
  const waitOn = [...new Set(d.ladders.map((l) => l.waiting_on).filter(Boolean) as string[])];
  const ladderOf = (l: PoLine) => d.ladders.find((x) => x.po_line?.id === l.ref.id || x.subject.id === l.ref.id);
  const pv = d.lines.find((l) => l.pv)?.pv;
  return (
    <div className="rc rc-page">
      <RecordsTabs />
      <PageHeader flow back={{ to: "/pos", label: "POs" }} title={`${first.doc_type === "Purchase order" ? "PO" : first.doc_type} ${d.po}`}
        meta={<>
          <RefLink r={first.vendor}>{first.vendor.label} <span className="rc-id">· {first.vendor_code}</span></RefLink>
          <span className="sep">·</span>{first.project ? <RefLink r={first.project} id={false} /> : <span className="rc-warn">no project</span>}
          <span className="sep">·</span><span>dated {day(first.doc_date)}</span>
          {first.buyer && <><span className="sep">·</span><span>{first.buyer} ({first.purch_group})</span></>}
        </>} />
      <Tiles>
        <Tile figure={rs(value)} label={`ordered · ${d.lines.length} ${d.lines.length === 1 ? "line" : "lines"}`} />
        <Tile figure={open ? rs(open) : "—"} label={open ? "still to be received" : "fully received"} />
        <Tile figure={first.revised?.length ? day(first.revised[first.revised.length - 1].date) : day(first.delivery_date)} label={first.revised?.length ? `delivery as the vendor now says (SAP: ${day(first.delivery_date)})` : "delivery date"} tone={first.revised?.length || first.days_past_due ? "caution" : undefined} />
        <Tile figure={waitOn.length ? waitOn.join(", ") : "—"} label={waitOn.length ? "whose move it is now" : "nobody's move on file"} tone={waitOn.length ? "caution" : undefined} />
      </Tiles>
      <Block title="Terms">
        <Facts rows={[
          ["Payment terms", first.payment_terms],
          ["Valid to", first.validity_end ? day(first.validity_end) : null],
          ["Price basis", pv ? `PV-linked: ${pv.index ?? "index not named"}${pv.base_month ? `, base ${pv.base_month}` : ""}${pv.variable_share != null ? `, ${Math.round(pv.variable_share * 100)}% variable` : ""}` : "Firm (no PV clause)"],
          ["Plant", first.plant],
          ["From PR", first.pr_line ? <Link to={lineTo("pr", first.pr_line.id)}>PR {first.pr_line.id}</Link> : <span className="rc-warn">no PR (an emergency buy)</span>],
        ]} />
      </Block>
      <Block title="Lines" count={d.lines.length}>
        <DataTable label="PO lines" rows={d.lines} rowKey={(l) => l.ref.id} two cols={[
          { id: "l", head: "Line", width: "minmax(0,1fr)", cell: (l) => <TitleCell title={l.material ? <RefLink r={l.material} id={false}>{l.text || l.material.label}</RefLink> : l.text} sub={`${l.ref.id}${l.material ? ` · ${l.material.id}` : ""}`} /> },
          { id: "q", head: "Ordered", width: "120px", end: true, label: "Ordered", cell: (l) => <span>{qty(l.qty, l.uom)}<small>{qty(l.received)} received</small></span> },
          { id: "r", head: "Rate", width: "120px", end: true, label: "Rate", cell: (l) => <span title={l.rate.provenance?.raw ?? undefined}>{rate(l.rate.base ?? l.rate.amount, l.uom)}<small>{rs(l.value)}</small></span> },
          { id: "o", head: "Open", width: "120px", end: true, label: "Open", cell: (l) => (l.status === "open" ? <span>{qty(l.open_qty, l.uom)}<small>{rs(l.open_value)}</small></span> : <span className="none">received</span>) },
          { id: "d", head: "Delivery", width: "116px", label: "Delivery", cell: (l) => <Delivery l={l} /> },
          { id: "f", head: "Flags", width: "170px", hide: "narrow", label: "Flags", cell: (l) => <Flags flags={l.flags} /> },
        ]} />
      </Block>
      <Block title="PR to payment" note="Each step's date and the row it is read from; the time before each step is attributed to whoever held it. A step the records cannot show is marked, never guessed.">
        <LineLadders items={d.lines.map((l) => ({ key: l.ref.id, title: l.text || l.ref.id, sub: `line ${l.item} · ${qty(l.qty, l.uom)}`, ladder: ladderOf(l) }))} />
      </Block>
      <Block title="Milestones" count={ms.length || undefined} note={ms.length ? "From the expediting tracker." : "Not in the expediting tracker: bulk material is not expedited."}>
        {ms.map((m) => <Milestones key={m.id} m={m} />)}
      </Block>
      <Block title="LCs and guarantees" count={gs.length || undefined} note={gs.length ? undefined : "No LC or bank guarantee against this PO."}>
        {gs.length > 0 && <GuaranteeTable rows={gs} />}
      </Block>
      <Block title="Invoices and payments" count={items.length || undefined} note={items.length ? "From the vendor ledger (FBL1N)." : "No invoice, payment or advance against this PO in the vendor ledger."}>
        <Facts rows={[
          ["Invoiced", led.invoiced ? <>{rs(led.invoiced, true)}{led.first_invoice && <small className="rc-sub">first invoice {day(led.first_invoice)}</small>}</> : null],
          ["Paid", led.paid ? <>{rs(led.paid, true)}{led.last_payment && <small className="rc-sub">last payment {day(led.last_payment)}</small>}</> : null],
          ["Advance", led.advance ? rs(led.advance, true) : null],
          ["Unpaid invoices", enIn(led.open_invoices ?? 0)],
        ]} />
        {items.length > 0 && (
          <DataTable label="Invoices and payments" rows={items} rowKey={(i) => `${i.doc_no}|${i.row}`} two cols={[
            { id: "k", head: "Document", width: "minmax(0,1fr)", cell: (i) => <TitleCell title={`${i.kind} ${i.doc_no}`} sub={[i.reference, i.text].filter(Boolean).join(" · ")} /> },
            { id: "d", head: "Dated", width: "100px", label: "Dated", cell: (i) => day(i.date) },
            { id: "n", head: "Net due", width: "100px", label: "Due", phone: "hide", cell: (i) => day(i.net_due) },
            { id: "a", head: "Amount", width: "120px", end: true, label: "₹", cell: (i) => rs(i.amount, true) },
            { id: "c", head: "Cleared", width: "150px", label: "Cleared", cell: (i) => (i.doc_type === "RE" ? (i.cleared_by ? <span>{day(i.cleared_on)}<small>by {i.cleared_by}</small></span> : <span className="rc-warn">unpaid</span>) : <span className="none">—</span>) },
          ]} />
        )}
      </Block>
    </div>
  );
}
