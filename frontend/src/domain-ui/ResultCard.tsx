import { useState } from "react";
import { Link } from "react-router-dom";
import { EntityText, Stage, type Entity, type StageKey } from "../components/domain";
import { FieldLabel } from "../ds";
import { namedQuestions, SHOWN } from "./openQuestions";
import "./result-card.css";

/** What every run ends on (ORGANISM's result object): the answer, the reasons as labelled points, what was done with a link to each, the next step, and what is still open. */
export type ResultData = {
  finding: string;
  points?: { label: string; text: string; entities?: Entity[] }[];
  next_step?: { who?: string | null; what?: string | null; by?: string | null } | null;
  done?: { action_id: string; label?: string | null; stage?: StageKey | string | null }[];
  open_questions?: { what: string; question?: string | null; owner?: string | null }[];
  checks?: string[];
};

const STAGES = new Set(["found", "worked", "decision_ready", "drafted", "approved", "sent", "answered", "held", "asking"]);

/** The one card a run ends on, wherever it was started (in place, the panel, the item, the Inbox): the progress line goes away when it arrives, and "How we got here" is a quiet link under it, never the destination. */
export function ResultCard({ data, runId, onNavigate }: { data: ResultData; runId?: string; onNavigate?: () => void }) {
  const next = data.next_step && (data.next_step.what || data.next_step.who) ? data.next_step : null;
  const open = namedQuestions(data.open_questions ?? []);
  const [allOpen, setAllOpen] = useState(false);
  return (
    <section className="rc" aria-label="Result">
      <p className="rc-answer"><b>{data.finding}</b></p>
      {(data.points ?? []).length > 0 && (
        <dl className="rc-points">
          {data.points!.map((p) => <div key={p.label + p.text}><dt><FieldLabel>{p.label}</FieldLabel></dt><dd><EntityText text={p.text} entities={p.entities} /></dd></div>)}
        </dl>
      )}
      {(data.done ?? []).length > 0 && (
        <div className="rc-block">
          <FieldLabel>Done</FieldLabel>
          <ul className="rc-done">
            {data.done!.map((d) => (
              <li key={d.action_id}>
                <Link to={`/approvals/${encodeURIComponent(d.action_id)}`} onClick={onNavigate}>{d.label ?? "A draft"}</Link>
                {d.stage && STAGES.has(d.stage) && <Stage stage={d.stage as StageKey} />}
              </li>
            ))}
          </ul>
        </div>
      )}
      {next && <p className="rc-next"><FieldLabel>Next</FieldLabel><span>{[next.who, next.what, next.by ? `by ${next.by}` : null].filter(Boolean).join(" · ")}</span></p>}
      {open.length > 0 && (
        <div className="rc-block">
          <FieldLabel>Still open</FieldLabel>
          <ul className="rc-open">{(allOpen ? open : open.slice(0, SHOWN)).map((q) => <li key={q.text}>{q.text}{q.owner ? <span className="muted"> · {q.owner}</span> : null}</li>)}</ul>
          {!allOpen && open.length > SHOWN && <button type="button" className="rc-more" onClick={() => setAllOpen(true)}>+{open.length - SHOWN} more</button>}
        </div>
      )}
      <p className="rc-foot">{(data.checks ?? []).join(" · ")}{runId && <>{(data.checks ?? []).length ? " · " : ""}<Link to={`/activity/${encodeURIComponent(runId)}`} onClick={onNavigate}>How we got here</Link></>}</p>
    </section>
  );
}
