import type { MessageDetail, OfferView } from "../../api/types";
import { humanize, shortDate } from "../../ui/format";

/** What an open message changes, sorted into the shapes a buyer reads: PO lines (was, now), quoted offers (exact price), and plain facts. */
export interface LineRow { id: string; partId: string | null; was: string | null; now: string | null }
/** A quoted price as the quote's own record states it: the amount is a decimal string straight from the API, never re-parsed from a label. */
export interface OfferRow { partId: string; amount: string; currency: string; basis: "each" | "per_1000"; unitUsd: string | null; breakQty: number | null; validTo: string | null; site: string | null; availableFrom: string | null; conditions: string | null }
export interface Fact { label: string; value: string }
export interface MessageView { headline: string; lines: LineRow[]; offerParts: string[]; facts: Fact[]; blocked: boolean }

const ISO = /^\d{4}-\d{2}-\d{2}$/;
const day = (v?: string | null) => (!v ? null : ISO.test(v) ? shortDate(v) : humanize(v));
const upper = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);
const UNKNOWN = /^unknown\s*\((.*)\)$/i;
const IS_OFFER = /^Offer\s/;

/** The one line a message is about. A held message's summary also lists why it was held; the reasons are shown as badges, so only its first sentence is the headline. */
export function headline(summary: string, kind?: string | null): string {
  let first = summary.split(/\.\s+Blocked:/)[0].replace(/\.$/, "");
  if (kind && first.toLowerCase().startsWith(`${kind.toLowerCase()}:`)) first = upper(first.slice(kind.length + 1).trim());
  first = first.replace(/^(Quote for \d+ parts?):.*$/, "$1"); // the part list is the table below
  return humanize(first).replace(/\bUSD ([\d,]+(?:\.\d+)?)/g, "$$$1").replace(/\bEUR ([\d,]+(?:\.\d+)?)/g, "€$1");
}

export function messageView(t: MessageDetail): MessageView {
  const lines: LineRow[] = [], offerParts: string[] = [], facts: Fact[] = [];
  let blocked = false;
  for (const c of t.changes) {
    const part = /\((HR-\d{5})\)/.exec(c.label)?.[1] ?? null;
    const offer = c.ref.type === "part" && IS_OFFER.test(c.label);
    if (/\(blocked\)/i.test(c.label)) blocked = true;
    else if (c.ref.type === "po_line") lines.push({ id: c.ref.id, partId: part, was: day(c.before), now: day(c.after) });
    else if (offer) { if (!offerParts.includes(c.ref.id)) offerParts.push(c.ref.id); }
    else facts.push({ label: humanize(c.label), value: c.before && c.after ? `${day(c.before)} → ${day(c.after)}` : day(c.after ?? c.before) ?? "" });
  }
  // Lines whose new date is "unknown (revised dates due Oct 10)": say "Unknown" in the table and the shared reason once, as a fact.
  const notes = new Set<string>();
  for (const l of lines) {
    const m = l.now ? UNKNOWN.exec(l.now) : null;
    if (m) { notes.add(m[1]); l.now = "Unknown"; }
  }
  for (const n of notes) {
    const rev = /^revised dates (.*)$/i.exec(n);
    facts.unshift(rev ? { label: "Revised dates", value: rev[1] } : { label: "New dates", value: upper(n) });
  }
  // One date, one chip: "Revised dates due Oct 10" and "Deadline Oct 10" are the same date, so the deadline chip takes the wording.
  const rev = facts.findIndex((f) => f.label === "Revised dates");
  const same = rev >= 0 ? facts.findIndex((f, i) => i !== rev && facts[rev].value.endsWith(f.value)) : -1;
  if (same >= 0) { facts[same].label = "Revised dates due"; facts.splice(rev, 1); }
  return { headline: headline(t.summary.summary, t.summary.kind), lines, offerParts, facts, blocked };
}

const site = (o: OfferView) => (o.origin_claim ? o.origin_claim.split(";")[0].trim() : o.origin ?? null);

/** The offers a message made, from the quote records (which hold the price exactly as quoted), in the order of the quote's lines. */
export function offerRows(offers: OfferView[], messageId: string): OfferRow[] {
  return offers.filter((o) => o.message.id === messageId).map((o) => ({
    partId: o.part.id, amount: o.price.amount, currency: o.price.currency, basis: o.price_basis ?? "each", unitUsd: o.unit_price_usd?.amount ?? null, breakQty: o.qty_break ?? null, validTo: o.valid_until ?? null,
    site: site(o), availableFrom: o.available_from ?? null, conditions: o.conditions ?? null,
  }));
}
