import { StatusLine } from "../ds/StatusLine";
import { useEffect, useRef, useState } from "react";
import { ArrowUp, X } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useResource } from "../api/useResource";
import { useRun } from "../organism/useRun";
import { buildRun } from "../organism/runModel";
import { humanize } from "../ui/format";
import { useAskState } from "./AskContext";
import { AskTurn } from "../sections/CaseAsk";
import { Disclose } from "../ds";
import { EntityChip } from "../domain-ui/EntityChip";
import { AskComposer } from "./AskBox";
import { rankExamples, shortAbout } from "../sections/agents/ask";
import { buildTrace } from "../sections/agents/trace";
import { useAgentLabels } from "../sections/agents/labels";
import { useMedia } from "../ui/useMedia";
import { ResultCard, type ResultData } from "../domain-ui/ResultCard";
import type { EntityRef } from "../api/types";

/** The conversation, beside the page (a bottom sheet below 1024 px): a header with the scope and a close, a body that scrolls, one follow-up line at the foot. Each turn: the question, one quiet line of steps while it works, then the answer line first, the reasons as rows, the rest behind "Read in full". */
export function AskPanel() {
  const { open, setOpen, thread, about, context, scope, send, err, connected, examples } = useAskState();
  const body = useRef<HTMLDivElement>(null);
  const [follow, setFollow] = useState("");
  const phone = useMedia("(max-width: 760px)");
  const close = () => setOpen(false);
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  });
  useEffect(() => { body.current?.scrollTo({ top: body.current.scrollHeight }); }, [thread.length]);
  if (!open) return null;
  const down = connected === false;
  if (context?.type === "item") return null;      // on a case the Ask panel sits in the rail's slot: CaseAskSlot, mounted by the case page
  return (
    <aside className="aipanel" role="dialog" aria-label="Lookout's answer">
      <i className="grab" aria-hidden />
      <div className="ai-h"><i className="ai-mark" aria-hidden /><b>Ask</b><span className="meta">{scope === "all" ? "Everything" : shortAbout(about)}</span>
        <button type="button" className="x" aria-label="Close" onClick={close}><X size={16} strokeWidth={1.5} aria-hidden /></button></div>
      <div className="ai-body" ref={body}>
        {thread.length === 0 && (
          <div className="turn">
            <p className="q">What would you like to know about {scope === "all" ? "everything" : shortAbout(about)}?</p>
            {examples.length > 0 && <div className="ask-ex in">{rankExamples(examples, scope === "all" ? null : context, about).slice(0, 5).map((x) => <button key={x.question} type="button" onClick={() => send(x.question, x.context ?? null)}>{x.question}</button>)}{down && <p className="ask-ex-f">Recorded answers. A new question needs the live agent.</p>}</div>}
          </div>
        )}
        {thread.map((t) => <div key={t.runId} className="cask-g"><AskTurn runId={t.runId} question={t.question} onRetry={() => send(t.question)} /></div>)}
        {err && <p className="turn-err" role="status">{err}</p>}
      </div>
      {!phone && <AskComposer inPanel />}
      {phone && <form className="foot-in" onSubmit={(e) => { e.preventDefault(); if (follow.trim()) { send(follow).then((ok) => ok && setFollow("")); } }}>
        <input aria-label="Ask a follow-up" placeholder={thread.length ? "Ask a follow-up…" : "Ask a question…"} value={follow} onChange={(e) => setFollow(e.target.value)} />
        <button type="submit" className="go" aria-label="Send" disabled={!follow.trim()}><ArrowUp size={16} strokeWidth={2} /></button>
      </form>}
    </aside>
  );
}

const sentences = (t: string) => t.split(/(?<=[.!?])\s+(?=[A-Z$0-9])/).map((x) => x.trim()).filter(Boolean);

/** One question and its answer. An earlier turn folds to its answer line. */
export function Turn({ runId, question, last = true, onClose, onRetry }: { runId: string; question: string; last?: boolean; onClose: () => void; onRetry?: () => void }) {
  const { run, events, error } = useRun(runId);
  const actions = useResource(() => api.actions().then((a) => a.filter((x) => x.run_id === runId)).catch(() => []), [runId, run?.status]);
  const [more, setMore] = useState(false);
  const [folded, setFolded] = useState(!last);
  useEffect(() => { if (last) setFolded(false); }, [last]);
  const v = run ? buildRun(events, run.run_id ?? runId) : null;
  const lines = v ? v.rows.flatMap((r) => (r.kind === "line" ? [r.line] : r.d.lines)).filter((l) => l.status !== "denied") : [];
  const live = lines[lines.length - 1];
  const rec = run?.recommendation;
  const result = (run as unknown as { result?: ResultData } | null)?.result;
  const waiting = (actions.data ?? []).find((a) => a.state === "proposed");
  const figures = (rec?.numbers ?? []).filter((n) => n.say || n.value).slice(0, 2);
  const seen = new Map<string, EntityRef>();
  for (const n of rec?.numbers ?? []) for (const r of n.provenance?.inputs ?? []) if (!seen.has(`${r.type}:${r.id}`)) seen.set(`${r.type}:${r.id}`, r);
  const sources = [...seen.values()].slice(0, 5);
  const failed = run?.status === "failed" || run?.status === "did_not_pass";
  const parts = rec ? sentences(humanize(rec.finding)) : [];
  const lead = parts[0] ?? "", rows = parts.slice(1, 5), rest = parts.slice(5);
  const label = useAgentLabels();
  const tr = buildTrace(events, Object.fromEntries(events.map((e) => e.agent ?? "").filter(Boolean).map((a) => [a, label(a)])));
  // The checks line: what code checked, in one line; the Reviewer's grade stays inside How we got here.
  const ver = run?.verifier as { numbers_checked?: number; numbers_from_tools?: number; open_questions_with_owner?: number } | null | undefined;
  const checks = ver?.numbers_checked != null ? `✓ ${ver.numbers_from_tools ?? 0} of ${ver.numbers_checked} figures checked against a lookup${ver.open_questions_with_owner ? ` · ${ver.open_questions_with_owner} open questions have an owner` : ""}` : "";
  const who = run ? [label("lookout"), ...(run.specialists ?? []).map((x) => label(x.agent, x.label))] : [];
  const steps = tr.groups.flatMap((g) => g.blocks.flatMap((b) => b.rows.map((r) => ({ ...r, who: b.label, stage: g.name })))).filter((r) => r.mark !== "redo");
  const inParallel = events.filter((e) => e.type === "child.started").length - events.filter((e) => e.type === "child.finished").length;
  const secs = Math.round(events.reduce((a, e) => Math.max(a, e.t_ms ?? 0), 0) / 1000);
  return (
    <div className="turn">
      <p className="q">{question}</p>
      {run && who.length > 0 && <p className="ask-who">{who.map((w, k) => <span key={w}><i className={k === 0 ? "lead" : "spec"} aria-hidden />{w}</span>)}{run.tool_calls ? <span>· {run.tool_calls} lookups</span> : null}</p>}
      {/* A run that ends is never left spinning or retried on its own: the answer is shown with the one plain reason, and asking again is the reader's choice. */}
      {(error || failed) && (
        <p className="error">
          {rec && !error ? `Not fully checked${run?.verifier?.reasons?.[0] ? `: ${humanize(run.verifier.reasons[0])}` : ""}.` : `That answer could not be ${error ? "loaded" : "finished"}${run?.verifier?.reasons?.[0] ? `: ${humanize(run.verifier.reasons[0])}` : ""}.`}{" "}
          {onRetry && <button type="button" className="linkbtn" onClick={onRetry}>Ask again</button>}
        </p>
      )}
      {!rec && !result && !error && !failed && (
        <>
          <StatusLine className="working" text={[tr.groups[tr.groups.length - 1]?.name ?? "Overview", `${secs} s`, inParallel > 1 ? `${inParallel} specialists in parallel` : ""].filter(Boolean).join(" · ")} note={v?.phase ?? (live ? humanize(live.text) : undefined)} />
          {steps.length > 0 && <ol className="ask-steps">{steps.slice(-4).map((r) => <li key={r.id}><span title={r.full ?? r.text}>{r.who} · {r.tool} · {r.text}</span><em>{r.right}</em></li>)}</ol>}
        </>
      )}
      {result && !folded && <ResultCard data={result} runId={runId} onNavigate={onClose} />}
      {result && folded && <button type="button" className="turn-fold" onClick={() => setFolded(false)}><b>{result.finding}</b></button>}
      {!result && rec && folded && <button type="button" className="turn-fold" onClick={() => setFolded(false)}><b>{lead}</b></button>}
      {!result && rec && !folded && (
        <>
          <p className="decision"><b>{lead}</b></p>
          {rows.length > 0 && <ul className="reasons">{rows.map((r) => <li key={r}>{r}</li>)}</ul>}
          {figures.length > 0 && <div className="mini-tiles">{figures.map((n) => <div key={n.id} className="mt"><b>{n.say ?? `${n.value} ${n.unit}`}</b><span>{humanize(n.name ?? n.id)}</span></div>)}</div>}
          {sources.length > 0 && <p className="srcs">{sources.map((r) => <EntityChip key={`${r.type}:${r.id}`} r={r} />)}</p>}
          {rest.length > 0 && <><Disclose open={more} onClick={() => setMore(!more)}>{more ? "Show less" : "Read in full"}</Disclose>{more && <p className="rest">{rest.join(" ")}</p>}</>}
          <p className="src">{checks}{run ? <>{checks ? " · " : ""}<Link to={`/activity/${encodeURIComponent(runId)}`} onClick={onClose}>How we got here →</Link></> : null}</p>
          {waiting && <Link className="ask-prep" to={waiting.item_key ? `/items/${encodeURIComponent(waiting.item_key)}?draft=${waiting.action_id}` : `/approvals/${waiting.action_id}`}><span>Prepared: email to <b>{waiting.target?.label ?? waiting.recipient}</b> · nothing is sent until you approve it</span><b>Review →</b></Link>}
        </>
      )}
    </div>
  );
}
