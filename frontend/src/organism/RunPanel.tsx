import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { RunDetail } from "../api/types";
import { AgentMark, Disclose } from "../ds";
import { checkFacts } from "../domain-ui/Agent";
import { buildRun, type Line, type RunView } from "./runModel";
import { useRun } from "./useRun";

const sec = (ms: number) => `${(ms / 1000).toFixed(1)} s`;

type Step = { line: Line; agent: string };
/** Every step in order, a specialist's steps carrying that specialist's mark. */
const steps = (v: RunView): Step[] => v.rows.flatMap((r) => (r.kind === "line" ? [{ line: r.line, agent: "lookout" }] : r.d.lines.map((line) => ({ line, agent: r.d.agent }))));

function StepList({ list, live }: { list: Step[]; live: boolean }) {
  const box = useRef<HTMLUListElement>(null);
  // The list has a fixed height and scrolls inside itself, pinned to the newest step.
  useEffect(() => { if (live && box.current) box.current.scrollTop = box.current.scrollHeight; }, [list.length, live]);
  return (
    <ul className="runsteps" ref={box}>
      {list.map(({ line, agent }) => {
        const on = live && line.status === "live";
        return (
          <li key={line.id} className={line.status === "denied" ? "denied" : on ? "cur" : ""}>
            <span className={`st ${line.status === "denied" ? "no" : on ? "on" : "ok"}`} aria-hidden>{line.status === "denied" ? "×" : on ? "" : "✓"}</span>
            <span><AgentMark agent={agent} /> {line.text}{line.why && <span className="w"> · why: {line.why}</span>}{line.status === "denied" && line.detail && <span className="w"> · refused: {line.detail}</span>}</span>
            <span className="ts">{sec(line.ms)}</span>
          </li>
        );
      })}
    </ul>
  );
}

/** "Work this with the agent", while it works: a bounded panel where the answer will be, steps ticking with their reason. When it ends the page folds it into the answer. */
export function RunPanel({ runId, onDone }: { runId: string; onDone: () => void }) {
  const { run, events, error } = useRun(runId);
  const v = buildRun(events, run?.run_id ?? runId);
  const list = steps(v);
  const done = useRef(false);
  const ended = !!run && run.status !== "running";
  useEffect(() => { if (ended && !done.current) { done.current = true; onDone(); } }, [ended, onDone]);
  return (
    <section className="ai run" aria-live="polite" aria-label="The agent is working">
      <div className="ai-h"><i className="ai-mark" aria-hidden /><b>Lookout is working this item</b><span className="meta">{list.length} {list.length === 1 ? "step" : "steps"} so far · {sec(v.elapsedMs)}</span></div>
      <div className="bar-prog" aria-hidden><i /></div>
      {error ? <p className="sm">That run could not be read. Open Agent runs to see it.</p> : <StepList list={list} live={!ended} />}
      <p className="sm muted">Nothing is sent from a run. When it finishes this folds into the answer, and any draft waits in <Link to="/approvals">Approvals</Link>.</p>
    </section>
  );
}

/** A finished run, folded to one line under the answer; it opens to every step with its reason. */
export function RunFold({ run }: { run: RunDetail }) {
  const [open, setOpen] = useState(false);
  const v = buildRun(run.events ?? [], run.run_id ?? "");
  const list = steps(v);
  const facts = checkFacts(run);
  return (
    <section className="ai-fold">
      <div className="collapsed">
        <i className="ai-mark" aria-hidden />
        <span><b>How the agent got here</b> · {list.length} {list.length === 1 ? "step" : "steps"}{run.duration_ms ? ` in ${Math.round(run.duration_ms / 1000)} s` : ""}</span>
        <span className="ds-trust inline">{facts.filter((f) => !f.text.startsWith("Reviewer") || f.tone !== "ok").map((f) => <span key={f.text} className={f.tone}>{f.text}</span>)}</span>
        <Disclose open={open} onClick={() => setOpen(!open)} className="open">{open ? "Hide details" : "Details"}</Disclose>
      </div>
      {open && (
        <div className="ai run">
          <StepList list={list} live={false} />
          {facts.filter((f) => f.text.startsWith("Reviewer")).map((f) => (
            <div key={f.text} className="missed"><p className="ds-caption">{f.detail ?? f.text}{f.missed ? ", with:" : ""}</p>{f.missed && <ul>{f.missed.map((m) => <li key={m}>{m}</li>)}</ul>}</div>
          ))}
          <p className="ds-caption">{[run.tool_calls != null ? `${run.tool_calls} lookups` : "", run.model ?? "", Number(run.original_cost_usd) > 0 ? `replayed, was $${Number(run.original_cost_usd).toFixed(2)}` : ""].filter(Boolean).join(" · ")}</p>
          {run.run_id && <p className="sm"><Link to={`/activity/${encodeURIComponent(run.run_id)}`}>Open the full trace</Link></p>}
        </div>
      )}
    </section>
  );
}

/** A finished run as ONE quiet line in the rail: the steps, the numbers checked, the Reviewer's score; Details opens the one place the detail lives. */
export function RunLine({ run, onDetails }: { run: RunDetail; onDetails: () => void }) {
  const list = steps(buildRun(run.events ?? [], run.run_id ?? ""));
  const numbers = checkFacts(run).find((f) => / numbers /.test(f.text));
  const g = run.recommendation?.grade;
  const failed = g?.checks_total != null && g.checks_passed != null ? g.checks_total - g.checks_passed : 0;
  const parts = [`${list.length} ${list.length === 1 ? "step" : "steps"}`, numbers?.text.replace(" the data", ""), g?.reviewer_score != null ? `Reviewer ${g.reviewer_score}` : "", failed > 0 ? `${failed} ${failed === 1 ? "check" : "checks"} did not pass` : ""].filter(Boolean);
  return <p className="run-line">{parts.join(" · ")} <button type="button" className="linkbtn" onClick={onDetails}>Details</button></p>;
}
