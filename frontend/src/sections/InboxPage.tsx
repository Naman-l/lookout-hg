import { NotFound } from "../ds";
import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ChevronRight, X } from "lucide-react";
import { api } from "../api/client";
import { useResource } from "../api/useResource";
import type { Action, ActionItem, MessageDetail, MessageSummary, OfferView } from "../api/types";
import { useMe } from "../api/useMe";
import { useCompany } from "../api/useCompany";
import { useMedia } from "../ui/useMedia";
import { usePartNames } from "../api/usePartNames";
import { useAskContext } from "../shell/AskContext";
import { RobotIcon, useRobots } from "../components/domain";
import { myChosenCases, myDraftCases, statusOf as caseStatus } from "../components/domain/caseStatus";
import { WhatChanges, type Change } from "../domain-ui/WhatChanges";
import { MailBody } from "./inbox/MailBody";
import "./inbox-page.css";

/** Inbox (FINAL 04): the message is the trigger, the case is where the buyer acts. Every row says who sent it, what it changes and how much,
 * which robots it touches and where the case it moves stands; the detail says it whole, line by line. No buttons here. */

type Tab = "all" | "held" | "notices" | "quotes";
const TABS: { id: Tab; label: string }[] = [{ id: "all", label: "All" }, { id: "held", label: "Held" }, { id: "notices", label: "Notices" }, { id: "quotes", label: "Quotes" }];
const NOTICES = ["force majeure", "slip", "closure", "price change"], QUOTES = ["quote", "correction"];
const inTab = (m: MessageSummary, t: Tab) => t === "all" || (t === "held" ? m.trust === "suspicious" : m.trust !== "suspicious" && (t === "notices" ? NOTICES : QUOTES).includes(m.kind ?? ""));
const KIND: Record<string, string> = { "force majeure": "Force majeure", slip: "Schedule slip", closure: "Plant closure", "price change": "Price increase", quote: "Quote", correction: "Correction", "payment change": "Payment change", "spot offer": "Spot offer" };
const day = (iso?: string | null) => (iso && /^\d{4}-\d{2}-\d{2}/.test(iso) ? new Date(`${iso.slice(0, 10)}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" }) : "");
const first = (n?: string | null) => (n ?? "").split(" ")[0];
const usd = (n: string) => `$${n}`;
const READ_KEY = "lookout.inbox.read";
const readSet = (): Set<string> => { try { return new Set(JSON.parse(localStorage.getItem(READ_KEY) ?? "[]")); } catch { return new Set(); } };
const markRead = (id: string) => { try { const s = readSet(); s.add(id); localStorage.setItem(READ_KEY, JSON.stringify([...s])); } catch { /* private mode: read marks last this visit */ } };

const changesOf = (m: MessageSummary) => (m.changes ?? []) as Change[];
const lines = (m: MessageSummary) => changesOf(m).filter((c) => c.ref.type === "po_line");
const offers = (m: MessageSummary) => changesOf(m).filter((c) => c.ref.type === "part" && c.label.startsWith("Offer"));
const deadline = (m: MessageSummary) => changesOf(m).find((c) => c.label === "Deadline")?.after ?? null;
const expires = (m: MessageSummary) => changesOf(m).find((c) => c.label === "Quote expires")?.after ?? /valid to (\d{4}-\d{2}-\d{2})/.exec(offers(m)[0]?.after ?? "")?.[1] ?? null;
const shortOf = (m: MessageSummary) => m.supplier_short ?? (m.company !== "not on file" ? m.company : null) ?? m.from;
/** "Offer 160.87 USD at 1000" -> {price "$160.87", qty "1,000"} */
const offerOf = (c: Change) => { const x = /Offer (?:per 1,000 |ea )?([\d.,]+) (\w{3})(?: at ([\d,]+))?/.exec(c.label); return x ? { price: x[2] === "USD" ? usd(x[1]) : `${x[1]} ${x[2]}`, qty: x[3] ? Number(x[3].replace(/,/g, "")).toLocaleString("en-US") : null } : null; };
const slip = (m: MessageSummary) => {
  const rows = lines(m).filter((c) => c.before && c.after && /^\d{4}/.test(c.after));
  const d = rows.map((c) => Math.round((Date.parse(c.after!) - Date.parse(c.before!)) / 864e5));
  const ids = new Set(rows.map((c) => c.ref.id));
  const split = [...ids].filter((id) => rows.filter((c) => c.ref.id === id).length > 1).length;
  const afters = rows.map((c) => c.after!).sort();
  return { n: ids.size, min: Math.min(...d), max: Math.max(...d), first: afters[0], last: afters[afters.length - 1], split, splitLine: [...ids].find((id) => rows.filter((c) => c.ref.id === id).length > 1) };
};

/** The size of the change, in one line for the row (short) or whole for the headline. */
/** The cases on the list by key and who signs each waiting draft: a quote linked to a case by part is named by that case (BUYER: "alternate for the <case> case"),
 * and every status word comes from Today's own rule (caseStatus.statusOf), so the Inbox and Today always say the same thing. Read once per page and again on every
 * invalidate() and window focus (useResource), so an approval anywhere changes the word here without a reload. */
type Cases = { items: Map<string, ActionItem>; draftOwner: Map<string, string>; actions: Action[] };
function useCases(): Cases | null {
  const r = useResource(() => Promise.all([api.actionItems().catch(() => [] as ActionItem[]), api.actions().catch(() => [] as Action[])]).then(([xs, as]) => ({
    items: new Map(xs.map((i) => [i.key, i])), draftOwner: new Map(as.map((a) => [a.action_id, (a as Action & { owner?: string | null }).owner ?? ""])), actions: as })), [], true);
  return r.data ?? null;
}
const titleOf = (cases: Cases | null) => (key?: string | null) => (key ? cases?.items.get(key)?.title : undefined);
const caseName = (title?: string) => title?.split(":")[0];
/** Where a payment-change letter sends the money, in its own words: the place on its "Bank:" line ("…, <place>"), else "a new bank account". */
const where = (body: string) => { const p = /^\s*Bank:[^\n]*,\s*([A-Z][\w ]+?)\s*$/m.exec(body)?.[1]; return p ? `a bank account in ${p}` : "a new bank account"; };

function fact(m: MessageSummary, names: (id: string) => string | undefined, whole = false, compare?: string | null, caseTitle?: (key?: string | null) => string | undefined, asOf?: string | null): string {
  const k = m.kind ?? "";
  if (k === "force majeure") { const n = new Set(lines(m).map((c) => c.ref.id)).size, due = day(deadline(m)); return `${n} lines can't ship${due ? `${whole ? ";" : " ·"} revised dates by ${due}` : ""}`; }
  if (k === "slip") {
    const s = slip(m); if (!s.n) return m.summary;
    const range = s.min === s.max ? `${s.min} d` : `${s.min}–${s.max} d`;
    return whole ? `${s.n} line${s.n === 1 ? "" : "s"} pushed out to ${day(s.first)}${s.first !== s.last ? ` – ${day(s.last)}` : ""}${s.splitLine ? `; line ${s.splitLine.split("/")[1]} split in two` : ""}`
      : `${s.n} line${s.n === 1 ? "" : "s"} pushed out ${range}, to ${day(s.last)}${s.split ? ` · ${s.split} split` : ""}`;
  }
  if (k === "closure") { const c = changesOf(m).find((x) => x.label === "Factory closure"), due = day(deadline(m)); return `${whole ? "Closed" : "closed"} ${day(c?.before)} – ${day(c?.after)}${due ? `${whole ? ";" : " ·"} last ship ${due}` : ""}`; }
  if (k === "price change") { const c = changesOf(m).find((x) => x.label === "Price change"); const pct = (c?.after?.match(/[+-]\d+(?:\.\d+)?%/g) ?? []).join(" / "); const due = day(deadline(m)); return `${pct}${c?.before ? ` from ${day(c.before)}` : ""}${due ? `${whole ? ";" : " ·"} lock by ${due}` : ""}`; }
  if (k === "payment change") { const amt = /USD ([\d,]+)/.exec(changesOf(m)[0]?.after ?? m.summary)?.[1]; return `${whole ? "Asks" : "asks"} to pay ${amt ? usd(amt) : "money"} to ${/bank details|account/i.test(m.summary) ? "new bank details" : "a new account"}`; }
  if (k === "spot offer") { const x = /([\d,]+) x (HR-\d{5}) at USD ([\d.,]+)/.exec(m.summary); return x ? `${whole ? "Offers " : ""}${x[1]} × ${x[2]} at $${x[3]}, paid in advance` : m.summary; }
  if (k === "correction") {      // the corrected offer is the one the message marks as the correction; the others it quotes stand
    const o = offers(m).find((c) => /correction/i.test(c.line ?? "")) ?? offers(m)[0], v = o && offerOf(o);
    const kept = offers(m).filter((c) => c !== o && c.ref.id === o?.ref.id).map(offerOf).filter((x) => x && x.qty !== v?.qty);
    return o && v ? `${whole ? "Corrects " : ""}${o.ref.id}${v.qty ? ` at ${v.qty}/yr` : ""}: ${v.price}${kept[0] ? ` (${kept[0].qty}/yr unchanged at ${kept[0].price})` : ""}` : m.summary;
  }
  if (k === "quote") {
    const parts = [...new Set(offers(m).map((o) => o.ref.id))];
    if (parts.length === 1) {
      const best = offers(m).map((o) => ({ o, v: offerOf(o) })).filter((x) => x.v).pop();
      if (whole) return `Quotes ${names(parts[0]) ?? parts[0]} (${parts[0]}) at ${best?.v?.price ?? "?"}${best?.v?.qty ? ` for ${best.v.qty}` : ""}`;
      if (compare) return compare;
      const exp = day(expires(m));
      return `${names(parts[0]) ?? parts[0]} (${parts[0]})${exp ? ` · valid to ${exp}` : ""}`;
    }
    const exp = expires(m);
    const soon = !!(exp && asOf) && Date.parse(exp!) - Date.parse(asOf!) <= 30 * 864e5;      // within 30 days of the data date (GET /api/health as_of)
    const alt = m.link === "part" && m.related_item && !m.related_item.endsWith(m.supplier?.id ?? "-") ? caseName(caseTitle?.(m.related_item)) : undefined;      // a quote for parts another supplier's case needs
    return `${whole ? "Quotes " : ""}${parts.length} parts${alt ? ` · alternate for the ${alt} case` : ""}${exp ? ` · ${soon ? "expires" : "valid to"} ${day(exp)}` : ""}`;
  }
  return m.summary;
}

type Word = { word: string; tone: "you" | "start" | "oth" | "held" | "none"; to: string | null };
/** The next step of the case the message moves: the word is Today's (caseStatus.statusOf on the same case); blue only when the message is from the case's own supplier and is not a quote. */
function statusOf(m: MessageSummary, me: string | null, cases: Cases | null): Word {
  const key = m.related_item;
  if (!key) return { word: "—", tone: "none", to: null };
  const to = `/items/${encodeURIComponent(key)}`;
  if (key.startsWith("trust:") || m.trust === "suspicious") return { word: "Held", tone: "held", to };
  const item = cases?.items.get(key);
  if (!item) return { word: "…", tone: "none", to };      // the case list is still loading: no word rather than a wrong one
  const own = (m.link === "message" || m.link === "supplier") && !QUOTES.includes(m.kind ?? "");
  const st = caseStatus(item, me, cases!.draftOwner, undefined, myDraftCases(cases!.actions, me), myChosenCases(cases!.actions, me));
  const tone: Word["tone"] = st.tone === "held" ? "held" : st.tone === "start" ? "start" : st.tone === "you" ? (own ? "you" : "oth") : "oth";
  const sk = item.stage?.key, anchor = sk === "drafted" ? "#act" : sk === "decision_ready" || sk === "worked" ? "#options" : "";      // where the case stands, not the word: a draft opens at the draft
  return { word: st.word, tone, to: `${to}${anchor}` };
}

function Robots({ ids }: { ids: string[] }) {
  const robots = useRobots();
  return <span className="ix-rb">{robots.map((r) => <i key={r.id} className={ids.includes(r.id) ? `on r-${(r.slot % 3) + 1}` : undefined} title={`${r.name} · ${ids.includes(r.id) ? "uses a part in this message" : "not affected"}`}><RobotIcon slot={r.slot} /></i>)}</span>;
}

/** A quote from a new supplier for one part: its landed price against the current supplier's, with the new duty. */
type Shorts = (id?: string | null) => string | undefined;
function useAltCompare(m: MessageSummary | null, shortById: Shorts): string | null {
  const part = m && m.kind === "quote" && m.trust === "new_sender" ? [...new Set(offers(m).map((o) => o.ref.id))] : [];
  const r = useResource(() => (part.length === 1 ? api.compare(part[0]).catch(() => null) : Promise.resolve(null)), [part.join()]);
  if (!r.data || !m) return null;
  const cols = (r.data as unknown as { columns: { label: string; is_current: boolean; landed: { offer?: { message?: { id: string }; supplier?: { id: string } | null }; total_known_usd?: { usd?: string | null } | null } }[] }).columns;
  const mine = cols.find((c) => c.landed.offer?.message?.id === m.ref.id), other = cols.find((c) => !c.is_current && c !== mine && c.landed.total_known_usd?.usd);
  if (!mine?.landed.total_known_usd?.usd || !other?.landed.total_known_usd?.usd) return null;
  const who = shortById(other.landed.offer?.supplier?.id) ?? other.label.split(" (")[0];
  return `$${Number(mine.landed.total_known_usd?.usd).toFixed(2)} vs ${who} $${Number(other.landed.total_known_usd?.usd).toFixed(2)} with duty`;
}

function Row({ m, me, sel, read, everyone, onSelect, shortById, cases }: { m: MessageSummary; me: string | null; sel: boolean; read: boolean; everyone: boolean; onSelect: () => void; shortById: Shorts; cases: Cases | null }) {
  const names = usePartNames(), nav = useNavigate(), cmp = useAltCompare(m, shortById);
  const st = statusOf(m, me, cases);
  const caseTitle = titleOf(cases);
  const asOf = useResource(api.health).data?.as_of ?? null;
  const f = fact(m, names, false, cmp, caseTitle, asOf);
  const kindWord = KIND[m.kind ?? ""] ?? "Message";
  return (
    <div className={`ix-row${sel ? " on" : ""}${read ? " read" : ""}`} role="option" aria-selected={sel} tabIndex={sel ? 0 : -1} onClick={onSelect}
      onKeyDown={(e) => { if (e.key === "Enter" && st.to) nav(st.to); }}>
      <span className="ix-l1"><b>{shortOf(m)}</b>{m.trust === "new_sender" && <span className="ix-new">new supplier</span>}
        <span className="ix-when">{everyone && m.owner && m.owner !== me ? `${first(m.owner)} · ` : ""}{day(m.date)}</span></span>
      <span className="ix-l2" title={`${kindWord} · ${f}`}><span className="k">{kindWord}</span> · <span className="f">{f}</span></span>
      <span className="ix-side"><Robots ids={(m.robots ?? []).map((r) => r.id)} />
        {st.to ? <Link to={st.to} className={`w k-${st.tone}`} onClick={(e) => e.stopPropagation()}>{st.word}</Link> : <span className="w k-none">—</span>}</span>
    </div>
  );
}

export function InboxPage() {
  const { id } = useParams();
  const msgId = id ? decodeURIComponent(id) : undefined;
  const nav = useNavigate();
  const { me } = useMe();
  const wide = useMedia("(min-width: 1200px)");
  const all = useResource(() => api.messages());
  const cases = useCases();
  const [tab, setTab] = useState<Tab>("all");
  const [scope, setScope] = useState<"mine" | "all">("mine");      // opens on Yours (FINAL 04); the kind tabs show on Everyone only
  const [q, setQ] = useState("");
  const [, bump] = useState(0);
  const read = readSet();
  const rows = (all.data ?? []).slice().sort((a, b) => b.date.localeCompare(a.date));
  const shortById: Shorts = (sid) => (sid ? rows.find((m) => m.supplier?.id === sid && m.supplier_short)?.supplier_short ?? undefined : undefined);
  const mineOnly = scope === "mine" && !!me;
  const base = mineOnly ? rows.filter((m) => (m.owner ?? "").split(" · ").includes(me)) : rows;
  const text = (m: MessageSummary) => [shortOf(m), m.from, m.from_email, m.summary, m.company, ...changesOf(m).map((c) => `${c.ref.id} ${c.label}`)].join(" ").toLowerCase();
  const shown = base.filter((m) => inTab(m, mineOnly ? "all" : tab) && (!q.trim() || text(m).includes(q.trim().toLowerCase())));
  const listRef = useRef<HTMLDivElement>(null), scrollRef = useRef<HTMLDivElement>(null);
  // A new scope, kind tab or search starts the list at the top (as Today).
  useEffect(() => { scrollRef.current?.scrollTo({ top: 0 }); }, [scope, tab, q]);
  const open = (m: MessageSummary) => { markRead(m.ref.id); bump((n) => n + 1); nav(`/inbox/${encodeURIComponent(m.ref.id)}`, { replace: !!msgId }); };
  // A wide screen never shows an empty detail: the first row opens, so what is selected is what is on top.
  useEffect(() => {
    if (!wide || msgId || !shown.length) return;
    const pick = shown[0];
    nav(`/inbox/${encodeURIComponent(pick.ref.id)}`, { replace: true });
  }, [wide, msgId, shown.length]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (msgId) { markRead(msgId); bump((n) => n + 1); } }, [msgId]);
  const keys = (e: React.KeyboardEvent) => {
    const at = shown.findIndex((m) => m.ref.id === msgId);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); const next = shown[Math.max(0, Math.min(shown.length - 1, at + (e.key === "ArrowDown" ? 1 : -1)))]; if (next) { open(next); setTimeout(() => listRef.current?.querySelector<HTMLElement>(".ix-row.on")?.focus(), 30); } }
  };
  const count = (t: Tab) => base.filter((m) => inTab(m, t)).length;
  const showList = wide || !msgId;
  return (
    <div className={`ix${showList ? "" : " ix-one"}`}>
      <div className="ix-head">
        <div className="ix-title"><h1>Inbox</h1>
          <div className="ix-seg" role="group" aria-label="Whose messages">
            {(["mine", "all"] as const).map((s) => <button key={s} type="button" aria-pressed={scope === s} className={scope === s ? "on" : undefined} disabled={s === "mine" && !me} onClick={() => setScope(s)}>
              {s === "mine" ? "Yours" : "Everyone"} {all.data && <em>{s === "mine" ? rows.filter((m) => (m.owner ?? "").split(" · ").includes(me ?? "")).length : rows.length}</em>}</button>)}
          </div>
        </div>
        {!mineOnly && <div className="ix-tabs" role="group" aria-label="Kinds">
          {TABS.map((t) => <button key={t.id} type="button" aria-pressed={tab === t.id} className={tab === t.id ? "on" : undefined} onClick={() => setTab(t.id)}>{t.label} {all.data && <em>{count(t.id)}</em>}</button>)}
        </div>}
      </div>
      <div className={`ix-grid${wide ? " wide" : ""}`}>
        {showList && (
          <div className="ix-list">
            <input className="ix-q" type="search" aria-label="Search the inbox" placeholder="Search sender, subject, part, PO line" value={q} onChange={(e) => setQ(e.target.value)} />
            <div className="ix-lscroll" ref={scrollRef}>
              <div ref={listRef} role="listbox" aria-label="Messages" onKeyDown={keys}>
                {!all.data ? [0, 1, 2, 3].map((n) => <div key={n} className="ix-sk" aria-hidden><i /><i /></div>)
                  : shown.length === 0 ? <p className="ix-empty">{q.trim() ? "No message matches." : "Nothing here."}</p>
                  : shown.map((m) => <Row key={m.ref.id} m={m} me={me} sel={m.ref.id === msgId} read={read.has(m.ref.id)} everyone={scope === "all"} onSelect={() => open(m)} shortById={shortById} cases={cases} />)}
              </div>
            </div>
          </div>
        )}
        {msgId && <div className="ix-dscroll" key={msgId}><Detail id={msgId} summary={rows.find((m) => m.ref.id === msgId) ?? null} me={me} shortById={shortById} cases={cases} onBack={wide ? undefined : () => nav("/inbox")} /></div>}
      </div>
    </div>
  );
}

function Detail({ id, summary, me, onBack, shortById, cases }: { id: string; summary: MessageSummary | null; me: string | null; onBack?: () => void; shortById: Shorts; cases: Cases | null }) {
  const r = useResource(() => api.thread(id), [id]);
  const asOf = useResource(api.health).data?.as_of ?? null;
  const names = usePartNames();
  const caseTitle = titleOf(cases);
  const cmp = useAltCompareSentence(summary, shortById);
  const company = useCompany();
  useAskContext(r.data ? { type: "message", id, label: "this message" } : null);
  useEffect(() => {
    if (!onBack) return;
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onBack(); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onBack]);
  if (r.error) return <div className="ix-d"><NotFound title="Message not found" line={`No message has the id ${id}.`} /></div>;
  if (!r.data || !summary) return <div className="ix-d"><span className="skel" style={{ width: 320 }} /></div>;
  const d = r.data as MessageDetail & { link?: string | null; imitates?: string | null };
  const m = summary;
  const held = m.trust === "suspicious";
  const st = statusOf(m, me, cases);
  const item = m.related_item ? cases?.items.get(m.related_item) : undefined;
  const kindWord = KIND[m.kind ?? ""] ?? "Message";
  const fromDomain = (m.from_email ?? "").split("@")[1] ?? "";
  const flags = new Set(m.trust_flags ?? []);
  const lookalike = held && d.imitates ? <>Sent from <Swapped a={fromDomain} b={d.imitates} /> <span className="m">· on file: {d.imitates}</span></> : null;
  const heldWhy: ReactNode[] = held ? [
    lookalike ?? (flags.has("sender_not_contact_on_file") ? <>Sent from {m.from_email}, not a contact on file</> : null),
    d.reply_to && flags.has("reply_to_freemail") ? <>Replies go to {d.reply_to}, a free mailbox</> : null,
    flags.has("bank_detail_change") ? (() => { const inv = [...new Set(d.body.match(/INV-[A-Z0-9-]+/g) ?? [])]; return <>{inv.length ? `Moves invoices ${inv.join(" and ")} to ${where(d.body)}` : "Asks to change where payments go"}</>; })() : null,
    flags.has("advance_payment_demand") ? <>Wants payment in advance</> : null,
    flags.has("instruction_in_message") ? <>Contains an instruction aimed at software or AI systems</> : null,
    flags.has("price_far_above_history") ? <>The price is far above what {company.short} has paid for the part</> : null,
    flags.has("supplier_on_hold") ? <>The supplier is on hold in the ERP</> : null,
    flags.has("urgency") ? <>Wants it confirmed today</> : null,
  ].filter(Boolean) : [];
  const due = day(deadline(m)), restart = changesOf(m).find((c) => c.label === "Partial restart")?.after?.split(" (")[0];
  const shared: ReactNode = m.kind === "force majeure"
    ? <>No ship date on any of the {new Set(lines(m).map((c) => c.ref.id)).size} lines until {shortOf(m)} sends revised dates{due ? <>, due <b>{due}</b></> : ""}.{restart ? ` Est. partial restart ${restart}.` : ""}</>
    : m.kind === "quote" && cmp ? cmp : null;
  const sender = d.summary.from ?? m.from;
  return (
    <article className="ix-d" aria-label="The message">
      {onBack && <button type="button" className="linkbtn ix-back" onClick={onBack}>‹ Inbox</button>}
      <div className="ix-meta">
        <span>{m.supplier ? <Link to={`/suppliers/${encodeURIComponent(m.supplier.id)}`} className="ix-co">{shortOf(m)}</Link> : <b className="ix-co">{shortOf(m)}</b>}
          {" · "}<span className="m">{sender !== shortOf(m) ? `${sender} ` : ""}&lt;{m.from_email}&gt;</span>
          {" · "}<span className={held && d.imitates ? "la" : "m"}>{m.trust === "on_file" ? "✓ contact on file" : held && d.imitates ? "look-alike" : held ? "not on file" : "new supplier"}</span></span>
        <span className="m kd">{kindWord} · {day(m.date)}</span>
      </div>
      <h2 className="ix-h">{fact(m, names, true, null, caseTitle, asOf)}</h2>
      {held && <p className="ix-held-line">Don't pay and don't reply. Nothing can be done from this message.</p>}
      {m.related_item && (
        <Link to={st.to ?? `/items/${encodeURIComponent(m.related_item)}`} className="ix-case">
          <Robots ids={(m.robots ?? []).map((x) => x.id)} />
          <span className="t">{m.link === "part" && <small>{QUOTES.includes(m.kind ?? "") ? "second source · " : "same part · "}</small>}{item?.title ?? m.related_item}</span>
          <span className={`w k-${st.tone}`}>{st.word}</span><ChevronRight size={16} strokeWidth={1.5} aria-hidden />
        </Link>
      )}
      {held ? (
        <section className="ix-why" aria-label="Why it is held"><div className="wc-cap">Why it is held</div>
          <ul>{heldWhy.map((w, n) => <li key={n}><X size={14} strokeWidth={2} aria-hidden />{w}</li>)}</ul></section>
      ) : (
        <WhatChanges changes={changesOf(m)} shared={shared} terms={m.kind === "quote" ? <QuoteTerms m={m} /> : null} caption="Changes" wasLabel="Confirmed" nowLabel="Dock date" qtyLabel="Open qty" />
      )}
      <details className="ix-raw"><summary>The message, as received</summary>
        <dl className="ix-hd"><dt>From</dt><dd>{sender} &lt;{m.from_email}&gt;</dd>{d.to && <><dt>To</dt><dd>{d.to}</dd></>}{d.reply_to && <><dt>Reply-to</dt><dd>{d.reply_to}</dd></>}<dt>Subject</dt><dd>{d.subject}</dd></dl>
        <MailBody body={d.body} highlights={d.highlights} entities={d.entities} suspect={held} />
      </details>
    </article>
  );
}

/** The look-alike domain with the swapped letters underlined: "acme-rnotor" against "acme-motor". */
function Swapped({ a, b }: { a: string; b: string }) {
  let s = 0; while (s < a.length && a[s] === b[s]) s++;
  let e = 0; while (e < a.length - s && a[a.length - 1 - e] === b[b.length - 1 - e]) e++;
  return <span>{a.slice(0, s)}<u className="swap">{a.slice(s, a.length - e)}</u>{a.slice(a.length - e)}</span>;
}

/** The whole comparison for a new supplier's one-part quote, as the shared sentence of What it changes. */
function useAltCompareSentence(m: MessageSummary | null, shortById: Shorts): ReactNode {
  const part = m && m.kind === "quote" && m.trust === "new_sender" ? [...new Set(offers(m).map((o) => o.ref.id))] : [];
  const r = useResource(() => (part.length === 1 ? api.compare(part[0]).catch(() => null) : Promise.resolve(null)), [part.join()]);
  return useMemo(() => {
    if (!r.data || !m) return null;
    const cols = (r.data as unknown as { columns: { label: string; is_current: boolean; landed: { offer?: { message?: { id: string }; supplier?: { id: string } | null }; total_known_usd?: { usd?: string | null } | null; total_if_china_usd?: { usd?: string | null } | null; unit_price_usd?: { usd?: string | null } | null; surcharge_usd?: { usd?: string | null } | null; tooling_per_unit_usd?: { usd?: string | null } | null } }[] }).columns;
    const mine = cols.find((c) => c.landed.offer?.message?.id === m.ref.id), other = cols.find((c) => !c.is_current && c !== mine && c.landed.total_known_usd?.usd);
    if (!mine?.landed.total_known_usd?.usd || !other?.landed.total_known_usd?.usd) return null;
    const origin = /\(([^)]+)\)$/.exec(mine.label)?.[1];
    const who = shortById(other.landed.offer?.supplier?.id) ?? other.label.split(" (")[0];
    const f = (x?: { usd?: string | null } | null) => (x?.usd ? `$${Number(x.usd).toFixed(2)}` : "");
    // what the bid tab's total adds up (quotes/service.py landed_cost): price, any surcharge, duty, any tooling; freight and insurance are not in the data
    const has = (k: "surcharge_usd" | "tooling_per_unit_usd") => [mine, other].some((c) => Number(c.landed[k]?.usd ?? 0) > 0);
    const covers = ["price", has("surcharge_usd") && "surcharge", "duty", has("tooling_per_unit_usd") && "tooling"].filter(Boolean).join(" + ");
    return <><b>{f(mine.landed.total_known_usd)} landed</b>{origin ? ` if its ${origin} origin holds` : ""}{mine.landed.total_if_china_usd ? ` (${f(mine.landed.total_if_china_usd)} if ruled China)` : ""}; {who} quoted {f(other.landed.unit_price_usd)}, <b>{f(other.landed.total_known_usd)}</b> with the new duty. Landed = {covers}; freight not included.</>;
  }, [r.data, m]); // eslint-disable-line react-hooks/exhaustive-deps
}

/** A quote's terms, one row each, read from the offer rows this message gave (/api/parts/{part}/offers): when, minimum, payment, origin, supplier.
 * A row shows only when every offer in the message says the same; nothing is written that the quote does not say. */
function QuoteTerms({ m }: { m: MessageSummary }) {
  const parts = [...new Set(offers(m).map((o) => o.ref.id))];
  const r = useResource(() => Promise.all(parts.map((p) => api.partOffers(p).catch(() => [] as OfferView[]))).then((xs) => xs.flat().filter((o) => o.message?.id === m.ref.id)), [m.ref.id]);
  const os = r.data ?? [];
  if (!os.length) return null;
  const one = <T,>(f: (o: OfferView) => T | null | undefined): T | null => { const v = f(os[0]); return v != null && v !== "" && os.every((o) => JSON.stringify(f(o)) === JSON.stringify(v)) ? v : null; };
  const lead = one((o) => o.lead_time ? `${o.lead_time.value ?? ""}|${o.lead_time.condition ?? ""}` : null);
  const [lv, lc] = (lead ?? "|").split("|"), lcMain = lc.replace(/\s*\(.*\)\s*$/, ""), lcNote = /\(([^)]*)\)/.exec(lc)?.[1];
  const moq = one((o) => o.moq), inc = one((o) => o.incoterm), pay = one((o) => o.payment_terms), origin = one((o) => o.origin_claim);
  const newSup = os.every((o) => !o.supplier);
  const cond = (one((o) => o.conditions) ?? "").split(/(?<=\.)\s+/).map((x) => x.replace(/\.$/, "").trim()).filter((x) => x && !/not in the supplier master/i.test(x));
  const rows: [string, ReactNode][] = [
    lv ? ["When", <><b>{[lv, lcMain].filter(Boolean).join(" ")}</b>{lcNote ? ` · ${lcNote}` : ""}</>] : null,
    moq != null || inc ? ["Minimum", <>{moq != null ? <b>MOQ {Number(moq).toLocaleString("en-US")}</b> : null}{moq != null && inc ? " · " : ""}{inc}</>] : null,
    pay ? ["Payment", pay] : null,
    origin ? ["Origin", origin] : null,
    newSup || cond.length ? ["Supplier", [newSup ? "new: not in the supplier master yet" : null, cond.join("; ")].filter(Boolean).join(" · ")] : null,
  ].filter(Boolean) as [string, ReactNode][];
  return rows.length ? <dl className="ix-terms">{rows.map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{v}</dd></Fragment>)}</dl> : null;
}
