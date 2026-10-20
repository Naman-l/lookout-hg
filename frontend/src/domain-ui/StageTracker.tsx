import { useEffect, useRef, useState, type ReactNode } from "react";
import { Bot, Check, CircleHelp, ListChecks, PenLine, Reply, Search, Send, ShieldAlert, ShieldCheck } from "lucide-react";
import type { Stage } from "../api/types";
import { StepLine, type Step } from "../ds/StepLine";
import "./stage-tracker.css";

type Key = Stage["key"];
/** The seven stages, each with one icon, one name and one line of meaning (the legend on the design page reads this table). */
export const STEPS: { key: Key; name: string; Icon: typeof Search; meaning: string }[] = [
  { key: "found", name: "Found", Icon: Search, meaning: "Lookout noticed it" },
  { key: "worked", name: "Worked", Icon: Bot, meaning: "the agent has looked into it" },
  { key: "decision_ready", name: "Decision ready", Icon: ListChecks, meaning: "the options are laid out" },
  { key: "drafted", name: "Needs your OK", Icon: PenLine, meaning: "a draft waits for its owner" },
  { key: "approved", name: "Approved", Icon: ShieldCheck, meaning: "signed by a person" },
  { key: "sent", name: "Sent", Icon: Send, meaning: "left for the supplier (simulated)" },
  { key: "answered", name: "Answered", Icon: Reply, meaning: "the supplier replied" },
];
export const HELD = { name: "Held", Icon: ShieldAlert, meaning: "may be fraud; nothing can be done from it" };
export const ASKING = { name: "Asking", Icon: CircleHelp, meaning: "the data cannot answer; a person must" };
const at = (k: Key) => STEPS.findIndex((s) => s.key === k);

/** What is known about a step that is done: when, who, and where to read more. The API gives the current stage only, so a caller passes what it has. */
export type StepFact = { at?: string; by?: string; text?: string; to?: string };
export type StageState = { stage: Stage } | { kind: "held" } | { kind: "asking" };

const when = (iso?: string | null) => (iso ? `${new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" })}, ${new Date(iso).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false })}` : "");

/** COMPACT, for a list row: seven segments in a fixed column (done ink, current accent with a dot, the rest hairline), then the current stage as a fixed-width pill with its icon. Held and Asking have no segments. `near` turns the current step amber (its date is within 7 days). */
export function StageCompact({ state, near = false }: { state: StageState; near?: boolean }) {
  if ("kind" in state) {
    const k = state.kind === "held" ? HELD : ASKING;
    return <span className="stc"><span className={`stc-pill ${state.kind}`}><k.Icon size={16} strokeWidth={1.5} aria-hidden />{state.kind === "held" ? "Held: do not act" : "Asking"}</span></span>;
  }
  // One word and one icon, coloured by what it means: amber needs you (or its date is near), green is done, grey is the rest.
  const s = state.stage, now = at(s.key), step = STEPS[now];
  const tone = near || (s.key === "drafted" && s.waiting_on === "you") ? "near" : s.key === "approved" || s.key === "sent" || s.key === "answered" ? "ok" : "cur";
  return (
    <span className="stc" title={`${s.label && s.label !== step.name ? s.label + ". " : ""}Step ${now + 1} of ${STEPS.length}, ${step.name}: ${s.next_act}`}>
      <span className={`stc-pill ${tone}`}><step.Icon size={16} strokeWidth={1.5} aria-hidden />{(s.label || step.name).replace(/\s*\(.*$/, "")}</span>
      <span className={`stc-seg${tone === "near" ? " near" : ""}`} aria-hidden>{STEPS.map((x, n) => <i key={x.key} className={n < now ? "d" : n === now ? "c" : ""} />)}</span>
    </span>
  );
}

/** FULL: a stepper. Horizontal in main, vertical in a rail (`vertical`). Each step has its icon, name and, when known, a time and who; the current step has an accent ring and who has the move; a done step opens what happened (above in main, beside in a rail, always inside the page). */
export function StageStepper({ stage, facts = {}, vertical = false, near = false }: { stage: Stage; facts?: Partial<Record<Key, StepFact>>; vertical?: boolean; near?: boolean }) {
  const now = at(stage.key);
  near = near || (stage.key === "drafted" && stage.waiting_on === "you"); // needs you is amber
  const [open, setOpen] = useState<Key | null>(null);
  const root = useRef<HTMLOListElement>(null);
  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(null); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(null); };
    document.addEventListener("mousedown", down); window.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", down); window.removeEventListener("keydown", key); };
  }, [open]);
  const who = stage.waiting_on;
  return (
    <ol className={`sts${vertical ? " v" : ""}`} aria-label="Where this stands" ref={root}>
      {STEPS.map((x, n) => {
        const done = n < now, cur = n === now, f = facts[x.key] ?? (cur ? { at: stage.at ?? undefined } : undefined);
        const body = (
          <>
            <span className="sts-dot">{done ? <Check size={16} strokeWidth={2} aria-hidden /> : <x.Icon size={16} strokeWidth={1.5} aria-hidden />}</span>
            <span className="sts-t"><b>{cur && x.key === "drafted" ? "Needs your OK" : x.name}</b>
              {f && (f.at || f.by) && <small>{[when(f.at), f.by].filter(Boolean).join(" · ")}</small>}
              {cur && who && <span className="sts-wait"><i className="av">{who === "you" ? "You" : who.slice(0, 2).toUpperCase()}</i>Waiting on {who}</span>}
            </span>
          </>
        );
        return (
          <li key={x.key} className={`sts-s${done ? " d" : cur ? ` c${near ? " near" : ""}` : " f"}`} aria-current={cur ? "step" : undefined}>
            {done ? <button type="button" className="sts-b" aria-expanded={open === x.key} onClick={() => setOpen(open === x.key ? null : x.key)}>{body}</button> : <div className="sts-b">{body}</div>}
            {done && open === x.key && (
              <div className="sts-pop" role="dialog" aria-label={x.name}>
                <b>{x.name}{f?.at ? `, ${when(f.at)}` : ""}</b>
                <p>{f?.text ?? x.meaning}{f?.by ? ` (${f.by})` : ""}</p>
                {f?.to && <a href={f.to}>Open it</a>}
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}

/** In a rail: the stage word with its icon, a seven-part progress bar under it, one quiet line (step, who has the move, when), and All steps opens the vertical stepper. */
/** `waitingOn` names who has the move when the viewer is not the signer: the API says "you" to every viewer, meaning the owner. */
export function StageRail({ stage, facts, near = false, waitingOn }: { stage: Stage; facts?: Partial<Record<Key, StepFact>>; near?: boolean; waitingOn?: string }) {
  const [all, setAll] = useState(false);
  const now = at(stage.key), step = STEPS[now], who = waitingOn && stage.waiting_on === "you" ? waitingOn : stage.waiting_on;
  const amber = near || (stage.key === "drafted" && who === "you");
  const tone = amber ? "near" : stage.key === "approved" || stage.key === "sent" || stage.key === "answered" ? "ok" : "cur";
  const line = [`Step ${now + 1} of ${STEPS.length}`, who ? `waiting on ${who}` : "", when(stage.at)].filter(Boolean).join(" · ");
  return (
    <div className="str" title={`${step.name}: ${stage.next_act}`}>
      <span className={`stc-pill ${tone}`}><step.Icon size={16} strokeWidth={1.5} aria-hidden />{(stage.label || step.name).replace(/\s*\(.*$/, "")}</span>
      <span className={`stc-seg${amber ? " near" : ""}`} aria-hidden>
        {STEPS.map((x, n) => <i key={n === now ? `${stage.key}-now` : x.key} className={n < now ? "d" : n === now ? "c" : ""} />)}
      </span>
      <small className="str-wait">{line}</small>
      <button type="button" className="stl-tog" aria-expanded={all} onClick={() => setAll(!all)}>{all ? "Hide steps" : "All steps"}</button>
      {all && <StageStepper stage={stage} facts={facts} vertical near={near} />}
    </div>
  );
}

/** The stage as the shared one-line StepLine: the seven stages, the current one named, who has the move. */
export function StageLine({ stage, near = false }: { stage: Stage; near?: boolean }) {
  const now = at(stage.key), who = stage.waiting_on;
  const mine = stage.key === "drafted" && who === "you";
  const tone = near || mine ? "amber" : stage.key === "approved" || stage.key === "sent" || stage.key === "answered" ? "green" : "grey";
  const steps: Step[] = STEPS.map((x, n) => ({ word: x.name, state: n < now ? "done" : n === now ? "current" : "todo" }));
  return <StepLine steps={steps} label={(stage.label || STEPS[now].name).replace(/\s*\(.*$/, "")} note={who ? `· waiting on ${who}` : null} tone={tone} />;
}

/** Held in the item header: the same line, red, with the one reason. */
export function StageHeld({ children }: { children: ReactNode }) {
  return <span className="stl"><i className="stl-dot red" aria-hidden /><b>Held</b><span className="stl-wait">· {children}</span></span>;
}

/** Held and Asking, in the item header. */
export function StageNote({ kind, children }: { kind: "held" | "asking"; children: ReactNode }) {
  return <div className="str-note"><StageCompact state={{ kind }} /><span>{children}</span></div>;
}
