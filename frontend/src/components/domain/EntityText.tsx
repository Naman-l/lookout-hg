import { Link } from "react-router-dom";
import { useState, type ReactNode } from "react";
import { CalendarDays, CircleCheck, Clock, Cog, Factory, FileText, ShieldAlert, User, type LucideIcon } from "lucide-react";
import { daysBetween } from "./DateDue";

export type EntityType = "part" | "supplier" | "supplier_lookalike" | "person" | "po_line" | "money" | "date" | "quantity" | "duration" | "supplier_claimed";
export interface Entity { start: number; end: number; type: EntityType | string; ref?: string | { id: string; label?: string | null } | null; label?: string | null; text?: string; trust?: string }

const ICON: Record<string, LucideIcon> = { part: Cog, supplier: Factory, supplier_lookalike: ShieldAlert, supplier_claimed: ShieldAlert, person: User, po_line: FileText, date: CalendarDays, duration: Clock };
const idOf = (e: Entity) => (typeof e.ref === "string" ? e.ref : e.ref?.id ?? null);
const href = (e: Entity): string | null => {
  const id = idOf(e);
  if (!id) return null;
  return e.type === "part" ? `/parts/${encodeURIComponent(id)}` : e.type === "supplier" ? `/suppliers/${encodeURIComponent(id)}` : e.type === "po_line" ? `/orders?q=${encodeURIComponent(id)}` : null;
};

/** Keep the spans that are valid (inside the text, and matching `text` when the span carries it) and do not overlap: sorted by start, an earlier or longer span wins, adjacent spans both stay. */
export function cleanEntities(text: string, entities: Entity[] = []): Entity[] {
  const ok = entities.filter((e) => Number.isInteger(e.start) && Number.isInteger(e.end) && e.start >= 0 && e.end > e.start && e.end <= text.length && (e.text === undefined || text.slice(e.start, e.end) === e.text))
    .sort((a, b) => a.start - b.start || b.end - b.start - (a.end - a.start));
  const out: Entity[] = [];
  let at = 0;
  for (const e of ok) if (e.start >= at) { out.push(e); at = e.end; }
  return out;
}

/** Inside a held or flagged message a name is only a claim: a supplier span never becomes a supplier chip (no link, no "on file" tick). It shows as the unverified claim it is. */
export function guardSuspect(entities: Entity[] = []): Entity[] {
  return entities.map((e) => (e.type === "supplier" ? { ...e, type: "supplier_claimed", ref: null, trust: undefined } : e));
}

/** One marker per kind of thing, the same everywhere (UI-STANDARD §9): a reader learns them once and skims by them. */
export const MARKERS: { type: EntityType; name: string; marker: string }[] = [
  { type: "money", name: "Money", marker: "bold, tabular figures" },
  { type: "quantity", name: "Quantity", marker: "tabular figures, muted unit" },
  { type: "date", name: "Date", marker: "calendar glyph; amber within 7 days, red when past" },
  { type: "duration", name: "Duration", marker: "clock glyph, outlined" },
  { type: "person", name: "Person", marker: "avatar dot and first name" },
  { type: "supplier", name: "Supplier", marker: "factory glyph, trust tick; a look-alike is red with a warning" },
  { type: "part", name: "Part", marker: "part glyph; its name on hover" },
  { type: "po_line", name: "PO line", marker: "muted monospace" },
];
const initial = (s: string) => s.trim().split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();

/** One identified thing inside running text, marked by its kind and clickable to its record where it has one. */
export function InlineEntity({ e, children, asOf }: { e: Entity; children: ReactNode; asOf?: string }) {
  const raw = typeof children === "string" ? children : "";
  if (e.type === "money") return <b className="dm-fig" data-type="money">{children}</b>;
  if (e.type === "quantity") {
    const m = /^([+\-]?[\d.,]+%?)\s*(.*)$/.exec(raw);
    return <span className="dm-fig dm-qty" data-type="quantity">{m ? <>{m[1]}{m[2] && <span className="dm-unit"> {m[2]}</span>}</> : children}</span>;
  }
  if (e.type === "po_line") {
    const id = idOf(e);
    const cls = "dm-po-text";
    return id ? <Link className={cls} to={href(e)!} title={id} data-type="po_line">{children}</Link> : <span className={cls} data-type="po_line">{children}</span>;
  }
  if (e.type === "person") return <span className="dm-inline-person" data-type="person"><i className="dm-dot" aria-hidden>{initial(raw || e.label || "?")}</i>{children}</span>;
  const iso = [e.ref, e.label].map((x) => (typeof x === "string" ? x : x?.id)).find((x) => x && /^\d{4}-\d{2}-\d{2}$/.test(x));
  const days = e.type === "date" && iso && asOf ? daysBetween(asOf, iso) : null;
  const tone = days == null ? undefined : days < 0 ? "red" : days <= 7 ? "amber" : undefined;
  const bad = e.type === "supplier_lookalike" || e.type === "supplier_claimed";
  const Icon = ICON[e.type] ?? FileText;
  const to = href(e);
  const id = idOf(e);
  const shown = children; // the words as written: a quoted table keeps its columns; the part's name is the hover
  const tip = e.type === "supplier_claimed" ? `Claimed: ${e.label ?? raw} (unverified)` : bad ? `Looks like ${e.label ?? "a supplier"} but is not on file` : days != null ? (days < 0 ? `${-days} days past` : days === 0 ? "On the data date" : `In ${days} days`) : e.label ?? (e.type === "part" ? id ?? undefined : undefined);
  const ok = e.type === "supplier" && e.trust === "on_file";
  const inner = <><Icon size={12} strokeWidth={1.75} aria-hidden /><span>{shown}</span>{ok && <><CircleCheck size={12} strokeWidth={2} className="dm-tick" aria-hidden /><span className="dm-sr"> on file</span></>}{bad && <span className="dm-sr"> (warning: {e.type === "supplier_claimed" ? "a claimed name, unverified" : "look-alike, not the supplier on file"})</span>}</>;
  const cls = `dm-inline${to ? " link" : ""}${e.type === "duration" ? " quiet" : ""}`;
  return to ? <Link className={cls} to={to} title={tip}>{inner}</Link> : <span className={cls} data-tone={bad ? "red" : tone} data-type={e.type} title={tip}>{inner}</span>;
}

/** Text with its identified parts, suppliers, people, PO lines, money and dates drawn as chips. Without entities it is the plain text. */
export function EntityText({ text, entities, asOf, suspect }: { text: string; entities?: Entity[]; asOf?: string; suspect?: boolean }) {
  const spans = cleanEntities(text, suspect ? guardSuspect(entities) : entities);
  if (spans.length === 0) return <>{text}</>;
  const parts: ReactNode[] = [];
  let at = 0;
  spans.forEach((e, n) => {
    if (e.start > at) parts.push(text.slice(at, e.start));
    parts.push(<InlineEntity key={n} e={e} asOf={asOf}>{text.slice(e.start, e.end)}</InlineEntity>);
    at = e.end;
  });
  if (at < text.length) parts.push(text.slice(at));
  return <>{parts}</>;
}

/** Sentence ranges of a text: one idea per line. A sentence ends at . ! or ? followed by a space and a capital, digit or quote. */
export function sentenceRanges(text: string): [number, number][] {
  const out: [number, number][] = [];
  let from = 0;
  const re = /[.!?](?=\s+["'“(]?[A-Z0-9])/g;
  for (let m = re.exec(text); m; m = re.exec(text)) { out.push([from, m.index + 1]); from = m.index + 1 + (text.slice(m.index + 1).match(/^\s*/)?.[0].length ?? 0); }
  if (from < text.length) out.push([from, text.length]);
  return out.filter(([a, b]) => b > a);
}

/** Running text as lines, one sentence each, the first `limit` shown and the rest behind "Read in full". Entities keep their place inside their sentence. */
export function EntityLines({ text, entities, limit = 3, asOf, suspect }: { text: string; entities?: Entity[]; limit?: number; asOf?: string; suspect?: boolean }) {
  const [all, setAll] = useState(false);
  const spans = cleanEntities(text, suspect ? guardSuspect(entities) : entities);
  const ranges = sentenceRanges(text);
  const shown = all ? ranges : ranges.slice(0, limit);
  return (
    <div className="dm-lines">
      {shown.map(([a, b]) => (
        <p key={a}><EntityText asOf={asOf} text={text.slice(a, b)} entities={spans.filter((e) => e.start >= a && e.end <= b).map((e) => ({ ...e, start: e.start - a, end: e.end - a }))} /></p>
      ))}
      {ranges.length > limit && <button type="button" className="dm-more" aria-expanded={all} onClick={() => setAll(!all)}>{all ? "Show less" : "Read in full"}</button>}
    </div>
  );
}

/** An answer's points as labelled rows: the label is the question it answers, the text the answer with its entities. */
export function Points({ points, asOf }: { points: { label: string; text: string; entities?: Entity[] }[]; asOf?: string }) {
  return (
    <dl className="dm-points">
      {points.map((p) => <div key={p.label}><dt>{p.label}</dt><dd><EntityText text={p.text} entities={p.entities} asOf={asOf} /></dd></div>)}
    </dl>
  );
}
