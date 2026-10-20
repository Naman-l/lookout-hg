// Design-system check: tokens.css is the only file allowed a colour, a px font size or a raw radius.
// Fails on any of these anywhere else in src/. Run: npm run check:ds  (add --report to list every hit)
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const root = new URL("../src/", import.meta.url).pathname;
const walk = (d) => readdirSync(d).flatMap((f) => { const p = join(d, f); return statSync(p).isDirectory() ? walk(p) : [p]; });
const files = walk(root).filter((f) => /\.(css|tsx?|svg)$/.test(f) && !/tokens\.css$|schema\.d\.ts$/.test(f));

const RULES = [
  ["colour", /#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|oklch|oklab|lch)\(/g, (m, line) => !/href=|\bid=|&#|url\(#|#\w+\)/.test(line) && !/^\s*(\/\/|\*)/.test(line)],
  ["font-size", /font-size:\s*(?!var\(--t-)[^;}]*\d|fontSize\s*[=:]\s*(?!["'`]var\()(?=\S)/g, () => true],
  ["font shorthand", /font:\s*(?:\d+\s+)?\d[\d.]*px/g, () => true],
  ["radius", /border-radius:\s*(?!var\(--r-|0\b|50%|inherit)[^;}]*\d/g, () => true],
  ["inline colour", /style=\{\{[^}]*\b(?:color|background|borderColor)\s*:\s*["'](?!var\()/g, () => true],
];
const hits = [];
for (const f of files) {
  readFileSync(f, "utf8").split("\n").forEach((line, i) => {
    for (const [name, re, ok] of RULES) { re.lastIndex = 0; let m; while ((m = re.exec(line))) { if (ok(m, line)) hits.push({ f: f.replace(root, ""), n: i + 1, name, text: m[0].slice(0, 60) }); } }
  });
}
const by = {};
for (const h of hits) by[h.name] = (by[h.name] ?? 0) + 1;
console.log(`design-system check: ${hits.length} raw value(s) outside tokens.css`, JSON.stringify(by));
if (process.argv.includes("--report")) for (const h of hits) console.log(`  ${h.f}:${h.n} [${h.name}] ${h.text}`);
if (hits.length) { if (!process.argv.includes("--report")) for (const h of hits.slice(0, 12)) console.log(`  ${h.f}:${h.n} [${h.name}] ${h.text}`); process.exit(1); }
console.log("ok: every colour, size and radius comes from tokens.css");
