// Unit test for the Orders model: open dollars, sorting, and the one count.
import { build } from "esbuild";
import { test } from "node:test";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const out = join(mkdtempSync(join(tmpdir(), "orders-")), "model.mjs");
await build({ entryPoints: ["src/sections/orders/model.ts"], outfile: out, bundle: true, format: "esm", logLevel: "silent" });
const { openValue, sortLines, countLines } = await import(pathToFileURL(out).href);

const line = (id, qty, usd, extra = {}) => ({ ref: { id }, part: { id: "HR-1" }, supplier: { id: "S", label: "Zed" }, qty: { value: String(qty) }, unit_price: usd == null ? null : { amount: "1", currency: "JPY", usd: String(usd) }, status: "OPEN", buyer: "Dana", days_past_due: 0, stale: false, ...extra });

test("open dollars are open quantity times the USD unit price, unknown without one", () => {
  assert.equal(openValue(line("a", 8500, "0.365523")).toFixed(2), "3106.95");
  assert.equal(openValue(line("a", 2, null)), null);
  assert.equal(openValue({ ...line("a", 2, null), unit_price: { amount: "5", currency: "USD" } }), 10);
});

test("sorting by promised puts dates in order and lines that may not be open last; a second pass flips", () => {
  const rows = [line("c", 1, 1, { promise_date: "2026-10-01" }), line("s", 1, 1, { promise_date: "2026-03-21", stale: true }), line("a", 1, 1, { promise_date: "2026-08-24" })];
  assert.deepEqual(sortLines(rows, "promised", false).map((l) => l.ref.id), ["a", "c", "s"]);
  assert.deepEqual(sortLines(rows, "promised", true).map((l) => l.ref.id), ["s", "c", "a"]);
  assert.deepEqual(sortLines(rows, "qty", false).length, 3);
});

test("one count: stale lines are not open, and past due counts only open lines", () => {
  const rows = [line("a", 1, 1, { days_past_due: 32 }), line("b", 1, 1), line("c", 1, 1, { stale: true, days_past_due: 90 })];
  assert.deepEqual(countLines(rows), { open: 2, late: 1, stale: 1 });
});
