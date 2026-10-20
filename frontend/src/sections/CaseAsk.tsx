import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { namedQuestions, SHOWN } from "../domain-ui/openQuestions";
import { Link } from "react-router-dom";
import { ArrowUp, X } from "lucide-react";
import { api } from "../api/client";
import { useResource } from "../api/useResource";
import { useMe } from "../api/useMe";
import type { Action, RunDetail } from "../api/types";
import { useRun } from "../organism/useRun";
import { buildRun } from "../organism/runModel";
import { agentName, humanize } from "../ui/format";
import { useAskState } from "../shell/AskContext";
import { stagedOf } from "../domain-ui/StagedNote";
import { shortAbout } from "./agents/ask";
import "./case-page.css";
import "./case-ask.css";

/** A table an answer that compares or lists comes back as (AGENT-BUILD-2's `tables`, built by code from the run's own tool results):
 * the Analysis card's table. A cell is a figure resolved by code ({id, say}) or null; the agent never types a figure. */
export type AskCell = { id: string; say: string } | string | null;
type Row = { label: string; cells: AskCell[]; ref?: { type: string; id: string } | null; part?: string | null; note?: string | null };
export type AskTable = { kind?: string; title: string; by?: string; columns: string[]; rows: (Row | AskCell[])[]; more?: number; more_what?: string | null };
/** the row-label column's header, by table kind (`columns` holds the figure columns only) */
const HEAD: Record<string, string> = { shortfall: "Part", po_lines: "PO line", late_lines: "PO line", exposure: "Part", quotes: "Quote" };
const cellText = (c: AskCell | undefined) => (c == null ? "" : typeof c === "string" ? c : c.say);
type Done = { text?: string | null; label?: string | null; action_id: string; stage?: string | null };
type Rec = NonNullable<RunDetail["recommendation"]> & { tables?: AskTable[] };
export type Turn = { runId: string; question: string };

const KEEP = 3;      // the thread the panel shows and the agent carries: the last 3 turns
const ROWS = 6;      // a table in the panel: 6 rows, then "+N more"
const sentences = (t: string) => t.split(/(?<=[.!?])\s+(?=[A-Z$0-9"“])/).map((x) => x.trim()).filter(Boolean);
const PROMPTS = ["Which of these lines stops a build first?", "Compare the other suppliers' prices for these parts", "What happens to next month if nothing lands?"];

/** The Ask panel on a case (F100, ask-panel.md): a working session beside the case, in the RightPanel frame at 400.
 * The buyer works the case with Lookout over a few turns; an answer that compares or lists is a table; when Lookout prepares
 * something it is filed under the case and the turn ends on "Prepared: … · Review ›", which opens the case's Approval card.
 * Nothing is approved or sent from here. Standalone: the case page mounts it in the rail's place. */
export function CaseAskPanel({ caseKey, title, about, seed, onSeeded, onClose, onReview, bound, bare }: {
  caseKey: string; title: string;
  /** the shared conversation (AskContext): the docked Ask bar and the case's buttons ask into the same thread; without it the panel keeps its own */
  bound?: { turns: Turn[]; send: (q: string) => Promise<boolean>; err: string | null; recorded: boolean };
  /** inside a frame that is already drawn (the shell's Ask column): no outline of its own */
  bare?: boolean;
  /** called once the seed is in the input, so it is not put there again */
  onSeeded?: () => void;
  /** the step the buyer is on, for the scope chip ("About: Decision") */
  about?: string;
  /** text to start the input with ("Ask for another option") */
  seed?: string;
  onClose: () => void;
  /** open the case's Approval card for a prepared draft; without it, the draft opens in Approvals */
  onReview?: (actionId: string) => void;
}) {
  const { me } = useMe();
  const health = useResource(api.health);
  const live = health.data?.agent_live === true;
  const recorded = bound ? bound.recorded : health.data ? !live : false;
  const examples = useResource(() => api.askExamples().catch(() => []), []);
  const mine = (examples.data ?? []).filter((x) => x.context?.id === caseKey).map((x) => x.question);
  const [own, setOwn] = useState<Turn[]>([]);
  const turns = (bound?.turns ?? own).slice(-KEEP);
  const [text, setText] = useState(seed ?? "");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const body = useRef<HTMLDivElement>(null);
  const frame = useRef<HTMLElement>(null);
  useEffect(() => {
    if (bare) return;
    const fit = () => { const el = frame.current; if (!el || getComputedStyle(el).position !== "sticky") { if (el) el.style.height = ""; return; } el.style.height = `${Math.max(320, window.innerHeight - Math.max(el.getBoundingClientRect().top, 16) - 16)}px`; };
    fit();
    window.addEventListener("resize", fit); document.addEventListener("scroll", fit, true);
    return () => { window.removeEventListener("resize", fit); document.removeEventListener("scroll", fit, true); };
  }, [bare]);
  const input = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { if (seed) { setText(seed); onSeeded?.(); setTimeout(() => { const el = input.current; if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); } }, 0); } }, [seed, onSeeded]);
  useEffect(() => { input.current?.focus(); }, []);
  useEffect(() => {
    const h = (e: globalThis.KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  useEffect(() => { body.current?.scrollTo({ top: body.current.scrollHeight, behavior: "smooth" }); }, [turns.length]);

  const send = async (q: string) => {
    const question = q.trim();
    if (!question || busy) return;
    setErr(null); setBusy(true);
    if (bound) { const ok = await bound.send(question); if (ok) setText(""); setBusy(false); return; }
    try {
      const last = turns[turns.length - 1]?.runId ?? null;
      const r = await api.ask(question, { type: "item", id: caseKey, label: title }, me ?? "", last);
      setOwn((t) => [...t, { runId: r.run_id, question }].slice(-KEEP));
      setText("");
    } catch (e) {
      setErr((e as Error).message === "no-model" ? "Live answers need the agent connected. The recorded questions still answer." : "Ask could not be reached. Try again.");
    } finally { setBusy(false); }
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(text); }
    else if (e.key === "ArrowUp" && !text && turns.length) { e.preventDefault(); setText(turns[turns.length - 1].question); }
  };
  const suggestions = recorded ? mine : mine.length ? mine.slice(0, 3) : PROMPTS;

  return (
    <aside ref={frame} className={`cask${bare ? " bare" : ""}`} role="complementary" aria-label={`Ask about ${title}`}>
      <div className="cask-h">
        <b title={title}>Ask · {title}</b>
        <button type="button" className="cask-x" aria-label="Close Ask" onClick={onClose}><X size={16} strokeWidth={1.5} aria-hidden /></button>
      </div>
      {recorded && <p className="cask-cap">Recorded examples · live answers need the agent</p>}
      <div className="cask-body" ref={body}>
        {turns.length === 0 && !text.trim() && suggestions.length > 0 && (
          <div className="cask-sugg">{suggestions.map((s) => <button key={s} type="button" onClick={() => void send(s)} disabled={busy}>{s}</button>)}</div>
        )}
        {turns.map((t) => <AskTurn key={t.runId} caseKey={caseKey} runId={t.runId} question={t.question} onReview={onReview} onRetry={() => void send(t.question)} />)}
        {(bound?.err ?? err) && <p className="cask-err" role="status">{bound?.err ?? err}</p>}
      </div>
      <form className="cask-in" onSubmit={(e) => { e.preventDefault(); void send(text); }}>
        {about && <span className="cask-chip">About: {about}</span>}
        <div className="cask-row">
          <textarea ref={input} rows={1} aria-label="Ask Lookout about this case" value={text} disabled={recorded}
            placeholder={recorded ? "Live only · showing recorded answers" : turns.length ? "Ask a follow-up…" : "Ask about this case…"}
            onChange={(e) => setText(e.target.value)} onKeyDown={onKey} />
          <button type="submit" className={`cask-go${text.trim() ? " on" : ""}`} aria-label="Send" disabled={recorded || busy || !text.trim()}><ArrowUp size={16} strokeWidth={2} aria-hidden /></button>
        </div>
      </form>
    </aside>
  );
}

/** The panel in the case's rail slot (F104: the rail's place, the frame, sticky), on the shared conversation. The case page mounts it
 * where the rail is while Ask is open: `{ask.open ? <CaseAskSlot about={step} /> : <Rail … />}`. */
export function CaseAskSlot({ about }: { about?: string }) {
  const ask = useAskState();
  const ctx = ask.context;
  if (!ctx || ctx.type !== "item") return null;
  return <CaseAskPanel caseKey={ctx.id} title={shortAbout(ask.about)} about={about} seed={ask.prefill || undefined} onSeeded={ask.takePrefill} onClose={() => ask.setOpen(false)}
    bound={{ turns: ask.thread, send: (q) => ask.send(q, ctx), err: ask.err, recorded: ask.connected === false }} />;
}

/** One turn: the question, then "Working… · <specialist>" while it runs, then the answer line, its table or rows, who worked and what was checked, and what was prepared. */
/** One Ask turn, wherever Ask is open (the case slot and the shell's panel): one renderer, so no screen shows the run's inner steps. */
export function AskTurn({ caseKey, runId, question, onReview, onRetry }: { caseKey?: string; runId: string; question: string; onReview?: (id: string) => void; onRetry: () => void }) {
  const { run: streamed, events, error } = useRun(runId);
  // A run can report finished a moment before its answer is stored: read it again until the answer is there (up to a minute: the answer is written after the checks), so a turn never ends blank.
  const [fresh, setFresh] = useState<RunDetail | null>(null);
  const run = fresh ?? streamed;
  const ended = !!streamed && streamed.status !== "running";
  useEffect(() => {
    if (!ended || run?.recommendation || run?.status === "failed") return;
    let n = 0, live = true;
    const t = setInterval(() => { n++; api.run(runId).then((r) => { if (live && (r.recommendation || r.status === "failed" || n >= 50)) { setFresh(r); clearInterval(t); } }).catch(() => {}); }, 1200);
    return () => { live = false; clearInterval(t); };
  }, [ended, runId, run?.recommendation, run?.status]);
  const v = streamed ? buildRun(events, streamed.run_id ?? runId) : null;
  const rec = (run?.recommendation ?? null) as Rec | null;
  const failed = !!error || run?.status === "failed" || (ended && !rec && !!fresh);
  const running = !error && !failed && !rec;
  const [secs, setSecs] = useState(0);
  useEffect(() => { if (!running) return; const t0 = Date.now(); const t = setInterval(() => setSecs(Math.round((Date.now() - t0) / 1000)), 1000); return () => clearInterval(t); }, [running]);
  const done = ((rec as { done?: Done[] } | null)?.done ?? []).filter((d) => d.action_id);
  const prepared = useResource(() => (running ? Promise.resolve([] as Action[]) : api.actions("proposed").then((a) => a.filter((x) => x.run_id === runId || done.some((d) => d.action_id === x.action_id))).catch(() => [] as Action[])), [runId, running, caseKey]);
  const team = [...new Set([...(run?.specialists ?? []).map((s) => agentName(s.agent)), ...(v?.agents ?? []).filter((a) => a !== "Lookout")].map((a) => a.replace(/’/g, "'")))].filter(Boolean);
  const who = v?.segments.find((s) => s.live)?.label ?? team[team.length - 1] ?? "Lookout";
  const parts = rec ? sentences(humanize(rec.finding)) : [];
  const tables = ((run as { tables?: AskTable[] } | null)?.tables ?? rec?.tables ?? []).filter((t) => t.rows.length > 0);      // RunDetail.tables, built by code from the run's own lookups
  const points = rec?.points ?? [];
  const oq = (rec?.open_questions ?? []) as { what: string; question?: string | null; owner?: string | null }[];
  const oqFirst = (run as { open_questions_first?: number | null } | null)?.open_questions_first;      // the Ask's open questions, ordered by code: show the first N, fold the rest

  const ver = run?.verifier;
  const checked = ver?.numbers_checked ?? 0, fromTools = ver?.numbers_from_tools ?? checked;
  const foot = [team.length ? team.join(" · ") : "Lookout", checked ? `${checked} figure${checked === 1 ? "" : "s"} checked` : ""].filter(Boolean).join(" · ");
  const review = (id: string) => (onReview ? <button type="button" className="cask-link b" onClick={() => onReview(id)}>Review ›</button>
    : <Link className="cask-link b" to={caseKey ? `/items/${encodeURIComponent(caseKey)}?draft=${encodeURIComponent(id)}` : `/approvals/${encodeURIComponent(id)}`}>Review ›</Link>);
  return (
    <div className="cask-turn">
      <p className="cask-q">{question}</p>
      {running && <p className="cask-work" role="status">Working… <span>· {who}{secs >= 3 ? <em> · {secs} s</em> : null}</span></p>}
      {failed && <p className="cask-err">That answer could not be finished. <button type="button" className="cask-link" onClick={onRetry}>Ask again</button></p>}
      {rec && (
        <div className="cask-a">
          <p className="cask-lead">{parts[0]}</p>
          {parts.length > 1 && <p className="cask-rest">{parts.slice(1, 3).join(" ")}</p>}
          {tables.map((t) => <AskTableView key={t.title} t={t} />)}
          {tables.length === 0 && points.length > 0 && <dl className="cask-kv">{points.map((p) => <div key={p.label + p.text}><dt>{p.label}</dt><dd>{humanize(p.text)}</dd></div>)}</dl>}
          {oq.length > 0 && <OpenQuestions qs={oq} first={oqFirst} />}
          <p className="cask-foot">{foot}{fromTools < checked && <span className="nc"> · {checked - fromTools} not checked</span>}{" · "}<Link to={`/activity/${encodeURIComponent(runId)}`}>How</Link></p>
          {(prepared.data ?? []).map((a) => <div key={a.action_id} className="cask-prep"><span>Prepared: {preparedLine(a)}</span>{review(a.action_id)}</div>)}
        </div>
      )}
    </div>
  );
}

/** "Still open": the first N questions the answer leaves open (code's order), the rest behind "+K other open questions". Without N from the run, none are shown. */
function OpenQuestions({ qs, first }: { qs: { what: string; question?: string | null; owner?: string | null }[]; first?: number | null }) {
  const [all, setAll] = useState(false);
  if (first == null) return null;
  const named = namedQuestions(qs);      // each names its part or PO line; the phase template and unnamed guesses are left out (BUYER R2)
  if (named.length === 0) return null;
  const shown = all ? named : named.slice(0, Math.min(first, SHOWN));
  const rest = named.length - shown.length;
  return (
    <div className="cask-oq">
      <h5>Still open</h5>
      <ul>{shown.map((q) => <li key={q.text}>{humanize(q.text)}{q.owner && <span> · {q.owner}</span>}</li>)}</ul>
      {rest > 0 && <button type="button" className="cask-link" onClick={() => setAll(true)}>+{rest} other open {rest === 1 ? "question" : "questions"}</button>}
    </div>
  );
}

function AskTableView({ t }: { t: AskTable }) {
  const rows: Row[] = t.rows.map((r) => (Array.isArray(r) ? { label: "", cells: r } : r));
  const labelled = rows.some((r) => r.label);
  const shown = rows.slice(0, ROWS);
  const more = (t.more ?? 0) + Math.max(0, rows.length - ROWS);
  // a column of figures is right-aligned
  const num = (n: number) => rows.some((r) => { const c = r.cells[n]; return !!c && typeof c === "object"; }) && rows.every((r) => { const c = r.cells[n]; return c == null || typeof c === "object" || /^[\s$€£%0-9.,+−-]*$/.test(c); });
  const cols = t.columns.length > (rows[0]?.cells.length ?? 0) && labelled ? t.columns.slice(1) : t.columns;      // a shape that still carries the label header
  return (
    <div className="cask-t">
      <h5>{t.title}{t.by && <span> · {t.by}</span>}</h5>
      <table className="cp-t"><thead><tr>{labelled && <th>{t.columns.length > cols.length ? t.columns[0] : HEAD[t.kind ?? ""] ?? ""}</th>}{cols.map((c, n) => <th key={c + n} className={num(n) ? "n" : undefined}>{c}</th>)}</tr></thead>
        <tbody>{shown.map((r, k) => <tr key={k}>{labelled && <td>{r.label}{r.part && t.kind === "quotes" && <small>{r.part}</small>}{r.note && <span className="cask-note">{r.note}</span>}</td>}      {/* the row's note: code's own words (a late line's supplier, days past due, buyer, robot) */}{r.cells.map((c, n) => <td key={n} className={num(n) ? "n" : undefined} title={c && typeof c === "object" ? c.id : undefined}>{cellText(c) || "—"}</td>)}</tr>)}</tbody></table>
      {more > 0 && <p className="cask-more">+{more} {t.more_what ?? "in Analysis"}</p>}      {/* more_what: the rows not named are counted, never hidden */}
    </div>
  );
}

/** "email to <contact> · <subject>", "decision · <subject>", "PO-line update · <subject>", "note to <reader> · <subject>": what it is and to whom (the words Approvals uses). */
function preparedLine(a: Action): string {
  const c = stagedOf(a);
  const kind = c ? (c.kind === "record" ? "decision" : c.kind === "erp_update" ? "PO-line update" : `note${c.to ? ` to ${c.to}` : ""}`) : a.type === "note" ? "note" : `email${a.recipient ? ` to ${a.recipient.replace(/\s*<.*>$/, "")}` : ""}`;
  const what = a.title ?? a.subject ?? "";
  return `${kind}${what && what.toLowerCase() !== kind.split(" ")[0].toLowerCase() ? ` · ${what}` : ""}`;
}
