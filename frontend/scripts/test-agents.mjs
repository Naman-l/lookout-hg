// Unit test for the run trace (FINAL 08 C): events in run order, grouped by the step they serve, the words each row reads.
import { build } from "esbuild";
import { test } from "node:test";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const out = join(mkdtempSync(join(tmpdir(), "agents-")), "trace.mjs");
await build({ entryPoints: ["src/sections/agents/trace.ts"], outfile: out, bundle: true, format: "esm", logLevel: "silent" });
const T = await import(pathToFileURL(out).href);

let seq = 0;
const ev = (type, agent, t_ms, payload = {}, summary = "") => ({ run_id: "r", seq: ++seq, t_ms, type, agent, agent_label: null, summary, payload });
const run = [
  ev("tool.called", "lookout", 10, { tool: "get_item", gate: "allowed" }),
  ev("tool.result", "lookout", 11, { tool: "get_item", numbers: [] }, "Read the item: A fire: x. Owner Dana Reyes."),
  ev("step.text", "lookout", 2000, {}, "Supply first."),
  ev("child.started", "supply_planner", 4000),
  ev("tool.called", "supply_planner", 5000, { tool: "open_supply", gate: "allowed" }),
  ev("tool.result", "supply_planner", 5100, { tool: "open_supply", numbers: [1, 2, 3] }, "Open supply for S: 12 lines, 5,042 EA (4,892 under the notice); 2 stale"),
  ev("tool.called", "supply_planner", 5200, { tool: "build_readiness", gate: "denied", gate_reason: "over the per-case limit" }),
  ev("child.finished", "supply_planner", 9000, {}, "Ten lines stopped."),
  ev("child.started", "buyers_clerk", 10000),
  ev("tool.result", "buyers_clerk", 12000, { tool: "draft_supplier_request" }, "Draft to Li Wei awaiting approval: revised dates"),
  ev("action.staged", "buyers_clerk", 12000, { action_id: "A-1" }, "Buyer's clerk drafted: revised dates"),
  ev("tool.called", "lookout", 13000, { tool: "get_handoffs", gate: "allowed" }),
  ev("tool.called", "lookout", 14000, { tool: "StructuredOutput", gate: "denied", gate_reason: "rewrite it to fit: the finding has 25 words; it is one decision" }),
  ev("tool.called", "lookout", 15000, { tool: "StructuredOutput", gate: "denied", gate_reason: "rewrite it to fit: the finding has 21 words; it is one decision" }),
  ev("verifier.result", "verifier", 16000, { passed: true, numbers_checked: 6, numbers_from_tools: 6, open_questions_with_owner: 14 }),
  ev("step.text", "reviewer", 17000, {}, "The Reviewer read the drafted request: it commits the company to nothing"),
  ev("review.result", "reviewer", 18000, { checks: [{ name: "a", passed: true }, { name: "b", passed: true }] }),
];

test("the trace runs Overview, Analysis, Draft before the decision, then Decision", () => {
  const t = T.buildTrace(run);
  assert.deepEqual(t.groups.map((g) => g.name), ["Overview", "Analysis", "Draft", "Decision"]);
  assert.equal(t.groups[2].note, "before the decision");
  const planner = t.groups[1].blocks[0];
  assert.equal(T.blockMeta(planner), "4.0 – 9.0 s · 2 lookups · 3 figures read");
  assert.deepEqual(planner.rows.map((r) => [r.mark, r.tool, r.text, r.right]), [["ok", "open_supply", "12 lines, 5,042 EA", "3 read"], ["no", "build_readiness", "refused: over the per-case limit", undefined]]);
  assert.deepEqual(planner.notes, ["Handed back: Ten lines stopped."]);
  assert.deepEqual(t.groups[0].blocks[0].rows[0].text, "Read the case · owner Dana Reyes");
  assert.deepEqual(t.groups[0].blocks[0].notes, ["Supply first."]);
});

test("the draft names its contact and waits in Approvals; the decision reads the checks", () => {
  const t = T.buildTrace(run);
  assert.deepEqual(t.staged, [{ id: "A-1", text: "Draft to Li Wei: revised dates", contact: "Li Wei" }]);
  const d = t.groups[3].blocks;
  assert.equal(d.length, 1);
  assert.equal(d[0].label, "Lookout");
  assert.deepEqual(d[0].rows.map((r) => r.tool), ["Format", "Verifier · code", "Reviewer"]);
  assert.equal(d[0].rows[0].text, "Rewritten twice: the finding had 25, then 21 words");
  assert.equal(d[0].rows[0].right, "15.0 s");
  assert.equal(d[0].rows[2].text, "2 of 2 checks, as recorded · the draft commits the company to nothing");
  assert.deepEqual([t.rewrites, t.read, t.checked, t.reviewer], [2, 3, { from: 6, of: 6, passed: true }, { passed: 2, of: 2 }]);
});

test("the API's own stage wins when it sends one (B-d)", () => {
  assert.equal(T.stageOf({ ...run[4], stage: "decision" }), "decision");
  assert.equal(T.stageOf(run[4]), "analysis");
});

const askOut = join(mkdtempSync(join(tmpdir(), "ask-")), "ask.mjs");
await build({ entryPoints: ["src/sections/agents/ask.ts"], outfile: askOut, bundle: true, format: "esm", logLevel: "silent" });
const A = await import(pathToFileURL(askOut).href);

test("Ask names a case by its short name and puts the questions about it first", () => {
  assert.equal(A.shortAbout("Yunzhan fire: Tern and Porter short of drive motors from October"), "Yunzhan fire");
  assert.equal(A.shortAbout("Suppliers"), "Suppliers");
  const ex = [{ question: "Which tariff exposure should Marcus look at first?" }, { question: "Is the Tern October build clear?" }, { question: "What does the Yunzhan fire cost us?" }, { question: "Where is it?", context: { type: "action_item", id: "disruption:SUP-0001" } }];
  assert.deepEqual(A.rankExamples(ex, { type: "action_item", id: "disruption:SUP-0001" }, "Yunzhan fire: x").map((x) => x.question), ["Where is it?", "What does the Yunzhan fire cost us?", "Which tariff exposure should Marcus look at first?", "Is the Tern October build clear?"]);
});
