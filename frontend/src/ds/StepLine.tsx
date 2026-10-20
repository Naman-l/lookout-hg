import { useState, type ReactNode } from "react";
import "./step-line.css";

export type StepState = "done" | "current" | "todo" | "problem" | "unknown" | "na";
export interface Step { word: string; state: StepState; date?: string }
export type StepTone = "amber" | "green" | "red" | "grey";

/** Where something stands, as one line: a dot and the word, who has the move, a text toggle; opened, the steps are one row of words
 *  (done muted, current bold, a problem red, todo and unknown light, unknown with a ?, not-applicable left out). The one component for an item, a draft and a part. */
export function StepLine({ steps, label, note, tone, closed = "All steps", open = "Hide steps", children }: { children?: ReactNode; steps: Step[]; label?: string; note?: string | null /* shown as given: the caller writes its own "· " */; tone?: StepTone; closed?: string; open?: string }) {
  const [all, setAll] = useState(false);
  const cur = steps.find((s) => s.state === "problem") ?? steps.find((s) => s.state === "current");
  const dot: StepTone = tone ?? (cur?.state === "problem" ? "red" : "grey");
  const shown = steps.filter((s) => s.state !== "na");
  return (
    <>
      <span className="stl">
        <i className={`stl-dot ${dot}`} aria-hidden /><b>{label ?? cur?.word ?? ""}</b>{note && <span className="stl-wait">{note}</span>}
        {shown.length > 1 && <button type="button" className="stl-tog" aria-expanded={all} onClick={() => setAll(!all)}>{all ? open : closed}</button>}
      </span>
      {all && (
        <ol className="stl-steps" aria-label="Steps">
          {shown.map((s, n) => <li key={n} className={`s-${s.state}`} aria-current={s.state === "current" ? "step" : undefined} title={s.date}>{s.word}{s.state === "unknown" ? "?" : ""}</li>)}
        </ol>
      )}
      {all && children && <div className="stl-more">{children}</div>}
    </>
  );
}
