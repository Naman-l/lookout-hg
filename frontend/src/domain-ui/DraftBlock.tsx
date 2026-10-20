import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type OrderLine } from "../api/client";
import type { Action } from "../api/types";
import { useCompany } from "../api/useCompany";
import "./draft-block.css";

/** The draft block (FINAL 03, SYNC §4): one component for Approvals, the case's action card and the Inbox reply.
 * The email is shown exactly as it will be sent; the marks are presentation only (the text and its payload hash never change).
 * Each mark is checked in code against the records: a PO line against GET /orders/{line}, a quantity or a date on a PO-line row
 * against that line's open quantity or promise. Nothing here is written by a model. */

type Span = { start: number; end: number; type: string; ref?: string | null; label?: string | null; text?: string | null };
export type Check = { lines: Record<string, OrderLine | null>; bad: { at: number; why: string }[]; poCount: number; loading: boolean };

/** "…is not an acceptance of it and does not waive any of …'s rights…": the sentence that keeps the company's rights, bold in the email. */
export const RIGHTS = /(is not an acceptance of it and does not waive any of [^.]*rights[^.]*|reserves its rights under the contract|does not waive[^.]*rights[^.]*|keeps all (?:of )?its rights[^.]*)/;
/** A phrase that would commit the company: bold red in the email, and it replaces "Commits … to nothing". */
export const COMMITS = /\b(we (accept|agree|will pay|commit|confirm the new)|we will take)\b[^.]*/i;
/** What the letter asks for: each numbered ask, plus each "please …" in the prose around them (a second ask for another case rides in a paragraph), never "please reply" or a list's lead-in. */
export const asksOf = (body: string) => body.split("\n").reduce((n, l) => n + (/^\d+\. /.test(l) ? 1 : /:\s*$/.test(l) ? 0 : (l.match(/\bplease (?!reply\b)/gi) || []).length), 0);
const MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December";
/** The reply date the letter itself asks for ("by the 10 October date you gave", "by 3 October"), as a buyer says it ("Oct 10"); null when the letter gives none. */
export function replyBy(body: string): string | null {
  const m = new RegExp(`\\bby (?:the )?(\\d{1,2}) (${MONTHS})\\b|\\bby (${MONTHS}) (\\d{1,2})\\b`).exec(body);
  if (!m) return null;
  const [d, mo] = m[1] ? [m[1], m[2]] : [m[4], m[3]];
  return `${mo.slice(0, 3)} ${Number(d)}`;
}

const PO_ROW = /^(?:- )?(HPO-\d{2}-\d{5}\/\d{2}|PO-\d{5}\/\d+)/;
const day = (iso?: string | null) => (iso ? new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" }) : "");
const dollars = (v?: string | null) => { if (!v) return ""; const x = Number(v); return x >= 1e6 ? `$${(x / 1e6).toFixed(2)}M` : x >= 1e4 ? `$${Math.round(x / 1e3)}K` : x >= 1e3 ? `$${(x / 1e3).toFixed(1)}K` : `$${Math.round(x)}`; };
const qtyNum = (t: string) => Number(t.replace(/[^\d.]/g, ""));

/** The PO line whose row a position sits on: a body line that starts with a PO line id owns its quantity and date. */
function rowLine(body: string, at: number): string | null {
  const from = body.lastIndexOf("\n", at - 1) + 1;
  return PO_ROW.exec(body.slice(from, body.indexOf("\n", from) < 0 ? undefined : body.indexOf("\n", from)))?.[1] ?? null;
}

/** Read every PO line the email names, once, and work out which marks do not match the records. */
export function useDraftCheck(a: Action | null): Check {
  const spans = (a?.body_entities ?? []) as Span[];
  const ids = useMemo(() => [...new Set(spans.filter((s) => s.type === "po_line" && s.ref).map((s) => s.ref as string))], [a?.action_id, a?.payload_hash]); // eslint-disable-line react-hooks/exhaustive-deps
  const [lines, setLines] = useState<Record<string, OrderLine | null>>({});
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let live = true;
    setLoading(true);
    Promise.all(ids.map((id) => api.order(id).then((r) => [id, r] as const, () => [id, null] as const))).then((rows) => { if (live) { setLines(Object.fromEntries(rows)); setLoading(false); } });
    return () => { live = false; };
  }, [ids.join("|")]); // eslint-disable-line react-hooks/exhaustive-deps
  const bad = loading ? [] : spans.flatMap((s) => { const why = verdict(a?.body ?? "", s, lines, undefined, a?.target?.id).bad; return why ? [{ at: s.start, why }] : []; });
  return { lines, bad, poCount: ids.length, loading };
}

/** What one mark says and whether it matches the record. */
function verdict(body: string, s: Span, lines: Record<string, OrderLine | null>, partLabel: (id: string) => string | undefined = () => undefined, supplierId?: string): { card: ReactNode; bad?: string } {
  const text = s.text ?? body.slice(s.start, s.end);
  const po = rowLine(body, s.start);
  const rec = po ? lines[po] : undefined;
  if (s.type === "po_line") {
    const r = lines[s.ref ?? text];
    // a partly received line is still open, as the server counts it
    if (!r || !(r.status === "OPEN" || (r.status === "PARTIAL" && qtyNum(r.qty_open.value) > 0))) return { card: <>{text} · not an open PO line in the records</>, bad: `${text} is not an open PO line` };
    return { card: <>{text} · {partLabel(r.part.id) ?? r.part.id}<br />{qtyNum(r.qty_open.value).toLocaleString("en-US")} EA open · promised {day(r.promise)}{r.unit_price?.usd ? ` · ${dollars(String(qtyNum(r.qty_open.value) * Number(r.unit_price.usd)))} open` : ""}{r.days_past_due ? ` · ${r.days_past_due} d past due` : ""}<br />✓ open{r.buyer ? ` · ${r.buyer.split(" ")[0]}’s line` : ""}</> };
  }
  if (s.type === "quantity" && rec) {
    const open = qtyNum(rec.qty_open.value);
    return qtyNum(text) === open ? { card: <>{text} · ✓ the open qty of {po}</> } : { card: <>{text} · the open qty of {po} is {open.toLocaleString("en-US")} EA</>, bad: `${po}: the email says ${text}, the record ${open.toLocaleString("en-US")} EA open` };
  }
  if (s.type === "date") {
    const before = body.slice(Math.max(0, s.start - 10), s.start);
    const verb = /(confirmed|promised) $/.exec(before)?.[1];
    if (rec && verb) {      // the letter's own word for the date ("confirmed 26 August") is the record's promise date
      return s.ref === rec.promise ? { card: <>{text} · ✓ the {verb} date of {po}</> } : { card: <>{text} · {po} is {verb} {day(rec.promise)}</>, bad: `${po}: the email says ${text}, the record ${day(rec.promise)}` };
    }
    return { card: <>{text} · a date from the notice or the data</> };
  }
  if (s.type === "person") return (s.ref ?? "").startsWith(`${supplierId}/`) ? { card: <>{s.label ?? text} · ✓ the contact on file</> } : { card: <>{s.label ?? text} · sender, the draft’s owner</> };
  if (s.type === "part") return { card: <>{s.label ?? text}</> };
  return { card: <>{s.label ?? text}</> };
}

/** Bold ranges: the rights sentence (bold) and any commitment (bold red). */
function emphasis(body: string): { start: number; end: number; cls: string }[] {
  const out: { start: number; end: number; cls: string }[] = [];
  for (const [re, cls] of [[new RegExp(RIGHTS.source, "g"), "rights"], [new RegExp(COMMITS.source, "gi"), "commit"]] as const) {
    let m: RegExpExecArray | null;
    while ((m = re.exec(body))) { out.push({ start: m.index, end: m.index + m[0].length, cls }); if (!m[0].length) re.lastIndex++; }
  }
  return out;
}

function Mark({ s, body, lines, supplierId, partLabel, upto }: { s: Span; body: string; lines: Record<string, OrderLine | null>; supplierId?: string; partLabel: (id: string) => string | undefined; upto?: number }) {
  const nav = useNavigate();
  const v = verdict(body, s, lines, partLabel, supplierId);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return;
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };      // the card closes on Esc even while the pointer rests on it (WCAG 1.4.13)
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [open]);
  const text = body.slice(s.start, upto ?? s.end);      // a table cell may show less of the mark ("355" for "355 EA"); the check reads the whole mark
  const go = s.type === "po_line" ? `/orders?q=${encodeURIComponent(s.ref ?? text)}` : s.type === "part" && s.ref ? `/parts/${encodeURIComponent(s.ref)}` : s.type === "person" && supplierId ? `/suppliers/${encodeURIComponent(supplierId)}` : null;
  return (
    <span className={`em${s.type === "po_line" ? " em-po" : ""}${v.bad ? " bad" : ""}${go ? " go" : ""}${open ? " open" : ""}`} tabIndex={0} role={go ? "link" : undefined}
      onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
      onClick={() => go && nav(go)} onKeyDown={(e) => { if (e.key === "Enter" && go) nav(go); }}>
      {text}<span className="ec" role="tooltip">{v.card}</span>
    </span>
  );
}

/** The body's marks and bold phrases, drawable over any range of the text (a paragraph, a list item, a table cell): cut at every boundary so nothing overlaps. */
function useMarks(a: Action, lines: Record<string, OrderLine | null>) {
  const body = a.body ?? "";
  const spans = ((a.body_entities ?? []) as Span[]).map((s) => {      // a date or a quantity mark stops before the sentence's punctuation
    if (s.type !== "date" && s.type !== "quantity") return s;
    let end = s.end;
    while (end > s.start && /[.,;:)]/.test(body[end - 1])) end--;
    return { ...s, end };
  }).filter((s) => s.end > s.start).sort((x, y) => x.start - y.start);
  const bold = emphasis(body);
  const partLabel = (id: string) => spans.find((x) => x.type === "part" && x.ref === id)?.label ?? undefined;      // the part as its own mark names it (name, id, robot)
  const all = [...new Set([0, body.length, ...spans.flatMap((s) => [s.start, s.end]), ...bold.flatMap((b) => [b.start, b.end])])].sort((x, y) => x - y);
  return (start: number, end: number): ReactNode[] => {
    const cuts = [start, ...all.filter((c) => c > start && c < end), end];
    const out: ReactNode[] = [];
    for (let n = 0; n < cuts.length - 1; n++) {
      const [from, to] = [cuts[n], cuts[n + 1]];
      const span = spans.find((s) => s.start <= from && to <= s.end);
      if (span && span.start !== from && from !== start) continue;      // the mark is drawn once, from its own start
      const piece = span && span.start === from ? <Mark key={from} s={span} body={body} lines={lines} supplierId={a.target?.id} partLabel={partLabel} upto={span.end > end ? end : undefined} /> : body.slice(from, to);
      const b = bold.find((x) => x.start <= from && (span ? span.end : to) <= x.end);
      out.push(b ? <b key={`b${from}`} className={b.cls === "commit" ? "commit" : undefined}>{piece}</b> : <span key={`t${from}`}>{piece}</span>);
    }
    return out;
  };
}

type Block = { kind: "p" | "ol" | "table"; start: number; end: number; lines: { start: number; end: number }[] };
/** The letter cut into blocks on blank lines: a numbered list, a run of PO-line rows (a table, A1 §3), or a paragraph. Offsets stay in the sent text. */
export function blocksOf(body: string): Block[] {
  const out: Block[] = [];
  const re = /\n\s*\n/g;
  let at = 0, m: RegExpExecArray | null;
  const push = (start: number, end: number) => {
    if (end <= start) return;
    const lines: { start: number; end: number }[] = [];
    let p = start;
    for (const l of body.slice(start, end).split("\n")) { lines.push({ start: p, end: p + l.length }); p += l.length + 1; }
    const rows = lines.filter((l) => PO_ROW.test(body.slice(l.start, l.end)));
    if (rows.length >= 2 && rows.length >= lines.length - 1) {      // an optional lead-in line stays a paragraph above the table
      const lead = lines.filter((l) => !PO_ROW.test(body.slice(l.start, l.end)));
      if (lead.length) out.push({ kind: "p", start: lead[0].start, end: lead[lead.length - 1].end, lines: lead });
      out.push({ kind: "table", start: rows[0].start, end: rows[rows.length - 1].end, lines: rows });
    } else if (lines.every((l, n) => /^\d+\. /.test(body.slice(l.start, l.end)) || (n > 0 && !body.slice(l.start, l.end).trim()))) out.push({ kind: "ol", start, end, lines });
    else if (lines.some((l) => /^\d+\. /.test(body.slice(l.start, l.end)))) {      // a lead-in sentence, then the numbered asks
      const k = lines.findIndex((l) => /^\d+\. /.test(body.slice(l.start, l.end)));
      out.push({ kind: "p", start: lines[0].start, end: lines[k - 1].end, lines: lines.slice(0, k) });
      out.push({ kind: "ol", start: lines[k].start, end, lines: lines.slice(k) });
    } else out.push({ kind: "p", start, end, lines });
  };
  while ((m = re.exec(body))) { push(at, m.index); at = m.index + m[0].length; }
  push(at, body.length);
  return out;
}

/** One PO-line row cut into its cells (separated by " · " or ", "), with each date cell named by its word ("confirmed 26 August" → Confirmed). */
export function cellsOf(body: string, l: { start: number; end: number }) {
  const text = body.slice(l.start, l.end).replace(/[.;]\s*$/, "");
  const cells: { start: number; end: number; head: string; past?: boolean }[] = [];
  // Read by the row's structure (UX R1-1): the PO line, then the part up to its id's closing parenthesis ("<name>, <spec>, <spec>
  // (<part id>)" is one cell, whatever commas its name has), then the rest on " · " or ", " ("1,320 EA" stays one cell).
  const pid = /\([A-Z]{2,}-\d{4,}\)/.exec(text);
  const partEnd = pid ? l.start + pid.index + pid[0].length : -1;
  const pieces: { start: number; end: number }[] = [];
  const sep = /\s+·\s+|,\s+/g;
  let last = text.startsWith("- ") ? 2 : 0, m: RegExpExecArray | null;
  while ((m = sep.exec(text))) { if (m.index > last) pieces.push({ start: l.start + last, end: l.start + m.index }); last = m.index + m[0].length; }
  if (text.length > last) pieces.push({ start: l.start + last, end: l.start + text.length });
  for (const { start, end: pieceEnd } of pieces) {
    const t = body.slice(start, pieceEnd);
    let end = pieceEnd;
    if (cells.length && /^(now )?past due$/i.test(t)) { cells[cells.length - 1].past = true; continue; }      // a "past due" cell is the Past due column
    if (cells.length >= 1 && start < partEnd) {      // inside the part's name: one Part cell up to the id's closing parenthesis
      if (cells.length === 1) cells.push({ start, end: partEnd, head: "Part" });
      continue;
    }
    let head = cells.length === 0 ? "PO line" : /^HR-\d{5}\b/.test(t) || /\([A-Z]{2,}-\d{4,}\)$/.test(t) ? "Part" : /^\d[\d,.]*\s*(EA|pcs|pieces)\b/i.test(t) ? "Qty" : "";
    const w = /^(confirmed|promised|now|revised|ship(?:s|ped)?|due)\s+/i.exec(t);
    let past = false;
    if (/\(past due\)$/i.test(t)) { past = true; end -= "(past due)".length; while (body[end - 1] === " ") end--; }
    if (w) head = w[1][0].toUpperCase() + w[1].slice(1).toLowerCase();
    const none = /^no (confirmed|promised|new) date\b/i.exec(t);      // "no promised date yet" sits in its column, said in full; "no new date" under Now
    if (none) head = none[1].toLowerCase() === "new" ? "Now" : none[1][0].toUpperCase() + none[1].slice(1).toLowerCase();
    cells.push({ start: w ? start + w[0].length : start, end, head, past });
  }
  return cells;
}

function Letter({ a, lines }: { a: Action; lines: Record<string, OrderLine | null> }) {
  const body = a.body ?? "";
  const draw = useMarks(a, lines);
  return (
    <>
      {blocksOf(body).map((b) => {
        if (b.kind === "ol") return <ol key={b.start} className="db-ol">{b.lines.filter((l) => body.slice(l.start, l.end).trim()).map((l) => { const n = /^\d+\. /.exec(body.slice(l.start, l.end))?.[0].length ?? 0; return <li key={l.start}>{draw(l.start + n, l.end)}</li>; })}</ol>;
        if (b.kind === "table") {
          const rows = b.lines.map((l) => cellsOf(body, l).map((c, n) => ({ ...c, key: c.head || `#${n}` })));
          const keys: string[] = [];
          for (const r of rows) for (const c of r) if (!keys.includes(c.key)) keys.push(c.key);
          const past = rows.some((r) => r.some((c) => c.past));
          return (
            <table key={b.start} className="db-tb"><thead><tr>{keys.map((h) => <th key={h} className={h === "Qty" ? "n" : undefined}>{h.startsWith("#") ? "" : h}</th>)}{past && <th>Past due</th>}</tr></thead>
              <tbody>{rows.map((r, k) => <tr key={k}>{keys.map((h) => { const c = r.find((x) => x.key === h); return <td key={h} className={h === "Qty" ? "n" : undefined}>{c ? draw(c.start, h === "Qty" ? c.end - (/\s*(EA|pcs|pieces)$/i.exec(body.slice(c.start, c.end))?.[0].length ?? 0) : c.end) : ""}</td>; })}{past && <td>{r.some((c) => c.past) ? "Past due" : ""}</td>}</tr>)}</tbody></table>
          );
        }
        return <p key={b.start} className="db-p">{b.lines.map((l, n) => <span key={l.start}>{n > 0 && <br />}{draw(l.start, l.end)}</span>)}</p>;
      })}
    </>
  );
}

/** The letter (A1): a header block (From · To · Subject), the body as an email (paragraphs, the numbered asks, PO lines as a table, every cell a checked mark),
 * and "View as sent" for the exact text whose hash is approved. In edit mode the subject and body are plain fields (no marks). */
export function DraftDoc({ a, check, contact, editing, draft, onDraft }: {
  a: Action; check: Check; contact: string; supplier?: string; editing?: boolean; draft?: { subject: string; body: string }; onDraft?: (d: { subject: string; body: string }) => void;
}) {
  const company = useCompany();
  const [plain, setPlain] = useState(false);
  const owner = (a as Action & { owner?: string | null }).owner;
  const toggle = <button type="button" className="db-plain" onClick={() => setPlain(!plain)} aria-pressed={plain}>{plain ? "View as email" : "Plain text"}</button>;
  return (
    <div className={`db${editing ? " edit" : ""}`}>
      <div className="db-hd">
        {owner && <><span className="k">From</span><span>{owner} · {company.full}</span></>}
        <span className="k">To</span><span><span className="to">{contact}</span> <span className="m">&lt;{a.recipient}&gt;</span></span>
        <span className="k">Subject</span>
        {editing ? <input className="subj" aria-label="Subject" autoFocus value={draft?.subject ?? ""} onChange={(e) => onDraft?.({ subject: e.target.value, body: draft?.body ?? "" })} />
          : <span className="subj-row"><span className="subj">{a.subject}</span>{toggle}</span>}
      </div>
      {editing ? <textarea className="db-body" aria-label="Email text" value={draft?.body ?? ""} onChange={(e) => onDraft?.({ subject: draft?.subject ?? "", body: e.target.value })} rows={Math.max(12, (draft?.body ?? "").split("\n").length + 2)} />
        : plain ? <pre className="db-body db-pre">{a.body}</pre> : <div className="db-body db-v2"><Letter a={a} lines={check.lines} /></div>}
      {!editing && <div className="db-sent"><button type="button" className="db-plain" onClick={() => setPlain(!plain)}>{plain ? "View as email" : "View as sent (plain text)"}</button></div>}
    </div>
  );
}

/** The Reviewer's grade of the run that wrote a draft: which of its checks were not met, named (BUYER final review #3). */
function useRunGrade(runId?: string | null): { passed: number; total: number; failed: { name: string; reason: string }[] } | null {
  const [g, setG] = useState<{ passed: number; total: number; failed: { name: string; reason: string }[] } | null>(null);
  useEffect(() => {
    let live = true;
    if (!runId) { setG(null); return; }
    api.run(runId).then((r) => {
      const grade = (r.recommendation as { grade?: { failed_checks?: { name: string; reason: string }[] } } | null)?.grade;
      if (live) setG({ passed: Number(r.checks_passed ?? 0), total: Number(r.checks_total ?? 0), failed: grade?.failed_checks ?? [] });
    }, () => live && setG(null));
    return () => { live = false; };
  }, [runId]);
  return g;
}

/** Before you approve · Checked against the records · For · History. */
export function DraftReview({ a, check, onFile = true, contact, short, company, by, chase, item, sent, children }: {
  a: Action; check: Check; onFile?: boolean; contact: string; short: string; company: string; by: string; chase?: string; sent?: boolean; children?: ReactNode;
  item?: { key: string; title: string; usd?: string; lines?: number } | null;
}) {
  const body = a.body ?? "", asks = asksOf(body), commit = body.match(COMMITS)?.[0], keeps = RIGHTS.test(body), reply = replyBy(body);
  const owner = ((a as Action & { owner?: string | null }).owner ?? "").split(" ")[0];
  const failed = a.unverified_checks ?? [];
  const run = useRunGrade(a.run_id);
  return (
    <>
      <div className="rv"><div className="rv-l">{sent ? "What was approved" : "Before you approve"}</div>
        <div className="rv-g">
          <span>To</span><span>{contact} ({short}){onFile ? " · ✓ contact on file" : <span className="no"> · not the contact on file</span>}</span>
          <span>Commits</span><span>{commit ? <b className="commit">{commit}</b> : `${company} to nothing (a request)`}{keeps ? " · keeps all rights" : ""}</span>
          {asks > 0 && <><span>Asks</span><span>{short} for {asks} thing{asks === 1 ? "" : "s"}{reply ? ` by ${reply}` : " · no reply date in the letter"}</span></>}
          <span>After</span><span>{chase ? `chase ${chase} · Today shows it · ` : ""}the reply returns to the case</span>
        </div>
      </div>
      <div className="rv"><div className="rv-l">Checked against the records</div>
        <div className="ok">
          {!check.loading && check.poCount > 0 && (check.bad.length
            ? <span className="no">{(() => { const n = new Set(check.bad.map((b) => b.why.split(":")[0])).size; return `${n} of ${check.poCount} PO lines ${n === 1 ? "doesn’t" : "don’t"} match`; })()}</span>
            : <>✓ {check.poCount} PO line{check.poCount === 1 ? "" : "s"} checked against open orders: open{owner ? `, ${owner}’s` : ""}, quantities and promised dates match</>)}
          {!check.loading && check.poCount > 0 && <br />}{onFile ? <>✓ {contact} is the contact on file</> : <span className="no">{a.recipient} is not the contact on file</span>}
          {failed.length ? <><br /><span className="no">Lookout’s checks did not all pass: {failed.join(", ")}</span></> : a.edited_by ? <><br /><span className="ed">Edited by {a.edited_by.split(" ")[0]} · figures not re-checked</span></> : null}
          {run && run.failed.length > 0 && <><br /><span className="ed">The case run’s checks: {run.passed} of {run.total} met · not met: {run.failed.map((f) => f.name).join("; ")}</span></>}
        </div>
      </div>
      {item && <div className="rv"><div className="rv-l">Case</div><Link className="lnk" to={`/items/${encodeURIComponent(item.key)}`}>{item.title}</Link>
        <div className="facts">{children}{item.usd && <b>{dollars(item.usd)}</b>}{item.lines ? <span>open on {item.lines} lines</span> : null}{by && <span>act by {by}</span>}</div></div>}
      <div className="rv"><div className="rv-l">History</div><div className="ok">Drafted by Lookout{a.run_id && <> · <Link className="lnk" to={`/activity/${encodeURIComponent(a.run_id)}`}>How Lookout worked this out</Link></>}</div></div>
    </>
  );
}

/** The decision: Approve and send (green) · Edit · Reject (red); the confirm box when a check failed or a mark does not match. */
export function DraftDecision({ me, busy, needsConfirm, confirmed, onConfirm, onApprove, onEdit, onReject }: {
  me: string; busy?: boolean; needsConfirm: string | null; confirmed: boolean; onConfirm: (v: boolean) => void; onApprove: () => void; onEdit: () => void; onReject: () => void;
}) {
  return (
    <div className="dd">
      {needsConfirm && <label className="db-fail"><input type="checkbox" checked={confirmed} onChange={(e) => onConfirm(e.target.checked)} /> <span>{needsConfirm} I checked this myself.</span></label>}
      <button type="button" className="db-btn go wide" disabled={busy || (!!needsConfirm && !confirmed)} onClick={onApprove}>Approve and send</button>
      <div className="db-act"><button type="button" className="db-btn sm" onClick={onEdit}>Edit</button><button type="button" className="db-btn sm no" onClick={onReject}>Reject</button></div>
      <div className="db-cap">Simulated · sends on approval · as {me}</div>
    </div>
  );
}
