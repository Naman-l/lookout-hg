// Unit test for the run page's steps: in time order, each at the time it started, no filler narration.
import { build } from "esbuild";
import { test } from "node:test";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const out = join(mkdtempSync(join(tmpdir(), "run-")), "model.mjs");
await build({ entryPoints: ["src/organism/runModel.ts"], outfile: out, bundle: true, format: "esm", logLevel: "silent" });
const { buildRun, isFiller } = await import(pathToFileURL(out).href);

const ev = (seq, t_ms, type, summary, extra = {}) => ({ run_id: "r", seq, t_ms, type, summary, agent: "lookout", ts: "", ...extra });
const events = [
  ev(1, 12, "run.started", "Working"),
  ev(4, 1936, "step.text", "I'm asking the supply side to map the open lines."),
  ev(5, 3306, "child.started", "Lookout asked the Supply planner: Map open lines", { payload: { child_run_id: "c1" } }),
  ev(6, 4292, "step.text", "I've asked the supply side and that is still running. I'll wait."),
  ev(7, 12845, "child.finished", "Found 5 open lines", { payload: { child_run_id: "c1" } }),
  ev(8, 12897, "step.text", "Still waiting for Buyer's clerk to finish"),
  ev(9, 13924, "step.text", "Now I'm asking for the acknowledgement to be drafted."),
  ev(21, 35873, "run.finished", "Run ok"),
];

test("filler narration is not a step; real narration is", () => {
  assert.equal(isFiller("Still waiting for Buyer's clerk to finish"), true);
  assert.equal(isFiller("I've asked the supply side and that is still running."), true);
  assert.equal(isFiller("Now I'm asking for the acknowledgement to be drafted."), false);
  const rows = buildRun(events, "r").rows;
  assert.deepEqual(rows.map((r) => (r.kind === "line" ? r.line.text.slice(0, 12) : "delegation")), ["I'm asking t", "delegation", "Now I'm aski"]);
});

test("rows are in time order and a delegation shows when it started, not when it finished", () => {
  const rows = buildRun(events, "r").rows;
  const at = rows.map((r) => (r.kind === "line" ? r.line.ms : r.d.startMs));
  assert.deepEqual(at, [...at].sort((a, b) => a - b));
  const d = rows.find((r) => r.kind === "delegation").d;
  assert.equal(d.startMs, 3306); assert.equal(d.ms, 12845);
});

test("self-corrections are one quiet line at the end; a real gate refusal stays a refused step", () => {
  const den = (seq, tool, reason) => ev(seq, seq * 100, "tool.called", `Lookout was refused ${tool}`, { payload: { tool, gate: "denied", gate_reason: reason } });
  const v = buildRun([
    ev(1, 10, "step.text", "Checking the order."),
    den(2, "StructuredOutput", "rewrite it to fit: the finding has 22 words"),
    den(3, "StructuredOutput", "rewrite it to fit: the finding has 21 words"),
    den(4, "Agent", "wait for Buyer's clerk to finish before the next step of the plan"),
    den(5, "get_part", "get_part is not part of Lookout's work"),
    ev(9, 900, "run.finished", "Run ok"),
  ], "r");
  const lines = v.rows.map((r) => r.line);
  assert.equal(lines.filter((l) => l.gate === "denied").length, 1);
  assert.equal(v.denied, 1);
  const last = lines[lines.length - 1];
  assert.equal(last.text, "The answer was rewritten 3 times to fit the format");
  assert.equal(last.quiet, true);
});

test("while a run is past its last lookup the status is in words; a format rewrite is never the status", () => {
  const call = (seq, t, extra = {}) => ev(seq, t, "tool.called", "Lookout reads the item", { tool_use_id: "u" + seq, payload: { gate: "allowed", ...extra } });
  const res = (seq, t) => ev(seq, t, "tool.result", "Read it", { tool_use_id: "u" + (seq - 1) });
  const den = ev(4, 400, "tool.called", "Lookout was refused StructuredOutput", { tool_use_id: "u4", payload: { tool: "StructuredOutput", gate: "denied", gate_reason: "rewrite it to fit: too long" } });
  const live = buildRun([call(1, 100), res(2, 200), den], "r");
  assert.equal(live.phase, "Checking every number against the data…");
  assert.equal(live.rows.some((r) => r.kind === "line" && /rewritten/.test(r.line.text)), false);
  const mid = buildRun([call(1, 100)], "r");
  assert.equal(mid.phase, undefined);
  const writing = buildRun([call(1, 100), res(2, 200), ev(5, 500, "verifier.result", "4 of 4 numbers from tools")], "r");
  assert.equal(writing.phase, "Writing up the answer…");
  const done = buildRun([call(1, 100), res(2, 200), den, ev(9, 900, "run.finished", "Run ok")], "r");
  assert.equal(done.phase, undefined);
  assert.equal(done.rows[done.rows.length - 1].line.quiet, true);
});
