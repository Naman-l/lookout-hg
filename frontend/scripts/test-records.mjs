// Unit test for the Records model (FINAL 06): which case a record is in, the case's short name, the orders' order and the promise-history words.
import { build } from "esbuild";
import { test } from "node:test";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const out = join(mkdtempSync(join(tmpdir(), "records-")), "model.mjs");
await build({ entryPoints: ["src/sections/records/model.ts"], outfile: out, bundle: true, format: "esm", logLevel: "silent" });
const M = await import(pathToFileURL(out).href);

const line = (id, part, extra = {}) => ({ ref: { id }, part: { id: part }, supplier: { id: "S1", label: "Shenzhen Yunzhan Precision Motor Co., Ltd." }, qty: { value: "10" }, unit_price: { amount: "2", currency: "USD", usd: "2" }, status: "OPEN", buyer: "Dana Reyes", days_past_due: 0, stale: false, ...extra });
const item = (key, title, extra = {}) => ({ key, title, group: key.split(":")[0], refs: [], at_stake: null, ...extra });

test("short names: the title up to its colon, without the on-time aside or the trailing 'with …'", () => {
  assert.equal(M.caseShort("Yunzhan fire: Tern and Porter short of drive motors from October"), "Yunzhan fire");
  assert.equal(M.caseShort("Vistaray delivers late (on time on 26% of 43 lines): secure the lidar"), "Vistaray delivers late");
  assert.equal(M.caseShort("Spot offer at 13.5x the usual price, with an instruction aimed at AI systems: do not order"), "Spot offer at 13.5x the usual price");
  assert.equal(M.caseShort("BCX (formerly Baycrest): old addresses forward only until Dec 31"), "BCX (formerly Baycrest)");
  assert.equal(M.caseShort("16 past-due lines, no updated promise"), "16 past-due lines, no updated promise");
});

test("a record is in a case by its refs; a line also by the lines the amount was computed from; a part also through its lines", () => {
  const fire = item("disruption:S1", "Yunzhan fire: x", { refs: [{ type: "supplier", id: "S1" }], at_stake: { provenance: { inputs: [{ type: "po_line", id: "L1" }] } } });
  const origin = item("unknown:origin", "5 parts missing country of origin (COO)", { refs: [{ type: "part", id: "P9" }] });
  const idx = M.indexCases([fire, origin], [line("L1", "P1"), line("L2", "P2")]);
  assert.deepEqual(idx.supplier.get("S1"), [fire]);
  assert.deepEqual(idx.line.get("L1"), [fire]);
  assert.equal(idx.line.get("L2"), undefined);
  assert.deepEqual(idx.part.get("P1"), [fire]);
  assert.deepEqual(idx.part.get("P9"), [origin]);
});

test("the list cell shows a case of the record's own before a rollup, real trouble before a held message, the soonest act-by first", () => {
  const aged = item("unknown:stale-orders", "3 aged open POs: close them");
  const fraud = item("trust:x", "Bank-detail change: do not pay", { group: "trust" });
  const fire = item("disruption:S1", "Yunzhan fire: x", { act_by: "2026-10-10" });
  const early = item("risk:S1", "Something sooner: x", { act_by: "2026-10-01" });
  assert.deepEqual(M.rankCases([aged, fraud, fire, early], "2026-09-25").map((i) => i.key), ["risk:S1", "disruption:S1", "trust:x", "unknown:stale-orders"]);
  assert.deepEqual(M.byActBy([aged, fire, fraud], "2026-09-25").map((i) => i.key), ["trust:x", "disruption:S1", "unknown:stale-orders"]);
  assert.ok(M.isRollup("deadline:chase") && M.isRollup("tariff:all") && M.isRollup("unknown:hts") && !M.isRollup("deadline:SUP-0042:2026-09-28"));
});

test("orders: past due oldest first, then promised soonest, then no date; lines that may not be open go to the foot", () => {
  const rows = [line("a", "P", { promise_date: "2026-10-10" }), line("b", "P", { promise_date: "2026-08-20", days_past_due: 36 }), line("c", "P"), line("d", "P", { promise_date: "2026-08-24", days_past_due: 32 }), line("s", "P", { promise_date: "2025-03-21", stale: true, days_past_due: 553 })];
  const o = M.orderLines(rows);
  assert.deepEqual(o.open.map((l) => l.ref.id), ["b", "d", "a", "c"]);
  assert.deepEqual(o.stale.map((l) => l.ref.id), ["s"]);
  assert.ok(M.whenMatches(rows[1], "late", "2026-09-25") && !M.whenMatches(rows[4], "late", "2026-09-25"));
  assert.ok(M.whenMatches(rows[2], "none", "2026-09-25"));
  assert.ok(M.whenMatches(line("m", "P", { promise_date: "2026-09-29" }), "month", "2026-09-25"));
});

test("open dollars per part and robots per supplier count only lines that are really open", () => {
  const rows = [line("a", "P1"), line("b", "P1"), line("s", "P1", { stale: true }), line("c", "P2", { supplier: { id: "S2" } })];
  assert.equal(M.openByPart(rows).get("P1"), 40);
  const lit = M.supplierRobots(rows, new Map([["P1", ["T"]], ["P2", ["H"]]]));
  assert.deepEqual([...lit.get("S1")], ["T"]);
  assert.deepEqual([...lit.get("S2")], ["H"]);
});

test("the words a buyer reads: dollars, dates, names and the promise history", () => {
  assert.equal(M.usd(2910000), "$2.91M");
  assert.equal(M.usd(396000), "$396K");
  assert.equal(M.usd(3892.4), "$3,892");
  assert.equal(M.day("2026-09-21", "2026"), "Sep 21");
  assert.equal(M.day("2025-03-21", "2026"), "Mar 21 2025");
  const shorts = M.supplierShorts([item("a:1", "x", { refs: [{ type: "supplier", id: "S1", label: "Shenzhen Yunzhan Precision Motor Co., Ltd." }] }), item("b:1", "y", { refs: [{ type: "supplier", id: "S1", label: "Yunzhan" }, { type: "part", id: "P", label: "p" }] })]);
  assert.equal(shorts.get("S1"), "Yunzhan");
  assert.equal(M.partName("GEARBOX, PLANETARY, 20:1, extra"), "Gearbox, planetary, 20:1");
  assert.equal(M.htsText("8501314000"), "8501.31.4000");
  assert.equal(M.htsText("850760"), "850760");
  assert.deepEqual(M.neededText({ key: "need", state: "done", detail: "222 EA needed in October (182 robots of Tern T2, 40 robots of Porter P5); 2940 over the next 12 months" }), ["222 EA in Oct", "182 Tern T2, 40 Porter P5"]);
  assert.equal(M.neededText({ key: "need", state: "na", detail: "Not in any planned build" }), null);
  assert.equal(M.receivedText({ key: "received", state: "late", detail: "Nothing received yet" }), "Nothing yet");
  assert.equal(M.receivedText({ key: "received", state: "late", detail: "1879 of 2600 EA received, last on Aug 24; the rest has not arrived" }), "1,879 of 2,600 EA · last Aug 24");
  assert.equal(M.receivedText({ key: "received", state: "unknown", detail: "Unknown: Nothing received yet" }), null);
  assert.equal(M.noticeDate("PO date Sep 21 passed; Jadepeak's notice of Sep 18 revised it to Nov 9"), "Sep 18");
});
