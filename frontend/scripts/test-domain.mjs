// Unit tests for the §7 domain components: each renders its meaning in words, copes with long and duplicate names, and passes the markup a11y checks.
import { build } from "esbuild";
import { test } from "node:test";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const out = join(mkdtempSync(join(tmpdir(), "domain-")), "domain.mjs");
await build({ entryPoints: ["scripts/domain-render.tsx"], outfile: out, bundle: true, format: "esm", platform: "node", jsx: "automatic", loader: { ".css": "empty" }, logLevel: "silent", banner: { js: "import { createRequire } from 'module'; const require = createRequire(import.meta.url);" } });
const D = await import(pathToFileURL(out).href);
const { html, h } = D;

const text = (m) => m.replace(/<[^>]*>/g, " ").replace(/&#x27;/g, "'").replace(/&amp;/g, "&").replace(/\s+/g, " ").trim();

/** Markup-level accessibility: icons hidden, links and buttons named, tooltips wired, tables headed, no raw codes. */
function a11y(m) {
  for (const s of m.match(/<svg[^>]*>/g) ?? []) assert.match(s, /aria-hidden="true"/, `svg must be hidden from assistive tech: ${s}`);
  for (const a of m.match(/<(a|button)\b[^>]*>[\s\S]*?<\/\1>/g) ?? []) assert.ok(/aria-label="[^"]+"/.test(a) || text(a).length > 0, `link/button needs a name: ${a}`);
  for (const [, id] of m.matchAll(/aria-describedby="([^"]+)"/g)) assert.ok(m.includes(`id="${id}"`) && m.includes('role="tooltip"'), `aria-describedby ${id} must point at a tooltip`);
  if (m.includes("<table")) { assert.match(m, /<caption/); assert.match(m, /<th scope="col"/); }
  assert.ok(!/<img\b/.test(m), "no bare images");
  assert.ok(!/\b[a-z]+_[a-z_]+\b/.test(text(m)), `a raw code reached the screen: ${text(m)}`);
}
const check = (node) => { const m = html(node); a11y(m); return m; };

test("Part: name, product hint and number; the whole chip links; a long name keeps its full text in the title", () => {
  const m = check(h(D.Part, { id: "HR-40110", name: "Drive motor", product: "Tern" }));
  assert.match(m, /href="\/parts\/HR-40110"/);
  assert.equal(text(m), "Drive motor · Tern HR-40110");
  const long = "Motor, brushless DC, 48 V 400 W, 86 mm frame, hall sensors, encoder, Tern drive";
  const l = check(h(D.Part, { id: "HR-1", name: long }));
  assert.ok(l.includes(`title="${long} HR-1"`) && l.includes('class="dm-name"'));
  assert.ok(!check(h(D.Part, { id: "HR-2", name: "X", to: false })).includes("<a "));
});

test("Part: two parts with one name stay distinct by product and number", () => {
  const a = text(check(h(D.Part, { id: "HR-40110", name: "Drive motor", product: "Tern" })));
  const b = text(check(h(D.Part, { id: "HR-40210", name: "Drive motor", product: "Porter" })));
  assert.notEqual(a, b);
});

test("Supplier: name, country code, trust in words with a mark", () => {
  const m = check(h(D.Supplier, { id: "SUP-0001", name: "Shenzhen Yunzhan Precision Motor Co., Ltd.", country: "CN", trust: "lookalike" }));
  assert.match(m, /href="\/suppliers\/SUP-0001"/);
  assert.match(text(m), /CN Look-alike$/);
  assert.match(text(check(h(D.Supplier, { id: "S", name: "A", trust: "on_file" }))), /On file/);
  assert.match(text(check(h(D.Supplier, { id: "S", name: "A", trust: "new" }))), /New/);
});

test("Money: $396K, $8,009 under $10K, $1.54M, exact cents only when exact", () => {
  const t = (v, exact) => text(check(h(D.Money, { value: v, exact })));
  assert.equal(t({ amount: "396000", currency: "USD" }), "$396K");
  assert.equal(t({ amount: "8009", currency: "USD" }), "$8,009");
  assert.equal(t({ amount: "1539053.57", currency: "USD" }), "$1.54M");
  assert.equal(t({ amount: "188.9875", currency: "USD" }, true), "$188.99");
  assert.equal(t({ amount: "1000", currency: "CNY", usd: "140" }), "$140");
  assert.match(check(h(D.Money, { value: { amount: "5", currency: "USD" }, risk: true })), /data-tone="red"/);
});

test("DateDue: counted from the data date; amber within 7 days, red when past, always with words", () => {
  const d = (date, extra = {}) => check(h(D.DateDue, { date, asOf: "2026-09-25", ...extra }));
  assert.equal(text(d("2026-10-10")), "Oct 10 in 15 days");
  assert.ok(!d("2026-10-10").includes("data-tone"));
  const soon = d("2026-10-01"); assert.match(soon, /data-tone="amber"/); assert.match(text(soon), /in 6 days/);
  const past = d("2026-09-23"); assert.match(past, /data-tone="red"/); assert.match(text(past), /2 days past/);
  assert.match(text(d("2026-09-25")), /on the data date/);
  assert.equal(text(check(h(D.DateDue, { date: null }))), "—");
  assert.match(text(check(h(D.DateDue, { date: "2026-10-10", daysLeft: 3 }))), /in 3 days/);
});

test("Stage: one pill each, Needs your OK amber, done green, Held red", () => {
  const s = (stage, waitingOn) => check(h(D.Stage, { stage, waitingOn }));
  assert.match(s("drafted", "you"), /data-tone="amber"[\s\S]*Needs your OK/);
  assert.match(s("drafted", "buyer"), /Drafted/);
  for (const k of ["approved", "sent", "answered"]) assert.match(s(k), /data-tone="green"/);
  assert.match(s("held"), /data-tone="red"[\s\S]*Held/);
  assert.match(s("asking"), /data-tone="amber"[\s\S]*Asking/);
  for (const [k, w] of [["found", "Found"], ["worked", "Worked"], ["decision_ready", "Ready to decide"]]) { const m = s(k); assert.ok(!m.includes("data-tone")); assert.match(text(m), new RegExp(w)); }
});

test("TrustBadge: a sentence, never the code; concern is red, verified is green", () => {
  const m = check(h(D.TrustBadge, { reason: "sender_domain_lookalike" }));
  assert.match(text(m), /The sender's domain looks like the supplier's but is not the one on file/);
  assert.match(m, /data-tone="red"/);
  assert.match(text(check(h(D.TrustBadge, { reason: "contact_on_file", ok: true }))), /Passed: The sender is a contact on file/);
  assert.match(text(check(h(D.TrustBadge, { reason: "some_new_flag" }))), /Some new flag/);
  for (const code of Object.keys(D.REASONS)) check(h(D.TrustBadge, { reason: code }));
  assert.equal((check(h(D.TrustBadges, { flags: [], onFile: true })).match(/data-tone="green"/g) ?? []).length, 3);
  assert.equal((check(h(D.TrustBadges, { flags: ["bank_detail_change", "reply_to_freemail"] })).match(/data-tone="red"/g) ?? []).length, 2);
});

test("ProblemKind: plain name, meaning on hover and focus, group names mapped; the legend lists all six", () => {
  assert.equal(D.kindOfGroup("disruption"), "cant_deliver");
  assert.equal(D.kindOfGroup("tariff"), "import_duty");
  assert.equal(D.kindOfGroup("trust"), "held_message");
  assert.equal(D.kindOfGroup("unknown"), "open_question");
  const m = check(h(D.ProblemKind, { kind: "cant_deliver" }));
  assert.match(m, /Supplier can&#x27;t deliver|Supplier can't deliver/);
  assert.match(m, /role="tooltip"[^>]*>A supplier cannot ship what we ordered/);
  assert.match(m, /tabindex="0"/);
  assert.match(check(h(D.ProblemKind, { kind: "held_message" })), /data-tone="red"/);
  assert.match(check(h(D.ProblemKind, { kind: "deadline", iconOnly: true })), /class="dm-sr">Deadline/);
  const legend = check(h(D.ProblemLegend));
  assert.equal((legend.match(/<dt/g) ?? []).length, 6);
  assert.ok(!/BOM|HTS|tariff|disruption/i.test(text(legend)), "no jargon in the legend");
});

test("People: first names; a shared first name adds the last initial; four or more become a count chip naming them", () => {
  const two = text(check(h(D.People, { names: ["Dana Reyes", "Dana Kim"] })));
  assert.match(two, /Dana R\./); assert.match(two, /Dana K\./);
  assert.match(text(check(h(D.People, { names: ["Dana Reyes", "Li Wei"] }))), /Dana.*Li/);
  const many = check(h(D.People, { names: ["A One", "B Two", "C Three", "D Four"] }));
  assert.match(text(many), /4 people/); assert.match(many, /role="tooltip"[^>]*>A One, B Two, C Three, D Four/);
  assert.match(text(check(h(D.Person, { name: "Dana Reyes" }))), /DR Dana/);
});

test("PoLine: the real number; PoLineTable collapses after 3 and shows was and now", () => {
  assert.equal(text(check(h(D.PoLine, { id: "HPO-26-00450 / 10", qty: "1200", uom: "EA", date: "2026-10-10" }))), "HPO-26-00450/10 · 1,200 EA · Oct 10");
  const rows = Array.from({ length: 5 }, (_, i) => ({ id: `HPO-26-00450 / ${10 + i}`, part: { id: "HR-40110", name: "Drive motor", product: "Tern" }, qty: 100 + i, uom: "EA", was: "Oct 1", now: "Nov 17" }));
  const m = check(h(D.PoLineTable, { rows }));
  assert.equal((m.match(/<tr>/g) ?? []).length, 1 + 3, "header + 3 rows");
  assert.match(m, /Show 2 more/); assert.match(m, /<th scope="col">Was<\/th><th scope="col">Now<\/th>/);
  assert.match(m, /HPO-26-00450\/10/);
  const two = check(h(D.PoLineTable, { rows: rows.slice(0, 2).map(({ was, now, ...r }) => r) }));
  assert.ok(!/Show \d+ more/.test(two) && !/>Was</.test(two));
});

test("Term: a known word carries its meaning, an unknown one is left alone", () => {
  const m = check(h(D.Term, { k: "BOM" }));
  assert.match(m, /role="tooltip"[^>]*>Bill of materials/);
  assert.equal(text(check(h(D.Term, { k: "Zorp" }))), "Zorp");
});

test("EntityText: chips inside text; overlapping spans keep the earlier or longer one, adjacent spans both stay, bad spans are ignored", () => {
  const text = "Ship HR-40110 to Yunzhan by Oct 10";
  const ents = [{ start: 5, end: 13, type: "part", ref: "HR-40110", label: "Drive motor" }, { start: 17, end: 24, type: "supplier", ref: "SUP-1" }, { start: 28, end: 34, type: "date" }];
  const m = check(h(D.EntityText, { text, entities: ents }));
  assert.equal(text.replace(/\s+/g, " "), "Ship HR-40110 to Yunzhan by Oct 10");
  assert.match(m, /href="\/parts\/HR-40110"/); assert.match(m, /href="\/suppliers\/SUP-1"/);
  assert.equal(m.replace(/<[^>]*>/g, ""), text, "the words stay as written; the part name is the hover");
  assert.match(m, /title="Drive motor"/);
  const spans = (e) => D.cleanEntities("0123456789", e).map((x) => [x.start, x.end]);
  assert.deepEqual(spans([{ start: 2, end: 6, type: "part" }, { start: 4, end: 8, type: "date" }]), [[2, 6]], "overlap: the earlier span wins");
  assert.deepEqual(spans([{ start: 2, end: 4, type: "part" }, { start: 2, end: 8, type: "date" }]), [[2, 8]], "same start: the longer wins");
  assert.deepEqual(spans([{ start: 0, end: 3, type: "part" }, { start: 3, end: 6, type: "date" }]), [[0, 3], [3, 6]], "adjacent both stay");
  assert.deepEqual(spans([{ start: -1, end: 3, type: "part" }, { start: 5, end: 99, type: "part" }, { start: 4, end: 4, type: "part" }]), []);
  assert.deepEqual(D.cleanEntities("Ship HR-1", [{ start: 5, end: 9, type: "part", text: "HR-1" }, { start: 0, end: 4, type: "part", text: "Nope" }]).map((x) => x.start), [5], "a span whose text does not match is dropped");
  assert.equal(m2(h(D.EntityText, { text: "plain" })), "plain");
});
test("EntityText: a look-alike supplier is red with a warning, never a link", () => {
  const m = check(h(D.EntityText, { text: "from Yunzhan Accounts", entities: [{ start: 5, end: 21, type: "supplier_lookalike", ref: "SUP-0001", label: "Shenzhen Yunzhan" }] }));
  assert.match(m, /data-tone="red"/); assert.ok(!m.includes("<a ")); assert.match(m, /look-alike/);
});
function m2(node) { return html(node); }

test("Inbox search match: the field, the snippet, the matched words marked; a bad span marks nothing", () => {
  const m = check(h(D.Match, { x: { field: "body", snippet: "Prices for the planetary gearbox PG120", start: 25, end: 32 } }));
  assert.match(m, /Message: …Prices for the planetary <mark class="ib-hit">gearbox<\/mark> PG120…/);
  assert.ok(!check(h(D.Match, { x: { field: "subject", snippet: "short", start: 3, end: 99 } })).includes("<mark"));
});

test("EntityText: money and quantity are bold tabular figures, a date is a chip toned by the data date, a duration is a quiet chip", () => {
  const text = "Pay $187,420 for 1,200 EA by Oct 1, restart in 6 to 8 weeks";
  const at = (s) => [text.indexOf(s), text.indexOf(s) + s.length];
  const ent = (s, type, extra = {}) => ({ start: at(s)[0], end: at(s)[1], type, ...extra });
  const m = check(h(D.EntityText, { text, asOf: "2026-09-25", entities: [ent("$187,420", "money"), ent("1,200 EA", "quantity"), ent("Oct 1", "date", { ref: "2026-10-01" }), ent("6 to 8 weeks", "duration")] }));
  assert.equal((m.match(/class="dm-fig/g) ?? []).length, 2);
  assert.match(m, /<span class="dm-unit"> EA<\/span>/, "the unit is muted");
  assert.match(m, /data-type="date"[^>]*data-tone="amber"|data-tone="amber"[^>]*data-type="date"/);
  assert.match(m, /dm-inline quiet/);
  assert.equal(m.replace(/<[^>]*>/g, ""), text);
});

test("EntityLines: one sentence per line, entities stay in their sentence, the rest is behind Read in full", () => {
  const text = "A fire stopped Plant 2. Revised dates are due Oct 10. Recovery takes 6 to 8 weeks. Nothing else is known.";
  const i = text.indexOf("Oct 10");
  const m = check(h(D.EntityLines, { text, limit: 2, entities: [{ start: i, end: i + 6, type: "date" }] }));
  assert.equal((m.match(/<p>/g) ?? []).length, 2);
  assert.match(m, /Read in full/); assert.match(m, /data-type="date"/);
  assert.deepEqual(D.sentenceRanges("One. Two? Three.").length, 3);
  assert.deepEqual(D.sentenceRanges("Costs 1.5 EUR each. Fine").length, 2, "a decimal point is not a sentence end");
});

test("Points: labelled rows", () => {
  const m = check(h(D.Points, { points: [{ label: "What changed", text: "Ten lines cannot ship." }, { label: "What to do", text: "Ask for dates." }] }));
  assert.equal((m.match(/<dt>/g) ?? []).length, 2); assert.match(m, /<dt>What changed<\/dt><dd>Ten lines cannot ship\./);
});

test("every entity type has its one marker: person dot, supplier glyph and tick, PO line in muted mono", () => {
  const t = "Li Wei at Yunzhan on HPO-26-00450/20";
  const m = check(h(D.EntityText, { text: t, entities: [{ start: 0, end: 6, type: "person" }, { start: 10, end: 17, type: "supplier", ref: "SUP-1", trust: "on_file" }, { start: 21, end: 36, type: "po_line", ref: "HPO-26-00450/20" }] }));
  assert.match(m, /class="dm-dot"[^>]*>LW<\/i>Li Wei/);
  assert.match(m, /dm-sr"> on file/); assert.match(m, /class="dm-po-text"/);
  assert.deepEqual(D.MARKERS.map((x) => x.type), ["money", "quantity", "date", "duration", "person", "supplier", "part", "po_line"]);
});

test("fraud mail: a supplier span in a held or flagged message is never a supplier chip; supplier_claimed is red with no link", () => {
  const text = "Please pay Yunzhan Precision (HK) Trading today";
  const ent = [{ start: 11, end: 40, type: "supplier", ref: "SUP-0001", label: "Shenzhen Yunzhan", trust: "on_file" }];
  const bad = check(h(D.EntityText, { text, entities: ent, suspect: true }));
  assert.ok(!bad.includes("<a "), "no link to the real supplier"); assert.ok(!/on file/.test(bad.replace(/<[^>]*>/g, " ")), "no on-file badge");
  assert.match(bad, /data-tone="red"/); assert.match(bad, /unverified/);
  const claimed = check(h(D.EntityText, { text, entities: [{ ...ent[0], type: "supplier_claimed" }] }));
  assert.ok(!claimed.includes("<a ")); assert.match(claimed, /data-tone="red"/);
  assert.match(check(h(D.EntityText, { text, entities: ent })), /href="\/suppliers\/SUP-0001"/, "a trusted message still links");
});
