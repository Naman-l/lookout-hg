// Unit tests for the HG screens' pure helpers: rupees in Indian units, day-first dates, and where a case stands from the viewer's side.
import { build } from "esbuild";
import { test } from "node:test";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const dir = mkdtempSync(join(tmpdir(), "ui-"));
const entry = join(dir, "entry.ts");
writeFileSync(entry, `export * from "${process.cwd()}/src/ui/format.ts"; export * from "${process.cwd()}/src/components/domain/caseStatus.ts"; export { rankExamples, shortAbout } from "${process.cwd()}/src/sections/agents/ask.ts";`);
const out = join(dir, "ui.mjs");
await build({ entryPoints: [entry], outfile: out, bundle: true, format: "esm", platform: "node", logLevel: "silent" });
const U = await import(pathToFileURL(out).href);

test("rupees read in Indian units, exact with lakh grouping", () => {
  assert.equal(U.inr(8500), "₹8,500");
  assert.equal(U.inr(1500000), "₹15 L");
  assert.equal(U.inr(14000000), "₹1.4 Cr");
  assert.equal(U.inr(3200000016), "₹320 Cr");
  assert.equal(U.inr(4249224, true), "₹42,49,224");
  assert.equal(U.inr(null), "—");
  assert.equal(U.enIn(128000), "1,28,000");
});

test("dates read day first; prose loses its ISO dates", () => {
  assert.equal(U.shortDate("2026-10-28"), "28 Oct");
  assert.equal(U.longDate("2026-10-20"), "20 Oct 2026");
  assert.equal(U.humanize("needed by 2026-11-03 in 2026-11"), "needed by 3 Nov in November");
});

const item = (over) => ({ key: "k", kind: "pr-late", tab: "requirement", severity: "high", title: "t", summary: "s", at_stake_label: "at stake", at_stake_rule: "", owner: "Sambhav Kumar",
  owner_ids: ["Sambhav"], waiting_on: "SCM", verticals: [], projects: [], site_impact: [], next_action: "", refs: [], dated: [], ...over });

test("where a case stands, from the viewer's side", () => {
  const st = (stage, me) => U.statusOf(item({ stage }), me).word;
  assert.equal(st({ key: "decision_ready", label: "Decide", step: 3, next_act: "" }, "Sambhav Kumar"), "Decide");
  assert.equal(st({ key: "decision_ready", label: "Decide", step: 3, next_act: "" }, "Jitender Swami"), "With Sambhav");
  assert.equal(st({ key: "signed", label: "Countersign", step: 5, next_act: "", waiting_on: "Satish Kumar Sharma" }, "Satish Kumar Sharma"), "Countersign");
  assert.equal(st({ key: "sent", label: "With Projects", step: 6, next_act: "" }, "Sambhav Kumar"), "With Projects");
  assert.equal(U.statusOf(item({ tab: "trust" }), "Sambhav Kumar").word, "Held");
  assert.ok(U.yourMove(item({ stage: { key: "drafted", label: "Needs your OK", step: 4, next_act: "" } }), "Sambhav Kumar"));
  assert.ok(!U.yourMove(item({ stage: { key: "sent", label: "Sent", step: 6, next_act: "" } }), "Sambhav Kumar"));
});

test("Ask's suggestions put the record on screen first", () => {
  const ex = [{ question: "a" }, { question: "b", context: { type: "item", id: "x" } }];
  assert.equal(U.rankExamples(ex, { type: "item", id: "x" }, "About")[0].question, "b");
});
