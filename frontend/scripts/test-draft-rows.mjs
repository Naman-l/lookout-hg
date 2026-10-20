// Unit test for the email's PO-line rows (UX R1-1/R1-2): a row is read by its structure (PO line · part · the rest), so a part name
// with commas in it stays one cell, and a row with fewer cells is padded by column, never shifted.
import { build } from "esbuild";
import { test } from "node:test";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const out = join(mkdtempSync(join(tmpdir(), "draft-rows-")), "db.mjs");
await build({ entryPoints: ["src/domain-ui/DraftBlock.tsx"], outfile: out, bundle: true, format: "esm", logLevel: "silent", jsx: "automatic", loader: { ".css": "empty" } });
const M = await import(pathToFileURL(out).href);
const row = (line) => M.cellsOf(line, { start: 0, end: line.length }).map((c) => [c.head, line.slice(c.start, c.end), !!c.past]);

test("a part name with one comma is one Part cell", () => {
  assert.deepEqual(row("- PO-1001/10, Motor, brushless (HR-90001), 300 EA, confirmed 3 March (past due)"),
    [["PO line", "PO-1001/10", false], ["Part", "Motor, brushless (HR-90001)", false], ["Qty", "300 EA", false], ["Confirmed", "3 March", true]]);
});

test("a part name with two commas and digits in it is still one Part cell", () => {
  assert.deepEqual(row("- PO-1002/10, Cell pack, 24 V, 10 Ah (HR-90002), 200 EA, promised 4 April"),
    [["PO line", "PO-1002/10", false], ["Part", "Cell pack, 24 V, 10 Ah (HR-90002)", false], ["Qty", "200 EA", false], ["Promised", "4 April", false]]);
});

test("a bare part id and a quantity with a thousands comma keep their cells", () => {
  assert.deepEqual(row("PO-1003/10, HR-90003, 1,200 EA, confirmed 5 May"),
    [["PO line", "PO-1003/10", false], ["Part", "HR-90003", false], ["Qty", "1,200 EA", false], ["Confirmed", "5 May", false]]);
});

test("a row with no promise date has fewer cells; the table pads it by column", () => {
  assert.deepEqual(row("- PO-1004/20, Sensor, optical (HR-90004), 50 EA"),
    [["PO line", "PO-1004/20", false], ["Part", "Sensor, optical (HR-90004)", false], ["Qty", "50 EA", false]]);
});

test("a 'past due' cell marks the row, it is not a column of its own", () => {
  assert.deepEqual(row("- PO-1005/10, Motor, frameless servo (HR-90005), 100 EA, promised 6 June, past due"),
    [["PO line", "PO-1005/10", false], ["Part", "Motor, frameless servo (HR-90005)", false], ["Qty", "100 EA", false], ["Promised", "6 June", true]]);
});

test("a row whose cells are separated by ' · ' keeps the part's commas in one cell and reads the qty, date and past due (LOOKOUT P1)", () => {
  assert.deepEqual(row("PO-1006/10 · Motor, BLDC (HR-90006) · 355 EA · promised 26 August (past due)"),
    [["PO line", "PO-1006/10", false], ["Part", "Motor, BLDC (HR-90006)", false], ["Qty", "355 EA", false], ["Promised", "26 August", true]]);
});

test("a ' · ' row with a thousands comma in its quantity and no date", () => {
  assert.deepEqual(row("- PO-1007/20 · Gearbox, planetary, 10:1 (HR-90007) · 1,320 EA"),
    [["PO line", "PO-1007/20", false], ["Part", "Gearbox, planetary, 10:1 (HR-90007)", false], ["Qty", "1,320 EA", false]]);
});

test("'no promised date yet' is the Promised cell, said in full", () => {
  assert.deepEqual(row("PO-1008/20 · Lidar, 2D safety (HR-90008) · 314 EA · no promised date yet"),
    [["PO line", "PO-1008/20", false], ["Part", "Lidar, 2D safety (HR-90008)", false], ["Qty", "314 EA", false], ["Promised", "no promised date yet", false]]);
});

test("'no new date' sits under Now, beside the row's Promised date and its past-due mark", () => {
  assert.deepEqual(row("PO-1009/30 · Harness, drive motor power (HR-90009) · promised 24 September (past due) · no new date"),
    [["PO line", "PO-1009/30", false], ["Part", "Harness, drive motor power (HR-90009)", false], ["Promised", "24 September", true], ["Now", "no new date", false]]);
});
