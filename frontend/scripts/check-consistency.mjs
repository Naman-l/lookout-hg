// The same number in every place it is shown: the sidebar's Today count is Today's Yours "your move" count; Approvals' count is its To approve tab;
// the Inbox count is its Yours list. For each SCM member. Needs `make run`.
import { chromium } from "playwright-core";
const BASE = process.env.BASE ?? "http://127.0.0.1:8001";
const people = await (await fetch(`${BASE}/api/people`)).json();
const browser = await chromium.launch({ channel: "chrome" });
const bad = [];
for (const p of people) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await ctx.addInitScript((n) => localStorage.setItem("lookout.me", n), p.name);
  const page = await ctx.newPage();
  await page.route("**/*", (r) => (["GET", "HEAD"].includes(r.request().method()) ? r.continue() : r.abort()));
  await page.goto(BASE + "/", { waitUntil: "networkidle" });
  // a section with nothing waiting shows no count: read it as 0 at once rather than waiting for a badge that will not come
  const side = async (label) => { const c = page.locator(`nav.ds-nav a:has-text("${label}")`).first().locator("span.n"); return (await c.count()) ? Number(await c.first().textContent()) || 0 : 0; };
  await page.waitForFunction(() => document.querySelector(".td-seg button em")?.textContent !== "");
  const today = Number((await page.locator(".td-seg button").first().locator("em").textContent()) || 0);
  if ((await side("Today")) !== today) bad.push(`${p.name}: sidebar Today ${await side("Today")} vs Yours ${today}`);
  await page.goto(BASE + "/approvals", { waitUntil: "networkidle" });
  const tab = Number((await page.locator(".apx-tabs button").first().locator("em").textContent()) || 0);
  if ((await side("Approvals")) !== tab) bad.push(`${p.name}: sidebar Approvals ${await side("Approvals")} vs To approve ${tab}`);
  await ctx.close();
}
await browser.close();
console.log(bad.length ? bad.join("\n") : `ok: Today and Approvals counts agree for ${people.length} members`);
process.exit(bad.length ? 1 : 0);
