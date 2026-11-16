// The PR-to-payment ladder (PLAN 6.2): fourteen rungs from Needed to Closed, each with its date, the row it is read from and whose move the wait
// before it was. A rung the data cannot show says so; nothing is inferred. Used on the PR and PO pages and on the case page.
import { Fragment, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { Ladder, Rung } from "../../api/types";
import { humanize, longDate } from "../../ui/format";
import { day, days, refTo } from "./shared";
import "./records.css";

const STATE_WORD: Record<Rung["state"], string> = { done: "done", now: "waiting", todo: "not yet", na: "not applicable", unknown: "not in the data" };

/** Where the ladder stands, in one sentence: whose move it is and since when, or that it closed, or why it stopped. */
export function ladderLine(l: Ladder): string {
  const closed = l.rungs.find((r) => r.key === "closed");
  if (closed?.state === "done") return `Closed${closed.date ? ` on ${day(closed.date)}` : ""}.`;
  if (l.waiting_on) {
    const now = l.rungs.find((r) => r.state === "now");
    return `With ${l.waiting_on}${l.days_waiting != null ? ` for ${days(l.days_waiting)}` : ""}${l.waiting_since ? ` (since ${day(l.waiting_since)})` : ""}${now ? ` · next: ${now.label}` : ""}.`;
  }
  const stop = l.rungs.find((r) => r.state === "na" && r.unknown && /^PR (deleted|closed)/.test(r.unknown));
  if (stop?.unknown) return `Stopped: ${humanize(stop.unknown.replace(/ on \?$/, " (date not on file)"))}.`;
  return "Nobody's move on file.";
}

/** The days each function has held this purchase so far, longest first: one bar each, the one holding it now marked. */
function Held({ held, now }: { held: Record<string, number>; now: string | null | undefined }) {
  const rows = Object.entries(held).filter(([, d]) => d > 0).sort((a, b) => b[1] - a[1]);
  if (!rows.length) return null;
  const max = rows[0][1];
  return (
    <div className="ldr-held" role="table" aria-label="Days held by each function">
      {rows.map(([w, d]) => (
        <div key={w} role="row" className={w === now ? "now" : undefined}>
          <span role="cell">{w}{w === now && <small> · now</small>}</span>
          <span role="cell" className="ldr-bar" aria-hidden><i style={{ width: `${Math.max(2, (100 * d) / max)}%` }} /></span>
          <span role="cell" className="end">{days(d)}</span>
        </div>
      ))}
    </div>
  );
}

/** Whose move the wait before a rung was, in words: "With Projects · 4 days", "With SCM now · 2 days so far". */
function whoText(r: Rung): string | null {
  if (!r.held_by) return null;
  if (r.state === "now") return `With ${r.held_by} now${r.days != null ? ` · ${days(r.days)} so far` : ""}`;
  return `With ${r.held_by}${r.days != null ? ` · ${days(r.days)}` : ""}`;
}

/** The source of a rung: the row it was read from, and the record it names when that record has a page. */
function Source({ r }: { r: Rung }) {
  if (!r.source && !r.ref) return null;
  const named = !!r.ref && (r.source ?? "").includes(r.ref.id);
  const to = r.ref ? refTo(r.ref) : null;
  const id = r.ref && !named ? (to ? <Link key="l" to={to}>{r.ref.id}</Link> : r.ref.id) : null;
  const parts: ReactNode[] = named && to ? [<Link key="s" to={to}>{r.source}</Link>] : [r.source, id].filter(Boolean);
  return <span className="ldr-src" title={r.source ?? undefined}>{parts.map((x, k) => <Fragment key={k}>{k > 0 && " · "}{x}</Fragment>)}</span>;
}

/** One PR line's or PO line's ladder: where it stands, the days held by each function, then every rung in order. */
export function LadderView({ ladder, title }: { ladder: Ladder; title?: string }) {
  return (
    <div className="ldr">
      {title && <p className="ldr-subject">{title}</p>}
      <p className={`ldr-line${ladder.waiting_on ? " wait" : ""}`}>{ladderLine(ladder)}</p>
      <Held held={ladder.held} now={ladder.waiting_on} />
      <ol className="ldr-rungs" aria-label="PR to payment">
        {ladder.rungs.map((r) => {
          const need = r.key === "needed";
          const who = whoText(r);
          const why = r.unknown ? humanize(r.unknown.replace(/ on \?$/, " (date not on file)")) : null;
          const note = r.state === "na" ? (why ? `Not applicable: ${why}` : "Not applicable to this line")
            : r.state === "unknown" ? `Not in the data${why ? `: ${why}` : ""}`
            : why;
          return (
            <li key={r.key} className={`ldr-r s-${r.state}${need ? " need" : ""}`} aria-current={r.state === "now" ? "step" : undefined}>
              <i className="ldr-mk" aria-hidden />
              <span className="ldr-l"><b>{need ? "Needed by" : r.label}</b><span className="sr">, {need ? (r.date ? "on file" : "not in the data") : STATE_WORD[r.state]}</span></span>
              <span className="ldr-d">{r.date ? longDate(r.date) : r.state === "now" ? "waiting" : "—"}</span>
              <span className="ldr-w">
                {who && <span className="ldr-who">{who}</span>}
                {r.why && <small>{humanize(r.why)}</small>}
                {note && <small className="ldr-note">{note}</small>}
              </span>
              <Source r={r} />
            </li>
          );
        })}
      </ol>
    </div>
  );
}
