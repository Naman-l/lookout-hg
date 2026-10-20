// Unit test for the live stream: scripted step.delta events that share a seq must accumulate, never be dropped by the de-dup.
import { build } from "esbuild";
import { test } from "node:test";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const out = join(mkdtempSync(join(tmpdir(), "stream-")), "runStream.mjs");
await build({ entryPoints: ["src/organism/runStream.ts"], outfile: out, bundle: true, format: "esm", logLevel: "silent" });
const { foldEvent } = await import(pathToFileURL(out).href);

const ev = (type, seq, summary) => ({ run_id: "r1", seq, ts: "", t_ms: 0, type, summary });
const run = (events) => events.reduce(foldEvent, { events: [], typing: "" });

test("deltas sharing one seq accumulate in order", () => {
  const s = run([ev("run.started", 1, "start"), ev("step.delta", 1, "I'm "), ev("step.delta", 1, "asking "), ev("step.delta", 1, "the supply side")]);
  assert.equal(s.typing, "I'm asking the supply side");
  assert.equal(s.events.length, 1);
});
test("the finished step.text replaces the typing", () => {
  const s = run([ev("step.delta", 1, "I'm asking"), ev("step.text", 2, "I'm asking the supply side."), ev("step.delta", 2, "Next")]);
  assert.equal(s.events.map((e) => e.type).join(), "step.text");
  assert.equal(s.typing, "Next");
});
test("a stored event seen twice is kept once", () => {
  const s = run([ev("tool.called", 3, "a"), ev("tool.called", 3, "a")]);
  assert.equal(s.events.length, 1);
});
test("deltas never enter the stored events", () => {
  assert.equal(run([ev("step.delta", 1, "x")]).events.length, 0);
});

// The step list carries the reason a step was taken (payload.why); a refused call shows its gate reason, never a why.
const outModel = join(mkdtempSync(join(tmpdir(), "model-")), "runModel.mjs");
await build({ entryPoints: ["src/organism/runModel.ts"], outfile: outModel, bundle: true, format: "esm", logLevel: "silent" });
const { buildRun } = await import(pathToFileURL(outModel).href);
const call = (seq, payload) => ({ run_id: "r1", seq, ts: "", t_ms: seq, type: "tool.called", summary: "Looked something up", tool_use_id: `t${seq}`, payload });
test("an allowed step keeps its why; a refused step does not", () => {
  const v = buildRun([call(1, { gate: "allowed", why: "Read what the system already worked out." }), call(2, { gate: "denied", gate_reason: "outside this role", why: "should not show" })], "r1");
  const lines = v.rows.map((r) => r.line);
  assert.equal(lines[0].why, "Read what the system already worked out.");
  assert.equal(lines[1].why, undefined);
  assert.equal(lines[1].detail, "outside this role");
});

// The buyer's words for trust codes (one table) and a quoted markdown row read as its cells.
const out2 = join(mkdtempSync(join(tmpdir(), "words-")), "words.mjs");
await build({ stdin: { contents: 'export { pipeRowsInWords } from "./src/ui/format.ts";', resolveDir: process.cwd(), loader: "ts" }, outfile: out2, bundle: true, format: "esm", logLevel: "silent" });
const { pipeRowsInWords } = await import(pathToFileURL(out2).href);

test("a quoted pipe row is shown as its cells; the text is not otherwise changed", () => {
  assert.equal(pipeRowsInWords("Row: | 1 | 8507.60 | Lithium-ion accumulators | 25% | Nov 1 | done"), "Row: 8507.60 · Lithium-ion accumulators · 25% · Nov 1 done");
  assert.equal(pipeRowsInWords("a|b is fine"), "a|b is fine");
  assert.equal(pipeRowsInWords("|---|---|---|").trim(), "");
});
