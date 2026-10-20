import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useResource, invalidate } from "../api/useResource";
import { useMe } from "../api/useMe";
import type { Action } from "../api/types";
import { useRun } from "../organism/useRun";
import { buildRun } from "../organism/runModel";
import { agentName, humanize } from "../ui/format";
import "./case-ask.css";

/** A change in flight, by draft id: the card that lists drafts reloads (and remounts this) while the clerk works, so the run is kept here, not in the component. */
type Flight = { runId: string; before: Action; after?: Action };
const pending = new Map<string, Flight>();
const reads = new Map<string, number>();      // reads of the draft after the run ended, by run: a remount does not start the count again

/** "Ask for changes" on a waiting draft (C3, F94/F100): a short box under the draft. The words go to Lookout's clerk, which
 * changes the draft through amend_draft (the only path that edits a draft); the panel then shows the new text with the change
 * marked (only what changed; the card shows the whole new text). The text has a new hash, so the owner signs again: nothing approved before carries over. Live only.
 * Standalone: the case's Approval card and Approvals mount it under the draft. */
export function AskForChanges({ action, onAmended }: { action: Action; onAmended?: (a: Action) => void }) {
  const { me } = useMe();
  const live = useResource(api.health).data?.agent_live === true;
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [flight, setFlight] = useState(() => pending.get(action.action_id) ?? null);
  const runId = flight?.runId ?? null, before = flight?.before ?? null;
  const start = (f: Flight | null) => { if (f) pending.set(action.action_id, f); else pending.delete(action.action_id); setFlight(f); };
  const [err, setErr] = useState<string | null>(null);
  if (action.state !== "proposed" && !flight) return null;
  if (!open && !runId) return <p className="afc"><button type="button" className="cask-link" disabled={!live} title={live ? "Tell Lookout what to change; you sign the new text" : "Live only: the agent is not connected"} onClick={() => setOpen(true)}>Ask for changes…</button>{!live && <span className="afc-note"> · live only</span>}</p>;
  const send = async () => {
    const what = text.trim();
    if (!what) return;
    setErr(null);
    try {
      const to = (action.recipient ?? "").replace(/\s*<.*>$/, "");
      const r = await api.ask(`Change the waiting draft ${action.action_id}${to ? ` to ${to}` : ""}: ${what}. Change that draft with amend_draft; do not write a new one.`, { type: "action", id: action.action_id }, me ?? "", null);
      start({ runId: r.run_id, before: action }); setOpen(false);
    } catch (e) {
      setErr((e as Error).message === "no-model" ? "Live only: the agent is not connected." : "Lookout could not be reached. Try again.");
    }
  };
  if (flight && runId && before) return <Amending flight={flight} onSettled={(after) => { const f = { ...flight, after }; pending.set(action.action_id, f); setFlight(f); if (after.payload_hash !== before.payload_hash) onAmended?.(after); }} onAgain={() => { start(null); setOpen(true); }} />;
  return (
    <form className="afc-box" onSubmit={(e) => { e.preventDefault(); void send(); }}>
      <textarea rows={2} autoFocus aria-label="What should change?" placeholder="What should change?" value={text} onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } if (e.key === "Escape") setOpen(false); }} />
      <div className="afc-row">
        {err && <span className="afc-err" role="status">{err}</span>}
        <button type="button" className="cask-link" onClick={() => setOpen(false)}>Cancel</button>
        <button type="submit" className="b9 dark" disabled={!text.trim()}>Ask for changes</button>
      </div>
    </form>
  );
}

/** While the clerk works: "Working… · Buyer's clerk". Then the new text with what was added marked, and the one consequence: a new signature. */
function Amending({ flight, onSettled, onAgain }: { flight: Flight; onSettled: (after: Action) => void; onAgain: () => void }) {
  const { runId, before } = flight;
  const after = flight.after ?? null;
  const { run, events, error } = useRun(runId);
  const ended = !!error || (!!run && run.status !== "running");
  const [tries, setTries] = useState(() => reads.get(flight.runId) ?? 0);
  const bump = () => setTries((n) => { reads.set(runId, n + 1); return n + 1; });
  useEffect(() => {
    if (!ended || after) return;
    // the amended draft keeps its action id; read it until the run's change is there (or the run is over without one)
    const t = setTimeout(() => api.action(before.action_id).then((a) => {
      if (a.payload_hash !== before.payload_hash || tries >= 4) { invalidate(); onSettled(a); } else bump();
    }).catch(bump), tries ? 1200 : 0);
    return () => clearTimeout(t);
  }, [ended, after, tries, before, onSettled]);
  const v = run ? buildRun(events, run.run_id ?? runId) : null;
  const who = v?.segments.find((s) => s.live)?.label ?? (run?.specialists ?? []).map((s) => agentName(s.agent)).pop() ?? "Lookout";
  if (!after) return <p className="afc cask-work" role="status">Working… <span>· {who}</span></p>;
  const changed = after.payload_hash !== before.payload_hash;
  if (!changed) {
    const why = run?.recommendation?.finding ? humanize(run.recommendation.finding) : "Lookout did not change the draft.";
    return <div className="afc-done"><p className="afc-lead">Not changed: {why}</p><button type="button" className="cask-link" onClick={onAgain}>Ask again</button></div>;
  }
  const old = new Set((before.body ?? "").split("\n").map((l) => l.trim()).filter(Boolean));
  const added = (after.body ?? "").split("\n").filter((l) => l.trim() && !old.has(l.trim()));      // the card's draft shows the whole new text; this shows what changed
  return (
    <div className="afc-done">
      <p className="afc-lead">Changed · needs your signature again</p>
      {added.length > 0 && <div className="afc-body">{added.map((l, n) => <ins key={n}>{l}</ins>)}</div>}
      <button type="button" className="cask-link" onClick={onAgain}>Ask for more changes…</button>
    </div>
  );
}
