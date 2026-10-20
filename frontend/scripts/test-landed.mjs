// Unit test for the landed-cost table (F103): the last PO pinned, offers cheapest landed first, the deciding cells bold, one line naming the point.
import { build } from "esbuild";
import { test } from "node:test";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const out = join(mkdtempSync(join(tmpdir(), "landed-")), "lc.mjs");
await build({ entryPoints: ["src/components/domain/landedCost.ts"], outfile: out, bundle: true, format: "esm", logLevel: "silent" });
const M = await import(pathToFileURL(out).href);
const m = (x) => (x == null ? null : { amount: String(x), currency: "USD", usd: String(x) });
const col = (label, cur, o) => ({ label, is_current: cur, landed: { offer: { offer_id: o.id ?? null, supplier: { type: "supplier", id: "S1" }, supplier_name: o.name ?? "Acme Energy Co., Ltd.", unit_price_usd: m(o.price), origin: o.origin ?? null, origin_claim: o.claim ?? null, incoterm_place: o.place ?? null, prepayment: o.pre ?? null, payment_terms: o.terms ?? null, qty_break: o.qty ?? null }, duty_usd: m(o.duty), duty_status: o.status ?? "none", total_known_usd: m(o.landed), total_if_china_usd: m(o.china), surcharge_usd: m(o.sur), tooling_per_unit_usd: null } });

test("duty variant: an offer dearer on the sheet can be cheaper landed once the new duty is counted", () => {
  const t = M.landedTable([
    col("Acme (Malaysia)", false, { id: 1, price: 1224.52, claim: "Malaysia (Penang assembly)", place: "Penang", status: "unknown_origin", landed: 1224.52, china: 1530.65 }),
    col("Current: Acme (last PO)", true, { price: 1137.12, origin: "CN", duty: 284.28, status: "owed", landed: 1421.4 }),
    col("Acme (China)", false, { id: 2, price: 1155.21, origin: "CN", duty: 288.8025, status: "owed", landed: 1444.0125 }),
  ], "duty");
  assert.deepEqual(t.rows.map((r) => r.label), ["Last PO · China", "Acme Penang · MY", "Acme China · CN"]);
  const pen = t.rows[1].cells;
  assert.deepEqual(t.cols.map((c) => c.head), ["Quoted", "Duty", "Landed", "vs last + duty"]);
  assert.deepEqual([pen.quoted.text, pen.duty.text, pen.duty.note, pen.landed.text, pen.landed.bold, pen.landed.note, pen.vs.text, pen.vs.bold], ["$1,224.52", "$0", "if origin holds", "$1,224.52", true, "(if China $1,530.65)", "\u221213.9%", true]);
  assert.equal(t.rows[2].cells.vs.text, "+1.6%");
  assert.equal(t.rows[2].cells.landed.note, undefined);      // a China offer has no "if China"
  assert.equal(t.line, null);      // F105: no code sentence
  assert.equal(M.landedLine("HR-1", [col("x", false, { price: 2238.52, place: "Penang", landed: 2238.52 }), col("Current", true, { price: 2100, landed: 2633.62 })]), "HR-1: Penang $2,238.52 vs $2,633.62 landed (\u221215.0%)");
});

test("quote variant: the reviewed offer's rise on the sheet and landed, with its terms", () => {
  const t = M.landedTable([
    col("Current: Acme (last PO)", true, { price: 370.52, origin: "DE", landed: 370.52 }),
    col("Acme", false, { id: 21, price: 445.298639, origin: "DE", sur: 15.585452, landed: 460.884091, pre: "30% on orders above EUR 25,000 net", terms: "Net 30 (was 45)" }),
  ], "quote");
  const q = t.rows[1].cells;
  assert.deepEqual(t.cols.map((c) => c.head), ["Quoted", "Landed", "vs last landed", "Terms"]);
  assert.deepEqual([t.rows.length, t.rows[1].label, q.landed.text, q.landed.bold, q.landed.tip, q.vsLanded.text, q.terms.text], [2, "Acme quote", "$460.88", true, "includes $15.59 surcharge / tooling per piece", "+24.4%", "30% prepay above EUR 25K · Net 30"]);
  assert.equal(M.landedTable([col("Current", true, { price: 1, landed: 1 })], "quote").rows.length, 1);
  const tiers = M.landedTable([col("Current", true, { price: 370.52, landed: 370.52 }), col("Acme", false, { id: 21, qty: 250, price: 445.3, landed: 460.88 }), col("Acme", false, { id: 22, qty: 100, price: 461.16, landed: 477.3 })], "quote");
  assert.deepEqual(tiers.rows.map((r) => r.label), ["Last PO · —", "Acme quote · 250 pcs", "Acme quote · 100 pcs"]);      // each price break its own row, the cheaper landed first and bold
  const cols = [col("Current", true, { price: 370.52, landed: 370.52 }), col("Acme", false, { id: 21, qty: 250, price: 445.3, landed: 460.88 }), col("Acme", false, { id: 22, qty: 100, price: 461.16, landed: 477.3 })];
  const at200 = M.landedTable(cols, "quote", { order: 200 });      // a 200-pc order is priced at the 100-pc break: that row bold, the 250 row plain, and the caption says so
  assert.deepEqual(at200.rows.slice(1).map((r) => [r.label, r.cells.landed.bold, r.cells.vsLanded.text]), [["Acme quote · 250 pcs", false, "+24.4%"], ["Acme quote · 100 pcs", true, "+28.8%"]]);
  assert.equal(at200.line, "Quote lists 100 and 250 pcs; 200 pcs priced at the 100-pc break until Acme confirms.");
  assert.equal(tiers.rows[1].cells.landed.bold, true);
});

test("quote variant: an offer whose origin is not proven says what it lands at if ruled China; a known origin says nothing", () => {
  const t = M.landedTable([
    col("Current: Acme (last PO)", true, { price: 1137.12, origin: "CN", duty: 284.28, status: "owed", landed: 1421.4 }),
    col("Acme (Malaysia)", false, { id: 31, price: 1224.52, claim: "Malaysia (Penang assembly)", place: "Penang", status: "unknown_origin", landed: 1224.52, china: 1530.65 }),
  ], "quote", { reviewed: "31" });
  const q = t.rows[1].cells;
  assert.deepEqual([q.landed.text, q.landed.note, q.vsLanded.text], ["$1,224.52", "(if China $1,530.65)", "−13.9%"]);
  const de = M.landedTable([col("Current", true, { price: 370.52, origin: "DE", landed: 370.52 }), col("Acme", false, { id: 21, price: 445.3, origin: "DE", landed: 460.88 })], "quote");
  assert.equal(de.rows[1].cells.landed.note, undefined);
});
