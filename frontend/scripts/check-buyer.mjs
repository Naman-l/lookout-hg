// The buyer's first minute, checked: a stranger meets a picker, then plain words. Needs `make run` (BASE) on a fresh database.
//   - no raw data on a buyer page (JSON, undefined, NaN)
//   - a check strip never says "ok" about something that is not wholly true
//   - the main path is four places, every link resolves, and Today opens on an item, not a build
//   - the bare "a" key approves nothing; the approve button names who signs
//   - bare ids on the main path are counted (Today, an item, Approvals, Inbox); IDS_STRICT=1 makes the budget a failure
import { chromium } from "playwright-core";

const BASE = process.env.BASE ?? "http://127.0.0.1:8000";
const STRICT = process.env.IDS_STRICT === "1";
const ID = /\b(HR-?\d{5}|HPO-\d\d-\d{5}\s*\/\s*\d+|PO-\d{5}\/\d+|SUP-\d{4}|V\d{5}|Q-[A-Z]{2}-\d\d-\d{4})\b/g;
const BUDGET = { today: 0, item: 0, approvals: 0, inbox: 0 };
const fails = [];
const fail = (m) => { fails.push(m); console.log("FAIL " + m); };

const browser = await chromium.launch({ channel: "chrome" });
const items = await (await fetch(`${BASE}/api/action-items`)).json();
for (const [w, h] of [[1440, 900], [390, 844]]) {
  const tag = `${w}px`;
  const ctx = await browser.newContext({ viewport: { width: w, height: h } });
  const page = await ctx.newPage();
  const posts = [];
  page.on("request", (r) => { if (r.method() === "POST") posts.push(r.url()); });

  // a number that does not exist is a plain sentence, never a blank page or a thrown error
  const thrown = [];
  page.on("pageerror", (e) => thrown.push(e.message));
  for (const path of ["/parts/NOPE-0", "/suppliers/NOPE-0", "/items/nope%3Anone"]) {
    await page.goto(BASE + path, { waitUntil: "networkidle" });
    const text = ((await page.locator("#root").innerText().catch(() => "")) || "").replace(/\s+/g, " ").trim();
    if (!/not found|could not be found/i.test(text)) fail(`${tag} ${path}: an unknown number must say it could not be found (got "${text.slice(0, 60)}")`);
  }
  if (thrown.length) fail(`${tag} an unknown number threw: ${thrown[0]}`);
  await page.goto(BASE + "/", { waitUntil: "networkidle" });
  await page.waitForTimeout(600);
  if (!(await page.locator(".whoami").count())) fail(`${tag} first open: no "Who are you?" picker`);
  await page.locator(".pcard").first().click();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.waitForTimeout(400);
  if (!(await page.locator(".me b").count())) fail(`${tag} header does not say who you are`);

  const routes = { today: "/", item: `/items/${encodeURIComponent(items[0].key)}`, approvals: "/approvals", inbox: "/inbox" };
  for (const [name, path] of Object.entries(routes)) {
    await page.goto(BASE + path, { waitUntil: "networkidle" });
    await page.waitForTimeout(300);
    const text = await page.innerText("main");
    if (/\{"|undefined|NaN|\[object /.test(text)) fail(`${tag} ${name}: raw data on the page`);
    if (/\b[a-z]+(?:_[a-z]+){1,}\b/.test(text.replace(/[A-Za-z]+:[A-Za-z]+-?\d*/g, ""))) fail(`${tag} ${name}: a snake_case code is on the page (${text.match(/\b[a-z]+(?:_[a-z]+)+\b/)?.[0]})`);
    if (/\btoday \d{1,2}:\d{2}/.test(text)) fail(`${tag} ${name}: "today HH:MM" beside the data date`);
    if (/\bReviewer\b[^.\n]*\d+ of \d+|\d+ lookups/.test(text)) fail(`${tag} ${name}: Reviewer counts or lookups outside Details`);
    if (/^\s*\|.*\|\s*$/m.test(text)) fail(`${tag} ${name}: a pipe table row is shown as text`);
    const ids = [...new Set(text.match(ID) ?? [])];
    console.log(`info ${tag} ${name}: ${ids.length} bare ids${ids.length ? " (" + ids.slice(0, 4).join(", ") + ")" : ""}`);
    if (STRICT && ids.length > BUDGET[name]) fail(`${tag} ${name}: ${ids.length} bare ids, budget ${BUDGET[name]}`);
  }

  // the panel: Work (Today, Approvals, Inbox), then one Records entry (Khalid: no build pages, compact records); every nav, footer and Records link resolves
  if (w >= 1024) {
    await page.goto(BASE + "/", { waitUntil: "networkidle" });
    const main = await page.locator("nav.ds-nav a").allInnerTexts();
    const robots = (await page.locator("nav.ds-nav a[href^='/builds/']").count());
    if (main.length !== 4 || robots !== 0) fail(`${tag} the sidebar has ${main.length} entries, not Work 3 + Records 1 (${main.join(" | ")})`);
    const hrefs = [...new Set([...(await page.locator("nav.ds-nav a, .side-foot a").evaluateAll((es) => es.map((e) => e.getAttribute("href")))), "/suppliers", "/parts", "/orders", "/forecast", "/data"])];
    for (const h of hrefs) {
      await page.goto(BASE + h, { waitUntil: "networkidle" });
      if (/does not exist/.test(await page.innerText("main"))) fail(`${tag} dead link ${h}`);
    }
    await page.goto(BASE + "/", { waitUntil: "networkidle" });
    await page.waitForTimeout(300);
    const top = await page.locator("main .dt-row, main a.td-row").first().getAttribute("href");
    if (!top || !top.startsWith("/items/")) fail(`${tag} Today opens on ${top}, not an item`);
  }

  // every internal link on the main screens opens a page (and the old /records paths land somewhere)
  if (w >= 1024) {
    const seen = new Set(["/records", "/records/import", "/records/parts"]);
    for (const start of ["/", `/items/${encodeURIComponent(items[0].key)}`, "/approvals", "/inbox", "/suppliers", "/parts", "/orders", "/forecast", "/data"]) {
      await page.goto(BASE + start, { waitUntil: "networkidle" });
      await page.waitForTimeout(200);
      for (const h of await page.locator("a[href^='/']").evaluateAll((es) => es.map((e) => e.getAttribute("href")))) if (h && !h.startsWith("/api")) seen.add(h);
    }
    let n = 0;
    for (const h of [...seen].slice(0, 70)) {
      await page.goto(BASE + h, { waitUntil: "networkidle" });
      const txt = await page.innerText("main").catch(() => "");
      if (/does not exist|could not be found|could not be loaded/i.test(txt)) fail(`${tag} link ${h} does not open a page`);
      n++;
    }
    console.log(`info ${tag} links checked: ${n}`);
  }

  // Ask is one labelled box at the foot of the page, never in the top bar
  await page.goto(BASE + "/", { waitUntil: "networkidle" });
  if (w > 760 && !(await page.locator(".top .askbar input").count())) fail(`${tag} no search field in the top bar`);
  if (w > 760 && !(await page.locator(".composer input").count())) fail(`${tag} no Ask composer at the bottom of the page`);
  if (w > 760 && (await page.locator(".top .composer, .top .scope").count())) fail(`${tag} an Ask control sits in the top bar`);
  if (w <= 760) {
    // on a phone the Ask tab is the one way in: it opens the sheet
    if (await page.locator(".composer-wrap").count()) fail(`${tag} a second Ask entry sits above the tab bar`);
    await page.getByRole("button", { name: "Ask" }).click();
    await page.waitForTimeout(300);
    if (!(await page.locator(".aipanel").count())) fail(`${tag} the Ask tab did not open the Ask sheet`);
    await page.locator(".aipanel .x").click();
    // one header row, not three
    const h = await page.locator(".pbar").evaluate((e) => e.getBoundingClientRect().height).catch(() => 999);
    if (h > 64) fail(`${tag} the header is ${Math.round(h)} px tall, not one row`);
  }

  // Ask is a field in the top bar and in place on a row; nothing is docked to the foot of a page or reserved for it
  for (const path of ["/", "/inbox", "/approvals", `/items/${encodeURIComponent(items[0].key)}`]) {
    await page.goto(BASE + path, { waitUntil: "networkidle" });
    if (await page.locator(".dock").count()) fail(`${tag} ${path}: an Ask dock is docked to the foot of the page`);
  }

  // every dropdown opens fully and on top: its menu is drawn at its own centre (nothing clips or covers it)
  if (w > 760) {
    await page.goto(BASE + "/", { waitUntil: "networkidle" });
    for (const [sel, menu] of [[".scope-btn", ".scope-menu"], [".td-dd", ".td-menu"]]) {
      await page.locator(sel).first().click();
      await page.waitForTimeout(200);
      const ok = await page.evaluate((m) => {
        const e = document.querySelector(m); if (!e) return "did not open";
        const r = e.getBoundingClientRect();
        if (r.width < 20 || r.height < 20 || r.bottom > innerHeight + 1 || r.right > innerWidth + 1) return `outside the window (${Math.round(r.width)}x${Math.round(r.height)})`;
        const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return hit && e.contains(hit) ? "" : "covered or clipped";
      }, menu);
      if (ok) fail(`${tag} the ${sel} menu is ${ok}`);
      await page.keyboard.press("Escape");
      await page.mouse.click(5, 5);
    }
  }

  // the Ask composer floats at the foot of main and never covers a line: scrolled to the end of a long list, nothing is drawn under it
  if (w > 760) {
    for (const path of ["/", "/suppliers", "/orders"]) {
      await page.goto(BASE + path, { waitUntil: "networkidle" });
      await page.waitForTimeout(250);
      await page.evaluate(() => { window.scrollTo(0, document.documentElement.scrollHeight); for (const s of document.querySelectorAll(".rc-scroll, .td-rows")) s.scrollTop = s.scrollHeight; });      // a page that holds still scrolls its own body
      await page.waitForTimeout(150);
      const covered = await page.evaluate(() => {
        const c = document.querySelector(".composer"); if (!c) return -1;
        let n = 0;
        for (const e of document.querySelectorAll("main .content *")) {
          if (e.children.length || !(e.textContent ?? "").trim()) continue;
          const q = e.getBoundingClientRect(); if (q.width < 2 || q.bottom < 0 || q.top > innerHeight) continue;
          const box = e.closest(".rc-scroll, .td-rows")?.getBoundingClientRect(); if (box && (q.top >= box.bottom || q.bottom <= box.top)) continue;      // clipped by its own scroll area: not drawn
          const hit = document.elementFromPoint(q.left + q.width / 2, Math.min(q.top + q.height / 2, innerHeight - 1));
          if (hit && c.contains(hit)) n++;
        }
        return n;
      });
      if (covered === -1) fail(`${tag} ${path}: no composer`); else if (covered > 0) fail(`${tag} ${path}: the Ask composer covers ${covered} lines at the end of the page`);
    }
  }

  // an item at a desktop width (FINAL 07 r12): the current step's one primary action is on screen without scrolling, and nothing is drawn over it
  if (w >= 1280) {
    await page.goto(`${BASE}/items/${encodeURIComponent(items[0].key)}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(800);
    const m = await page.evaluate(() => {
      const card = document.querySelector(".cp-card:not(.ro)");
      if (!card) return { missing: true };
      const b = card.querySelector(".b9.dark");
      if (!b) return { none: true };
      const r = b.getBoundingClientRect(), hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return { below: r.bottom > window.innerHeight, covered: !(hit && b.contains(hit)), label: b.textContent };
    });
    if (m.missing) fail(`${tag} the item has no current step card`);
    else if (!m.none) { if (m.below) fail(`${tag} the item's primary (${m.label}) is below the fold`); if (m.covered) fail(`${tag} something is drawn over the item's primary (${m.label})`); }
  }

  // an item's wide tables stay in their column: opened, the month table never runs past the main column into the rail
  if (w >= 1280) {
    for (const it of items.filter((x) => x.group === "disruption").slice(0, 3)) {
      await page.goto(`${BASE}/items/${encodeURIComponent(it.key)}`, { waitUntil: "networkidle" });
      const sum = page.getByText(/^Month by month/).first();
      if (!(await sum.count())) continue;
      await sum.click(); await page.waitForTimeout(250);
      const over = await page.evaluate(() => {
        const main = document.querySelector(".item-main"); if (!main) return 0;
        const mr = main.getBoundingClientRect().right;
        return [...main.querySelectorAll("*")].filter((e) => { const q = e.getBoundingClientRect(); return q.width > 0 && q.right > mr + 1 && !e.closest(".tablewrap"); }).length;
      });
      if (over) fail(`${tag} ${it.key}: ${over} elements run past the main column`);
      const dec = await page.locator(".tablewrap").evaluateAll((es) => es.filter((e) => e.getBoundingClientRect().right > (document.querySelector(".item-main")?.getBoundingClientRect().right ?? 1e9) + 1).length);
      if (dec) fail(`${tag} ${it.key}: the month table crosses into the rail`);
    }
  }

  // every strip claim is styled ok only when it says all
  for (const it of items.slice(0, 8)) {
    await page.goto(`${BASE}/items/${encodeURIComponent(it.key)}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(250);
    for (const s of await page.locator(".ds-trust span").evaluateAll((es) => es.map((e) => ({ c: e.className, t: e.textContent ?? "" })))) {
      const m = s.t.match(/^(\d+) of (\d+)/);
      if (s.c.includes("ok") && m && m[1] !== m[2]) fail(`${tag} ${it.key}: "${s.t}" is styled ok`);
      if (/every open question/i.test(s.t)) fail(`${tag} ${it.key}: a blanket claim: "${s.t}"`);
    }
  }

  // the bare "a" key approves nothing
  await page.goto(BASE + "/approvals", { waitUntil: "networkidle" });
  const first = page.locator("a.dt-row, a.ds-row, a.td-row, a.apq-row").first();
  if (await first.count()) {
    await first.click();
    await page.waitForTimeout(400);
    if (await page.getByText(/can sign this|can approve this email/).count()) {
      // a draft that is not yours says who can sign it and offers to switch; there is no disabled Approve button
      if (!(await page.getByRole("button", { name: /^Switch to / }).count())) fail(`${tag} a draft that is not yours has no Switch button`);
      if (await page.getByRole("button", { name: /^Approve and send/ }).count()) fail(`${tag} a draft that is not yours shows an Approve button`);
    } else {
      // FINAL 03: "Approve and send", with the signer named in the caption under it ("Simulated · sends on approval · as <name>")
      const label = await page.locator(".db-btn.go").first().innerText().catch(() => "");
      const cap = await page.locator(".db-cap").first().innerText().catch(() => "");
      if (!/^Approve and send$/.test(label.trim()) || !/[Ss]imulated.* as .+/.test(cap)) fail(`${tag} approve button does not name who signs: "${label}" / "${cap}"`);
    }
    await page.keyboard.press("a");
    await page.waitForTimeout(300);
    if (posts.some((u) => u.includes("/approve"))) fail(`${tag} the "a" key approved a draft`);
  }
  await ctx.close();
}

// a four-owner item: every draft is signed by its own owner, so each person sees only their own as "to sign"; a prepared draft nobody chose stays off Approvals (Khalid 11:35)
{
  const owners = ["Dana Reyes", "Priya Nair", "Tom Okafor", "Marcus Lee"];
  const mk = (n, owner) => ({ action_id: `A-mock${n}`, type: "supplier_request", state: "proposed", payload_hash: "h", item_key: "mock:four", run_id: "r", target: { type: "supplier", id: "SUP-0000", label: null }, recipient: `s${n}@b.example`, subject: `Draft ${n}`, body: "Hello", proposed_at: `2026-09-2${n}T09:00:00Z`, owner, chosen: true });
  const acts = [...owners.map((o, n) => mk(n + 1, o)), { ...mk(5, owners[0]), subject: "Draft 5 unchosen", chosen: false }];
  const item = { key: "mock:four", group: "disruption", severity: "high", title: "Mock item", owner: owners.join(" · "), headline: "x" };
  for (const me of owners.slice(0, 2)) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: "block" });
    await ctx.addInitScript((m) => localStorage.setItem("lookout.me", m), me);
    const page = await ctx.newPage();
    await page.route("**/api/actions", (r) => r.fulfill({ json: acts }));
    await page.route("**/api/action-items", (r) => r.fulfill({ json: [item] }));
    await page.goto(BASE + "/approvals", { waitUntil: "networkidle" });
    await page.waitForTimeout(500);
    const text = await page.locator("#root").innerText();
    const mine = acts.filter((a) => a.owner === me && a.chosen).map((a) => a.subject);
    const others = acts.filter((a) => a.owner !== me || !a.chosen).map((a) => a.subject);
    if (!mine.every((t) => text.includes(t)) || others.some((t) => text.includes(t))) fail(`${me}: To sign must list only the draft they own (${mine.join(", ")}), not ${others.join(", ")}`);
    await ctx.close();
  }
}
// reopening Import with every answer already saved opens at the preview, never at question 1
{
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: "block" });
  await ctx.addInitScript(() => localStorage.setItem("lookout.me", "Dana Reyes"));
  const page = await ctx.newPage();
  const q = (n) => ({ id: `q${n}`, kind: "x", question: `Question ${n}?`, covers: "1 entry", file: "f.csv", examples: [], entries: 1, proposed: "Link", state: "accepted", answer: null });
  await page.route("**/api/imports/questions", (r) => r.fulfill({ json: { import_id: "i", questions: [q(1), q(2)] } }));
  await page.route("**/api/imports/dry-run", (r) => r.fulfill({ json: { hash: "h", files: [{ file: "f.csv", rows_in: 2, rows_out: 2, changes: [] }], checks: [{ name: "c", passed: true }], answers: { total: 2, changed: 0, skipped: 0 }, recipe_steps: 1 } }));
  await page.goto(BASE + "/data/import", { waitUntil: "networkidle" });
  await page.waitForTimeout(500);
  const text = await page.locator("#root").innerText();
  if (/1 of 2/.test(text) || !/rows in/i.test(text)) fail("Import with every answer saved must open at the preview, not at question 1");
  await ctx.close();
}
await browser.close();
console.log(fails.length ? `${fails.length} buyer check(s) failed` : "buyer checks ok: picker, plain pages, true strips, no key approves");
process.exit(fails.length ? 1 : 0);
