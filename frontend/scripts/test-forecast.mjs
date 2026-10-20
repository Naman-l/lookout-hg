// Unit test for the Forecast grid's arithmetic: totals and the sparkline.
import { build } from "esbuild";
import { test } from "node:test";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const out = join(mkdtempSync(join(tmpdir(), "forecast-")), "model.mjs");
await build({ entryPoints: ["src/sections/forecast/model.ts"], outfile: out, bundle: true, format: "esm", logLevel: "silent" });
const { totals, rowTotal, sparkPoints } = await import(pathToFileURL(out).href);

const rows = [{ product: "A", months: [{ month: "2026-10", units: 182 }, { month: "2026-11", units: 188 }] }, { product: "B", months: [{ month: "2026-10", units: 18 }, { month: "2026-11", units: 12 }] }];

test("totals per month and overall; a row's own total", () => {
  assert.deepEqual(totals(rows), { months: ["2026-10", "2026-11"], byMonth: [200, 200], all: 400 });
  assert.equal(rowTotal(rows[0]), 370);
  assert.deepEqual(totals([]), { months: [], byMonth: [], all: 0 });
});

test("sparkline: lowest at the bottom, highest at the top, flat in the middle, empty is empty", () => {
  assert.equal(sparkPoints([1, 3], 80, 24), "2.0,22.0 78.0,2.0");
  assert.equal(sparkPoints([5, 5, 5], 80, 24), "2.0,12.0 40.0,12.0 78.0,12.0");
  assert.equal(sparkPoints([], 80, 24), "");
});
