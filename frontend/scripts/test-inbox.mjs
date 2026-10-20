// Unit test for the Inbox message model: what a message changes, sorted into lines, offers (exact prices) and facts.
import { build } from "esbuild";
import { test } from "node:test";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const out = join(mkdtempSync(join(tmpdir(), "inbox-")), "model.mjs");
await build({ entryPoints: ["src/sections/inbox/model.ts"], outfile: out, bundle: true, format: "esm", logLevel: "silent" });
const { messageView, headline, offerRows } = await import(pathToFileURL(out).href);
const out2 = join(mkdtempSync(join(tmpdir(), "inbox-")), "money.mjs");
await build({ entryPoints: ["src/components/domain/Money.tsx"], outfile: out2, bundle: true, format: "esm", jsx: "automatic", logLevel: "silent" });
const { moneyText } = await import(pathToFileURL(out2).href);

const msg = (summary, changes) => ({ summary: { summary }, changes });
const po = (id, label, before, after) => ({ ref: { type: "po_line", id }, label, before, after });

test("a force majeure notice: ten lines say Unknown once, the shared reason is one fact", () => {
  const rows = [po("HPO-26-00450/20", "Cannot ship: force majeure (HR-40120)", "2026-08-25", "unknown (revised dates due Oct 10)"), po("HPO-26-00450/10", "Cannot ship: force majeure (HR-40110)", "2026-08-26", "unknown (revised dates due Oct 10)")];
  const v = messageView(msg("Force majeure: 10 open PO lines cannot ship; revised dates promised by Oct 10.", [...rows, { ref: { type: "supplier", id: "S" }, label: "Deadline", before: null, after: "2026-10-10" }]));
  assert.deepEqual(v.lines.map((l) => [l.id, l.partId, l.was, l.now]), [["HPO-26-00450/20", "HR-40120", "Aug 25", "Unknown"], ["HPO-26-00450/10", "HR-40110", "Aug 26", "Unknown"]]);
  assert.deepEqual(v.facts, [{ label: "Revised dates due", value: "Oct 10" }], "the same date is one chip, not two");
  assert.equal(v.headline, "Force majeure: 10 open PO lines cannot ship; revised dates promised by Oct 10", "no kind given in this fixture: unchanged");
  assert.equal(headline("Force majeure: 10 open PO lines cannot ship.", "force majeure"), "10 open PO lines cannot ship");
});

const MSG = "2026-09-11_Angebot_AN-2026-1187";
const offer = (part, amount, currency, qty, extra = {}) => ({ message: { id: MSG }, part: { id: part }, price: { amount, currency }, price_basis: "each", unit_price_usd: null, qty_break: qty, valid_until: "2026-10-31", origin: "DE", origin_claim: null, available_from: null, conditions: null, ...extra });

test("a German quote: the price is the record's decimal, so EUR 389,50 shows as 389.50 and never 38,950", () => {
  const rows = offerRows([offer("HR-12210", "389.5", "EUR", 100), offer("HR-12210", "376.1", "EUR", 250), offer("HR-99999", "1", "EUR", 1, { message: { id: "other" } })], MSG);
  assert.deepEqual(rows.map((r) => [r.partId, r.amount, r.breakQty]), [["HR-12210", "389.5", 100], ["HR-12210", "376.1", 250]]);
  assert.deepEqual(rows.map((r) => moneyText({ amount: r.amount, currency: r.currency }, true)), ["€389.50", "€376.10"]);
});

test("the offer parts of a message come from its changes, once each; the label is never parsed for a price", () => {
  const ch = (id, label) => ({ ref: { type: "part", id }, label, before: null, after: "x" });
  const v = messageView(msg("Quote", [ch("HR-12210", "Offer 389,50 EUR at 100"), ch("HR-12210", "Offer 376,10 EUR at 250"), ch("HR-20103", "Offer 1.234,56 EUR")]));
  assert.deepEqual(v.offerParts, ["HR-12210", "HR-20103"]);
});

test("eleven prices from one quote (BCX) all come through, and two sites of one part are told apart", () => {
  const eleven = Array.from({ length: 11 }, (_, i) => offer(`HR-201${String(i).padStart(2, "0")}`, `${10 + i}.25`, "USD", null));
  assert.equal(offerRows(eleven, MSG).length, 11);
  const two = offerRows([offer("HR-50110", "1155.21", "USD", null, { origin: "CN", origin_claim: "China (Huizhou)" }), offer("HR-50110", "1224.52", "USD", null, { origin: null, origin_claim: "Malaysia (Penang assembly; cells from the Huizhou plant)", available_from: "2027-02-01" })], MSG);
  assert.deepEqual(two.map((r) => r.site), ["China (Huizhou)", "Malaysia (Penang assembly"]);
  assert.equal(two[1].availableFrom, "2027-02-01");
});

test("moved promise dates become was and now; a price notice becomes a fact", () => {
  const v = messageView(msg("Moves 1 line", [po("HPO-26-00623/10", "Promise date moves (HR-21107)", "2026-09-28", "2026-10-30"), { ref: { type: "supplier", id: "S" }, label: "Price change", before: "2026-11-01", after: "+8.5% extruded profiles from 2026-11-01" }]));
  assert.deepEqual(v.lines[0], { id: "HPO-26-00623/10", partId: "HR-21107", was: "Sep 28", now: "Oct 30" });
  assert.equal(v.facts[0].value, "Nov 1 → +8.5% extruded profiles from Nov 1");
});

test("a blocked change is not shown as a change; the held headline is the first sentence only", () => {
  const v = messageView(msg("Asks to send USD 187,420 to new bank details and update the vendor master. Blocked: the sender's domain imitates a supplier's; asks to change where payments go. Nothing may follow from it.", [{ ref: { type: "supplier", id: "" }, label: "Payment change request (blocked)", before: null, after: "asks to pay" }]));
  assert.equal(v.blocked, true); assert.equal(v.facts.length, 0); assert.equal(v.lines.length, 0);
  assert.equal(headline("Asks to send USD 187,420 to new bank details. Blocked: because."), "Asks to send $187,420 to new bank details");
});

test("BCX quotes per 1,000: the quoted price and the price each are different figures, each in its own column value", () => {
  const rows = offerRows([offer("HR-20103", "240.58", "USD", null, { price_basis: "per_1000", unit_price_usd: { amount: "0.24058" } }), offer("HR-12210", "389.5", "EUR", 100)], MSG);
  assert.deepEqual(rows.map((r) => [r.basis, r.unitUsd]), [["per_1000", "0.24058"], ["each", null]]);
  assert.equal(moneyText({ amount: rows[0].unitUsd, currency: "USD" }, true), "$0.2406");
  assert.equal(moneyText({ amount: rows[0].amount, currency: "USD" }, true), "$240.58");
  assert.equal(moneyText({ amount: "1.5", currency: "USD" }, true), "$1.50", "four decimals only under one");
});

test("a quote headline says how many parts, not the list", () => assert.equal(headline("Quote for 11 parts: HR-20103, HR-20104, HR-20110."), "Quote for 11 parts"));
