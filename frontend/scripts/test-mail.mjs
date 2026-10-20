// Unit test for cutting a mail body into prose and fixed-spacing blocks.
import { build } from "esbuild";
import { test } from "node:test";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const out = join(mkdtempSync(join(tmpdir(), "mail-")), "m.mjs");
await build({ entryPoints: ["src/sections/inbox/mailBlocks.ts"], outfile: out, bundle: true, format: "esm", logLevel: "silent" });
const { mailBlocks } = await import(pathToFileURL(out).href);

const body = [
  "Dear Dana,", "",
  "We regret to inform you that a fire broke out in the coil winding", "workshop of our Plant 2. No one was injured.", "",
  "PO            Line  Part       Open qty", "HPO-26-00450  20    HR-40120   445", "HPO-26-00450  10    HR-40110   355", "",
  "Best regards,", "Li Wei", "Yunzhan Precision",
].join("\n");

test("prose is reflowed, an aligned table keeps its spacing, the signature keeps its lines", () => {
  const b = mailBlocks(body);
  assert.deepEqual(b.map((x) => x.kind), ["prose", "prose", "pre", "pre"]);
});

test("the greeting is a short block, the paragraph is prose, offsets cover the text without moving a character", () => {
  const b = mailBlocks(body);
  assert.equal(b[1].kind, "prose"); // the greeting is its own short paragraph
  assert.equal(body.slice(b[1].start, b[1].end).split("\n").length, 2);
  assert.equal(b[2].kind, "pre"); assert.match(body.slice(b[2].start, b[2].end), /HPO-26-00450 {2}20/);
  for (const x of b) assert.ok(x.end > x.start && x.end <= body.length);
  assert.ok(b.every((x, i) => i === 0 || x.start >= b[i - 1].end));
});
