import { Link, useParams } from "react-router-dom";
import { NotFound } from "../../ds";
import { useRunPoll } from "../../shell/AskPanel";
import { humanize, longDate } from "../../ui/format";
import type { RunEvent } from "../../api/types";
import "./agents.css";

/** How we got here: the answer first, then its checks, then every step in order: who did it, what they looked up and why, what came back. */
export function RunTrace() {
  const { id = "" } = useParams();
  const run = useRunPoll(id);
  if (run === null) return <NotFound title="No such run" line={`No run has the id ${id}.`} />;
  if (!run) return <div className="uth"><span className="skel" style={{ width: 320 }} /></div>;
  const rec = run.recommendation as (typeof run.recommendation & { recommended?: { kind: string; reason?: string } | null; open_questions?: { question: string; owner: string }[]; grade?: { reviewer_score?: number; failed_checks?: { name: string; reason: string }[]; checks_passed?: number; checks_total?: number } }) | null | undefined;
  const ver = run.verifier as { checked?: number; failures?: string[] } | null | undefined;
  const mocked = run.recorded;
  const groups: { agent: string; label: string; rows: RunEvent[] }[] = [];
  for (const e of run.events ?? []) {
    const last = groups[groups.length - 1];
    if (!last || last.agent !== e.agent) groups.push({ agent: e.agent, label: e.agent_label, rows: [e] }); else last.rows.push(e);
  }
  return (
    <div className="uth rt">
      <p className="cp-crumb"><Link to="/activity">Agent activity</Link>{run.item_key && !run.item_key.startsWith("ask:") && <> › <Link to={`/items/${encodeURIComponent(run.item_key)}`}>the case</Link></>}</p>
      <h1>How we got here</h1>
      <p className={`uth-mode${mocked ? " mocked" : ""}`}>{mocked ? "A replay of a mocked recording: written by hand to show how a model's run on this case reads. No model ran on this machine; the draft and the checks are today's, by code."
        : "Drafted by code: no model is connected on this machine. The steps are the same a model run takes; every figure is a lookup's."} · {longDate(run.started_at)} · {run.wall_ms != null ? `${(run.wall_ms / 1000).toFixed(1)} s` : "running"}</p>
      {run.question && <p className="rt-q">{run.question}</p>}
      {rec && <div className="rt-a"><b>{humanize(rec.finding)}</b>{rec.recommended && <p>Recommended: <b>{rec.recommended.kind.replace(/_/g, " ")}</b>{rec.recommended.reason ? ` · ${rec.recommended.reason}` : ""} (advice: the owner chooses)</p>}
        {(rec.open_questions ?? []).length > 0 && <ul>{(rec.open_questions ?? []).slice(0, 6).map((u) => <li key={u.question}>{u.question} <small>(ask {u.owner})</small></li>)}</ul>}</div>}
      <p className="rt-c">{ver ? `${(ver.checked ?? 0) - (ver.failures ?? []).length} of ${ver.checked ?? 0} checks passed` : "No checks recorded"}{(ver?.failures ?? []).length ? `: ${(ver?.failures ?? []).join("; ")}` : ""}
        {rec?.grade ? ` · Reviewer ${rec.grade.reviewer_score} (${rec.grade.checks_passed} of ${rec.grade.checks_total})${(rec.grade.failed_checks ?? []).length ? `: ${(rec.grade.failed_checks ?? []).map((f) => f.reason).join("; ")}` : ""}` : ""}</p>
      <ol className="rt-steps">
        {groups.map((g, n) => (
          <li key={n} className={`rt-g a-${g.agent}`}><b>{g.label}</b>
            <ul>{g.rows.filter((e) => e.type !== "child.finished").map((e) => (
              <li key={e.run_id + e.seq} className={`t-${e.type.replace(".", "-")}`}>
                {e.type === "tool.called" ? <><span className="tool">{String((e.payload as { tool?: string } | undefined)?.tool ?? e.summary)}</span> {String((e.payload as { why?: string } | undefined)?.why ?? "")}</>
                  : e.type === "tool.result" ? <small>→ {humanize(e.summary)}</small> : humanize(e.summary)}
              </li>))}</ul>
          </li>
        ))}
      </ol>
    </div>
  );
}
