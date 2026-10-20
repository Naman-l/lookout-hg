import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, imports } from "../api/client";
import { useResource } from "../api/useResource";
import type { ActionItem, ImportAnswer, ImportDryRun, ImportQuestion } from "../api/types";
import { Link } from "react-router-dom";
import { statusOf } from "../components/domain/caseStatus";
import { builtAt } from "./data/DataPage";
import { Expander } from "../ui/Expander";
import "./import/card.css";
import { IssueTable } from "./import/IssueTable";
import "./import/import.css";
import { Button, EmptyState, Field, Notice, PageHeader, Row, RowGroup, Skeleton, Tile, Tiles } from "../ds";
import { ReadAFile } from "./Steward";
import { useMe } from "../api/useMe";

const fmt = (n: number) => n.toLocaleString("en-US");

type Stage = "questions" | "dryrun" | "done";

const KIND: Record<string, string> = { alias: "Same company", currency: "Currency", origin: "Country of origin", duplicate_row: "Repeated row", possible_duplicate: "Possible repeat", stock_count: "Stock on hand", other: "Question" };

/** Import files: a short deck of questions (one card covers many entries), a dry run, then approve and load. */
export function Import() {
  const { me } = useMe();
  const [reload, setReload] = useState(0);
  const deck = useResource(imports.deck, [reload]);
  const stamp = useResource(() => api.stamp().catch(() => null));
  const items = useResource(() => api.actionItems().catch(() => [] as ActionItem[]));
  const [answers, setAnswers] = useState<Record<string, ImportAnswer>>({});
  const [i, setI] = useState(0);
  const [stage, setStage] = useState<Stage>("questions");
  const [dry, setDry] = useState<ImportDryRun | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [params] = useSearchParams();
  const qs = deck.data?.questions ?? [];
  // The server remembers each answer (state, and the answer when it was changed): the deck starts from what is already decided, not from nothing.
  useEffect(() => {
    if (!deck.data) return;
    const seeded: Record<string, ImportAnswer> = {};
    for (const q of deck.data.questions) {
      if (q.state === "open") continue;
      seeded[q.id] = { question_id: q.id, action: q.state === "accepted" ? "accept" : q.state === "changed" ? "change" : "skip", ...(q.answer ? { value: q.answer } : {}) };
    }
    setAnswers((a) => ({ ...seeded, ...a }));
    const first = deck.data.questions.findIndex((q) => q.state === "open");
    setI((n) => (first >= 0 && !params.get("card") ? first : n));
  }, [deck.data]); // eslint-disable-line react-hooks/exhaustive-deps
  // Reopened with every answer already saved: open at the first step not done, the preview. Read from the saved states, once; Back still returns to the cards.
  const opened = useRef(false);
  useEffect(() => {
    if (opened.current || !deck.data || qs.length === 0 || params.get("card")) return;
    opened.current = true;
    if (qs.every((q) => q.state !== "open")) imports.dryRun().then((d) => { setDry(d); setStage("dryrun"); }, () => {});
  }, [deck.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const answered = qs.filter((q) => answers[q.id]).length;
  // A link from elsewhere ("Add a stock count") opens the deck on that card.
  const want = params.get("card");
  useEffect(() => { const n = qs.findIndex((q) => q.id === want); if (want && n >= 0) setI(n); }, [want, qs.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const record = (q: ImportQuestion, a: Omit<ImportAnswer, "question_id">) => {
    const next = { ...answers, [q.id]: { question_id: q.id, ...a } };
    setAnswers(next);
    imports.answer([next[q.id]], me ?? "").catch(() => setErr("That answer could not be saved."));
    const open = qs.findIndex((x, n) => n > i && !next[x.id]);
    const any = qs.findIndex((x) => !next[x.id]);
    if (open >= 0) setI(open); else if (any >= 0) setI(any); else finish();
  };
  const acceptAll = () => {
    const next = { ...answers };
    for (const q of qs) if (!next[q.id]) next[q.id] = { question_id: q.id, action: "accept" };
    setAnswers(next);
    imports.answer(Object.values(next), me ?? "").catch(() => setErr("Those answers could not be saved."));
    finish();
  };
  const finish = () => {
    imports.dryRun().then((d) => { setDry(d); setStage("dryrun"); }, () => setErr("The preview could not be made."));
  };
  const approve = () => dry && imports.approve(dry.hash, me ?? "").then(() => { setStage("done"); setReload((n) => n + 1); }, () => setErr("The answers changed since the dry run. Run it again."));

  const steps = [["questions", "Questions"], ["dryrun", "Preview"], ["done", "Approve"]] as const;
  return (
    <div className="pg-fix">
      <PageHeader back={{ to: "/data", label: "Data" }} title="Import files"
        meta={<span className="ds-stepper">{steps.map(([k, l], n) => <span key={k} className={k === stage ? "now" : ""} aria-current={k === stage ? "step" : undefined}>{n > 0 && <i aria-hidden>›</i>}{l}</span>)}</span>} />
      <div className="pg-body">
      {stage === "questions" && <ReadAFile />}
      {deck.loading && <Skeleton width={320} />}
      {err && <Notice tone="risk">{err}</Notice>}
      {deck.data && qs.length === 0 && stage === "questions" && <EmptyState>Nothing needs an answer. Every file is understood.</EmptyState>}

      {stage === "questions" && qs.length > 0 && (
        <>
          <Card key={qs[i].id} q={qs[i]} index={i} total={qs.length} onAnswer={(a) => record(qs[i], a)}
            meta={stamp.data ? `Proposed · cleaning recipe ${stamp.data.recipe_hash.slice(0, 8)} · ${builtAt(stamp.data.built_at)}` : "Proposed"}
            onToday={sameCase(qs[i], items.data ?? [])} me={me} />
          {qs.length - answered > 0
            ? <div className="ds-actions" style={{ marginTop: "calc(-1 * var(--s3))" }}><Button onClick={acceptAll}>Accept all {qs.length - answered} remaining</Button><span className="ds-caption">uses each card’s proposed answer</span></div>
            : <div className="ds-actions"><Button variant="primary" onClick={finish}>Preview the load</Button></div>}
        </>
      )}

      {stage === "dryrun" && dry && (
        <DryRun dry={dry} qs={qs} answers={answers} onBack={() => { setStage("questions"); setI(0); }} onApprove={approve} />
      )}

      {stage === "done" && (
        <>
          <p className="ds-decision">Loaded. Today and every section now read the imported data.</p>
          <div className="ds-actions"><Button variant="primary" to="/">Open Today</Button></div>
        </>
      )}
      </div>
    </div>
  );
}

/** The case on Today whose parts are exactly this question's entries (the origin card and "5 parts missing country of origin"). */
function sameCase(q: ImportQuestion, items: ActionItem[]): ActionItem | null {
  const want = new Set(Array.isArray(q.entries) ? q.entries : []);
  if (!want.size) return null;
  return items.find((i) => { const parts = (i.refs ?? []).filter((r) => r.type === "part").map((r) => r.id); return parts.length === want.size && parts.every((p) => want.has(p)); }) ?? null;
}

function Card({ q, index, total, meta, onToday, me, onAnswer }: {
  q: ImportQuestion; index: number; total: number; meta: string; onToday: ActionItem | null; me: string | null;
  onAnswer: (a: { action: ImportAnswer["action"]; value?: string }) => void;
}) {
  const [changing, setChanging] = useState(false);
  const stock = q.kind === "stock_count";
  const [value, setValue] = useState(stock ? "" : q.proposed.answer);
  const [all, setAll] = useState(false);
  useEffect(() => { setChanging(false); setValue(stock ? "" : q.proposed.answer); setAll(false); }, [q.id, q.proposed.answer, stock]);
  return (
    <section className="im-plain" aria-label={`Card ${index + 1} of ${total}`}>
      <div className="im-card">
        <header className="im-card-head">
          <span className="im-kind">{KIND[q.kind] ?? "Question"}</span>
          {q.file && <span className="im-file-name">{q.file}</span>}
          <span className="dm-rel">covers {fmt(q.covers)} {q.covers === 1 ? "entry" : "entries"}</span>
          <span className="im-of">{index + 1} of {total}</span>
        </header>
        <h3 className="im-q">{q.question}</h3>
        <div className="im-proposed">
          <span className="im-cap">{stock ? "What we have" : meta}</span>
          {stock ? <b className="unk">not in the data</b> : <b>{q.proposed.answer}</b>}
          {q.proposed.effect && <p>{q.proposed.effect[0].toUpperCase() + q.proposed.effect.slice(1).replace(/[.\s]+$/, "")}.</p>}
        </div>
        {onToday && <p className="im-today">The same {fmt(q.covers)} {q.kind === "origin" ? (q.covers === 1 ? "part is" : "parts are") : q.covers === 1 ? "entry is" : "entries are"} on Today: <Link to={`/items/${encodeURIComponent(onToday.key)}`}>{onToday.title}</Link> · {statusOf(onToday, me, new Map()).word}</p>}
        {(q.examples ?? []).length > 0 && (
          <table className="dm-table im-ex">
            <caption className="dm-sr">Examples</caption>
            <thead><tr><th scope="col">Written as</th><th scope="col">Becomes</th></tr></thead>
            <tbody>{(q.examples ?? []).slice(0, 3).map((e) => <tr key={`${e.from}${e.to}`}><td>{e.from}</td><td>{/^unknown$/i.test(e.to) ? "Left blank" : e.to}{e.note && <span className="dm-hint"> ({e.note})</span>}</td></tr>)}</tbody>
          </table>
        )}
        {!changing && (
          <div className="ds-actions">
            <Button variant="primary" onClick={() => onAnswer({ action: "accept" })}>Accept</Button>
            <Button onClick={() => setChanging(true)}>{stock ? "Give counts" : "Change"}</Button>
            <Button variant="quiet" onClick={() => onAnswer({ action: "skip" })}>Skip for now</Button>
            {q.entries && q.entries.length > 0 && <Button variant="quiet" onClick={() => setAll(!all)}>{all ? "Hide the entries" : `Show all ${fmt(q.covers)}`}</Button>}
          </div>
        )}
      </div>
      {all && q.entries && q.entries.length > 0 && <p className="ds-entries">{q.entries.join(" · ")}</p>}
      {changing ? (
        <div className="ds-actions">
          <div style={{ flex: "1 1 100%" }}>
            {stock
              ? <Field kind="textarea" autoFocus rows={5} value={value} onChange={(e) => setValue(e.target.value)} aria-label="Stock counts, one PART=QTY per line" placeholder={"PT-1001=120\nPT-1002=2500"} />
              : <Field autoFocus value={value} onChange={(e) => setValue(e.target.value)} aria-label="Your answer" />}
          </div>
          <Button variant="primary" disabled={!value.trim()} onClick={() => onAnswer({ action: "change", value: value.trim() })}>{stock ? "Save counts" : "Save answer"}</Button>
          <Button variant="quiet" onClick={() => setChanging(false)}>Cancel</Button>
        </div>
      ) : null}
    </section>
  );
}

function DryRun({ dry, qs, answers, onBack, onApprove }: { dry: ImportDryRun; qs: ImportQuestion[]; answers: Record<string, ImportAnswer>; onBack: () => void; onApprove: () => void }) {
  const ok = dry.checks.every((c) => c.passed);
  const passed = dry.checks.filter((c) => c.passed).length;
  const dropped = dry.files.reduce((a, f) => a + (f.rows_in - f.rows_out), 0);
  return (
    <>
      <p className="ds-decision">
        {ok ? "Every row is accounted for. " : "Some checks did not pass, so nothing can be loaded. "}
        {dropped > 0 ? `${fmt(dropped)} duplicate rows were dropped, each recorded with the row it repeats.` : "No rows were dropped."}
      </p>
      <Tiles>
        <Tile figure={fmt(dry.files.reduce((a, f) => a + f.rows_in, 0))} label="rows in" />
        <Tile figure={fmt(dry.files.reduce((a, f) => a + f.rows_out, 0))} label="rows out" />
        <Tile figure={fmt(dropped)} label="duplicates dropped" />
        <Tile figure={`${passed} of ${dry.checks.length}`} label="checks passed" tone={ok ? "positive" : "critical"} />
      </Tiles>
      <div className="ds-actions"><Button variant="primary" disabled={!ok} onClick={onApprove}>Approve and load</Button><Button variant="quiet" onClick={onBack}>Back to questions</Button></div>
      <RowGroup>Files</RowGroup>
      {dry.files.map((f) => (
        <section key={f.file} className="im-file">
          <header><h3>{f.file}</h3><span>{fmt(f.rows_in)} → {fmt(f.rows_out)} rows · {f.changes.length} {f.changes.length === 1 ? "issue" : "issues"}</span></header>
          <IssueTable file={f.file} lines={f.changes} />
        </section>
      ))}
      <Expander title="Checked by the system" hint={`${passed} of ${dry.checks.length} passed`}>
        {dry.checks.map((c) => <Row key={c.name} state={c.passed ? "done" : "disrupted"} title={c.name} note={c.passed ? "passed" : "did not pass"} />)}
      </Expander>
      <Expander title="Answers you gave" hint={`${dry.answers.total} cards${dry.answers.changed ? ` · ${dry.answers.changed} changed` : ""}${dry.answers.skipped ? ` · ${dry.answers.skipped} skipped` : ""}`}>
        {qs.map((q) => { const a = answers[q.id]; return <Row key={q.id} title={q.question} sub={a?.action === "accept" ? q.proposed.answer : a?.action === "change" ? a.value ?? "" : "left unknown"} />; })}
      </Expander>
    </>
  );
}
