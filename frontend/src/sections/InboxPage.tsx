import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useResource } from "../api/useResource";
import type { MessageSummary } from "../api/types";
import { useMe } from "../api/useMe";
import { useMedia } from "../ui/useMedia";
import { useAskContext } from "../shell/AskContext";
import { inr, longDate, shortDate } from "../ui/format";
import { NotFound } from "../ds";
import { Mail } from "./case/Mail";
import "./inbox-page.css";
import "./case/case.css";

/** Inbox: the shared SCM mailbox. The message is the trigger; the case is where the owner acts. Every row says who sent it (a vendor on file, a colleague,
 * a look-alike, a stranger), what kind of message it is, what it means in one line, and where the case it feeds stands. Trust is computed in code before
 * anyone reads it; a held message is quoted data only. */
type Tab = "all" | "held" | "internal" | "vendors" | "quotes";
const TABS: { id: Tab; label: string }[] = [{ id: "all", label: "All" }, { id: "held", label: "Held" }, { id: "internal", label: "From the company" }, { id: "vendors", label: "From vendors" },
  { id: "quotes", label: "Quotes" }];
const inTab = (m: MessageSummary, t: Tab) => t === "all" || (t === "held" ? m.trust === "blocked" : m.trust === "blocked" ? false
  : t === "internal" ? m.sender_class === "internal" : t === "vendors" ? m.sender_class === "vendor" : ["Quote", "Spot offer"].includes(m.kind));
const CLASS: Record<string, string> = { vendor: "vendor on file", internal: "colleague", lookalike_vendor: "look-alike of a vendor", lookalike_internal: "look-alike of the company", unknown: "not on file" };

export function InboxPage() {
  const { id } = useParams();
  const nav = useNavigate();
  const { me } = useMe();
  const wide = useMedia("(min-width: 1024px)");
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const [tab, setTab] = useState<Tab>("all");
  const [q, setQ] = useState("");
  const list = useResource(() => api.messages(q.trim().length > 1 ? { q: q.trim() } : {}), [q], true);
  const rows = useMemo(() => (list.data ?? []).filter((m) => (scope === "all" || !me || (m.owner ?? "").split(" · ").includes(me)) && inTab(m, tab)), [list.data, scope, me, tab]);
  const sel = id ? decodeURIComponent(id) : wide ? rows[0]?.ref.id : undefined;
  const row = (m: MessageSummary) => (
    <Link key={m.ref.id} to={`/inbox/${encodeURIComponent(m.ref.id)}`} className={`ibx-row${sel === m.ref.id ? " on" : ""}${m.trust === "blocked" ? " held" : ""}`}>
      <span className="ibx-l1"><b>{m.from}</b><small>{shortDate(m.date)}</small></span>
      <span className="ibx-l2">{m.ref.label}</span>
      <span className="ibx-l3">{m.trust === "blocked" ? <em className="hb">Held</em> : <em className={`k k-${m.sender_class}`}>{m.kind}</em>}{m.simulated && <em>simulated</em>}
        <span className="mean">{m.summary}</span></span>
      {m.related_item && <span className="ibx-l4">{m.related_stage ? `${m.related_stage.label}` : "Case"} · {m.related_title}</span>}
    </Link>
  );
  return (
    <div className={`ibx${wide ? " two" : ""}`}>
      <div className="ibx-head">
        <h1>Inbox</h1>
        <div className="td-seg" role="group" aria-label="Whose messages">
          {(["mine", "all"] as const).map((s) => <button key={s} type="button" className={scope === s ? "on" : undefined} aria-pressed={scope === s} disabled={s === "mine" && !me} onClick={() => setScope(s)}>{s === "mine" ? "Yours" : "Everyone"}</button>)}
        </div>
      </div>
      <div className="ibx-tabs" role="group" aria-label="Kinds">
        {TABS.map((t) => <button key={t.id} type="button" className={tab === t.id ? "on" : undefined} aria-pressed={tab === t.id} onClick={() => setTab(t.id)}>{t.label} <em>{(list.data ?? []).filter((m) => (scope === "all" || !me || (m.owner ?? "").includes(me)) && inTab(m, t.id)).length}</em></button>)}
        <input className="td-f td-q ibx-q" type="search" placeholder="Search mail, PR/PO numbers, vendors" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search the inbox" />
      </div>
      <div className="ibx-grid">
        {(wide || !sel) && <div className="ibx-list" role="list">{list.loading && !list.data ? <p className="apq-empty">Loading…</p> : rows.length ? rows.map(row) : <p className="apq-empty">No messages here.</p>}</div>}
        {sel && <Detail id={sel} me={me} onBack={wide ? undefined : () => nav("/inbox")} />}
      </div>
    </div>
  );
}

function Detail({ id, me, onBack }: { id: string; me: string | null; onBack?: () => void }) {
  const d = useResource(() => api.thread(id), [id], true);
  useAskContext(d.data ? { type: "message", id, label: d.data.subject.replace(/^((re|fw|fwd):\s*)+/i, "") } : null);
  const [run, setRun] = useState("");
  if (d.error) return <NotFound title="No such message" line={`Nothing in the inbox has the id ${id}.`} />;
  if (!d.data) return <div className="ibx-d"><span className="skel" style={{ width: 320 }} /></div>;
  const m = d.data, s = m.summary;
  const held = s.trust === "blocked";
  const start = async (kind: "triage" | "reply") => {
    try { const r = kind === "triage" ? await api.triageRun(id, me ?? "") : await api.replyRun(id, me ?? ""); setRun(r.run_id); } catch (e) { setRun((e as Error).message === "no-model" ? "none" : "err"); }
  };
  return (
    <div className="ibx-d">
      {onBack && <button type="button" className="cp-link" onClick={onBack}>‹ Inbox</button>}
      <h2 className="ibx-dh">{m.subject}</h2>
      <p className="ibx-meta">{s.from} · {CLASS[s.sender_class] ?? s.sender_class}{s.contact ? ` (${s.contact})` : ""} · {s.company} · {longDate(s.date)}{s.owner ? ` · owner ${s.owner}` : ""}</p>
      {held ? (
        <div className="ibx-held">
          <b>Held before anyone read it.</b> {s.trust_flags.join("; ")}.{m.imitates ? ` The sender's domain imitates ${m.imitates}.` : ""}{m.claimed ? ` It asks for ${inr(m.claimed.amount, true)}; nothing is paid.` : ""}
        </div>
      ) : (
        <p className="ibx-means"><b>{s.kind}.</b> {s.summary}</p>
      )}
      {s.related_item && <p className="ibx-case">Feeds <Link to={`/items/${encodeURIComponent(s.related_item)}`}>{s.related_title}</Link>{s.related_stage ? ` · ${s.related_stage.label}` : ""}</p>}
      {(m.dates ?? []).length > 0 && (
        <div className="ibx-sec"><h3>The dates it carries</h3>
          <table className="cp-t"><tbody>{(m.dates ?? []).map((x, n) => <tr key={n}><td>{x.what}</td><td>{longDate(x.date)}</td><td><small>{x.line}</small></td></tr>)}</tbody></table></div>
      )}
      {(m.moves ?? []).length > 0 && (
        <div className="ibx-sec"><h3>The lines it moves</h3>
          <table className="cp-t"><thead><tr><th>Line</th><th>Item</th><th>Was</th><th>Now</th><th className="n">Qty</th></tr></thead>
            <tbody>{(m.moves ?? []).map((x, n) => <tr key={n}><td>{x.label}</td><td>{x.ref.label}</td><td>{/^\d{4}-/.test(x.was ?? "") ? shortDate(x.was) : x.was}</td><td>{/^\d{4}-/.test(x.now ?? "") ? shortDate(x.now) : x.now}</td><td className="n">{x.qty ?? ""}</td></tr>)}</tbody></table></div>
      )}
      {m.quote && (
        <div className="ibx-sec"><h3>The quote</h3>
          <dl className="cp-kv">
            <dt>When</dt><dd>valid to {longDate(m.quote.validity)}{m.quote.delivery ? ` · delivery ${m.quote.delivery}` : ""}</dd>
            <dt>Payment</dt><dd>{m.quote.payment ?? "not stated"}</dd>
            <dt>Price basis</dt><dd>{m.quote.price_basis ?? "—"}</dd>
            <dt>Vendor</dt><dd>{m.quote.vendor}{m.quote.in_library == null ? " · not in the vendor master" : m.quote.in_library ? " · in the library" : " · not in the library"}{m.quote.msme ? " · MSME" : ""}</dd>
          </dl>
          <table className="cp-t"><thead><tr><th>Vendor</th><th>Material</th><th className="n">Qty</th><th className="n">Rate</th><th className="n">Last PO</th><th className="n">Budget</th></tr></thead>
            <tbody>{m.quote.rows.map((r, n) => { const x = r as { vendor: string; material: string; qty: string; rate?: number; last_po?: number; budget?: number; line?: string };
              return <tr key={n}><td>{x.vendor}</td><td>{x.material}</td><td className="n">{x.qty}</td><td className="n">{inr(x.rate)}</td><td className="n">{x.last_po ? inr(x.last_po) : "—"}</td><td className="n">{x.budget ? inr(x.budget) : "—"}</td></tr>; })}</tbody></table></div>
      )}
      <div className="ibx-sec"><Mail m={m} /></div>
      {!held && !s.simulated && (
        <div className="cp-foot">
          <span className="pp">{run === "none" ? "No model is connected: the case page has the code's reading and routes." : run === "err" ? "Lookout could not start." : run ? <Link to={`/activity/${run}`}>Lookout is reading it ›</Link> : "Lookout reads it as data; any draft waits for the owner's signature."}</span>
          <button type="button" className="b9" onClick={() => start("triage")}>What does this mean?</button>
          <button type="button" className="b9" onClick={() => start("reply")}>Draft a reply</button>
        </div>
      )}
      {(m.sent ?? []).length > 0 && <p className="ibx-case">Sent to this sender since: {(m.sent ?? []).map((x) => `${x.subject} (${shortDate(x.sent_on)})`).join("; ")}</p>}
    </div>
  );
}
