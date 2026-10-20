import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ChevronLeft, ShieldAlert } from "lucide-react";
import { api } from "../../api/client";
import { useResource } from "../../api/useResource";
import type { MessageDetail, Stage as ApiStage } from "../../api/types";
import { useAskContext } from "../../shell/AskContext";
import { usePartNames } from "../../api/usePartNames";
import { Button, NotFound, Skeleton } from "../../ds";
import { EntityText, ItemLink, Person, PoLineTable, Supplier, TrustBadges, type StageKey, type SupplierTrust } from "../../components/domain";
import { useNamed } from "../../ui/useNamed";
import { Expander } from "../../ui/Expander";
import { longDate, shortDate } from "../../ui/format";
import { useMedia } from "../../ui/useMedia";
import { MailBody } from "./MailBody";
import { Analyst } from "./Analyst";
import { OfferTable } from "./OfferTable";
import { headline, messageView, offerRows } from "./model";

const trustOf = (t: MessageDetail["summary"]): SupplierTrust => (t.trust === "on_file" ? "on_file" : t.trust === "suspicious" && (t.trust_flags ?? []).includes("sender_domain_lookalike") ? "lookalike" : "new");
const company = (m: MessageDetail["summary"]) => (m.company && m.company !== "not on file" ? m.company : m.from || "Unknown sender");
const kindLabel = (k?: string | null) => (k ? k[0].toUpperCase() + k.slice(1) : "");
/** The header line cut at a word, for the Ask dock's "About:" chip. */
const short = (s: string, n = 38) => (s.length <= n ? s : `${s.slice(0, n).replace(/\s+\S*$/, "")}…`);
const stageKey = (s?: ApiStage | null): StageKey | null => (s ? (s.key as StageKey) : null);

const fromEmail = (t: MessageDetail) => t.from_email ?? (t.summary as { from_email?: string | null }).from_email ?? null;

function Headers({ t }: { t: MessageDetail }) {
  const replyBad = (t.summary.trust_flags ?? []).some((f) => f.startsWith("reply_to"));
  const rows: [string, ReactNode, boolean?][] = [
    ["From", fromEmail(t) ? `${t.summary.from} <${fromEmail(t)}>` : t.summary.from], ["Reply-to", t.reply_to ?? null, replyBad],
    ["To", t.to || null], ["Date", longDate(t.summary.date)], ["Subject", <EntityText key="s" text={t.subject} entities={t.subject_entities} suspect={(t.summary.trust_flags ?? []).length > 0 || t.summary.trust === "suspicious"} />],
  ];
  return <dl className="ib-hdrs">{rows.filter(([, v]) => v).map(([k, v, bad]) => <div key={k}><dt>{k}</dt><dd data-tone={bad ? "red" : undefined}>{v}</dd></div>)}</dl>;
}

/** One open message: what it says in one line, what it changes as a table, the facts as chips, the actions; the sender, trust and linked item in the rail. */
export function Message({ id, onBack }: { id: string; onBack: () => void }) {
  const phone = useMedia("(max-width: 760px)");
  const r = useResource(() => api.thread(id), [id]);
  const partName = usePartNames();
  const named = useNamed();
  const offerParts = r.data ? messageView(r.data).offerParts : [];
  const offers = useResource(() => Promise.all(offerParts.map((p) => api.partOffers(p).catch(() => []))).then((x) => offerRows(x.flat(), id)), [id, offerParts.join(",")]);
  const itemKey = r.data?.related_item ?? null;
  const item = useResource(() => (itemKey ? api.item(itemKey).catch(() => null) : Promise.resolve(null)), [itemKey]);
  useAskContext(r.data ? { type: "message", id, label: short(named(headline(r.data.summary.summary, r.data.summary.kind))) } : null);
  if (r.loading) return <Skeleton width={360} />;
  if (r.error || !r.data) return <NotFound title="Message not found" line={`No message has the id ${id}.`} />;
  const t = r.data, m = t.summary, held = m.trust === "suspicious";
  const v = messageView(t);
  const title = named(v.headline);
  const lines = v.lines.map((l) => ({ id: l.id, part: l.partId ? { id: l.partId, name: partName(l.partId) } : null, was: l.was, now: l.now }));
  return (
    <div className={`ib-msg${held ? " held" : ""}`}>
      <Button variant="quiet" onClick={onBack}><ChevronLeft size={16} aria-hidden />Inbox</Button>
      <div className="ib-grid">
        <div className="ib-main">
          <header className="ib-head">
            <div className="ib-meta">
              <Supplier id={m.supplier?.id ?? ""} name={company(m)} trust={trustOf(m)} to={!!m.supplier?.id} />
              {m.kind && <span className="ib-kind">{kindLabel(m.kind)}</span>}
              <span className="ib-date">{shortDate(m.date)}</span>
            </div>
            <h2>{title}</h2>
            <p className="ib-from">{m.from && m.from !== company(m) && <Person name={m.from} label={m.from} />}{fromEmail(t) && <span className="dm-id">{fromEmail(t)}</span>}</p>
          </header>
          {held && <div className="ib-held" role="alert"><ShieldAlert size={16} aria-hidden /><span><b>Held:</b> nothing can be done from this message.</span></div>}
          {v.facts.length > 0 && <div className="ib-facts">{v.facts.map((f) => <span className="ib-fact" key={f.label + f.value}><span>{f.label}</span><b>{f.value}</b></span>)}</div>}
          {lines.length > 0 && <PoLineTable rows={lines} caption="Order lines this message changes" />}
          {(offers.data ?? []).length > 0 && <OfferTable rows={offers.data!} />}
          {!held && <Analyst id={id} onFile={m.trust === "on_file"} />}
          <Expander title="The message, as received"><Headers t={t} /><MailBody body={t.body} highlights={t.highlights} entities={t.entities} suspect={held || (m.trust_flags ?? []).length > 0} /></Expander>
        </div>
        <aside className="ib-rail" aria-label="About this message">
          <section><h3 className="ib-cap">Trust</h3>
            {phone
              ? <details className="ib-trust-d"><summary>{(m.trust_flags ?? []).length ? `${(m.trust_flags ?? []).length} concerns` : m.trust === "on_file" ? "Sender verified" : "Nothing amiss"}<span>details</span></summary><TrustBadges flags={m.trust_flags ?? []} onFile={m.trust === "on_file"} /></details>
              : <TrustBadges flags={m.trust_flags ?? []} onFile={m.trust === "on_file"} />}</section>
          {itemKey && item.data && <section><h3 className="ib-cap">Linked to</h3><ItemLink id={itemKey} title={item.data.title} group={item.data.group} stage={stageKey(item.data.stage)} waitingOn={item.data.stage?.waiting_on} />
            {(t.sent ?? []).map((s) => <p className="ib-sent" key={s.action_id}><Link to={`/approvals/${encodeURIComponent(s.action_id)}`}>Sent {shortDate(s.sent_on)} · {s.subject} (simulated)</Link></p>)}</section>}
          {!(itemKey && item.data) && (t.sent ?? []).length > 0 && <section><h3 className="ib-cap">Sent</h3>
            {(t.sent ?? []).map((s) => <p className="ib-sent" key={s.action_id}><Link to={`/approvals/${encodeURIComponent(s.action_id)}`}>Sent {shortDate(s.sent_on)} · {s.subject} (simulated)</Link></p>)}</section>}
        </aside>
      </div>
    </div>
  );
}
