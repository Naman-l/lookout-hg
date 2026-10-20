import type { RunEvent } from "../../api/types";

/** A run read as a trace (FINAL 08 C): its events in run order, grouped by the step of the case they serve, then by agent. Pure, so it is unit-tested. */

export type Stage = "overview" | "analysis" | "draft" | "decision";
/** The run order: the draft is prepared before Lookout decides (F94, UX QA-2). */
export const RUN_ORDER: { key: Stage; name: string; note?: string }[] = [
  { key: "overview", name: "Overview" }, { key: "analysis", name: "Analysis" }, { key: "draft", name: "Draft", note: "before the decision" }, { key: "decision", name: "Decision" },
];
const FROM_API: Record<string, Stage> = { overview: "overview", analysis: "analysis", draft: "draft", decision: "decision", understand: "overview", analyze: "analysis", prepare: "draft", decide: "decision" };      // B-d sends the case words (F94); the older names read the same

export type Row = { id: string; mark: "ok" | "no" | "redo"; tool: string; text: string; full?: string; right?: string; actionId?: string; mono: boolean };
export type Block = { agent: string; label: string; lead: boolean; startMs: number; endMs: number; lookups: number; read: number; rows: Row[]; notes: string[] };
export type Group = { stage: Stage; name: string; note?: string; blocks: Block[] };
export type Trace = { groups: Group[]; lookups: number; read: number; rewrites: number; checked?: { from: number; of: number; passed: boolean }; reviewer?: { passed: number; of: number }; staged: { id: string; text: string; contact?: string }[] };

type P = { tool?: string; gate?: string; gate_reason?: string; numbers?: unknown[]; action_id?: string; stage?: string; passed?: boolean; numbers_checked?: number; numbers_from_tools?: number; open_questions_with_owner?: number; failures?: string[]; checks?: { name: string; passed: boolean }[] };
const p = (e: RunEvent) => (e.payload ?? {}) as P;
const sec = (ms: number) => `${(ms / 1000).toFixed(1)} s`;
const SYSTEM = new Set(["verifier", "reviewer"]);

/** The step an event serves: the API's own stage when it has one, else read from who did it and with which tool. */
export function stageOf(e: RunEvent): Stage | null {
  const s = (e as RunEvent & { stage?: string }).stage ?? p(e).stage;
  if (s && FROM_API[s]) return FROM_API[s];
  const a = e.agent ?? "lookout", tool = p(e).tool ?? "";
  if (SYSTEM.has(a) || e.type === "verifier.result" || e.type === "review.result" || e.type === "revision.started") return "decision";
  if (a === "buyers_clerk" || e.type === "action.staged") return "draft";
  if (a === "lookout") return tool === "get_handoffs" || tool === "StructuredOutput" ? "decision" : tool === "get_item" || e.type === "step.text" ? "overview" : null;
  return "analysis";
}

/** "rewrite it to fit: the finding has 25 words; …" twice -> "Rewritten twice: the finding had 25, then 21 words". */
export function rewriteText(reasons: string[]): string {
  const n = reasons.length;
  const times = n === 1 ? "once" : n === 2 ? "twice" : `${n} times`;
  const words = reasons.map((r) => r.match(/the (\w+) has (\d+) words/));
  if (words.every(Boolean)) return `Rewritten ${times}: the ${words[0]![1]} had ${words.map((w) => w![2]).join(", then ")} words`;
  return `Rewritten ${times}: ${(reasons[0] ?? "").replace(/^rewrite it to fit:\s*/i, "").split(";")[0]}`;
}

/** A lookup's result as one line: what came back, not the lookup restated. "Disrupted supply for X: 10 lines across 5 parts (…)" -> "10 lines across 5 parts". */
export function oneLine(tool: string, text: string): string {
  if (tool === "get_item" && /^Read the item/.test(text)) { const o = text.match(/Owner ([^.]+)\.?$/); return `Read the case${o ? ` · owner ${o[1]}` : ""}`; }
  const head = text.indexOf(": ");
  const body = head > 0 && head < 90 ? text.slice(head + 2) : text;
  return body.split(/; | \(|\. /)[0].replace(/\.$/, "");
}

export function buildTrace(events: RunEvent[], labels: Record<string, string> = {}): Trace {
  const groups: Group[] = RUN_ORDER.map((s) => ({ stage: s.key, name: s.name, note: s.note, blocks: [] }));
  const at = (s: Stage) => groups.find((g) => g.stage === s)!;
  const t: Trace = { groups, lookups: 0, read: 0, rewrites: 0, staged: [] };
  const rewrites: string[] = [];
  let rewriteMs = 0;
  let draft: string | undefined;
  let firstChild = false;
  const block = (s: Stage, agent: string, ms: number): Block => {
    const g = at(s);
    const owner = SYSTEM.has(agent) ? "lookout" : agent;
    let b = g.blocks[g.blocks.length - 1];
    if (!b || b.agent !== owner) {
      b = { agent: owner, label: labels[owner] ?? (owner === "lookout" ? "Lookout" : owner), lead: owner === "lookout", startMs: ms, endMs: ms, lookups: 0, read: 0, rows: [], notes: [] };
      g.blocks.push(b);
    }
    b.endMs = Math.max(b.endMs, ms);
    return b;
  };
  for (const e of events) {
    if (e.agent_label && e.agent) labels[e.agent] ??= e.agent_label;
    if (e.type === "child.started") { firstChild = true; const cs = stageOf(e); if (cs) block(cs, e.agent ?? "", e.t_ms ?? 0); continue; }
    const s = stageOf(e);
    const a = e.agent ?? "lookout", ms = e.t_ms ?? 0, q = p(e), id = `${e.run_id}:${e.seq}`;
    if (e.type === "tool.called") {
      if (q.tool === "StructuredOutput") { if (q.gate === "denied") { rewrites.push(q.gate_reason ?? ""); rewriteMs = ms; t.rewrites += 1; } continue; }
      t.lookups += 1;
      if (!s) continue;
      const b = block(s, a, ms);
      b.lookups += 1;
      if (q.gate === "denied") b.rows.push({ id, mark: "no", tool: q.tool ?? "", text: `refused: ${q.gate_reason ?? "outside what this agent may do"}`, mono: true });
    } else if (e.type === "tool.result" && s) {
      const n = (q.numbers ?? []).length;
      t.read += n;
      const b = block(s, a, ms);
      b.read += n;
      if (q.tool === "draft_supplier_request") { draft = e.summary.replace(/ awaiting approval/, ""); continue; }      // the staged action below says it, once
      b.rows.push({ id, mark: "ok", tool: q.tool ?? "", text: oneLine(q.tool ?? "", e.summary), full: e.summary, right: s === "overview" || s === "decision" ? sec(ms) : n ? `${n} read` : undefined, mono: true });
    } else if (e.type === "action.staged") {
      const b = block("draft", a, ms);
      const text = draft ?? e.summary.replace(/^Buyer's clerk drafted:\s*/, "");
      t.staged.push({ id: q.action_id ?? "", text, contact: text.match(/^Draft to ([^:]+):/)?.[1] });
      b.rows.push({ id, mark: "ok", tool: "draft_supplier_request", text, right: "prepared", actionId: q.action_id, mono: true });
      draft = undefined;
    } else if (e.type === "child.finished" && s) {
      block(s, a, ms).notes.push(`Handed back: ${e.summary}`);
    } else if (e.type === "step.text" && a === "lookout" && !firstChild && s) {
      block(s, a, ms).notes.push(e.summary);
    } else if (e.type === "verifier.result") {
      if (rewrites.length) block("decision", "lookout", ms).rows.push({ id: `${id}:fmt`, mark: "redo", tool: "Format", text: rewriteText(rewrites), right: sec(rewriteMs), mono: false });
      rewrites.length = 0;
      t.checked = { from: q.numbers_from_tools ?? 0, of: q.numbers_checked ?? 0, passed: q.passed !== false };
      const extra = (q.failures ?? []).length ? ` · failed: ${(q.failures ?? []).join("; ")}` : "";
      block("decision", "verifier", ms).rows.push({ id, mark: q.passed === false ? "no" : "ok", tool: "Verifier · code", text: `${q.numbers_from_tools ?? 0} of ${q.numbers_checked ?? 0} figures checked against a lookup · ${q.open_questions_with_owner ?? 0} open questions have an owner${extra}`, right: sec(ms), mono: false });
    } else if (e.type === "review.result") {
      const checks = q.checks ?? [], ok = checks.filter((c) => c.passed).length, failed = checks.filter((c) => !c.passed).map((c) => c.name);
      t.reviewer = { passed: ok, of: checks.length };
      const note = events.find((x) => x.type === "step.text" && x.agent === "reviewer")?.summary.split(": ").slice(1).join(": ").replace(/^it /, "the draft ");
      block("decision", "reviewer", ms).rows.push({ id, mark: failed.length ? "no" : "ok", tool: "Reviewer", text: [`${ok} of ${checks.length} checks, as recorded`, failed.length ? `failed: ${failed.join(", ")}` : note].filter(Boolean).join(" · "), right: sec(ms), mono: false });
    }
  }
  if (rewrites.length) block("decision", "lookout", events[events.length - 1]?.t_ms ?? 0).rows.push({ id: "fmt", mark: "redo", tool: "Format", text: rewriteText(rewrites), mono: false });
  t.groups = groups.filter((g) => g.blocks.length > 0);
  return t;
}

/** "4.2 – 16.4 s · 5 lookups · 93 figures read"; figures read only on Analysis, where the analysts read the data (AGENT-EXPERT: the clerk re-reads the case's figures, which would inflate a Draft count). */
export const blockMeta = (b: Block, stage?: Stage) => [`${(b.startMs / 1000).toFixed(1)} – ${sec(b.endMs)}`, b.lookups && b.agent !== "lookout" ? `${b.lookups} ${b.lookups === 1 ? "lookup" : "lookups"}` : "", b.read && b.agent !== "lookout" && (stage ?? "analysis") === "analysis" ? `${b.read} figures read` : ""].filter(Boolean).join(" · ");
