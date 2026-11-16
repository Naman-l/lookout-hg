// No screen scrolls sideways, on a phone (390) or a desktop (1440), for two personas. GET only: every other request is aborted. Needs `make run`.
import { chromium } from "playwright-core";
const BASE = process.env.BASE ?? "http://127.0.0.1:8001";
const enc = encodeURIComponent;
const items = await (await fetch(`${BASE}/api/action-items`)).json();
const msgs = await (await fetch(`${BASE}/api/messages`)).json();
const routes = ["/", "/approvals", "/inbox", `/inbox/${enc(msgs[0].ref.id)}`, "/vendors", "/vendors/100601", "/materials", "/materials/11000020", "/prs", "/prs/1000203689", "/pos", "/pos/4500120768",
  "/requirements", "/workfronts", "/lookup", "/insights/team", "/insights/projects", "/insights/projects/gaya", "/insights/pricing", "/insights/estimates", "/brief/Sambhav", "/org", "/org?view=list",
  "/data", "/data/import", "/hood", "/activity", "/more", "/design", ...items.slice(0, 27).map((i) => `/items/${enc(i.key)}`)];
const browser = await chromium.launch({ channel: "chrome" });
const bad = [];
for (const [w, h] of [[390, 844], [1440, 900]]) {
  for (const who of ["Sambhav Kumar", "Satish Kumar Sharma"]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h } });
    await ctx.addInitScript((p) => localStorage.setItem("lookout.me", p), who);
    const page = await ctx.newPage();
    await page.route("**/*", (r) => (["GET", "HEAD"].includes(r.request().method()) ? r.continue() : r.abort()));
    for (const r of w === 1440 && who !== "Sambhav Kumar" ? routes.slice(0, 12) : routes) {
      await page.goto(BASE + r, { waitUntil: "networkidle" });
      const wide = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      if (wide > 1) bad.push(`${w}px ${who.split(" ")[0]} ${r}: ${wide}px sideways`);
    }
    await ctx.close();
  }
}
await browser.close();
console.log(bad.length ? bad.join("\n") : `ok: ${routes.length} routes at 390 and 1440 px, no sideways scroll`);
process.exit(bad.length ? 1 : 0);
