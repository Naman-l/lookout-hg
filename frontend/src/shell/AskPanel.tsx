import { useEffect, useRef, useState } from "react";
import { ArrowUp, ArrowUpRight, CornerDownRight, X } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useResource } from "../api/useResource";
import { humanize } from "../ui/format";
import { useAskState } from "./AskContext";
import { AskComposer } from "./AskBox";
import { rankExamples, shortAbout } from "../sections/agents/ask";
import { useMedia } from "../ui/useMedia";
import { AgentMark } from "../ui/AgentMark";
import type { RunDetail } from "../api/types";

/** The conversation, beside the page (a bottom sheet below 1024 px): the scope and a close, a body that scrolls, the composer at the foot. */
export function AskPanel() {
  const { open, setOpen, thread, about, context, scope, send, err, examples } = useAskState();
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
  return (
    <aside className="aipanel" role="dialog" aria-label="Lookout's answer">
      <i className="grab" aria-hidden />
      <div className="ai-h"><i className="ai-mark" aria-hidden /><b>Ask</b><span className="meta">{scope === "all" ? "Everything" : shortAbout(about)}</span>
        <button type="button" className="x" aria-label="Close" onClick={close}><X size={16} strokeWidth={1.5} aria-hidden /></button></div>
      <div className="ai-body" ref={body}>
        {thread.length === 0 && (
          <div className="turn">
            <p className="q">What would you like to know about {scope === "all" ? "everything" : shortAbout(about)}?</p>
            {examples.length > 0 && <div className="ask-ex in">{rankExamples(examples, scope === "all" ? null : context, about).slice(0, 5).map((x) => <button key={x.question} type="button" onClick={() => send(x.question, x.context ?? null)}>{x.question}</button>)}</div>}
            <p className="ask-ex-f">No model is connected here: Lookout answers from the records by rule, and says when they do not hold the answer.</p>
          </div>
        )}
        {thread.map((t, n) => <Turn key={t.runId} runId={t.runId} question={t.question} last={n === thread.length - 1} onClose={close} onRetry={() => send(t.question)} onFollow={(q) => send(q)} />)}
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

/** A run, read again every second while it works. */
export function useRunPoll(runId: string | null) {
  const [tick, setTick] = useState(0);
  const r = useResource(() => (runId ? api.run(runId).catch(() => null) : Promise.resolve(null)), [runId, tick], true);
  useEffect(() => {
    if (!runId || (r.data && r.data.status !== "running")) return;
    const t = setTimeout(() => setTick((n) => n + 1), 700);
    return () => clearTimeout(t);
  }, [runId, r.data, tick]);
  return r.data as RunDetail | null | undefined;
}

type Table = { title: string; by: string; columns: string[]; rows: { label: string; sub?: string | null; url?: string | null; cells: ({ say: string; id: string } | null)[] }[]; more?: number; all_url?: string | null };
type Step = { agent: string; tool: string; why: string; found: string };

/** One question and its answer: the steps while it works, then the answer line, its rows and tables, what is not known and who could say, and any draft it
 * prepared (nothing is sent until its owner signs). */
export function Turn({ runId, question, last = true, onClose, onRetry, onFollow }: { runId: string; question: string; last?: boolean; onClose: () => void; onRetry?: () => void; onFollow?: (q: string) => void }) {
  const run = useRunPoll(runId);
  const [folded, setFolded] = useState(!last);
  const [how, setHow] = useState(false);
  useEffect(() => { if (last) setFolded(false); }, [last]);
  const rec = run?.recommendation as (RunDetail["recommendation"] & { points?: { label: string; text: string }[]; tables?: Table[]; open_questions?: { question: string; owner: string }[]; action_ids?: string[];
    follow_ups?: string[]; plan?: Step[] }) | null | undefined;
  const steps = (run?.events ?? []).filter((e) => ["step.text", "tool.called", "child.started"].includes(e.type));
  const plan = rec?.plan ?? [];
  const agents = [...new Set(plan.map((p) => p.agent).filter((a) => a !== "lookout"))];
  return (
    <div className="turn">
      <p className="q">{question}</p>
      {run?.status === "failed" && <p className="error">That answer could not be finished. {onRetry && <button type="button" className="linkbtn" onClick={onRetry}>Ask again</button>}</p>}
      {(!run || run.status === "running") && <ol className="ask-steps live" aria-live="polite">{steps.slice(-3).map((e) => <li key={e.seq + e.run_id}><AgentMark agent={e.agent} /><span>{e.agent_label} · {humanize(String((e.type === "tool.called" && e.payload?.why) || e.summary))}</span></li>)}<li className="ask-wait"><i /><i /><i /></li></ol>}
      {rec && folded && <button type="button" className="turn-fold" onClick={() => setFolded(false)}><b>{humanize(rec.finding)}</b></button>}
      {rec && !folded && (
        <>
          <p className="decision"><b>{humanize(rec.finding)}</b></p>
          {(rec.points ?? []).length > 0 && <ul className="reasons">{(rec.points ?? []).map((p) => <li key={p.label + p.text}><b>{p.label}</b> · {humanize(p.text)}</li>)}</ul>}
          {((rec.tables ?? []) as Table[]).map((t) => (
            <div key={t.title} className="ask-t"><p className="ask-th">{t.title} <small>· {t.by}</small></p>
              <table className="cp-t"><thead><tr><th />{t.columns.map((c) => <th key={c} className="n">{c}</th>)}</tr></thead>
                <tbody>{t.rows.map((r, i) => (
                  <tr key={r.label + i}>
                    <td>{r.url ? <Link className="ask-rl" to={r.url} onClick={onClose}>{r.label}</Link> : r.label}{r.sub && <small className="ask-rs">{r.sub}</small>}</td>
                    {r.cells.map((c, k) => <td key={k} className="n" title={c?.id || undefined}>{c?.say ?? ""}</td>)}
                  </tr>))}</tbody></table>
              {(t.more || t.all_url) ? <p className="ask-more">{t.more ? <span>+{t.more} more</span> : null}{t.all_url && <Link to={t.all_url} onClick={onClose}>See them all<ArrowUpRight size={12} strokeWidth={1.75} aria-hidden /></Link>}</p> : null}</div>
          ))}
          {(rec.open_questions ?? []).length > 0 && <ul className="reasons">{(rec.open_questions ?? []).slice(0, 4).map((u) => <li key={u.question}>Unknown · {u.question} <small>(ask {u.owner})</small></li>)}</ul>}
          {(rec.action_ids ?? []).map((a) => <Link key={a} className="ask-prep" to={`/approvals/${a}`} onClick={onClose}><span>Prepared for your signature · nothing is sent until you sign</span><b>Review →</b></Link>)}
          {plan.length > 0 && (
            <div className="ask-how">
              <button type="button" className="ask-how-btn" aria-expanded={how} onClick={() => setHow(!how)}>
                <span className="ask-how-marks" aria-hidden>{(agents.length ? agents : ["lookout"]).map((a) => <AgentMark key={a} agent={a} />)}</span>
                {plan.length} lookup{plan.length === 1 ? "" : "s"}{agents.length ? ` by the ${agents.map(agentName).join(", ")}` : ""}<small>{how ? "Hide" : "Show the steps"}</small>
              </button>
              {how && <ol className="ask-plan">{plan.map((p, i) => <li key={i}><AgentMark agent={p.agent} /><span><b>{p.why}</b><small>{p.found}</small></span></li>)}</ol>}
            </div>
          )}
          {last && onFollow && (rec.follow_ups ?? []).length > 0 && (
            <div className="ask-next" role="group" aria-label="Ask next">
              {(rec.follow_ups ?? []).slice(0, 3).map((f) => <button key={f} type="button" onClick={() => onFollow(f)}><CornerDownRight size={14} strokeWidth={1.5} aria-hidden />{f}</button>)}
            </div>
          )}
          <p className="src">Answered by code from the records, no model · <Link to={`/activity/${encodeURIComponent(runId)}`} onClick={onClose}>How we got here →</Link></p>
        </>
      )}
    </div>
  );
}

const AGENT_NAMES: Record<string, string> = { site_planner: "site planner", sourcing_analyst: "sourcing analyst", price_analyst: "price analyst", inbox_analyst: "inbox analyst", buyers_clerk: "buyer's clerk" };
const agentName = (a: string) => AGENT_NAMES[a] ?? a.replace(/_/g, " ");
