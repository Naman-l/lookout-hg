// Unit test for the check strip: an answer with no numbers shows no "0 of 0 numbers match" pass.
import { build } from "esbuild";
import { test } from "node:test";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const out = join(mkdtempSync(join(tmpdir(), "checks-")), "agent.mjs");
await build({ entryPoints: ["src/domain-ui/Agent.tsx"], outfile: out, bundle: true, format: "esm", platform: "node", jsx: "automatic", loader: { ".css": "empty" }, logLevel: "silent", banner: { js: "import { createRequire } from 'module'; const require = createRequire(import.meta.url);" } });
const { checkFacts } = await import(pathToFileURL(out).href);

const run = (v) => ({ verifier: { failures: [], ...v }, recommendation: {} });

test("no numbers to check is not a pass: the line is not shown", () => {
  assert.deepEqual(checkFacts(run({ numbers_checked: 0, numbers_from_tools: 0 })), []);
});

test("numbers that all match say so; numbers that do not say how many do", () => {
  assert.equal(checkFacts(run({ numbers_checked: 3, numbers_from_tools: 3 }))[0].text, "3 of 3 numbers match the data");
  const f = checkFacts(run({ numbers_checked: 3, numbers_from_tools: 2 }))[0];
  assert.equal(f.tone, "caution"); assert.match(f.text, /2 of 3/);
});
