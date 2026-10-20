import { Disclose } from "../ds";
import { namedQuestions } from "./openQuestions";
import { useState } from "react";
import { Link } from "react-router-dom";
import type { ReactNode } from "react";
import type { Recommendation as Rec, RunDetail } from "../api/types";
import { humanize } from "../ui/format";
import { useNamed } from "../ui/useNamed";
import { clock } from "../api/freshness";

export { AgentMark } from "../ui/AgentMark";

/* Agent: what the agents produced, and the proof that came with it. */

/** The agent's answer: the finding, what it assumes, what would change it, and what only a person can answer. */
export function Recommendation({ rec, tiles, children }: { rec: Rec; tiles?: ReactNode; children?: ReactNode }) {
  return (
    <>
      <p className="ds-decision">{humanize(rec.finding)}</p>
      {tiles}
      {children}
    </>
  );
}
export function Assumptions({ rec }: { rec: Rec }) {
  return (
    <dl className="kv">
      <dt>Assumes</dt><dd>{rec.assumptions.join(" ")}</dd>
      <dt>Would change it</dt><dd>{rec.would_change.join(" · ")}</dd>
    </dl>
  );
}

type Fact = { tone: "ok" | "caution"; text: string; missed?: string[]; detail?: string };

/** What was checked, as facts the run itself reports. A claim is printed only when its field is there, and it is styled ok only when it is wholly true. */
export function checkFacts(run: RunDetail | null): Fact[] {
  const v = run?.verifier;
  const out: Fact[] = [];
  if (v) {
    const all = v.numbers_checked === v.numbers_from_tools;
    // an answer with no numbers has nothing to check: that is not a pass, so no line at all
    if ((v.numbers_checked ?? 0) > 0) out.push({ tone: all ? "ok" : "caution", text: all ? `${v.numbers_checked} of ${v.numbers_checked} numbers match the data` : `${v.numbers_from_tools} of ${v.numbers_checked} numbers in the answer come from the data` });
    // Counted from the questions the page shows, not from the verifier's tally (which counts the model's own questions only).
    const qs = namedQuestions(run?.recommendation?.open_questions ?? []);
    const questions = qs.length;
    if (questions > 0) {
      const owned = qs.filter((q) => q.owner).length;
      out.push(owned === questions
        ? { tone: "ok", text: `${questions} open ${questions === 1 ? "question has" : "questions have"} an owner` }
        : { tone: "caution", text: `${owned} of ${questions} open questions have an owner` });
    }
    for (const f of v.reasons ?? []) out.push({ tone: "caution", text: humanize(f) });
  }
  const g = run?.recommendation?.grade;
  if (g?.checks_total != null && g.checks_passed != null) {
    const full = g.checks_passed === g.checks_total;
    const missed = (g.failed_checks ?? []).map((c) => `${humanize(c.name)}: ${humanize(c.reason)}`);
    const names = (g.failed_checks ?? []).map((c) => humanize(c.name));
    out.push({ tone: full ? "ok" : "caution", text: full ? "Reviewer: every check passed" : `Reviewer: ${names.length === 1 ? "one check" : names.length ? `${names.length} checks` : "a check"} did not pass${names.length ? ` (${names.join("; ")})` : ""}`, detail: `${g.checks_passed} of ${g.checks_total} checks passed`, missed: full ? undefined : missed.length ? missed : g.summary ? [humanize(g.summary)] : undefined });
  }
  return out;
}

/** The quiet strip under a Recommendation. Nothing is shown for a figure the run did not report. */
export function CheckStrip({ run, runId, link = true, hideReviewer = false }: { run: RunDetail | null; runId?: string | null; link?: boolean; hideReviewer?: boolean }) {
  return (
    <div className="ds-trust">
      {checkFacts(run).filter((f) => !(hideReviewer && f.text.startsWith("Reviewer") && f.tone === "ok")).map((f) => <span key={f.text} className={f.tone}>{f.text}</span>)}
      {link && (runId ?? run?.run_id) && <Link to={`/activity/${encodeURIComponent((runId ?? run?.run_id) as string)}`}>How we got here</Link>}
    </div>
  );
}

/** How the answer was reached, in one glance; the full trace is one click away. */
export function RunTrace({ run, runId }: { run: RunDetail; runId: string | null }) {
  const who = Array.from(new Set((run.events ?? []).filter((e) => e.type === "child.started").map((e) => e.agent_label ?? ""))).filter(Boolean);
  const secs = run.duration_ms ? Math.round(run.duration_ms / 1000) : null;
  return (
    <div className="trace">
      <p className="ds-decision">{secs !== null ? `Worked out in ${secs} s` : "Worked out"}{who.length ? ` with ${who.join(" and ")}` : ""}.</p>
      <ul className="plainlist">
        {checkFacts(run).map((f) => <li key={f.text} className={f.tone}>{f.text}</li>)}
        {run.tool_calls != null && <li>{run.tool_calls} lookups{run.denied_calls ? `, ${run.denied_calls} refused` : ""}</li>}
      </ul>
      {runId && <p><Link to={`/activity/${encodeURIComponent(runId)}`}>Open the full trace</Link></p>}
    </div>
  );
}

/** Who decided what, newest first, each as a ready sentence. Absent until the contract carries decisions. */
export function DecisionHistory({ decisions }: { decisions?: { text: string; at?: string }[] | null }) {
  const named = useNamed();
  const [open, setOpen] = useState<Set<number>>(new Set());
  if (!decisions || decisions.length === 0) return null;
  // The sentence arrives with a calendar date typed into it; every record is made on the data's today, so it reads as a time of day.
  const plain = (t: string) => named(t.replace(/ on (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{1,2}(?=[:,. ])/, ""));
  const toggle = (n: number) => setOpen((o) => { const x = new Set(o); if (x.has(n)) x.delete(n); else x.add(n); return x; });
  // One line per decision (time · what); a long one opens in full from its own line.
  return (
    <ul className="plainlist decisions">
      {decisions.map((d, n) => {
        const text = plain(d.text), long = text.length > 90, full = open.has(n);
        return (
          <li key={n}>
            <span className="muted">{d.at ? clock(d.at) : ""}</span>
            <span className={`dec-t${full ? " full" : ""}`} title={long && !full ? text : undefined}>{text}</span>
            {long && <Disclose open={full} onClick={() => toggle(n)}>{full ? "Show less" : "Read in full"}</Disclose>}
          </li>
        );
      })}
    </ul>
  );
}
