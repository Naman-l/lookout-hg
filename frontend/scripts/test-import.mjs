// Unit test for the Import issue lines: "<count> <what> (<handling>)" split into three parts.
import { build } from "esbuild";
import { test } from "node:test";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const out = join(mkdtempSync(join(tmpdir(), "import-")), "model.mjs");
await build({ entryPoints: ["src/sections/import/model.ts"], outfile: out, bundle: true, format: "esm", logLevel: "silent" });
const { parseIssue, parseIssues } = await import(pathToFileURL(out).href);

test("an issue line splits into count, what and handling", () => {
  assert.deepEqual(parseIssue("12 Payment terms typed several ways (NET60, Net 45 days, NET 30) (fixed)"), { count: 12, text: "Payment terms typed several ways (NET60, Net 45 days, NET 30)", handling: "fixed" });
  assert.deepEqual(parseIssue("1,539 Rows (dropped)"), { count: 1539, text: "Rows", handling: "dropped" });
});

test("a what cut inside a bracket loses its partial word and ends in an ellipsis, never mid-word", () => {
  assert.equal(parseIssue("15 Country typed several ways (United States, USA, US; China, PRC, CN; Ta (fixed)").text, "Country typed several ways (United States, USA, US; China, PRC, CN…");
});

test("every handling is understood; a line that does not parse is kept whole", () => {
  for (const h of ["fixed", "inferred", "flagged", "linked", "unknown", "dropped"]) assert.equal(parseIssue(`3 Something (${h})`).handling, h);
  assert.deepEqual(parseIssues(["no count here"]), [{ raw: "no count here" }]);
});
