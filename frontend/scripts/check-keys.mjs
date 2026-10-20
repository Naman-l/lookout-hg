// Keyboard pass: on each screen, Tab never traps, every stop shows a focus ring, a focused control is never left
// under the pinned bars, and Enter on a row opens it. Run against a running app:
//   BASE=http://127.0.0.1:8000 npm run check:keys
import { chromium } from "playwright-core";

const BASE = process.env.BASE ?? "http://127.0.0.1:8000";
const SIZES = [[390, 844], [1440, 900]];
const ROUTES = ["/", "/more", "/shelf", "/approvals", "/inbox", "/parts/HR-40110", "/items/disruption%3ASUP-0001", "/data/import", "/orders"];
const STOPS = 36;

const browser = await chromium.launch({ channel: "chrome" });
const bad = [];
let stops = 0;
for (const [w, h] of SIZES) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h } });
  await ctx.addInitScript(() => { try { localStorage.setItem("lookout.me", "Dana Reyes"); } catch { /* a person has chosen who they are */ } });
  const page = await ctx.newPage();
  for (const r of ROUTES) {
    await page.goto(BASE + r, { waitUntil: "networkidle" });
    await page.waitForTimeout(250);
    const seen = new Set();
    for (let n = 0; n < STOPS; n++) {
      await page.keyboard.press("Tab");
      const f = await page.evaluate(() => {
        const e = document.activeElement;
        if (!e || e === document.body) return null;
        const cs = getComputedStyle(e), rect = e.getBoundingClientRect();
        const covered = !e.closest(".ds-tabs, .stick") && [...document.querySelectorAll(".ds-tabs, .stick")].some((b) => { const q = b.getBoundingClientRect(); return q.height > 0 && q.top < rect.bottom && q.bottom > rect.top && q.left < rect.right && q.right > rect.left; });
        const ring = (cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) > 0) || cs.boxShadow !== "none" || e.closest(".field, .shelf");
        return { id: `${e.tagName.toLowerCase()}.${String(e.className).split(" ")[0]}|${(e.getAttribute("aria-label") || e.textContent || "").trim().slice(0, 24)}`, ring: !!ring, hidden: covered };
      });
      if (!f) continue;
      stops++;
      if (!f.ring) bad.push(`${w}px ${r}: no focus ring on ${f.id}`);
      if (f.hidden) bad.push(`${w}px ${r}: ${f.id} sits under a pinned bar`);
      seen.add(f.id);
    }
    if (seen.size < 2 && !r.startsWith("/shelf")) bad.push(`${w}px ${r}: Tab reached only ${seen.size} control(s)`);
  }
  // Enter on a row opens it
  for (const [route, sel, expect] of [["/", ".dt-row, a.td-row", /^\/(items|builds)\//], ["/more", ".nav-row", /^\/(suppliers|parts|orders|forecast|activity|data|shelf)/]]) {
    await page.goto(BASE + route, { waitUntil: "networkidle" });
    await page.waitForTimeout(300);
    const first = page.locator(sel).first();
    await first.focus(); await page.keyboard.press("Enter"); await page.waitForTimeout(500);
    const path = new URL(page.url()).pathname;
    if (!expect.test(path)) bad.push(`${w}px ${route}: Enter on a row did not open it (${path})`);
  }
  await page.close();
}
await browser.close();
console.log(`${stops} focus stops on ${ROUTES.length} screens at ${SIZES.map((s) => s[0]).join(", ")} px`);
if (bad.length) { console.log([...new Set(bad)].join("\n")); process.exit(1); }
console.log("Tab never traps, every stop has a focus ring, nothing hides under a pinned bar, Enter opens rows");
