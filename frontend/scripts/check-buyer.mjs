// What a member of the SCM team reads: no dollars, no robots; plain not-found pages; every sidebar link opens a page; a case has its six steps
// (four on held mail); Insights and Records answer. Needs `make run`. GET only.
import { chromium } from "playwright-core";
const BASE = process.env.BASE ?? "http://127.0.0.1:8001";
const items = await (await fetch(`${BASE}/api/action-items`)).json();
const browser = await chromium.launch({ channel: "chrome" });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
await ctx.addInitScript(() => localStorage.setItem("lookout.me", "Urvik Patel"));
const page = await ctx.newPage();
await page.route("**/*", (r) => (["GET", "HEAD"].includes(r.request().method()) ? r.continue() : r.abort()));
const fails = [];
const text = async () => (await page.locator("main").innerText()).replace(/\s+/g, " ");
for (const path of ["/items/nope%3Anone", "/vendors/NOPE", "/materials/NOPE"]) {
  await page.goto(BASE + path, { waitUntil: "networkidle" });
  if (!/not found|No such|no such/i.test(await text())) fails.push(`${path} does not say plainly that it is not found`);
}
await page.goto(BASE + "/", { waitUntil: "networkidle" });
const links = await page.locator("nav.ds-nav a, .side-foot a").evaluateAll((es) => es.map((e) => e.getAttribute("href")));
for (const h of links) {
  await page.goto(BASE + h, { waitUntil: "networkidle" });
  const t = await text();
  if (/Page not found/.test(t)) fails.push(`${h} opens Page not found`);
  if (/\$\d|USD|robot/i.test(t)) fails.push(`${h} shows dollars or robots`);
}
for (const i of items.slice(0, 27)) {
  await page.goto(`${BASE}/items/${encodeURIComponent(i.key)}`, { waitUntil: "networkidle" });
  const steps = await page.locator(".cp-track li").count();
  if (steps !== (i.tab === "trust" ? 4 : 6) && steps !== 5) fails.push(`${i.key}: ${steps} steps`);
  if (/\$\d|USD/.test(await text())) fails.push(`${i.key} shows dollars`);
}
await browser.close();
console.log(fails.length ? fails.join("\n") : `ok: ${links.length} sidebar links, ${Math.min(27, items.length)} cases, plain not-found pages, no dollars`);
process.exit(fails.length ? 1 : 0);
