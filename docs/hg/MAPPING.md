# Lookout → Lookout for HG Infra: feature mapping

One row per Lookout feature, taken from three places: the README (§1–§16, §22 and "Since the submission"), the code, and a read-only
walk of the Halden app on :8000 as Dana Reyes and Priya Nair (166 screenshots, 0 non-GET requests; kept outside the repo).

**Verdicts.** **keep**: same behaviour, HG words only. **adapt**: same mechanics, HG domain logic. **replace**: the feature's job is
done by a different HG feature. **new**: not in Lookout. **drop**: not carried over, with the reason.

Every keep / adapt / new row must work in the HG app before "done" (§8 of the brief).

---

## 1. Shell (every page)

| # | Lookout feature | Verdict | HG behaviour |
|---|---|---|---|
| 1.1 | "Who are you?" picker, remembered on this computer (localStorage), no sign-in | keep | Lists the SCM team from the team table with role and purchasing group: since 21 Oct 2026 the 25 people of HG's SCM organogram ("Jitender Swami · AM, aggregate (Dhule, Aurangabad, Gaya, Tumkur, JH-10, JH-13) · A01"). The persona decides "Yours", what they may sign (DoA) and whether they see every Team page (Head, GM) or only their own. |
| 1.2 | "You are Dana Reyes · change" in the top bar | keep | Same, HG persona. |
| 1.3 | "Data as of Fri Sep 25, 2026", link to Data, hover = rebuild time + checks | adapt | "Data as of 20 Oct 2026". Hover lists every source with its own export date (ME5A, ME2N, MB51, vendor master, fund sheets, payment projection, trackers); a source older than 7 days is marked stale (the Oct fund sheet, built 18 Sep). |
| 1.4 | ⌘K search across linked records (part, PO, supplier, person) | adapt | Finds a PR no., PO no., material doc, vendor (name, code, GSTIN), material (code, name), project (name, any alias, plant code) or person. "Arurangabad" finds Aurangabad (plant 1905); "Ahmedabad" finds Narol. |
| 1.5 | Sidebar: Work (Today, Approvals, Inbox, with counts) · Records · Data / Under the hood at the foot | adapt | Work (Today, Approvals, Inbox) · **Insights (Team, Projects, Pricing, Estimates)** · Records · Data / Under the hood. Counts follow the same "your move" rule. |
| 1.6 | Ask bar at the foot, "About: <page>", `/` to focus | keep | Scope follows the page: Today, a case, a project, a vendor, a material, Team, Pricing, Estimates, a PR or PO. |
| 1.7 | Company name under the brand ("Halden Robotics") from configuration | keep | "H.G. Infra Engineering Ltd." from `recipes/hg/answers.yaml`. |
| 1.8 | Offline banner (service worker keeps last-read screens; never replays a write) | keep | Unchanged. |
| 1.9 | Keyboard: j/k between Today rows, Enter opens, Esc closes menus | keep | Unchanged. |
| 1.10 | Live counts endpoint (`/api/counts`) feeding the sidebar | adapt | HG counts: open PRs, open PO lines, waiting drafts, countersigns waiting, held mail, data issues. |

## 2. Today

| # | Lookout feature | Verdict | HG behaviour |
|---|---|---|---|
| 2.1 | Yours / Everyone switch with counts | adapt | **Yours** = items on your purchasing group or verticals (Head and GM: items they own, e.g. long-lead decisions and countersigns). **Everyone** = the whole SCM team. |
| 2.2 | The viewer's share on a team case (Dana's duty share $424K of $1.43M) | adapt | Each person sees their own share where the case spans people: the aggregate-spread case shows each roads/railway buyer's own sites; the quarry closure shows each buyer's own project; the PRs-without-project row shows each person's own PRs. Team totals appear only in Everyone and in the case summary. |
| 2.3 | Kind tabs with counts: Disruption, Supplier risk, Trust, Deadlines, Import duty, Unknowns | replace | **Requirement · After PO · Price · Payments · Vendor risk · Trust · Unknowns**, each set by the detector that raised the item (PLAN §7). |
| 2.4 | Filter: search items | keep | Searches titles, summaries, project names and aliases, PR/PO numbers, vendors, materials. |
| 2.5 | Filter: Act by (Within 7 days / 30 days / No date) | adapt | Overdue · This week · 2 weeks · This month · No date. |
| 2.6 | Filter: robot chips T2 / P5 / H1 | replace | **Vertical chips** Roads · Rly · BESS · Solar · T&D. |
| 2.7 | — | new | **Project picker** (any project, by name or alias). |
| 2.8 | — | new | **Waiting on** filter: SCM / Projects / Finance / QA / Vendor / Management, from each item's computed `waiting_on`. |
| 2.9 | Robot icon columns, lit when the item touches that robot; tooltip = shortfall | replace | **Five vertical columns**, lit when the item touches that vertical. Tooltip names the projects and the site impact ("Gaya OHE · mast erection stops ~12 Nov"). |
| 2.10 | Row: title (one per cause) + subtitle "kind · key facts" | keep | e.g. "Gaya: 32 PRs short-closed after RFQ" / "Requirement · 4 vendors quoted · ₹3.2 Cr enquiry". |
| 2.11 | Owner column (Everyone only) | keep | First names of the SCM owners. |
| 2.12 | Exposure column, "—" when not computable; "claimed" on held mail | adapt | **₹ at stake**, Indian units (₹1.4 Cr, ₹15 L, ₹8,500), its rule in a tooltip; "—" when not computable and the Unknowns tab says why; held mail shows "claimed". |
| 2.13 | Act by column (days from the data date) | adapt | Dates from PO validity, MFC dates, LC deadlines, quote validity, price-notice effective dates, lead-time cut-offs; written "28 Oct". |
| 2.14 | Status: 7-dot strip + word (Start / Review / Decide / Approve / With … / Held / Approved / Sent / Replied) | adapt | Same strip and words, plus **With Projects / With Finance / With QA / With Management** when the move sits outside SCM (an internal note sent and not answered, or a detector that says the PR waits on a spec). |
| 2.15 | Ranking: live disruptions first, then money, then days left; signed or sent sink; no model sorts | adapt | **Work-front stoppages first** (an item with a site-impact date inside the horizon), then ₹ at stake, then days left; signed or sent sink to the bottom. Code only. |
| 2.16 | "Waiting on others · N" band under the viewer's own moves | keep | Unchanged. |
| 2.17 | Count line under the title ("3 to sign · 1 held · …", README §4) | adapt | e.g. "4 to sign · 2 held · ₹38 Cr at stake this month · 9 waiting on Projects". Every figure computed. |
| 2.18 | Dated rows folded under a cause (a supplier's closure, quote lapse under its fire) | adapt | A vendor's or project's other dated facts fold under the main case (e.g. the GIS quote's lapse folds under the PV long-lead decision for the same project when both exist). |
| 2.19 | Every row and every child reachable by key (`/api/action-items/{key}`) | keep | Frozen HG keys (PLAN §7). |
| 2.20 | Phone: all filters fold into one Filters button | keep | Including vertical, project and Waiting on. |

## 3. The case page

| # | Lookout feature | Verdict | HG behaviour |
|---|---|---|---|
| 3.1 | Breadcrumb "Today › Disruption"; title | keep | HG kinds ("Today › Requirement"). |
| 3.2 | Impact line: robot icons, "Short Oct 182 Tern · …", "(up to: stock on hand is not in the data)", "$392K on 10 PO lines", Act by, supplier, owner | adapt | Vertical icons · **site impact by month** ("Nov: Gaya OHE mast erection · Dec: Dhule P-Way") · "(up to: site stock is not in the data)" · **₹ on N PR/PO lines** · Act by · vendor · owner · **waiting on**. |
| 3.3 | Six steps: Overview · Analysis · Decision · Approval · Sent · Response | keep | Same six, same rules. |
| 3.4 | "Recorded" step set when the choice is a decision on record (Overview · Analysis · Decision · Approval · Recorded) | keep | Unchanged. |
| 3.5 | Overview = the source as it came in (the email; the lines it names) | adapt | The email, the SAP rows (ME5A/ME2N/MB51 lines with their export row), or the sheet cells (requirement / fund sheet, with cell reference). No interpretation. |
| 3.6 | Analysis = agent's reading (shown only if verified, with Reviewer grade) + findings each over the record it rests on + "What we don't know" table (question · who · why it matters) | adapt | Same layout; findings from HG code facts (turnaround, effort on cancelled PRs, index movement, L1 vs last vs budget, late streak, MSME due). |
| 3.7 | Decision table (Route · What it changes · Earliest help · Cost · Goes to), Recommended mark, Also start, footer, owner-only choose | keep | HG routes (PLAN §8). "Goes to" is a vendor's contact on file **or an internal function owner on file**. |
| 3.8 | "Ask for another option" button on Decision | keep | Unchanged. |
| 3.9 | Approval = the draft for the chosen route, rights kept, money committed, drafts also started | adapt | Adds the **DoA line** ("₹50 Cr commitment: above ₹5 Cr, also needs Rajeev Malhotra, Head SCM"). |
| 3.10 | Sent = the simulated outbox | keep | Internal notes show "Sent to <function owner> (simulated)". |
| 3.11 | Response = what the reply changed per line + offer to draft the PO date update as a note | adapt | Offers the SAP change as a note for signature: PO delivery date change, PR short-close, PO validity extension, PR release. |
| 3.12 | Held message steps: Overview · Analysis (indicators) · Controls · Done | keep | For both fraud mails and the injection offer. Controls: "do not pay", "confirm by phone with the contact on file", "inform Finance", "report the look-alike domain to IT" (internal look-alike: "confirm with the sender in person or on the number on file"). Each recorded with who and when. |
| 3.13 | Right rail: Deadlines | keep | The case's dated facts (validity end, MFC date, LC deadline, quote lapse). |
| 3.14 | Right rail: Supplier panel (OTD 88% (112/127) · avg 7 d late · Net 60 · FOB · contact on file) | adapt | **Vendor panel**: on-time % from MB51 receipt vs PO delivery date (n/m), average days late, payment terms (advance against ABG / LC / RTGS before dispatch), **MSME flag and whether an invoice falls due within 45 days**, GSTIN, approved verticals in the library, contact on file. |
| 3.15 | — | new | **Project panel**: vertical, stage, plant code(s), project head and planner, median PR → PO days for the project. |
| 3.16 | Linked cases ("same part", "same supplier") | adapt | "same vendor", "same project", "same material", "same PR / PO" (the IEEMA claim links to the MFC case on the same transformer PO). |
| 3.17 | Checks ("6 of 6 checks passed") | keep | Same verifier on HG figures. |
| 3.18 | Messages · Drafts · History links | keep | History = who chose, signed, countersigned, held or sent, and when. |
| 3.19 | "On you" / "Ask about <step>"; scoped Ask with seeded suggestions and recorded answers | keep | Seeded HG questions per case (PLAN §11). |
| 3.20 | "From your discussion" line above routes; routes Ask raised move up; an Ask draft marks its route started or becomes its own row | keep | Unchanged. |
| 3.21 | Review button on a case not yet reviewed | keep | Unchanged. |
| 3.22 | Run live (when a model is connected) | keep | Unchanged. |
| 3.23 | Time-phased "month by month" MRP block for the main part (README §5) | replace | **Requirement vs supply by month** for the case's material and project (requirement sheet vs open POs by delivery month vs received), "up to" without site stock. |

## 4. Decisions

| # | Lookout feature | Verdict | HG behaviour |
|---|---|---|---|
| 4.1 | Route table per case kind as code (`option_kinds.py`), labels and buttons fixed | adapt | HG table (PLAN §8): 14 case kinds, ~50 routes. |
| 4.2 | Figures in every column computed by code (`options.py`, `route_figures.py`) | adapt | HG figures: PV cost per month of delay, stockist premium, storage cost, LD exposure, PV difference, L1 premium, LC value; "not in the records" where none. |
| 4.3 | Agent marks one route Recommended with a reason (advice; verifier checks the kind is in the table) | keep | Unchanged. |
| 4.4 | Nothing preselected; Continue waits for a pick | keep | Unchanged. |
| 4.5 | Also start (a dated route on or before the act-by; a second source when sole source or < 60% on time) | adapt | Same rule shapes: a dated route before the act-by (e.g. "ask vendors to hold quotes" beside the cancellation approval), an alternate vendor from the library beside a late-streak ask. |
| 4.6 | Footer says what Continue will do | keep | Unchanged. |
| 4.7 | Choose is owner-only, written to the ledger (who, when, append-only) | keep | Unchanged; owners from purchasing group / vertical. |
| 4.8 | Choosing returns the route's draft: the run's, or one written in code to the route's contact | adapt | Code drafts in HG house style: vendor letters and internal memos (PLAN §9). |
| 4.9 | One email per contact: a second route to the same contact is added as a paragraph | keep | Also for internal notes to the same function owner. |
| 4.10 | Ask's work comes back to Decision in the same visit | keep | Unchanged. |

## 5. Agent runs and how we got here

| # | Lookout feature | Verdict | HG behaviour |
|---|---|---|---|
| 5.1 | Review: steps stream live in Analysis, one plain line per step, written by code | keep | HG purposes ("I'm asking the price side to read the IEEMA index against the PO's base month"). |
| 5.2 | Checks then one result line ("Worked in 52 s · drafted 1 request to … · now: … · 6 of 6 checks · Reviewer 100") | keep | e.g. "Worked in 41 s · drafted 1 note to the Gaya project head · now: Decide · 6 of 6 checks · Reviewer 92". |
| 5.3 | Reload reattaches to the run in progress (SSE) | keep | Unchanged. |
| 5.4 | A run that fails its checks needs an explicit tick before approval | keep | Unchanged. |
| 5.5 | How we got here: answer first, checks, a reason per step, handoffs, the clerk's draft | keep | Unchanged. |
| 5.6 | Orchestrator + 6 specialists, allow-lists, gate, verifier, Reviewer | adapt | Supply planner → **Site requirement planner**; Tariff analyst → **Price and PV analyst**; Sourcing analyst (RFQ, CS, L1 vs last vs budget), Inbox analyst, Data steward, **Buyer's clerk** (only drafter; Indian business style; internal memo style for Projects / Finance / QA). |
| 5.7 | 24 MCP tools over the records, numbers with stable ids | adapt | HG tools (PLAN §10). |
| 5.8 | Morning run replays saved runs for the top items at start-up (no key) | adapt | Replays HG recordings for the demo stories. |
| 5.9 | Hybrid mode (replay where recorded, live otherwise) | keep | Unchanged. |
| 5.10 | Agent activity page (runs, figures checked, drafts, median time, cost) and run trace page | keep | HG runs. |
| 5.11 | Reviewer critical check "nothing commits the company" | adapt | Plus "no award, no MFC, no payment promise in a letter; an internal memo commits no money". |

## 6. Approvals

| # | Lookout feature | Verdict | HG behaviour |
|---|---|---|---|
| 6.1 | Tabs: To approve / With others / Sent / Rejected; Yours to sign vs Others | keep | Plus a **"Needs your countersign"** group for the Head of SCM. |
| 6.2 | Only drafts the buyer chose reach Approvals | keep | Unchanged. |
| 6.3 | Recipient fixed to the contact on file | adapt | Vendor: contact on file. Internal note: the named function owner on file (project head, planner, Finance treasury, QA). |
| 6.4 | Exact text shown; approve carries its sha256; stale or second approval refused (409) | keep | Unchanged. |
| 6.5 | Owner-only signing (403 otherwise) | keep | Owner = the SCM person on the item's purchasing group / vertical. |
| 6.6 | Reject with a reason; the next run follows it | keep | Unchanged. |
| 6.7 | One open request per contact; new ask merged into the waiting one | keep | Also per internal function owner. |
| 6.8 | Sent shows everywhere at once (case, Today, Approvals, Inbox, outbox) | keep | Unchanged. |
| 6.9 | Edit a waiting draft (hash changes, approval restarts) | keep | Unchanged. |
| 6.10 | — | new | **Delegation of authority** from `doa.csv`: above the threshold the owner signs first, then the draft waits on the Head of SCM; both signatures in the ledger; sent only after the countersign. |

## 7. Inbox

| # | Lookout feature | Verdict | HG behaviour |
|---|---|---|---|
| 7.1 | Trust check before any model reads a message (look-alike domain, free-mail reply-to, bank change, text aimed at software) | keep | Same rules, no vendor named in code. |
| 7.2 | — | new | **Internal sender class**: the company domain, matched to people on file (SCM team, project heads, Finance, QA). A look-alike of the internal domain is held exactly like a vendor look-alike. |
| 7.3 | Held mail with a red badge; text folded, shown only as quoted data | keep | Unchanged. |
| 7.4 | "What it means" in one line, written by code | adapt | HG kinds: PR request, cancellation instruction, MFC request, inspection call, PV claim, price notice, quote, LC request, ABG reminder, inspection failure, quarry closure, strike, warranty notice, fund mismatch, revised schedule, spec chase, rename. |
| 7.5 | The dates it carries | keep | Validity, MFC date, inspection date, effective date, LC deadline, ABG expiry, closure window. |
| 7.6 | The lines it moves (PO lines, old vs new) | adapt | PR and PO lines, old vs new date. |
| 7.7 | The Today item it feeds, with its stage | keep | Unchanged. |
| 7.8 | What does this mean? / Draft a reply | keep | Unchanged. |
| 7.9 | Yours / Everyone in the Inbox | keep | Owner of a message = owner of the item it feeds, else the buyer of the PR/PO lines it names. |
| 7.10 | Quote facts block (When · Minimum · Payment · Origin · Supplier) and price table | adapt | When (validity, delivery) · Minimum · Payment terms · Price basis (Firm / PV with index) · Vendor (in library? MSME?). Table: material, qty, unit rate, against last PO and budget rate. |
| 7.11 | Entity chips in the email (parts, suppliers, POs, people, money, dates) | adapt | Projects (any alias), plant codes, materials, vendors, PR/PO numbers, people, ₹ amounts (incl. "₹3.2 Cr", "15 L"), dates. |
| 7.12 | `make simulate-replies` closes the loop with a marked simulated reply | adapt | Also simulates a reply from Projects / Finance / QA to an internal note. |

## 8. Records

| # | Lookout feature | Verdict | HG behaviour |
|---|---|---|---|
| 8.1 | Records as one sidebar entry with a tab row; title, tabs, filters fixed | keep | Tabs: **Vendors · Materials · PRs · POs · Requirements · Work fronts**. |
| 8.2 | Suppliers list (open $, past due, on time, late in a row, case) | adapt | **Vendors**: SAP master linked to the library row; approved verticals, on-time %, open POs (₹), MSME, both codes of a renamed vendor (linked, never merged), case. |
| 8.3 | Supplier page (profile, orders, messages, records, "in a case", KPIs, news watch) | adapt | Vendor page: profile (GSTIN, MSME, bank masked, library verticals), POs, quotes (every one, with CS outcome), messages, records (codes), in a case, KPIs. No news watch (8.15). |
| 8.4 | Parts list (category, origin, HTS, supplier, open supply) | replace | **Materials**: material master (code, group, base unit and alternate unit, PV index link), open PRs/POs. |
| 8.5 | Part page (facts, figures, where used, quotes beside current order, compare with the agent) | adapt | Material page: master facts, **rate history by site and by vendor**, **where used (which projects)**, open PRs/POs, quotes side by side with the last PO and the budget rate; "Compare quotes with the agent" (Sourcing analyst). |
| 8.6 | Orders list (open lines, past due filter, plain-word flags "3 may not really be open") | adapt | Two tabs, **PRs** and **POs**, with plain-word flags: "PR created the same day as its PO", "PO with no PR", "PR with no project", "3 may not really be open". |
| 8.7 | Forecast grid (robots per month) | replace | **Requirements**: the 3-month sheet per project and material, with the fund-sheet figure beside it. |
| 8.8 | BOM page | drop | HG has no BOM explosion: the requirement sheet is the demand. |
| 8.9 | Build readiness (per robot and month, worst first) | replace | **Work-front readiness** per project and month: requirement lines covered by a PO arriving in time, arriving late, under a disruption, or with no PO (unknown stock). Worst first. |
| 8.10 | 14-stage part/PO ladder with "All steps" (date, who, source) | replace | **PR-to-payment ladder**: Needed → PR raised → PR released → RFQ sent → Quotes in → CS approved → PO released → MFC issued → Inspected → Dispatched → Received (GRN) → Invoiced → Paid → Closed. Each rung: date, source row, **whose move it was**. Time between rungs split by who held it feeds Team and Projects. |
| 8.11 | Records Yours / Everyone switch | keep | Yours = your purchasing group. |
| 8.12 | "In a case" lists on record pages | keep | Unchanged. |
| 8.13 | Part at the shelf (type or scan a part number on a phone) | adapt | **Material lookup on site**: type or scan a material code; shows open PRs/POs, last rate, vendor. |
| 8.14 | More page on the phone (Records sections with counts) | keep | HG sections. |
| 8.15 | Supplier news watch (news feed matched to the master) | drop | HG's sources have no news feed; external events (quarry closure, strike) arrive as mail and become Today items. |

## 9. Data, Import, Under the hood, phone, hindsight

| # | Lookout feature | Verdict | HG behaviour |
|---|---|---|---|
| 9.1 | Data page: one row per defect, what was found, what was done, who decides; load checks; rebuild summary | keep | One row per planted defect (PLAN §5.4). |
| 9.2 | Data page tabs: Needs a decision / Handled by Lookout; Yours / Everyone | keep | Unchanged. |
| 9.3 | "How the data is rebuilt" fold (steps, recipe hash) | keep | HG steps. |
| 9.4 | Import: steward reads a new export, detects drift, one question card at a time, preview, Approve; nothing loads before | keep | Seeded drifted **ME2N export** (renamed SAP columns, dd.mm.yyyy dates, Indian digit grouping, "Arurangabad" plant text). Card: "'Arurangabad' looks like Aurangabad (same plant 1905). Link?". |
| 9.5 | Accept / Change / Skip; Accept all remaining | keep | Unchanged. |
| 9.6 | Sandbox for steward-written steps | keep | Unchanged. |
| 9.7 | Under the hood (agents, tools, recorded runs, how a case is worked) | keep | Re-captioned for HG. Low priority. |
| 9.8 | Phone shell: tab bar Today, Approvals, Inbox, Ask, More; sign from the floor | keep | Sign a draft (and a countersign) from a phone. |
| 9.9 | Hindsight (`AS_OF=`) builds the records as they stood that day | adapt | HG cut on **1 Sep 2026**: the MFC / PO-validity case is already on the list, weeks before the vendor's ₹1.4 Cr firm-price claim (PLAN §12). |
| 9.10 | Entity recognition (`/api/annotate`) | adapt | HG entities (7.11). |
| 9.11 | Design system page (`/design`) | keep | Unchanged; adds vertical tokens and icons. |

## 10. Insights (new; leadership asked for these)

| # | Lookout feature | Verdict | HG behaviour |
|---|---|---|---|
| 10.1 | (README §2: "No dashboards or scorecards") | new | **Team**: Head and GM see everyone, a member sees their own page. Per member: open PRs and their age; POs released in the last 30/90 days (count, ₹); median PR → PO days against **their vertical's** median only; savings against last price and against budget; **effort on PRs later cancelled**; **days items waited on others, by function**; workload balance. No ranking; no counts of emails, hours or logins; default order is by vertical then name. |
| 10.2 | — | new | **Projects**: all ~30 by vertical, with open PRs, median turnaround, cancelled PRs, budget vs actual purchase value, requirement vs fund vs received, long-lead status, ₹ at risk, days waiting on Projects. Project page: ladder timeline, work-front readiness, top materials, its Today items. |
| 10.3 | — | new | **Pricing**: per material, rate by site and by vendor, spread and 12-month trend, last price vs budget vs latest quote, PV items against their index. Unexplained spreads say what is unknown and who could answer. |
| 10.4 | — | new | **Estimates**: per project and month, requirement vs fund vs MB51 received; accuracy and bias; repeat over-askers; names that do not resolve across sheets. |
| 10.5 | — | new | **Daily brief**: one page per person, rendered as the Outlook email they would get each morning (ageing PRs, milestones due, items waiting on them, vendors to chase). Nothing is sent. |
| 10.6 | — | new | Insights pages: read-only, computed by code, fixed header, existing DataTable / filters / chips, every figure clicks through to its source rows, Ask scoped to the page. |

## 11. Records layer, recipe and guardrails (under the screens)

| # | Lookout feature | Verdict | HG behaviour |
|---|---|---|---|
| 11.1 | Recipe: one step per defect, docstring = defect · rule · consequence; replayed by `make build-data` with no model and no key | keep | `recipes/hg/steps/` (PLAN §5.4). |
| 11.2 | `answers.yaml`: decisions a person made, with who answered and why | adapt | company, as-of, internal domain, project-name mapping, vendor rename link, DoA thresholds, purchasing group → person, turnaround targets per vertical, cement bag weight. |
| 11.3 | Load gate (rows reconciled, raw kept, inferred labelled, aliases linked not merged, joins resolve, unique keys); a failed check writes no database | adapt | Gate tables move from code to the recipe (`recipes/hg/gate.yaml`), plus HG checks: sheet amounts = qty × rate within rounding, fund subtotals add up, MB51 net per PO line ≥ 0. |
| 11.4 | Raw beside clean (`raw_*` tables; `<field>_raw` columns) | keep | Unchanged. |
| 11.5 | Value objects: Money (amount, currency, **usd**, rate), Quantity, Unknown, Provenance | adapt | **Money carries `base` and the base currency comes from the recipe** (INR); `usd` goes away. |
| 11.6 | Extraction records: quote prices from mail cite their exact line, checked on every build | keep | For the aggregate quotes, the GIS quote, the cement spot offer and the PV claim. |
| 11.7 | Approved supplier links in the ledger (linked, never merged) | keep | Vendor links (renamed vendor) and project aliases approved in Import. |
| 11.8 | Build carries the ledger, runs and outbox across rebuilds | keep | Unchanged. |
| 11.9 | No customer names or ids in code or prompts (test scans app code from the recipe and data) | adapt | Same principle; the test reads `recipes/hg` and `data/` (project names, plant codes, team, vendors, contacts, id shapes). |
| 11.10 | Event log (Watcher) | keep | Unchanged. |
| 11.11 | Duty / tariff module (HTS, origin, three buckets) | drop | HG's price risk is escalation and PV, not import duty; the BESS imports' duty is outside the brief's sources. The price-and-PV module replaces it (PLAN §6). |
| 11.12 | Consignments (material at a contract manufacturer) | drop | No HG equivalent in the sources. The WO-vs-supply-PO case covers material bought through a contractor. |
| 11.13 | Stock counts (a person's count turns unknown into covered) | drop for now | Site stock is not in HG's data; shortages stay "up to". Listed as next work. |
| 11.14 | FX rates (six currencies) | drop | All HG lines are INR; a foreign-currency quote (the BESS containers) is stated in INR on the PO. |
| 11.15 | Supplier risk flags (insolvency, prepayment, terms cut, price jump) | adapt | HG vendor-risk flags: late streak, inspection failure, sole source in a vertical, renamed entity, not in the approved library, advance paid with late delivery. |

## 12. Evals, checks and developer tools

| # | Lookout feature | Verdict | HG behaviour |
|---|---|---|---|
| 12.1 | `make test` (backend, eval, Watcher unit tests) | adapt | Generic tests kept; Halden-specific ones skipped with a reason each (listed in NOTES.md); HG tests added. |
| 12.2 | `make numbers` (every screen figure recomputed from `data/` by an independent pandas oracle) | adapt | New HG oracle and sweep; 0 mismatches required. |
| 12.3 | `make api` (every route, bad input a clean 4xx) | adapt | HG routes. |
| 12.4 | `make tools` (each agent tool's contract) | adapt | HG tools. |
| 12.5 | `make hindsight` | adapt | HG cuts (1 Sep, 1 Oct, 14 Oct, 20 Oct). |
| 12.6 | `make perturbed` (renamed supplier, other fraud amount) | adapt (Phase 4, if time) | A renamed vendor and another fraud amount on HG data; otherwise listed as skipped. |
| 12.7 | `make eval` / `eval-gate` (15 Halden cases, judge, held-out sheets) | drop for HG, kept in the tree | The answer sheets are Halden's. `eval-gate` runs on HG recordings once Phase 4 records them; Halden sheets skipped with reasons. |
| 12.8 | `make scenarios` (fire, injection, fraud end to end via the Watcher) | adapt | HG scenarios: the MFC case end to end, the cement injection, the bank-change fraud. |
| 12.9 | `make demo-state` (rebuild + replay pinned runs) | adapt | HG demo items. |
| 12.10 | `make check-ui` (tokens, no sideways scroll, keyboard, consistency, buyer checks) | adapt | HG routes in the scripts. |
| 12.11 | `python -m evals.generality` (12 unseen variants) | drop | Built on Halden's categories; no HG equivalent planned. |
| 12.12 | Dev pages (`/dev/landed-cost`, `/dev/ask/:id`) | drop / keep | Landed-cost story is Halden's duty model (drop); the Ask test page stays. |
