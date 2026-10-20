// Turns a run's events into what How we got here shows. Pure: no React, no fetching, so it is unit-checkable.
import type { RunEvent } from "../api/types";
import { agentName, humanize } from "../ui/format";

export type Gate = "allowed" | "denied" | "staged";

export interface Line { id: string; text: string; why?: string; detail?: string; gate?: Gate; ms: number; status: "done" | "denied" | "live"; action?: string; quiet?: boolean }
export interface Delegation {
  id: string; agent: string; label: string; question: string; answer?: string; startMs: number; ms: number; done: boolean; lines: Line[];
}
export type Row = { kind: "line"; line: Line } | { kind: "delegation"; d: Delegation };

export interface RunView {
  rows: Row[];
  finished: boolean; failed: boolean; verified: boolean;
  elapsedMs: number; agents: string[]; toolCalls: number; denied: number; costUsd?: string;
  /** What a person is told while the run is past its last lookup: the agent checks and writes, in words; undefined while a lookup is live or once it ends. */
  phase?: string;
  rewrites: number;
  segments: { label: string; agent: string; from: number; to: number; live: boolean }[];
}

const say = humanize;

/** The agent fixing its own work, not a gate saying no: an answer sent back to fit the format, or a hand-off not ready yet. */
const isSelfCorrection = (tool: unknown, reason: string) =>
  tool === "StructuredOutput" || /^(wait for .+ to (finish|hand off)|read .+ handoff first)/.test(reason);
const times = (n: number) => (n === 1 ? "once" : n === 2 ? "twice" : `${n} times`);

/** Narration that says nothing new ("still waiting for the clerk", "that is still running"): not a step. */
export const isFiller = (text: string) => /\bstill (waiting|running)\b|\bthat is still running\b|\bI'll (wait|check back)\b/i.test(text);
const payload = (e: RunEvent): Record<string, unknown> => (e.payload ?? {}) as Record<string, unknown>;

export function buildRun(events: RunEvent[], runId: string): RunView {
  const sorted = [...events].sort((a, b) => a.t_ms - b.t_ms || a.seq - b.seq);
  const rows: Row[] = [];
  const kids = new Map<string, Delegation>();
  const results = new Map<string, RunEvent>();
  for (const e of sorted) if (e.type === "tool.result" && e.tool_use_id) results.set(e.tool_use_id, e);

  const finishedRun = sorted.some((e) => e.type === "run.finished" || e.type === "run.failed");
  let toolCalls = 0, denied = 0, rewrites = 0, finished = false, failed = false, verified = false, elapsed = 0, cost: string | undefined;
  for (const e of sorted) {
    elapsed = Math.max(elapsed, e.t_ms);
    const own = e.run_id === runId;
    const p = payload(e);
    switch (e.type) {
      case "child.started": {
        const id = String(p.child_run_id ?? e.tool_use_id ?? e.seq);
        // A delegation names the specialist it asks. If the event still carries Lookout as its agent, read the
        // specialist out of "Lookout asked the Supply planner: <question>".
        const m = e.summary.match(/^Lookout asked the (.+?):\s*(.*)$/);
        const label = m ? m[1] : agentName(e.agent_label ?? e.agent) || "Specialist";
        const agent = m ? label.toLowerCase().replace(/[’']/g, "").replace(/\s+/g, "_") : e.agent ?? "";
        const d: Delegation = { id, agent, label, question: say(m ? m[2] : e.summary), startMs: e.t_ms, ms: e.t_ms, done: false, lines: [] };
        kids.set(id, d); rows.push({ kind: "delegation", d });
        break;
      }
      case "child.finished": {
        const d = kids.get(String(p.child_run_id ?? e.tool_use_id ?? ""));
        if (d) { d.done = true; d.answer = say(e.summary); d.ms = e.t_ms; }
        break;
      }
      case "tool.called": {
        const reason = String(p.gate_reason ?? "");
        if (p.gate === "denied" && isSelfCorrection(p.tool ?? p.name, reason)) { rewrites++; break; }
        toolCalls++;
        const gate = (p.gate as Gate | undefined) ?? "allowed";
        if (gate === "denied") denied++;
        const res = e.tool_use_id ? results.get(e.tool_use_id) : undefined;
        const line: Line = {
          id: `${e.run_id}-${e.seq}`, text: say(res?.summary ?? e.summary), gate, ms: (res ?? e).t_ms,
          detail: gate === "denied" ? String(p.gate_reason ?? "") : undefined,
          why: gate !== "denied" && typeof p.why === "string" && p.why ? say(p.why) : undefined,
          status: gate === "denied" ? "denied" : res || gate === "staged" || finishedRun ? "done" : "live",
        };
        place(rows, kids, own, e, line);
        break;
      }
      case "step.text": if (isFiller(e.summary)) break; place(rows, kids, own, e, { id: `${e.run_id}-${e.seq}`, text: say(e.summary), ms: e.t_ms, status: "done" }); break;
      case "action.staged": {
        const a = (e.refs ?? []).find((r) => r.type === "action");
        place(rows, kids, own, e, { id: `${e.run_id}-${e.seq}`, text: e.summary, ms: e.t_ms, status: "done", gate: "staged", action: a?.id });
        break;
      }
      case "verifier.result": verified = true; rows.push({ kind: "line", line: { id: `v${e.seq}`, text: checkWords(e.summary, sorted.some((x) => x.type === "revision.started" && x.seq > e.seq)), ms: e.t_ms, status: "done" } }); break;
      case "run.finished": finished = true; cost = typeof p.cost_usd === "string" ? p.cost_usd : p.cost_usd != null ? String(p.cost_usd) : undefined; break;
      case "run.failed": finished = true; failed = true; break;
      default: break;
    }
  }
  // the format-fixing note is part of the finished trace; while the run goes it is never the status
  if (rewrites && finished) rows.push({ kind: "line", line: { id: "rewrites", text: `The answer was rewritten ${times(rewrites)} to fit the format`, ms: elapsed, status: "done", quiet: true } });
  const delegations = [...kids.values()];
  // A finished run has no live step: a delegation that never reported finished folds with its last line as the answer.
  if (finished) for (const d of delegations) if (!d.done) { d.done = true; d.answer = d.answer ?? d.lines[d.lines.length - 1]?.text; }
  const segments = [
    { label: "Lookout", agent: "lookout", from: 0, to: delegations[0]?.ms ?? elapsed, live: false },
    ...delegations.map((d, n) => ({ label: d.label, agent: d.agent, from: n === 0 ? 0 : delegations[n - 1].ms, to: d.done ? d.ms : elapsed, live: !d.done && !finished })),
  ];
  const anyLive = [...rows.flatMap((r) => (r.kind === "line" ? [r.line] : r.d.lines))].some((l) => l.status === "live");
  const phase = !finished && toolCalls > 0 && !anyLive ? (verified ? "Writing up the answer…" : "Checking every number against the data…") : undefined;
  return {
    phase, rewrites,
    rows, finished, failed, verified, elapsedMs: elapsed, toolCalls, denied, costUsd: cost,
    agents: ["Lookout", ...delegations.map((d) => d.label)], segments,
  };
}

function place(rows: Row[], kids: Map<string, Delegation>, own: boolean, e: RunEvent, line: Line) {
  const child = !own ? kids.get(e.run_id) : undefined;
  if (child) child.lines.push(line);
  else rows.push({ kind: "line", line });
}

/** The check line in a buyer's words: where the answer was revised once after a check, say so instead of "failed". */
const checkWords = (s: string, revised: boolean) => {
  const t = s.replace(/numbers from tools/, "numbers checked against the data").replace(/ · 0 open questions? with an owner/, "");
  return revised ? t.replace(/ · \d+ checks? failed/, " · revised once after a check") : t;
};
