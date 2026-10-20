import { api } from "../api/client";
import { useResource } from "../api/useResource";
import type { Ladder as LadderT } from "../api/types";
import { humanize, shortDate } from "../ui/format";
import { StepLine, type Step } from "../ds/StepLine";

type StepState = "done" | "current" | "todo" | "problem" | "unknown" | "na";
const STEP: Record<string, StepState> = { done: "done", expected: "todo", late: "problem", disrupted: "problem", unknown: "unknown", na: "na" };
const WORD: Record<string, string> = { late: "late", disrupted: "disrupted", expected: "expected" };

/** "the supplier", a buyer's first name: the person to ask, as the API names them. */
const ask = (o: string) => (o === o.toLowerCase() ? `the ${o}` : o);

/** The counts as a short phrase: "3 shown · 2 disrupted · 8 unknown". Never a percent. */
export function ladderCounts(l: LadderT): string {
  const c = l.counts ?? {};
  return [["done", "shown"], ["expected", "expected"], ["late", "late"], ["disrupted", "disrupted"], ["unknown", "unknown"]]
    .filter(([k]) => (c[k] ?? 0) > 0).map(([k, w]) => `${c[k]} ${w}`).join(" · ");
}

/** Where it stands in one line, the steps behind "All steps", and under them who to ask for what the records do not show. */
export function Ladder({ ladder }: { ladder: LadderT }) {
  const rungs = ladder.rungs;
  const bad = rungs.find((r) => r.state === "disrupted" || r.state === "late");
  const next = rungs.find((r) => r.state === "expected");
  const here = bad ?? next ?? [...rungs].reverse().find((r) => r.state === "done");
  const steps: Step[] = rungs.map((r) => ({ word: r.label, state: r === here && !bad ? "current" : STEP[r.state], date: r.date ? shortDate(r.date) : undefined }));
  const unknown = rungs.filter((r) => r.state === "unknown");
  const owners = new Map<string, number>();
  for (const r of unknown) { const o = ask(r.unknown?.owner ?? "supplier"); owners.set(o, (owners.get(o) ?? 0) + 1); }
  const missing = unknown.length ? `${unknown.length} ${unknown.length === 1 ? "step" : "steps"} not in the data` : "";
  const label = here ? (WORD[here.state] ? `${here.label}, ${WORD[here.state]}` : here.label) : "Not started";
  const note = [bad || next ? humanize(here?.detail ?? "") : "", missing].filter(Boolean).map((t) => ` · ${t}`).join("");
  return (
    <div className="ladder"><StepLine steps={steps} label={label} tone={bad ? "red" : next ? "amber" : "green"} note={note}>
      {owners.size > 0 && <p className="ladder-ask">Not in the data: ask {[...owners].map(([o, n]) => `${o} (${n})`).join(", ")}</p>}
    </StepLine></div>
  );
}

/** The stage ladder of one PO line, fetched when its row is opened. */
export function PoLineStages({ id }: { id: string }) {
  const r = useResource(() => api.phasesLine(id), [id]);
  if (r.loading) return <span className="skel" style={{ width: 280 }} />;
  if (r.error || !r.data) return <p className="empty">The stages of this line could not be loaded.</p>;
  return <Ladder ladder={r.data} />;
}
