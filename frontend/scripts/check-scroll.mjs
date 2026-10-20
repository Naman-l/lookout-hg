// No scroll surprises: every screen, at phone, tablet and desktop widths, must not scroll sideways,
// must hide its scrollbars, and must have one scroll surface (the page). Run against a running app:
//   BASE=http://127.0.0.1:8000 npm run check:scroll
import { chromium } from "playwright-core";

const BASE = process.env.BASE ?? "http://127.0.0.1:8000";
const SIZES = [[360, 780], [390, 844], [768, 1024], [1440, 900]];
const j = async (p) => (await fetch(`${BASE}/api${p}`)).json();
const enc = encodeURIComponent;

const items = await j("/action-items");
const msgs = await j("/messages");
const actions = await j("/actions");
const runs = await j("/runs");
const routes = ["/", "/inbox", "/suppliers", "/parts", "/parts/bom", "/orders", "/forecast", "/approvals", "/activity", "/data", "/data/import", "/more", "/shelf",
  `/inbox/${enc(msgs[0]?.ref.id ?? "")}`, "/suppliers/SUP-0001", "/parts/HR-40110", "/parts/bom/HR-90020",
  ...items.map((i) => `/items/${enc(i.key)}`),
  ...actions.slice(0, 2).map((a) => `/approvals/${a.action_id}`),
  ...runs.slice(0, 2).map((r) => `/activity/${r.run_id}`)];

const browser = await chromium.launch({ channel: "chrome" });
const bad = [];
let checked = 0;
for (const [w, h] of SIZES) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h } });
  await ctx.addInitScript(() => { try { localStorage.setItem("lookout.me", "Dana Reyes"); } catch { /* a person has chosen who they are */ } });
  const page = await ctx.newPage();
  for (const r of routes) {
    await page.goto(BASE + r, { waitUntil: "networkidle" });
    await page.waitForTimeout(250);
    const res = await page.evaluate(() => {
      const de = document.scrollingElement;
      const nested = [...document.querySelectorAll("body *")].filter((e) => {
        const cs = getComputedStyle(e);
        return /(auto|scroll)/.test(cs.overflowY + cs.overflowX) && (e.scrollHeight > e.clientHeight + 1 || e.scrollWidth > e.clientWidth + 1) && !e.closest(".drawer, .sheetm") && !e.matches(".apx .apq, .apx .apd, .apx .apr, .rc-scroll, .ld-list, .ld-detail, .ai-body, .td-rows, .rbp-body, .pg-body, .rt-trace, .dp-steps, .ix-lscroll, .ix-dscroll, .item-main, .rail-scroll, .item-grid>.rail, .tablewrap, .ds-seg, .ml-pre");
      }).map((e) => `${e.tagName.toLowerCase()}.${String(e.className).split(" ")[0]}`);
      const wide = [...document.querySelectorAll("main *")].filter((e) => e.getBoundingClientRect().right > de.clientWidth + 1 && e.offsetParent !== null).slice(0, 3).map((e) => `${e.tagName.toLowerCase()}.${String(e.className).split(" ")[0]}`);
      window.scrollTo(0, document.body.scrollHeight);
      const tabs = [...document.querySelectorAll(".ds-tabs")].find((t) => getComputedStyle(t).position === "fixed"), kids = [...document.querySelectorAll("main > *")].filter((e) => e.getBoundingClientRect().height > 0);
      const last = kids[kids.length - 1];
      const covered = !!(tabs && getComputedStyle(tabs).display !== "none" && last && last.getBoundingClientRect().bottom > tabs.getBoundingClientRect().top + 1);
      return { covered, sw: de.scrollWidth, cw: de.clientWidth, bars: getComputedStyle(document.documentElement).scrollbarWidth, nested, wide };
    });
    checked++;
    const why = [];
    if (res.sw > res.cw) why.push(`sideways ${res.sw}>${res.cw} (${res.wide.join(", ")})`);
    if (res.covered) why.push("the tab bar covers the end of the page");
    if (res.bars !== "none") why.push("scrollbar visible");
    if (res.nested.length) why.push(`nested scroll: ${res.nested.join(", ")}`);
    if (why.length) bad.push(`${w}px ${r}: ${why.join("; ")}`);
  }
  await page.close();
}
await browser.close();
console.log(`${checked} screens checked at ${SIZES.map((s) => s[0]).join(", ")} px`);
if (bad.length) { console.log(bad.join("\n")); process.exit(1); }
console.log("no sideways scroll, no visible scrollbars, no nested scrolling beyond the master-detail columns, the item's two columns, Today's rows, the Inbox's two columns, the Ask panel and the sub-navigation row");
