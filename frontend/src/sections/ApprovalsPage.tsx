import { NotFound } from "../ds";
import { chosenDraft } from "../components/domain/caseStatus";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, type OrderLine } from "../api/client";
import { invalidate, useResource } from "../api/useResource";
import type { Action, ActionItem } from "../api/types";
import { useMe } from "../api/useMe";
import { useCompany } from "../api/useCompany";
import { useSupplierNames } from "../api/useSupplierNames";
import { useMedia } from "../ui/useMedia";
import { useAskContext } from "../shell/AskContext";
import { moneyText } from "../components/domain";
import { COMMITS, DraftDecision, DraftDoc, DraftReview, asksOf, replyBy, useDraftCheck } from "../domain-ui/DraftBlock";
import { StagedDecision, StagedDoc, StagedState, stagedNoun, stagedOf, stagedTitle, type StagedEdit } from "../domain-ui/StagedNote";
import { caseShort } from "../ui/cases";
import { first } from "../components/domain/caseStatus";
import "./approvals.css";

type Tab = "sign" | "others" | "sent" | "rejected";
const TABS: { id: Tab; label: string; empty: string }[] = [
  { id: "sign", label: "To approve", empty: "Nothing to approve." }, { id: "others", label: "With others", empty: "Nothing waits on anyone else." },
  { id: "sent", label: "Sent", empty: "Nothing sent yet." }, { id: "rejected", label: "Rejected", empty: "Nothing rejected." },
];
const OUTWARD: Action["type"][] = ["supplier_request", "supplier_alias"];
/** Everything that needs a signature (F101): the emails, and the notes, decisions and PO-line updates staged on a case. */
const signable = (a: Action) => OUTWARD.includes(a.type) || !!stagedOf(a);
const same = (a: Action, b: Action) => a.type !== "note" && a.item_key === b.item_key && a.type === b.type && a.recipient === b.recipient;      // a staged note is never replaced by another
const ownerOf = (a: Action) => (a as Action & { owner?: string | null }).owner ?? "";
const day = (iso?: string | null) => (iso ? new Date(`${iso.slice(0, 10)}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" }) : "");
/** The contact the email is addressed to, as the email names them ("Dear <name>"); else the address. */
const contactOf = (a: Action) => {
  const people = (a.body_entities ?? []) as { type: string; ref?: string | null; text?: string | null }[];
  const onFile = people.find((e) => e.type === "person" && !!a.target && (e.ref ?? "").startsWith(`${a.target.id}/`));      // the supplier's contact, not a buyer who signs
  return onFile?.text ?? a.target?.label ?? a.recipient ?? "";      // a name, never the raw address
};
const shortOf = (a: Action, nameOf: (id: string) => string | undefined) => a.target?.label ?? (a.target ? nameOf(a.target.id) ?? a.target.id : "");
const month = (ym: string) => new Date(`${ym}-01T00:00:00Z`).toLocaleDateString("en-US", { month: "short", timeZone: "UTC" });
/** A draft's own PO lines, read from the orders it names (AI-UI-SYNC A3): their open $, how many, how many past due and the most days late. */
type Own = { usd: number; lines: number; late: number; days: number };
const ownOf = (ls: (OrderLine | null)[]): Own | null => {
  const xs = ls.filter((l): l is OrderLine => !!l), late = xs.filter((l) => (l.days_past_due ?? 0) > 0);
  return xs.length ? { usd: xs.reduce((t, l) => t + Number(l.qty_open.value) * Number(l.unit_price?.usd ?? 0), 0), lines: xs.length, late: late.length, days: Math.max(0, ...late.map((l) => l.days_past_due ?? 0)) } : null;
};
const usdText = (n: number) => moneyText({ amount: n, currency: "USD", usd: String(n) });
/** What a draft puts at stake, in one line: its own lines' open $, the robots short in the first month when the draft covers its whole case, its lines and how many are past due. */
const stakeOf = (i: ActionItem | undefined, own: Own | null) => {
  if (!own) return null;
  const short = i?.lines_in_scope === own.lines ? i.robots_short ?? [] : [], m = short.map((r) => r.month).sort()[0];
  const robots = m ? `${short.filter((r) => r.month === m).sort((x, y) => y.robots - x.robots).map((r) => `${r.robots} ${r.product.label?.split(" ")[0] ?? r.product.id}`).join(" + ")} short in ${month(m)}` : "";
  const late = !own.late ? "" : own.late === own.lines ? `${own.days} d late` : `${own.late} past due`;
  return <>{[usdText(own.usd), robots, `${own.lines} line${own.lines === 1 ? "" : "s"}`].filter(Boolean).join(" · ")}{late && <>, <em>{late}</em></>}</>;
};
const MON = "JanFebMarAprMayJunJulAugSepOctNovDec";
/** The letter's own reply-by as a sortable key ("10-10"); "99" when it gives none. */
const replyKey = (body: string) => { const r = replyBy(body); if (!r) return "99"; const [m, d] = r.split(" "); return `${String(MON.indexOf(m) / 3 + 1).padStart(2, "0")}-${d.padStart(2, "0")}`; };

/** Who the server says a draft belongs to, learned the moment it refuses someone else: the button is never offered again. */
const learned = new Map<string, string>();

/** Approvals (FINAL 03): the queue, the email exactly as it will be sent, and the decision with what it commits and what was checked. */
export function ApprovalsPage() {
  const { id, tab: tabParam } = useParams();
  const nav = useNavigate();
  const { me } = useMe();
  const nameOf = useSupplierNames();
  const three = useMedia("(min-width: 1280px)");
  const desk = useMedia("(min-width: 1024px)");
  const all = useResource(() => api.actions());
  const items = useResource(() => api.actionItems().catch(() => [] as ActionItem[]));
  const itemOf = (a: Action) => items.data?.find((i) => i.key === a.item_key);
  const asOfDate = useResource(api.health).data?.as_of ?? null;      // a recorded note's date: the data date, the one its rail shows
  const outward = (all.data ?? []).filter(signable).sort((a, b) => (b.proposed_at ?? "").localeCompare(a.proposed_at ?? ""));
  const isMine = (a: Action) => { const o = learned.get(a.action_id) ?? ownerOf(a); return !o || !me || o === me; };
  const proposed = outward.filter((a) => a.state === "proposed" && chosenDraft(a));      // only the drafts the buyer chose; a prepared, unchosen one stays on its case
  const heads = proposed.filter((a, i) => !proposed.slice(0, i).some((b) => same(a, b)));      // a newer draft of the same request replaces the older one
  // Each draft's own lines (A3): the orders it names, read once.
  const [own, setOwn] = useState<Record<string, Own | null>>({});
  const pending = proposed.filter((a) => !(a.action_id in own));
  useEffect(() => {
    if (!pending.length) return;
    let live = true;
    Promise.all(pending.map((a) => {
      const ids = [...new Set((a.body_entities ?? []).filter((e) => e.type === "po_line" && e.ref).map((e) => e.ref as string))];
      return Promise.all(ids.map((x) => api.order(x).catch(() => null))).then((ls) => [a.action_id, ownOf(ls)] as const);
    })).then((xs) => { if (live) setOwn((m) => ({ ...m, ...Object.fromEntries(xs) })); });
    return () => { live = false; };
  }, [pending.map((a) => a.action_id).join()]); // eslint-disable-line react-hooks/exhaustive-deps
  /** Past-due lines first, the latest first (BUYER-F 05); then the letter's own reply-by (A3). */
  const actBy = (a: Action) => { const d = own[a.action_id]?.days; return d ? `0-${String(9999 - d).padStart(4, "0")}` : `1-${replyKey(a.body ?? "")}`; };
  const byDate = (xs: Action[]) => [...xs].sort((a, b) => actBy(a).localeCompare(actBy(b)));
  const buckets: Record<Tab, Action[]> = useMemo(() => ({
    sign: byDate(heads.filter(isMine)), others: byDate(heads.filter((a) => !isMine(a))),
    sent: outward.filter((a) => a.state === "executed" || a.state === "approved"), rejected: outward.filter((a) => a.state === "rejected"),
  }), [all.data, items.data, me, own]); // eslint-disable-line react-hooks/exhaustive-deps
  const selected = id ? outward.find((a) => a.action_id === id) : undefined;
  const tabOf = (a?: Action): Tab => (!a ? "sign" : a.state === "rejected" ? "rejected" : a.state !== "proposed" ? "sent" : isMine(a) ? "sign" : "others");
  const tab = TABS.find((t) => t.id === tabParam)?.id ?? tabOf(selected);
  const rows = buckets[tab];
  const ready = !!all.data && !!items.data;      // ownership needs both: until then nothing is shown as empty or counted

  // On a desktop the email is never empty while there is something to read: the first row opens by itself.
  useEffect(() => { if (desk && ready && !id && rows[0] && !pending.length) nav(`/approvals/${rows[0].action_id}`, { replace: true }); }, [desk, id, tab, rows[0]?.action_id, pending.length, ready]); // eslint-disable-line react-hooks/exhaustive-deps

  const status = (a: Action) => (a.state === "proposed" ? (isMine(a) ? <span className="w you">Approve</span> : <span className="w">With {first(learned.get(a.action_id) ?? ownerOf(a))}</span>)
    : a.state === "rejected" ? <span className="w">Rejected</span> : stagedOf(a) ? <span className="w">Recorded</span> : <span className="w">Sent</span>);
  /** A row's name: the supplier for an email, the case for a staged note. */
  const nameOfRow = (a: Action) => (stagedOf(a) ? (itemOf(a) ? caseShort(itemOf(a)!) : a.item_key ?? "") : shortOf(a, nameOf));
  const queue = (
    <nav className="apq" aria-label={TABS.find((t) => t.id === tab)?.label}>
      {!ready ? [0, 1, 2].map((n) => <div key={n} className="apq-sk" aria-hidden><i /><i /></div>)
        : rows.length === 0 ? <p className="apq-empty">{TABS.find((t) => t.id === tab)?.empty}</p>
        : rows.map((a) => (
          <Link key={a.action_id} to={`/approvals/${a.action_id}`} className={`apq-row${a.action_id === id ? " on" : ""}`} aria-current={a.action_id === id ? "page" : undefined}>
            <b>{nameOfRow(a)}</b><small>{a.subject}</small>
            {a.state === "proposed" && own[a.action_id] && <span className="apq-stake">{stakeOf(itemOf(a), own[a.action_id] ?? null)}</span>}
            <span className="apq-l3">{status(a)}{stagedOf(a) && a.state !== "proposed" ? <span className="by">{day(asOfDate)}</span>
              : a.state === "proposed" && replyBy(a.body ?? "") ? <span className="by">reply by {replyBy(a.body ?? "")}</span> : null}</span>
          </Link>
        ))}
    </nav>
  );
  const showQueue = desk || !id;
  return (
    <div className={`apx${three ? " three" : ""}`}>
      <h1 className="apx-h">Approvals</h1>
      <div className="apx-tabs" role="group" aria-label="Approvals">
        {TABS.map((t) => <button key={t.id} type="button" aria-pressed={tab === t.id} className={tab === t.id ? "on" : undefined} onClick={() => nav(`/approvals/tab/${t.id}`)}>{t.label} {ready && <em>{buckets[t.id].length}</em>}</button>)}
      </div>
      <div className="apx-grid">
        {three ? queue : desk && rows.length > 0 ? (
          <label className="apx-pick">Draft <select value={id ?? ""} onChange={(e) => nav(`/approvals/${e.target.value}`)}>
            {rows.map((a) => <option key={a.action_id} value={a.action_id}>{nameOfRow(a)}: {a.subject}</option>)}
          </select></label>
        ) : showQueue && !id ? queue : null}
        {id ? <Detail key={id} id={id} mine={selected ? isMine(selected) : true} owner={selected ? (learned.get(selected.action_id) ?? ownerOf(selected)) : ""} item={selected ? itemOf(selected) ?? null : null}
          onBack={desk ? undefined : () => nav(`/approvals/tab/${tab}`)} onLearned={(who) => { if (selected) learned.set(selected.action_id, who); invalidate(); }} />
          : desk && ready && rows.length === 0 ? <p className="apq-empty">{TABS.find((t) => t.id === tab)?.empty}</p> : null}
      </div>
    </div>
  );
}

type Mode = "read" | "edit" | "reject";

/** The draft flow (FINAL 03): the email, Approve and send · Edit · Reject, the checks. `inCase` lays it out inside a case's Approval card (FINAL 07): the email, then the decision under it. */
export function DraftFlow(props: { id: string; mine: boolean; owner: string; item: ActionItem | null; onBack?: () => void; onLearned: (who: string) => void; inCase?: boolean; onDecided?: (a: Action) => void }) {
  return <Detail {...props} />;
}

function Detail({ id, mine, owner, item, onBack, onLearned, inCase, onDecided }: { id: string; mine: boolean; owner: string; item: ActionItem | null; onBack?: () => void; onLearned: (who: string) => void; inCase?: boolean; onDecided?: (a: Action) => void }) {
  const r = useResource(() => api.action(id), [id]);
  const [a, setA] = useState<Action | null>(null);
  const [mode, setMode] = useState<Mode>("read");
  const [draft, setDraft] = useState({ subject: "", body: "" });
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [sedit, setSedit] = useState<StagedEdit | null>(null);      // a staged decision's words while the owner edits them
  useEffect(() => {
    if (!sedit) return;
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setSedit(null); };      // Esc restores the staged words
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [sedit]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const { me, setMe } = useMe();
  const company = useCompany();
  const health = useResource(api.health);
  const nameOf = useSupplierNames();
  useEffect(() => { if (r.data) setA(r.data); }, [r.data]);
  const sup = useResource(() => (r.data?.target?.type === "supplier" ? api.supplier(r.data.target.id).catch(() => null) : Promise.resolve(null)), [r.data?.target?.id]);
  const check = useDraftCheck(a);
  useAskContext(inCase ? undefined : a ? { type: "action", id: a.action_id, label: stagedOf(a) ? stagedNoun(stagedOf(a)!) : "this email" } : null);      // on a case, Ask stays about the case
  useEffect(() => {
    if (mode !== "edit") return;
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setMode("read"); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [mode]);

  if (r.loading && !a) return <div className="apd"><span className="skel" style={{ width: 320 }} /></div>;
  if (r.error || !a) return <div className="apd"><NotFound title="Draft not found" line={`No draft has the id ${id}.`} /></div>;
  const filed = (sup.data as { contact?: { name?: string | null; email?: string | null } | null } | null)?.contact;
  const onFile = !filed?.email || filed.email.toLowerCase() === (a.recipient ?? "").toLowerCase();      // the address is the contact the supplier record holds
  const contact = (onFile && filed?.name) || contactOf(a), short = shortOf(a, nameOf), legal = a.target ? nameOf(a.target.id) ?? "" : "";
  const asOf = day(health.data?.as_of);
  const chase = item?.act_by && health.data?.as_of && item.act_by >= health.data.as_of ? day(item.act_by) : "";      // the case's chase date, as its stage sets it (stage.py: "Chase if nothing comes by")      // the data date: a wall-clock time would clash with it
  const failed = a.unverified_checks ?? [];
  const needsConfirm = failed.length ? `Lookout’s checks did not all pass (${failed.join(", ")}).` : !onFile ? `${a.recipient} is not the contact on file.` : check.bad.length ? (() => { const n = new Set(check.bad.map((b) => b.why.split(":")[0])).size; return `${n} of ${check.poCount} PO lines ${n === 1 ? "doesn’t" : "don’t"} match the records.`; })() : null;
  const refuse = (e: unknown) => {
    setBusy(false);
    const detail = e instanceof ApiError ? e.detail : "";
    const who = /belongs to (.+?):/i.exec(detail)?.[1];
    if (who) { onLearned(who); return; }
    setErr(detail ? detail.charAt(0).toUpperCase() + detail.slice(1) : "That did not go through. Try again.");
    api.action(id).then(setA, () => undefined);
  };
  const approve = () => { if (!me) return; setBusy(true); setErr(null); api.approve(a.action_id, a.payload_hash, me, !!needsConfirm && confirmed).then((x) => { setA(x); setBusy(false); invalidate(); onDecided?.(x); }, refuse); };
  const save = () => { if (!me) return; setBusy(true); setErr(null); api.editAction(a.action_id, draft.subject, draft.body, me).then((x) => { setA(x); setMode("read"); setConfirmed(false); setBusy(false); }, refuse); };
  const reject = () => { if (!me || !reason.trim()) return; setBusy(true); setErr(null); api.reject(a.action_id, reason.trim(), me).then((x) => { setA(x); setMode("read"); setBusy(false); invalidate(); onDecided?.(x); }, refuse); };
  const proposed = a.state === "proposed", sent = a.state === "executed" || a.state === "approved";
  const staged = stagedOf(a);
  if (staged) {
    const saveStaged = () => {
      if (!me || !sedit) return;
      setBusy(true); setErr(null);
      api.editAction(a.action_id, a.subject ?? "", sedit.body, me, staged.kind === "record" ? { reason: sedit.reason, recheck_on: sedit.recheck_on } : undefined)
        .then((x) => { setA(x); setSedit(null); setMode("read"); setBusy(false); }, refuse);
    };
    // A note, a decision or a PO-line update: the same Approve (owner-only, bound to the hash of the text shown), Reject with a reason, nothing sent.
    const decided = !proposed ? <StagedState a={a} c={staged} asOf={asOf} />
      : !mine ? (
        <div className="db-state"><b>With {first(owner)}</b><span>Only {owner} can approve this.</span>
          <div className="db-act" style={{ marginTop: 8 }}><button type="button" className="db-btn sm" onClick={() => setMe(owner)}>Switch to {first(owner)}</button></div></div>
      ) : mode === "reject" ? (
        <div className="dd"><textarea className="db-reason" autoFocus aria-label="Why reject it" placeholder="Why is this being rejected?" value={reason} onChange={(e) => setReason(e.target.value)} />
          <div className="db-act"><button type="button" className="db-btn sm no" disabled={busy || !reason.trim()} onClick={reject}>Reject</button><button type="button" className="db-btn sm q" onClick={() => setMode("read")}>Cancel</button></div></div>
      ) : sedit ? (
        <div className="dd"><button type="button" className="db-btn ink wide" disabled={busy || !sedit.body.trim() || (staged.kind === "record" && !sedit.reason.trim())} onClick={saveStaged}>Save</button>
          <div className="db-act"><button type="button" className="db-btn sm q" onClick={() => setSedit(null)}>Cancel</button></div>
          <div className="db-cap">You approve the saved words, not the old ones.</div></div>
      ) : <StagedDecision me={me ?? "…"} busy={busy || !me} c={staged} onApprove={approve} onReject={() => { setReason(""); setMode("reject"); }}
          onEdit={staged.kind === "record" ? () => setSedit({ body: a.body ?? "", reason: staged.reason ?? "", recheck_on: staged.recheck_on ?? "" }) : undefined} />;
    if (inCase) return <div className="dfc"><StagedDoc a={a} c={staged} item={item} edit={sedit} onEdit={setSedit} /><div className="dfc-dec">{decided}{err && <p className="apr-err" role="alert">{err}</p>}</div></div>;
    return (
      <>
        <article className="apd" aria-label={stagedTitle(a)}>
          {onBack && <button type="button" className="linkbtn apd-back" onClick={onBack}>‹ Approvals</button>}
          <h2 className="apd-h">{stagedTitle(a)}</h2>
          <StagedDoc a={a} c={staged} item={item} edit={sedit} onEdit={setSedit} />
        </article>
        <aside className="apr" aria-label="The decision">{decided}{err && <p className="apr-err" role="alert">{err}</p>}</aside>
      </>
    );
  }

  const decision = !proposed ? (
    <div className="db-state">{sent
      ? <><b>Sent {asOf}{replyBy(a.body ?? "") ? ` · response due ${replyBy(a.body ?? "")}` : ""}</b><span>Approved by {a.decided_by} · waiting for {contact} · simulated, nothing left this computer</span></>
      : <><b>Rejected by {a.decided_by}</b><span>{a.reason}</span></>}</div>
  ) : !mine ? (
    <div className="db-state"><b>With {first(owner)}</b><span>Only {owner} can approve this email.</span>
      <div className="db-act" style={{ marginTop: 8 }}><button type="button" className="db-btn sm" onClick={() => setMe(owner)}>Switch to {first(owner)}</button></div></div>
  ) : mode === "edit" ? (
    <div className="dd"><button type="button" className="db-btn ink wide" disabled={busy || (!draft.subject.trim() || !draft.body.trim())} onClick={save}>Save draft</button>
      <div className="db-act"><button type="button" className="db-btn sm q" onClick={() => setMode("read")}>Cancel</button></div>
      <div className="db-cap">You approve the saved text, not the old one.</div></div>
  ) : mode === "reject" ? (
    <div className="dd"><textarea className="db-reason" autoFocus aria-label="Why reject it" placeholder="Why is this being rejected?" value={reason} onChange={(e) => setReason(e.target.value)} />
      <div className="db-act"><button type="button" className="db-btn sm no" disabled={busy || !reason.trim()} onClick={reject}>Reject</button><button type="button" className="db-btn sm q" onClick={() => setMode("read")}>Cancel</button></div></div>
  ) : (
    <DraftDecision me={me ?? "…"} busy={busy || !me} needsConfirm={needsConfirm} confirmed={confirmed} onConfirm={setConfirmed} onApprove={approve}
      onEdit={() => { setDraft({ subject: a.subject ?? "", body: a.body ?? "" }); setMode("edit"); }} onReject={() => { setReason(""); setMode("reject"); }} />
  );
  if (inCase) {
    const asks = asksOf(a.body ?? ""), due = replyBy(a.body ?? "");
    return (
      <div className="dfc">
        <p className="dfc-to">Email to <b>{contact}</b>{short ? ` (${short})` : ""}{onFile ? " · on file" : <span className="no"> · not the contact on file</span>}{asks ? ` · asks ${asks}${due ? ` by ${due}` : ""}` : ""} · {(a.body ?? "").match(COMMITS) ? <b className="commit">commits</b> : "commits nothing"}</p>
        <DraftDoc a={a} check={check} contact={contact} supplier={legal} editing={mode === "edit"} draft={draft} onDraft={setDraft} />
        <div className="dfc-dec">{decision}{err && <p className="apr-err" role="alert">{err}</p>}</div>
      </div>
    );
  }
  return (
    <>
      <article className="apd" aria-label="The email">
        {onBack && <button type="button" className="linkbtn apd-back" onClick={onBack}>‹ Approvals</button>}
        <h2 className="apd-h">Email to {contact}{short ? ` (${short})` : ""}</h2>
        <DraftDoc a={a} check={check} contact={contact} supplier={legal} editing={mode === "edit"} draft={draft} onDraft={setDraft} />
      </article>
      <aside className="apr" aria-label="The decision">
        {decision}
        {err && <p className="apr-err" role="alert">{err}</p>}
        {/* the case by its title only: its $ and act-by live on the case and on the list row (BUYER-F 05) */}
        <DraftReview a={a} check={check} onFile={onFile} contact={contact} short={short} company={company.short} by="" chase={chase} sent={sent} item={item ? { key: item.key, title: item.title } : null} />
      </aside>
    </>
  );
}
