// Unit test for "Still open" (BUYER R2 #3/#4): each question names its part or PO line and who answers it; the workflow-phase
// template and the unnamed guesses are left out, duplicates merge, and the list shows three before "+N more".
import { build } from "esbuild";
import { test } from "node:test";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const out = join(mkdtempSync(join(tmpdir(), "open-q-")), "oq.mjs");
await build({ entryPoints: ["src/domain-ui/openQuestions.ts"], outfile: out, bundle: true, format: "esm", logLevel: "silent" });
const { namedQuestions } = await import(pathToFileURL(out).href);

test("named questions stay, in order, with who answers; the template and the unnamed guess go", () => {
  const qs = [
    { what: "whether this order is still open", question: "Was Motor order (PO-1001 line 1) (AB-90001) delivered, cancelled, or is it really still open?", owner: "Dana" },
    { what: "whether this order is still open", question: "Was Lidar order (PO-1002 line 1) (AB-90002) delivered, cancelled, or is it really still open?", owner: "Marcus" },
    { what: "old orders probably not really open", question: "Was each delivered, cancelled, or is it really still open?", owner: "Dana" },
    { what: "Where PO-1001/1 is in: quoted, acknowledged, shipped", question: "Has the supplier acknowledged PO-1001?", owner: "supplier" },
    { what: "Where PO-1001/1 is in: through customs", question: "Has the customs broker cleared PO-1001?", owner: "broker" },
  ];
  assert.deepEqual(namedQuestions(qs), [
    { text: "Was Motor order (PO-1001 line 1) (AB-90001) delivered, cancelled, or is it really still open?", owner: "Dana" },
    { text: "Was Lidar order (PO-1002 line 1) (AB-90002) delivered, cancelled, or is it really still open?", owner: "Marcus" },
  ]);
});

test("a bare 'country of origin' is shown by its own question that names the part; duplicates merge; the owner is capitalised", () => {
  const qs = [
    { what: "country of origin (and 2 like it)", question: "Where is Ball screw (AB-13103) made? Ask the supplier for a certificate of origin.", owner: "Dana" },
    { what: "country of origin", question: "Where is Ball screw (AB-13103) made? Ask the supplier for a certificate of origin.", owner: "Dana" },
    { what: "country of origin unknown", question: "Where are these parts made? Ask each supplier for a certificate of origin.", owner: "Dana" },
    { what: "late line ships before the duty date", question: "When will the late line of AB-40220 ship?", owner: "supplier" },
  ];
  assert.deepEqual(namedQuestions(qs), [
    { text: "Where is Ball screw (AB-13103) made? Ask the supplier for a certificate of origin.", owner: "Dana" },
    { text: "When will the late line of AB-40220 ship?", owner: "Supplier" },
  ]);
});

test("a question with no question text falls back to its 'what' when that names an id", () => {
  assert.deepEqual(namedQuestions([{ what: "the promised date of PO-1003/10", owner: null }, { what: "country of origin" }]),
    [{ text: "the promised date of PO-1003/10", owner: null }]);
});
