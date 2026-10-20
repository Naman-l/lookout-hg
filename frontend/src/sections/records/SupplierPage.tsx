import { useParams, useSearchParams } from "react-router-dom";
import { useAskContext } from "../../shell/AskContext";
import { api } from "../../api/client";
import { useResource } from "../../api/useResource";
import type { ActionItem } from "../../api/types";
import { EmptyState, NotFound, PageHeader, Row, StateChip, Tile, Tiles } from "../../ds";
import { humanize, shortDate } from "../../ui/format";
import { TRUST } from "../Inbox";
import { byActBy, isRollup, supplierRobots, usd } from "./model";
import { PoLineTable } from "./PoLineTable";
import { CaseBlock, RobotSlots, SkeletonRows, TextTabs, setParam, useRecords } from "./ui";
import { ListBody, RecordsTabs } from "./lists";

type Tab = "profile" | "orders" | "messages" | "records";

/** A supplier (FINAL 06 §2): the cases it is in, what to watch, its figures; its open lines, messages and vendor records as tabs. */
export function SupplierPage() {
  const { id = "" } = useParams();
  const sid = decodeURIComponent(id);
  const [params, setParams] = useSearchParams();
  const r = useRecords();
  const s = useResource(() => api.supplier(sid), [sid]);
  useAskContext(s.data ? { type: "supplier", id: sid, label: s.data.ref.label ?? sid } : null);
  const msgs = useResource(() => api.messages());
  const x = s.data;
  const lines = (r.lines.data ?? []).filter((l) => l.supplier.id === sid || (x?.record_ids ?? []).includes(l.supplier.id ?? ""));
  const lit = supplierRobots(lines.map((l) => ({ ...l, supplier: { ...l.supplier, id: sid } })), r.robotsOf).get(sid) ?? [];
  if (s.loading && !x) return <div className="rc"><h1><span className="skel" style={{ width: 360 }} /></h1><SkeletonRows n={3} /></div>;
  if (s.error || !x) return <NotFound title="Supplier not found" line={`No supplier has the id ${sid}.`} />;
  const mail = (msgs.data ?? []).filter((m) => m.supplier?.id === sid || x.messages.some((y) => y.id === m.ref.id));
  const open = lines.filter((l) => !l.stale);
  const cases = byActBy(r.idx.supplier.get(sid) ?? [], r.asOf);
  const tab = (["orders", "messages", "records"].includes(params.get("s") ?? "") ? params.get("s") : "profile") as Tab;
  // A message held in this supplier's name: what it asked for, and who to call instead.
  const held = (i: ActionItem) => (i.group === "trust" && /bank|payment/i.test(i.title)
    ? `Someone using this name asked to change bank details (${usd(Number((i.at_stake as { usd?: string } | null)?.usd ?? 0))}). Do not pay; confirm by phone${x.contact ? ` with ${x.contact.name}` : " with the contact on file"}.` : null);
  // A team list (the aged POs, the chase) counts every supplier's lines: on this page it counts this supplier's ("3 aged open POs" -> "2 aged open POs").
  const scoped = (i: ActionItem) => {
    const mine = lines.filter((l) => (r.idx.line.get(l.ref.id ?? "") ?? []).includes(i)).length;
    const n = Number(i.title.match(/^(\d+)/)?.[1] ?? NaN);
    return isRollup(i.key) && mine > 0 && mine < n ? i.title.replace(/^\d+/, String(mine)) : i.title;
  };
  // …and names only the buyers of this supplier's lines in it (not every buyer the team list names).
  const teamOwners = (i: ActionItem) => {
    if (!isRollup(i.key)) return null;
    const who = [...new Set(lines.filter((l) => (r.idx.line.get(l.ref.id ?? "") ?? []).includes(i)).map((l) => l.buyer))];
    return who.length ? who.join(" · ") : null;
  };
  const d = x.delivery;
  return (
    <div className="rc rc-fixed">
      <RecordsTabs on="suppliers" />
      <PageHeader
        title={x.ref.label}
        meta={<span className="rc-meta"><RobotSlots robots={r.robots} lit={lit} on="its open lines go into it" off="none of its open lines" /><span className="sep">·</span>{x.country}<span className="sep">·</span>{x.terms}<span className="sep">·</span>{x.incoterms}{x.tier != null && <><span className="sep">·</span>tier {x.tier}</>}</span>}
      />
      <TextTabs<Tab> label="Supplier" value={tab} onChange={(t) => setParam(setParams, "s", t === "profile" ? null : t)}
        tabs={[{ id: "profile", label: "Profile" }, { id: "orders", label: "Orders", count: open.length }, { id: "messages", label: "Messages", count: mail.length }, { id: "records", label: "Records", count: x.record_ids.length }]} />
      <ListBody>
      {tab === "profile" && (
        <>
          <CaseBlock cases={cases} r={r} held={(i) => held(i) ?? teamOwners(i)} retitle={scoped} />
          {(x.risk ?? []).length > 0 && (
            <section className="rc-sec rc-watch" aria-label="Watch">
              <h2 className="rc-h2">Watch</h2>
              {(x.risk ?? []).map((f) => <p key={f.kind}>{f.text.replace(/^Reported (\d{4}-\d{2}-\d{2}):/, (_, iso: string) => `${shortDate(iso)}:`)}</p>)}
            </section>
          )}
          <div className="rc-sec" style={{ marginTop: "var(--s5)" }}>
            <Tiles>
              <Tile figure={usd(Number(x.open_value?.usd ?? x.open_value?.amount ?? 0))} label="open value" />
              {d?.streak ? <Tile figure={`${d.streak.late_in_row} late in a row`} label={d.streak.line} />      // a current streak says more than the all-time share (UX/SIDEQ ruling)
                : d && d.n > 0 && <Tile figure={`${Math.round(d.on_time_pct * 100)}%`} label={`on time: ${d.on_time} of ${d.n} closed lines`} />}
              {d && d.late > 0 && <Tile figure={`${Math.round(d.avg_days_late)} d`} label={`average days late, over ${d.late} late lines`} />}
              <Tile figure={x.past_due_lines} label={`${x.past_due_lines === 1 ? "line" : "lines"} past due`} />
              {x.contact ? <Tile figure={x.contact.name} label={`contact on file · ${x.contact.email}`} /> : <Tile figure="—" label="no contact on file" />}
            </Tiles>
          </div>
        </>
      )}
      {tab === "orders" && (r.lines.loading && !r.lines.data ? <SkeletonRows n={4} /> : lines.length === 0 ? <EmptyState>No open PO lines with this supplier.</EmptyState> : (
        <PoLineTable label={`Open PO lines with ${x.ref.label}`} lines={lines} r={r} drop="supplier" open={params.get("open")} onOpen={(o) => setParam(setParams, "open", o)} />
      ))}
      {tab === "messages" && (
        <div className="rc-sec">
          {mail.length === 0 && <EmptyState>No messages from this supplier.</EmptyState>}
          {mail.map((m) => (
            <Row key={m.ref.id} to={`/inbox/${encodeURIComponent(m.ref.id ?? "")}`} title={`${m.from}${m.company ? ` · ${m.company}` : ""}`} sub={humanize(m.summary)}
              figure={<StateChip tone={m.trust === "suspicious" ? "critical" : undefined}>{TRUST[m.trust ?? "on_file"].label}</StateChip>} note={shortDate(m.date)} />
          ))}
        </div>
      )}
      {tab === "records" && (
        <div className="rc-sec">
          <p>{x.record_ids.map((y) => <span key={y} className="pn">{y} </span>)}</p>
          <p className="muted">{x.records === 1 ? "One record" : `${x.records} records for one company`}, none merged.</p>
        </div>
      )}
      </ListBody>
    </div>
  );
}
