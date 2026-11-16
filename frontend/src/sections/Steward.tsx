import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useRunPoll } from "../shell/AskPanel";
import { Expander } from "../ui/Expander";
import { humanize } from "../ui/format";
import { Notice, Row, RowGroup, Tile, Tiles } from "../ds";
import { useMe } from "../api/useMe";

type Reading = {
  file: string; table: string; fit: number; rows_in: number; rows_out: number; mapping: Record<string, string>; already_on_file: number;
  findings: { issue: string; count: number; consequence: string; example: string; handling: string }[];
  questions: { question: string; covers: number; proposed_answer: string; why_it_blocks: string }[];
  checks: { name: string; passed: boolean; detail?: string }[]; script: string;
};

/** Read an unfamiliar file: pick a CSV (or the example waiting in data/incoming), the Data steward reads it by code, and its proposal appears below.
 * Nothing is loaded. */
export function ReadAFile() {
  const { me } = useMe();
  const pick = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const send = async (name: string, text: string) => {
    setErr(null); setBusy(true); setRunId(null); setFile(name);
    try { const r = await api.stewardRun(name, text, me ?? ""); setRunId(r.run_id); }
    catch (e) { setErr((e as Error).message === "bad-file" ? "That needs to be a .csv file under 2 MB." : "The file could not be sent. Try again."); }
    finally { setBusy(false); if (pick.current) pick.current.value = ""; }
  };
  const onFile = async (f: File | undefined) => { if (f) await send(f.name, await f.text()); };
  const example = async () => { const x = await fetch("/api/imports/steward-example").then((r) => r.json() as Promise<{ filename: string; text: string }>); if (x.filename) await send(x.filename, x.text); };
  return (
    <section className="im-steward">
      <p>A file the recipe has never seen? <button type="button" className="linkbtn" disabled={busy} onClick={() => pick.current?.click()}>{busy ? "Sending…" : "Have the Data steward read it"}</button>{" "}
        or <button type="button" className="linkbtn" disabled={busy} onClick={example}>try the site office's ME2N download</button>. It reads the CSV by code, tries one step on a copy and proposes the questions. Nothing loads.</p>
      <input ref={pick} type="file" accept=".csv,text/csv" hidden aria-label="Choose a CSV file" onChange={(e) => onFile(e.target.files?.[0])} />
      {err && <Notice tone="risk">{err}</Notice>}
      {runId && <ReadingView key={runId} runId={runId} file={file ?? ""} />}
    </section>
  );
}

function ReadingView({ runId, file }: { runId: string; file: string }) {
  const run = useRunPoll(runId);
  const top = useRef<HTMLDivElement>(null);
  useEffect(() => { top.current?.scrollIntoView?.({ block: "start", behavior: "smooth" }); }, []);
  if (run === null) return <Notice tone="risk">That reading could not be found.</Notice>;
  if (!run || run.status === "running") return <div ref={top} aria-live="polite"><p className="ds-wait">Reading {file}<span className="ds-caret" aria-hidden /></p></div>;
  const r = (run.recommendation as { steward?: Reading } | null)?.steward;
  if (run.status === "failed" || !r) return <Notice tone="risk">The steward could not finish reading {file}. <Link to={`/activity/${encodeURIComponent(runId)}`}>How we got here</Link></Notice>;
  const passed = r.checks.filter((c) => c.passed).length;
  return (
    <div ref={top}>
      <p className="ds-decision">{humanize(run.recommendation?.finding ?? "")}</p>
      <Tiles>
        <Tile figure={String(r.rows_in)} label="rows in" />
        <Tile figure={String(r.rows_out)} label="rows out" />
        <Tile figure={String(Object.keys(r.mapping).length)} label="columns matched" />
        <Tile figure={`${passed} of ${r.checks.length}`} label="checks passed" tone={passed === r.checks.length ? "positive" : "critical"} />
      </Tiles>
      <RowGroup>What it found</RowGroup>
      {r.findings.map((f, n) => <Row key={n} title={`${f.count} · ${f.issue}`} sub={`${f.consequence}${f.example ? ` · e.g. ${f.example}` : ""}`} />)}
      {r.questions.length > 0 && <RowGroup>Waiting for a person to decide</RowGroup>}
      {r.questions.map((q, n) => <Row key={n} state="unknown" title={q.question} sub={`Covers ${q.covers} ${q.covers === 1 ? "row" : "rows"} in ${file}. Proposed: ${q.proposed_answer}. ${q.why_it_blocks}`} />)}
      <Expander title="Checked by the system" hint={`${passed} of ${r.checks.length} passed`}>
        {r.checks.map((c) => <Row key={c.name} state={c.passed ? "done" : "disrupted"} title={c.name} sub={c.detail} note={c.passed ? "passed" : "waits"} />)}
      </Expander>
      <Expander title="The one step it tried" hint="on a copy of the file"><pre className="json">{r.script}</pre></Expander>
      <p className="ds-note">A proposal, read by code (no model is connected here): nothing was loaded or changed. <Link to={`/activity/${encodeURIComponent(runId)}`}>How we got here</Link></p>
    </div>
  );
}
