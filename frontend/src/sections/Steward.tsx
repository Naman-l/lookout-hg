import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { RunDetail, RunEvent } from "../api/types";
import { useRun } from "../organism/useRun";
import { Expander } from "../ui/Expander";
import { humanize } from "../ui/format";
import { NO_AGENT, isNoAgent } from "../ui/copy";
import { Notice, Row, RowGroup, Tile, Tiles } from "../ds";
import { Recommendation } from "../domain-ui/Agent";
import { useMe } from "../api/useMe";

const str = (v: unknown) => (typeof v === "string" ? v : v == null ? "" : String(v));
type Check = { name: string; passed: boolean; detail?: string };

/** What the steward put on the record, read from its tool calls: findings, the questions only a person can answer, the one script and its checks. */
function reading(events: RunEvent[]) {
  const args = (name: string) => events.filter((e) => e.type === "tool.called" && e.payload?.name === name).map((e) => (e.payload?.args ?? {}) as Record<string, unknown>);
  const tried = events.filter((e) => e.type === "tool.result" && typeof e.payload?.script === "string").pop();
  return {
    findings: args("add_finding"),
    questions: args("ask_user"),
    script: tried ? str(tried.payload?.script) : "",
    checks: ((tried?.payload?.checks as Check[] | undefined) ?? []),
  };
}

const figure = (rec: RunDetail["recommendation"], tail: string) => rec?.numbers.find((n) => n.id.endsWith(`:${tail}`))?.value;

/** Read an unfamiliar file (FINAL 09 §2, one line under the header): pick a CSV, the Data steward reads it, and its proposal appears below. Nothing is loaded. */
export function ReadAFile() {
  const { me } = useMe();
  const pick = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onFile = async (f: File | undefined) => {
    if (!f) return;
    setErr(null); setBusy(true); setRunId(null); setFile(f.name);
    try {
      const r = await api.stewardRun(f.name, await f.text(), me ?? "");
      setRunId(r.run_id);
    } catch (e) {
      const m = (e as Error).message;
      setErr(m === "no-model" ? `${NO_AGENT} A new file cannot be read now; the example file still works.` : m === "bad-file" ? "That needs to be a .csv file under 2 MB." : "The file could not be sent. Try again.");
    } finally { setBusy(false); if (pick.current) pick.current.value = ""; }
  };

  return (
    <section className="im-steward">
      <p>A file the recipe has never seen? <button type="button" className="linkbtn" disabled={busy} onClick={() => pick.current?.click()}>{busy ? "Sending…" : "Have the Data steward read it"}</button> (agent): it reads the CSV, tries one step on a copy and proposes the questions. Nothing loads.</p>
      <input ref={pick} type="file" accept=".csv,text/csv" hidden aria-label="Choose a CSV file" onChange={(e) => onFile(e.target.files?.[0])} />
      {err && <Notice tone={isNoAgent(err) ? undefined : "risk"}>{err}</Notice>}
      {runId && <Reading key={runId} runId={runId} file={file ?? ""} />}
    </section>
  );
}

function Reading({ runId, file }: { runId: string; file: string }) {
  const { run, events, error } = useRun(runId);
  const top = useRef<HTMLDivElement>(null);
  useEffect(() => { top.current?.scrollIntoView?.({ block: "start", behavior: "smooth" }); }, []);
  if (error) return <Notice tone="risk">That reading could not be found.</Notice>;
  const failed = run?.status === "failed" || events.some((e) => e.type === "run.failed");
  const done = !!run && run.status !== "running" && !!run.recommendation;
  const said = events.filter((e) => (e.type === "tool.result" || e.type === "step.text") && e.summary).map((e) => humanize(e.summary));
  if (failed) return <Notice tone="risk">The steward could not finish reading {file}. <Link to={`/activity/${encodeURIComponent(runId)}`}>How we got here</Link></Notice>;
  if (!done || !run?.recommendation) {
    return (
      <div ref={top} aria-live="polite">
        <p className="ds-wait">Reading {file}<span className="ds-caret" aria-hidden /></p>
        {said.length > 0 && <p className="ds-caption">{said[said.length - 1]}</p>}
      </div>
    );
  }
  const rec = run.recommendation, r = reading(events);
  const passed = r.checks.filter((c) => c.passed).length;
  return (
    <div ref={top}>
      {run.recorded && <Notice>Saved answer: the example file. {NO_AGENT}</Notice>}
      <Recommendation rec={rec} tiles={(
        <Tiles>
          {figure(rec, "rows_in") && <Tile figure={figure(rec, "rows_in")} label="rows in" />}
          {figure(rec, "rows_out") && <Tile figure={figure(rec, "rows_out")} label="rows out" />}
          {r.checks.length > 0 && <Tile figure={`${passed} of ${r.checks.length}`} label="checks passed" tone={passed === r.checks.length ? "positive" : "critical"} />}
        </Tiles>
      )} />
      {r.findings.length > 0 && (
        <>
          <RowGroup>What it found</RowGroup>
          {r.findings.map((f, n) => <Row key={n} title={`${str(f.count)} · ${humanize(str(f.issue))}`} sub={`${humanize(str(f.consequence))}${f.example ? ` e.g. ${str(f.example)}` : ""}`} />)}
        </>
      )}
      {r.questions.length > 0 && <RowGroup>Waiting for a person to decide</RowGroup>}
      {r.questions.map((q, n) => (
        <Row key={n} state="unknown" title={humanize(str(q.question))} sub={`Covers ${str(q.covers)} ${Number(q.covers) === 1 ? "entry" : "entries"} in ${file}. Proposed: ${humanize(str(q.proposed_answer))} ${humanize(str(q.why_it_blocks))}`} />
      ))}
      {r.checks.length > 0 && (
        <Expander title="Checked by the system" hint={`${passed} of ${r.checks.length} passed`}>
          {r.checks.map((c) => <Row key={c.name} state={c.passed ? "done" : "disrupted"} title={c.name} sub={c.detail} note={c.passed ? "passed" : "did not pass"} />)}
        </Expander>
      )}
      {r.script && (
        <Expander title="The one step it tried" hint="on a copy of the file">
          <pre className="json">{r.script}</pre>
        </Expander>
      )}
      <p className="ds-note">This is a proposal: nothing was loaded or changed. <Link to={`/activity/${encodeURIComponent(runId)}`}>How we got here</Link></p>
    </div>
  );
}
