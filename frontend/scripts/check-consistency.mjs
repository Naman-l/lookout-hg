// The designer's ten inconsistencies, as a check on the running app (desktop and phone):
// ids, PO-line format, headline numbers, tile colour, segmented control, filters, expand pattern, breadcrumb, content width, the clock.
import { chromium } from "playwright-core";

const BASE = process.env.BASE ?? "http://127.0.0.1:8000";
const enc = encodeURIComponent;
const items = await (await fetch(`${BASE}/api/action-items`)).json();
const routes = ["/", "/inbox", "/suppliers", "/suppliers/SUP-0001", "/parts", "/parts/HR-40110", "/orders", "/approvals", "/activity", "/data", ...items.slice(0, 4).map((i) => `/items/${enc(i.key)}`)];
const browser = await chromium.launch({ channel: "chrome" });
const bad = [];
for (const [w, h] of [[1440, 900], [390, 844]]) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h } });
  await ctx.addInitScript(() => { try { localStorage.setItem("lookout.me", "Dana Reyes"); } catch { /* a person has chosen who they are */ } });
  const page = await ctx.newPage();
  const widths = new Set();
  for (const r of routes) {
    await page.goto(BASE + r, { waitUntil: "networkidle" }); await page.waitForTimeout(300);
    const res = await page.evaluate(() => {
      const ink = getComputedStyle(document.body).color;
      const out = [];
      // the email is shown exactly as it will be sent, so its own wording is not held to the page's format
      const clone = document.body.cloneNode(true); clone.querySelectorAll(".mail").forEach((m) => m.remove());
      const text = clone.textContent ?? "";
      for (const a of document.querySelectorAll("a.pn")) if (getComputedStyle(a).color !== ink) out.push("id link not ink: " + a.textContent);
      if (/HPO-\d{2}-\d{5}\s+\/\s+\d+/.test(text)) out.push("PO line with spaces around the slash (the real number is HPO-26-00450/20)");
      for (const b of document.querySelectorAll(".ds-tile b")) if (getComputedStyle(b).color !== ink) out.push("tile figure not ink: " + b.textContent);
      const seg = [...document.querySelectorAll(".ds-seg button")].map((b) => getComputedStyle(b).fontSize);
      if (new Set(seg).size > 1) out.push("segmented controls differ in size");
      if (document.querySelector("input.field, .more")) out.push("legacy filter or Show-more control");
      const hasList = document.querySelector("table, .ds-row, .dt-row, .td-row, .apq-row"), tile = document.querySelector(".ds-tile");
      if (/\/(parts|suppliers|builds)\//.test(location.pathname) && hasList && tile && tile.getBoundingClientRect().top > hasList.getBoundingClientRect().top) out.push("headline tiles sit below the list");
      const back = document.querySelector(".ds-hd .back");
      if (back && !["Today", "Inbox", "Suppliers", "Parts", "Approvals", "Orders"].includes(back.textContent.trim())) out.push("breadcrumb is not a nav label: " + back.textContent);
      const main = document.querySelector("main");
      const mw = Math.round(main.getBoundingClientRect().width);
      const clocks = (document.querySelector(".top")?.textContent ?? "").match(/\b(today|updated|Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d{1,2}:\d{2}/g);
      if (clocks) out.push("a second clock in the header: " + clocks.join(", "));
      return { out, mw };
    });
    widths.add(res.mw);
    for (const o of res.out) bad.push(`${w}px ${r}: ${o}`);
  }
  if (widths.size > 1) bad.push(`${w}px: pages have different content widths ${[...widths].join(", ")}`);
  await page.goto(BASE + "/", { waitUntil: "networkidle" });
  const names = await page.evaluate(() => ({ h1: document.querySelector("h1")?.textContent, nav: [...document.querySelectorAll(".ds-nav a, .ds-tabs a")].map((a) => a.textContent.trim()) }));
  if (names.h1 !== "Today" || !names.nav.some((n) => n.startsWith("Today"))) bad.push(`${w}px: Today is not "Today" everywhere (${names.h1}; ${names.nav.join("|")})`);
  await page.close();
}
await browser.close();
console.log(`consistency: ${routes.length} screens at 1440 and 390`);
if (bad.length) { console.log([...new Set(bad)].join("\n")); process.exit(1); }
console.log("ok: ids, PO-line format, headline tiles, tile colour, segmented control, filters, expand pattern, breadcrumbs, content width and the clock are consistent");
