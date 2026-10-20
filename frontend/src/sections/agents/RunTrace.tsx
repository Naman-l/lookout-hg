import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { useResource } from "../../api/useResource";
import type { ActionItem, RunDetail, RunEvent } from "../../api/types";
import { useRun } from "../../organism/useRun";
import { NotFound, RightPanel } from "../../ds";
import { modelName } from "../../ui/format";
import { day } from "../records/model";
import { Mark } from "./UnderTheHood";
import { blockMeta, buildTrace, type Row } from "./trace";
import { useAgentLabels } from "./labels";
import "./agents.css";

const sec = (ms: number) => `${Math.round(ms / 1000)} s`;

/** Elapsed time that keeps ticking while the run is live. */
function useElapsed(baseMs: number, live: boolean) {
  const [extra, setExtra] = useState(0);
  useEffect(() => {
    setExtra(0);
    if (!live) return;
    const start = Date.now();
    const t = setInterval(() => setExtra(Date.now() - start), 500);
    return () => clearInterval(t);
  }, [baseMs, live]);
  return baseMs + extra;
}

/** A run (FINAL 08 C): the answer in one line, then every step in run order (Overview · Analysis · Draft · Decision), by agent and tool, and "This run" beside it. */
export function RunTrace() {
  const { id = "" } = useParams();
  const { run, events, error } = useRun(id);
  if (error) return <NotFound title="Run not found" line={`No agent run has the id ${id}.`} />;
  if (!run) return <div className="ag"><span className="ag-sk1" style={{ width: 320 }} /><div className="ag-sk" aria-hidden><i /><i /><i /></div></div>;
  return <RunBody run={run} events={events} />;
}

function RunBody({ run, events }: { run: RunDetail; events: RunEvent[] }) {
  const items = useResource(() => api.actionItems().catch(() => [] as ActionItem[]));
  const label = useAgentLabels();
  const t = buildTrace(events, Object.fromEntries([...(run.specialists ?? []).map((s) => s.agent), ...events.map((e) => e.agent ?? "")].filter(Boolean).map((a) => [a, label(a)])));
  const finished = events.some((e) => e.type === "run.finished" && !e.parent_run_id) || run.status !== "running";
  const lastMs = events.reduce((a, e) => Math.max(a, e.t_ms ?? 0), 0);
  const elapsed = useElapsed(finished ? (run.duration_ms ?? lastMs) : lastMs, !finished);
  const item = (items.data ?? []).find((i) => i.key === run.item_key);
  const isAsk = (run.item_key ?? "").startsWith("ask:");
  const title = run.title ?? item?.title ?? (isAsk ? "A question to Lookout" : run.item_key ?? "Agent run");
  const rec = run.recommendation as unknown as { finding?: string } | null | undefined;
  const staged = t.staged[0];
  const contact = staged?.contact;
  const current = t.groups[t.groups.length - 1]?.name;
  const recorded = !!run.recorded;
  const cost = recorded ? Number(run.original_cost_usd ?? 0) : Number(run.cost_usd ?? 0);
  const meta = !finished ? `Working · ${current ?? "Overview"} · ${sec(elapsed)}`
    : [recorded ? `Recorded ${day((run.recorded_at ?? run.started_at ?? "").slice(0, 10))}` : day((run.started_at ?? "").slice(0, 10)), sec(elapsed), recorded ? "replayed" : ""].filter(Boolean).join(" · ");
  const row = (r: Row) => (
    <li key={r.id} className={`rt-row ${r.mark}${!r.mono || r.actionId ? " wrap" : ""}`}>
      <span className="rt-m" aria-label={r.mark === "no" ? "refused or failed" : r.mark === "redo" ? "rewritten" : "done"}>{r.mark === "no" ? "×" : r.mark === "redo" ? "↺" : "✓"}</span>
      {r.mono ? <code>{r.tool}</code> : <span className="rt-t">{r.tool}</span>}
      <span className="rt-x" title={r.full}>{r.text}{r.actionId && <> · <Link to={`/approvals/${encodeURIComponent(r.actionId)}`}>waits in Approvals</Link></>}</span>
      <span className="rt-r">{r.right}</span>
    </li>
  );
  return (
    <div className="ag rt pg-fix">
      <nav className="rt-crumb"><Link to="/activity">Agent activity ›</Link></nav>
      <h1 className="rt-h1">{title}</h1>
      <p className="rt-meta">{meta}</p>
      {finished && rec?.finding && (
        <div className="rt-answer">
          <span title={rec.finding}><em>Answer</em>{rec.finding.split(/(?<=[.;])\s/)[0].replace(/[.;]$/, "")}{contact && <> · draft to {contact}</>}</span>
          {item ? <Link to={`/items/${encodeURIComponent(item.key)}`}>Open the case →</Link> : isAsk ? <Link to="/">Open Today →</Link> : null}
        </div>
      )}
      <div className="rt-cols pg-body">
        <div className="rt-trace" aria-live="polite">
          {t.groups.length === 0 && <p className="ag-none">No steps are recorded for this run yet.</p>}
          {t.groups.map((g, gi) => (
            <section key={g.stage} className="rt-g" aria-label={g.name}>
              <h2>{gi + 1} · {g.name}{g.note && <> · {g.note}</>}</h2>
              {g.blocks.map((b, bi) => (
                <div key={`${b.agent}-${bi}`} className="rt-b">
                  <div className="rt-bh"><b><Mark role={b.lead ? "orchestrator" : "specialist"} />{b.label}</b><span>{blockMeta(b, g.stage)}</span></div>
                  <ul>{b.rows.map(row)}</ul>
                  {b.notes.map((n, k) => <p key={k} className="rt-note" title={n}>{n}</p>)}
                </div>
              ))}
            </section>
          ))}
          {!finished && <p className="rt-working">Working…</p>}
          <details className="rt-raw"><summary>Raw events (JSON)</summary><pre className="json">{JSON.stringify(events, null, 2)}</pre></details>
        </div>
        <RightPanel label="This run" className="rt-panel">
          <RightPanel.Section title="This run">
            <dl><div><dt>Agents</dt><dd>{(run.specialists ?? []).map((s) => label(s.agent, s.label)).join(", ") || "Lookout"}</dd></div></dl>
          </RightPanel.Section>
          <RightPanel.Section title="Checks">
            <dl>
              <div><dt>Lookups</dt><dd>{run.tool_calls ?? t.lookups}</dd></div>
              <div><dt>Figures read</dt><dd>{t.read}</dd></div>
              {t.checked && <div><dt>Figures checked</dt><dd>{t.checked.from} of {t.checked.of}</dd></div>}
              {t.reviewer && <div><dt>Reviewer</dt><dd>{t.reviewer.passed} of {t.reviewer.of}</dd></div>}
              <div><dt>Rewrites</dt><dd>{t.rewrites}</dd></div>
            </dl>
          </RightPanel.Section>
          {staged && <RightPanel.Section title="Draft"><dl><div><dt>Prepared for</dt><dd><Link to={`/approvals/${encodeURIComponent(staged.id)}`}>{contact ?? "the draft"} · in Approvals</Link></dd></div></dl></RightPanel.Section>}
          <RightPanel.Section title="Run">
            <dl>
              <div><dt>{recorded ? "Recorded cost" : "Cost"}</dt><dd>${cost.toFixed(2)}</dd></div>
              {run.model && <div><dt>Model</dt><dd>{modelName(run.model)}</dd></div>}
              {run.prompt_hash && <div><dt>Prompt</dt><dd><code>{run.prompt_hash}</code></dd></div>}
            </dl>
          </RightPanel.Section>
        </RightPanel>
      </div>
    </div>
  );
}
