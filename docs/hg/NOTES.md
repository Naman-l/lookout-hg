# Notes

Deviations from the brief, things a reviewer should know, and every skipped or removed Halden piece with its reason. Kept current at
the end of every phase.

## Phase 0

### Deviation: the copy command

The brief's `rsync … --exclude data …` excludes **every** folder named `data` at any depth, which would have dropped
`frontend/src/sections/data/` (the Data issues and Import screens). The copy used `--exclude /data` (only the root dataset), and also
left out `*.egg-info`, `.pytest_cache` and the Watcher's event logs, which are machine state. The untouched copy is commit `baseline`.

### The read-only walk of :8000

- Driven by a Playwright script that **aborts every request that is not GET or HEAD** and logs it; the persona was set through
  `localStorage` (client-side only). Result: **0 non-GET requests attempted**, 166 screenshots plus the visible text of each screen.
- Screens walked as Dana Reyes and Priya Nair at 1440×900 and 390×844: Today (Yours, Everyone), ⌘K search, every case page and each
  of its open steps (19 cases for Dana, 11 for Priya), Approvals, Inbox (a notice and a held message), Suppliers and a supplier page,
  Parts and a part page, BOM, Orders, Forecast, Data, Import, Under the hood, Agent activity and a run trace, More, Part at the shelf.
- The screenshots and the script are outside the repo (they show the Halden data):
  `/private/tmp/claude-501/-Users-joveo-Downloads-lookout-main/cf3e6d71-8425-4b09-93c4-5824f9325e49/scratchpad/walk/`.
- Features seen on screen that the brief's list did not name, now in MAPPING.md: the Records Yours/Everyone switch, the Data page's
  "Needs a decision / Handled by Lookout" tabs and rebuild fold, Agent activity and the run trace page, Part at the shelf, the quote facts
  block in the Inbox, "Ask for another option" on Decision, the offline banner, j/k keyboard navigation.

### Real-data hygiene (the review repo)

`~/Downloads/scm-departmental-review` holds real people's names (presenters, mail senders and recipients), real vendor names (in the
case studies and the payment projections), HG's real mail domain and a personal OneDrive link. Only project names, plant codes,
verticals, material names, units, rate ranges, sheet layouts and the patterns of the lessons and case studies are carried into the
dummy data. Persona and contact names were checked against the review repo before use (no matches).

### Environment

- This Mac has Python 3.14 and 3.11. Lookout needs 3.12+ (PEP 701 f-strings) and pandas below 3; the Makefile's interpreter choice and
  the pandas pin are fixed in Phase 1 (PLAN §3).
- Port 8001 was free; the HG app will only ever run there, from `~/Downloads/lookout-hg`, with its own venv and database.

## Phase 1

### Deviation: Halden tests removed, not skipped (PLAN D3)

D3 planned to keep the Halden-only tests and skip them. After the instruction "remove all Halden code, only the HG recipe and domain", the
tests that exercised removed Halden code were removed with it. None was removed silently: each is listed below with its reason and, where
the behaviour carries over to HG, the phase whose HG test replaces it. All are recoverable from the `baseline` commit. Tests of platform
code that is still in the tree but still on Halden fixtures (the agents, the ledger, the verifier, trust) are **kept and skipped**, one
reason per file, in `backend/tests/conftest.py`.

### Deviation: the eval harness removed; the number check rebuilt

`evals/` was the Halden eval suite (cases, held-out sets, judge calibration, round reports) around a harness whose oracle read the Halden
files. It was removed with the rest. The number check is rebuilt from scratch as `evals/hg_oracle.py` (pandas over `data/` and
`answers.yaml`, importing nothing from the app) and `evals/number_check.py` (`make numbers`: every figure the API serves for a screen against
the oracle). Phase 1 covers the Data page: 33 figures, 0 mismatches. Each later phase adds its screens. The agent eval runner returns in
Phase 4 with the mocked HG recordings.

### Platform files still on Halden code

Listed here until Phases 2-4 re-pointed them; the list (`backend/tests/pending.py`) is empty since Phase 4.

### Fixes made while testing the data

- The generator's mail `Message-ID`s used the clock and the process id, so two runs differed. They are now built from the mail's date and
  sequence: two runs of `make data` give byte-identical files (46 files).
- Hindsight: a vendor created after the data date (the renamed firm's new code, 10 Sep) and vendor-library approvals after it were still
  read in an early build. The horizon step now cuts both row by row, and the library's approval dates are stored as ISO dates. The
  generator also wrote 12 library approvals later than the library's own save date (3 Oct); they are moved back a year.
- One party in the payment projection ("45 L" row) carried a label from the review repo. It is now "Misc. site services"; a test reads
  the review repo's people, vendors, mail domain and file links and fails if any appears anywhere in this tree.
- Two docstrings of mine named HG projects and a team member's SAP user; they now use generic examples (caught by the customer-facts scan).

### To know

- After `make build-data`, restart `make run`. The build writes a new file and renames it over the old one; the running server's
  connection pool keeps reading the file it opened. This is the baseline's behaviour (`app/db.py` is unchanged), not an HG change.

### Change after Phase 1: real plant codes (21 Oct 2026)

Asked for: the 30 real projects across five verticals, with their real plant codes. Phase 1 had real codes only where the review repo's
requirement sheets print one (14 projects) and assigned the rest in made-up series (roads 115x, BESS 21xx, Solar 22xx, T&D 23xx). Three
assigned codes were in fact other HG plants: 1151 is Ayodhya's (it had been given to Tumkur), 1152 is Narol's and 1154 is OD-CRRR Pkg III's.

- **Source.** HG's own SAP MB51 exports in `~/Downloads` (`MB51FY2526.parquet`, `MB51FY2627.xlsx`), read only for their `Plant` and
  `Name 1` columns, with a throwaway venv in the session scratchpad. No supplier, material, user or amount was taken from them.
- **26 projects** now carry the plant code and plant name the exports print (FY26-27 first): Tumkur 1138, JH-10 1142, JH-13 1143, JEC 1147,
  Tirupati 1148, Ayodhya 1151, Narol 1152, KD-01 1131, KD-02 1132, AP-01 1133, Karnal 1141, GEW-05 1145; railway 1902-1908, Thane 2002,
  DLF 1153; Banaskantha 2109, Dholera 2110; Bikaner 2104, Jodhpur 2108; TBCB Angul 2501. Also corrected: JEC's plant name is "Jamshedpur
  Elevated Corridor" (the generator had "Economic"), and AP-01 is "Raipur Visakhapatnam (RVAP-1)". The head-office plant is 1001, HO Jaipur
  (was a made-up 1000, Gurugram).
- **Matched from public sources, not the export.** The export names plants by contract, not site, for three of them. 2109 "NVVN1/BESS-01
  185 MW" is Banaskantha: HG's NVVN 185 MW BESS award is held by its Banaskantha BESS company and connects at the Banaskantha (Radhanesda)
  pooling station. 2501 "TRANSMISSION PROJECT (ERGS-I)" is the TBCB Angul line: ERGS-I is the Angul-Sundargarh 765 kV LILO that HG won
  through TBCB. **Dholera = 2110 "GUVNL/BESS/PHASE-IV 250 MW" is an inference:** it is the only other BESS plant in the export, and the fund
  sheet pairs "Banaskatha & Dholera", but no public source names the GUVNL Phase-IV site. Worth confirming with someone at HG.
- **Four projects have no plant yet**: Pune-Shirur, BESS Chorniya, UPPTCL Mirzapur-Chunar and Jamshedpur 400 kV. None is in either export,
  which ends in May 2026. That does not mean none has a plant: Pune-Shirur shows by name ("Pune to Shirur") in the review repo's September
  MB51 pivot, which carries no codes, and Chorniya was awarded in April 2025 but had no receipts by May 2026. No file here gives their codes. The user's choice: keep all 30, leave these four without a code. The directory's plant cell is blank; the generator gives them no
  PRs, POs or receipts (Pune-Shirur's civil-works demand, the UPPTCL and Jamshedpur cable PRs and one Jamshedpur pipeline PR are gone);
  their fund lines, look-ahead items, the Chorniya GIS quotes and the mails stay. Step 05 raises `projects.no_sap_plant` (4, leave, owner SAP
  admin), the oracle counts blank plants, and `test_defects` #14 checks that the four have no SAP rows.
- **Other real plants not modelled**: the solar O&M plants (1727 Bikaner cluster; 1728 and 1729 Jodhpur), Jodhpur's other contracts (2105
  UVSC, 2106 SSSPL), and HG plants outside the 30 (OD-05 1136, OD-06 1137, GEW-04 1144, GEW-06 1146, OD-CRRR 1154, DMRC-DC-01A 2001, Prakasha
  1115 and others). One plant per project keeps every PR, PO and receipt on the project's main plant.
- **Knock-on.** Removing those rows shifts the generator's random sequence, so most document numbers changed (late cable PR 1000204034,
  MFC PO 4500120768, PV-claim PO 4500121087, containers PO 4500123578, ABG PO 4500120419, WO 4500122442; the bank-change fraud now asks
  ₹42,49,224) and six planted counts moved: cement in bags 59, same-day PRs 39, reversals and returns 88 (70 + 18), price per 1,000 16, RFQ
  before PR 20, ordered outside the library 10. Each is still found and counted twice, by the recipe and independently; the tests and step
  docstrings carry the new numbers. Fixed story figures did not move (₹16.2 Cr MFC PO, ₹1.4 Cr protection, ₹52,94,689 vs ₹43,56,293 PV claim,
  ₹3.43 Cr Gaya enquiry, ₹9.65 Cr GIS quote). `make data` is still byte-identical run to run.
- **Checks.** `make build-data`: 78 of 78 load checks, 26 data issues; `AS_OF=2026-09-01`: 73 of 73 checks; `make test`: 68 passed;
  `make numbers`: 34 figures, 0 mismatches; Data page screenshots at 1440 and 390 show the new issue.

## Phases 2-4 (21 Oct 2026, run back to back)

The user asked for every remaining phase with no review stop ("implement all the phases of the plan, no review required"). Phases 2, 3 and 4 were
built together; each still ends with its checks (below). Records and Insights were built in parallel lanes on the same contracts.

### What each phase delivered

- **Phase 2 (records and Today).** `Money.usd` became `Money.base` (the recipe's `base_currency`, INR); `fmt` writes ₹ in Indian units (₹1.4 Cr,
  ₹15 L, ₹8,500) and dates day first. Services for projects, vendors (codes linked, never merged), materials, PRs, POs, receipts (delivery against
  the PO date, the late streak), quotes and CS (L1 against the last PO rate at the plant and the budget), indices and PV, the look-ahead, payments
  (LC/BG, the vendor ledger), requirements against supply by month, work-front readiness, the DoA, and the 14-rung PR-to-payment ladder with
  whose move each wait was (PLAN 6.2). Twenty-one detectors raise **27 cases on 20 Oct, split as the plan expected** (3 requirement, 4 after PO,
  6 price, 3 payments, 5 vendor risk, 3 trust, 3 unknowns). Today, the shell (Insights section, per-source data-as-of hover with the stale ones
  marked), search across projects and their aliases, PR/PO numbers, vendors, materials and people, and Records.
- **Phase 3 (routes, ledger, letters, approvals, inbox).** The route table of PLAN 8 with figures from the records; the ledger gains `signed` (the
  owner's signature on a draft above the DoA threshold) and the Head of SCM's countersign on the same hash; `internal_note` (a memo to the person
  on file who owns the function, sent simulated, the case reading "With Projects / Finance / QA" until they answer); house style in code for
  letters and memos; one open letter per contact; the case page in six steps (four for held mail); Approvals with "Needs your countersign"; the
  Inbox with sender classes (vendor, colleague, look-alike, stranger), what each message means, the dates it carries, the lines it moves, the quote
  facts; simulated replies with what they change.
- **Phase 4 (agents, Ask, hindsight, import).** Runs drafted by code, two mocked recordings, Ask answered by code, the verifier and the Reviewer in
  code, Under the hood, Agent activity and the run trace, the Data steward on an unseen export, hindsight over four cuts, Insights (Team, Projects,
  Pricing, Estimates, the Daily brief).

### Deviation: no model, so runs are drafted by code (Q4)

No `ANTHROPIC_API_KEY` or Claude login is configured for the app on this machine, so the plan's fallback applies. Every case is worked by a run
**drafted by code** (`app/organism/coderun.py`): the same plan per kind of case (PLANS), the same tools with every figure cited by id, a rule
recommends one route (advice), the Buyer's clerk's draft for it is prepared for the owner, and the verifier and the Reviewer check it. Every
screen says "drafted by code, no model". As the user asked ("mock 1-2 agent recordings"), two recordings were **written by hand**
(`app/organism/recordings/hg/`: the Aurangabad MFC case and the Gaya cancellation); a replay is labelled mocked wherever it shows, and its draft and
checks are today's, by code. The Halden live runner (claude-agent-sdk, its gate, prompts, constitution and verifier) was removed with the rest of
the Halden code; the specialists' instruction files are rewritten for HG so a live path can be added later. Ask answers from the records by rule
(PR and PO numbers, vendors, projects and their aliases, materials, spreads, the cost of waiting, preparing a note on a case) and says when the
records cannot answer.

### Deviation: a planted defect in the data, fixed in the generator

The late-streak vendor's "last four receipts late" was broken by one on-time receipt on 18 Oct for a line due 19 Oct. The generator now receives
that line six days late, which is after the data date, so the export does not hold it (the line reads open, one day past due). No random draw
moved: MB51 is one row shorter (5,944) and its receipt numbers after 18 Oct shift; every other file is byte-identical. `make data` is still
byte-identical run to run.

### Rules settled while building

- **Late streak** fires on a vendor that has *turned* late: its last four receipts or more late, after at least five receipts on time on 75% or
  more. Four chronically late vendors (on time 22-38%) show on their vendor pages, not on Today.
- **PR stuck** shows on its own when a dated mail names the hold, or when it is above ₹25 L and the wait is outside SCM. Six PRs waiting on SCM's own
  CS approval are the buyer's queue: they are on the PR list, Team and Projects.
- **Quote lapse** reads quotes held only in mail; the CS tracker's quotes are SCM's tracked pipeline.
- **Rate spread**: eight materials are bought at more than twice the price between projects (the real sheets' spreads). One case, led by the
  material the most projects buy (aggregate 20 mm, ₹499 to ₹1,820 per MT), with the other seven folded under it.
- **Folds**: a vendor's revised schedule under its late streak; the GIS quote's lapse under BESS Chorniya's long-lead decision; the October and
  December fund-sheet mismatches under November's.
- **Owners**: the Head of SCM owns the long-lead decisions (with the vertical lead) and sees every countersign; the GM owns the library question
  and the cross-vertical rate spread; a buyer's Yours is their share of a team case.
- **A draft a run prepared** is not in Approvals until its owner chooses its route; the case reads Decide until then.
- **One letter per contact** holds only between letters that need the same signatures: an ask that commits nothing never waits behind someone
  else's countersign. A paragraph added for another case names its own PO.
- **The inspection case** fires once the vendor has called for the inspection (the tracker's call date on or before the data date).
- Recipe additions, each with who answered: `pv_variable_share` (the IEEMA weights where no PO states one), `material_words` (the words a closure
  or strike notice uses for the material it stops).
- **A rate contract** (a CS with no PR behind it) quotes a rate and no quantity: an L1 above the last PO on one is "₹ unknown: the quantity this
  rate will buy", with the rate gap per unit, never ₹0. (Three such cases are on Today on 1 Sep; found while scripting the demo.)
- **Units** are written as SAP writes them ("per MT", "per NO"), never lower-cased.
- **Text aimed at software** in a held message adds a second control: report the message to IT.

### Insights (the parallel lane)

- **Team** is visible to the Head and the GM for everyone and to each member for themselves (403 otherwise); its order is vertical, then name,
  and no route takes a sort. Days waited are the sum of the ladders' own `held`, by function.
- **Turnaround** leaves out a PR keyed in the day of its PO (the TAT report's own defect), matching the PR list.
- **Over-asks**: no requirement-sheet month has closed yet (the sheets cover Oct-Dec; the data ends 20 Oct), so accuracy reads "not yet". A
  project over-asks when a month's requirement is more than the fund check's own ₹25 L and 10% above the most it received in any one month of the
  past year. Four repeat over-askers. (Against the recent average, 13 of 16 projects were flagged, which says nothing.)
- **Received** on the Projects page covers the three full months before the data date, side by side with the three-month sheets: the materials
  the project's requirement rows name, or every material when no sheet covers it.
- **A fund column covering several projects** ("KD-1&2") is shown whole on each, never split. **₹ at risk** counts only cases labelled at
  stake or claimed; a case naming several projects is shown as "shared", counted in full.
- **Spreads**: a site is asked why when it is more than a set share above the median; the share falls back to `fund_check.min_share` (10%) until
  `price_spread_share` is answered in answers.yaml.
- **The Daily brief**: the Head and the GM get the team-wide PRs, milestones and vendors; anyone can open anyone's brief (it carries only that
  person's own cases).
- The PR-to-payment ladder is built for every line in a background thread at start-up (about 1.2 s), so the first Team page is not slow.

### The contract

`api/openapi.yaml` is now generated from the server's own schema (`app.openapi()`), and `npm run types` writes the UI's types from it, so the two
cannot drift. It was hand-kept for Halden.

### Checks at the end of Phase 4

- `make test`: the backend unit tests, the HG behaviour tests in `backend/tests/hg` (Today, the ladder, approvals and the countersign, runs, the
  API contract: every GET answers a bad id with a 4xx, never a 500) and the Insights tests.
- `make numbers`: 427 figures, 0 mismatches, against an independent pandas oracle (`evals/hg_oracle.py`): the Data page, every story's ₹ at stake
  on Today, each vendor's PO and open value on Records, and on Insights each project's open and cancelled PR lines and received value (the 14
  projects no requirement sheet covers) and each material's lowest and highest site rate. Two oracle errors were found and fixed on the way, not
  in the app: MB51 exports a reversal with its minus already, and a line under 0.5% open counts as received (the reversals step's rule).
- `make hindsight`: four cuts (1 Sep, 1 Oct, 14 Oct, 20 Oct), 0 failures; on 1 Sep the MFC case is already on Today, its ₹ unknown until the
  vendor states its price on 15 Oct.
- `make scenarios`: the MFC case signed and countersigned through the API, the cement injection and the bank-change fraud held: 13 of 13 steps.

### Records (the parallel lane)

- Vendors, Materials (a rate chart with one dot per PO line), PRs, POs, Requirements, Work fronts and the material Lookup, each with its detail
  page; the 14-rung ladder as a component the case page also uses. Filters live in the URL; Yours / Everyone filters by the buyer.
- Additive API: `GET /vendors/{id}/quotes` (each quote with what it was for and how its CS came out), `MaterialDetail.beside` (each quote against
  the last PO rate at that project and the budget), `PoDetail.ledger_items` (the FBL1N lines on the PO).
- Still loose: `guarantees`, `milestones`, `ledger`, `by_vendor` and `where_used` are untyped dicts in the API, typed locally in the screens.
  Work fronts are fetched once per project (30 calls, about 0.2 s); a `/workfronts` for all projects would remove the fan-out.

## Phase 5 (21 Oct 2026)

`docs/hg/DEMO.md`: a 10-minute walkthrough for the Head of SCM. Rajeev's morning on Today, Vikram signing the MFC letter, the same case on 1 Sep
(the hindsight moment), Pooja on what Lookout refuses to do, Rajeev's countersign and Insights. Its eight screenshots (`docs/hg/shots/`) were
taken by walking the script on a fresh `make demo-state`, so every figure in the text is one the screen shows. (Script and shots redone on 22 Oct
for the real team: Satish, Sambhav, Govind and Jitender; see below.) `make then` serves the 1 Sep
records on :8002 beside today's, for the hindsight moment in a browser.

Found and fixed while walking it:
- Team summed every line's wait into one figure ("35,709 days held by others"). It now shows what a line waited, on others and on SCM;
  the sums stay on the member's page. A project's days held by Projects say over how many lines.
- The case page's step names hung below the sticky header's background, so scrolled content showed through them.
- An unknown ₹ read "—" on Today; it reads "unknown" (the tooltip says who can answer) and "₹ unknown" on the case.
- A closure or strike named material groups by their codes ("ele-misc, gsb"); it names them by the material master's category.
- `check-consistency.mjs` waited 30 s for a count badge that a section with nothing waiting never shows (10 minutes for ten people); it now
  reads a missing badge as 0 at once, and reads the nav's own count element.

Checks at the end: `make test` 107 passed; `make numbers` 427 figures, 0 mismatches; `make hindsight` 39 cases over 4 days, 0 failures;
`make scenarios` 13 of 13; `make check-ui` all passing (tokens, 54 routes at 390 and 1440 px with no sideways scroll, keyboard, counts for
10 members, plain pages); `tsc` clean.

## Removed or skipped Halden pieces

Every row is recoverable from the `baseline` commit.

### Removed code and data

| What | Reason |
|---|---|
| `recipes/halden/` (26 steps, 9 extractions, answers, README) | The Halden recipe; replaced by `recipes/hg/` (29 steps, 3 extractions). |
| `dummy_data/generate.py` | The Halden generator; replaced by `dummy_data/generate_hg.py`, `hg_cast.py`, `hg_sheets.py`, `hg_mail.py`. |
| `backend/app/domain/parts`, `bom`, `demand`, `tariffs`, `consignments`, `stock`, `news` | Halden-only domains (part numbers, BOMs, robot demand, US duty, consigned material, stock counts, news). HG has PR, PO, receipt, project, material, fund, requirement, tracker and mail domains instead. |
| `backend/app/domain/orders/notice.py` | The Halden tariff notice reader. |
| `backend/app/domain/suppliers/risk.py` | The Halden supplier-risk detector (sole source of a robot part, news words). HG's vendor signals (late streak, rename, PV claims) are Phase 2 detectors. |
| `backend/app/domain/imports/steward/fixtures/` | The drift fixture was Halden's purchase-order export re-exported; an HG drift fixture returns with Import in Phase 4. |
| `backend/app/organism/dev/` (fakes, bench, smoke, fire) | Developer stand-ins that fake the Halden services. |
| `backend/app/organism/recordings/` (83 files) | Saved Halden runs; Phase 4 adds one or two mocked HG recordings. |
| `watcher/scenario.py`, `watcher/fixture_app.py` | The Watcher's Halden scenario and fixture app. |
| `evals/` (cases, held-out sets, judge calibration, rounds, reports, harness) | The Halden eval suite; see "the eval harness removed" above. |
| `backend/app/organism/` runner, gate, verifier, review, regrade, context packet, lookout tools, toolkit, services, prepare, lifecycle, carry, answer rules, spotlight, prompts, workflows (Phases 2-4) | The Halden live agent layer on claude-agent-sdk and Halden tools. Replaced by `coderun.py`, `replay.py`, `ask.py`, `verify.py`, `tools.py`, `api.py` (no model is connected here; see Phases 2-4). |
| `backend/app/domain/attention/` options, route_figures, findings, notices, option_kinds, tools; `actions/tools.py`; `inbox/tools.py`; `orders/tools.py`; `quotes/tools.py`; `phases/service.py`, `phases/tools.py`; `imports/steward/tools.py` | Halden detectors, routes and agent tools. Replaced by `attention/detectors.py`, `routes.py`, `phases/ladder.py` and `imports/steward/hg.py`. |
| Frontend: Bom, Build, Shelf, FireOptions, the forecast and orders sections, the part and supplier pages, LandedStory, CaseAsk, ShareBar, AskForChanges, AskTestPage, Robot, Part, PoLine, ProblemKind, Supplier, ItemLink, Stage, DraftBlock, StagedNote, WhatChanges, PoLineList, StageTracker, ResultCard, Agent, EntityChip, useNamed, runModel, useRun, RunPanel | Robot-era screens and components. Replaced by the HG Today, case page (`sections/Item.tsx`, `sections/case/`), Approvals, Inbox, Records, Insights, Ask panel and agent pages. |

### Removed tests (backend/tests/domain, backend/tests/tools)

| Test | Reason | HG replacement |
|---|---|---|
| test_build.py, test_helpers.py, test_horizon.py | Halden facts and helpers (part numbers, HTS, incoterms). | Rewritten for HG in Phase 1 (same names). |
| test_no_customer_facts_anywhere.py, test_no_halden_logic.py | Read the Halden recipe and supplier master. | Phase 1: test_no_customer_facts_anywhere.py (reads `recipes/hg` and `data/`), test_no_halden_left.py, tests/test_no_real_names.py. |
| test_health_company.py (domain copy) | Asserted the Halden brand. | The top-level tests/test_health_company.py runs. |
| test_numbers.py, test_number_truth.py | Halden headline numbers and the Halden number sweep. | Phase 1: evals/hg_oracle.py and `make numbers`; widened each phase. |
| test_consignment_item.py, test_tariff_buckets.py, test_tariff_rules.py, test_duty_two_steps.py | Consigned material and US duty: no HG counterpart. | None. |
| test_one_supply_calc.py, test_shortage_monthly.py, test_readiness_cases.py, test_verifier_products.py | Robot build readiness and part shortage against a forecast: no HG counterpart. | None (HG's "work front stops" detector is Phase 2). |
| test_disruption_rules.py, test_fire_options.py, test_restart_span.py, test_dated_reason.py | The Halden supplier fire and its routes. | Phase 2 detectors (supply-stop, schedule-slip) and Phase 3 routes. |
| test_risk_rules.py, test_supplier_risk.py | The Halden supplier-risk detector (removed). | Phase 2 vendor signals. |
| test_supplier_streak.py | Late streak on Halden receipts. | Phase 2: `late-streak` detector on MB51 receipts. |
| test_email_deadlines.py, test_events.py | Dates from Halden mail, news and the notice. | Phase 1 covers HG mail facts (test_defects: facts in prose); Phase 2 deadlines. |
| test_extraction.py | Halden quote extractions. | Phase 1: test_defects (quotes only in mail cite their line); the extraction service in Phase 4. |
| test_quotes.py | Offers, landed cost and the bid tab in USD. | Phase 2: quotes and comparative statements in INR. |
| test_api.py, test_api_contract.py, test_records.py, test_item_tiles.py, test_provenance_walk.py, test_today.py | Record routes, contract and Today on Halden records. | Phase 2. |
| test_stage.py, test_phases.py | The stage ladder on Halden rungs. | Phase 2: PR-to-commissioning ladder. |
| test_annotate.py, test_linked_cases.py, test_case_viewer.py, test_case_frame.py, test_sources_api.py | Case page mechanics on Halden cases. | Phase 3. |
| test_action_names.py, test_draft_owner.py, test_reply_owner.py, test_route_choice.py, test_route_figures.py | Approvals and routes on Halden drafts. | Phase 3, with the DoA countersign and internal notes. |
| test_inbox_cases.py, test_inbox_sent.py, test_simulate_reply.py | Inbox on Halden mail. | Phase 3. |
| test_agents_api.py, test_answer_rules.py, test_measurable_figures.py, test_named_unknowns.py, test_catalogue.py | Agents, answer rules and glossaries on Halden recordings and eval sheets. | Phase 4. |
| test_import_flow.py, test_import_perturbed.py, test_perturbed.py, test_drift_fit.py, test_profile_sandbox.py | Import and the Data steward on Halden files and fixtures. | Phase 4. |
| tools/test_tool_contract.py | The agent's tools on the Halden database. | Phase 4. |

### Skipped tests

None since Phase 4. The Halden-era organism tests (`backend/tests/organism/`, 19 files) and `test_counts.py` tested the removed live runner, its
gate, verifier, recordings and Halden fixtures; they were removed (recoverable from `baseline`) and replaced by `backend/tests/hg/`: Today's 27
cases and their figures, the folds and shares, the ladder, approvals with the countersign over HTTP, internal notes and replies, one letter per
contact, house style, code runs, the mocked replay, Ask, and the steward.

## Change after Phase 5: HG's SCM organogram (21-22 Oct 2026)

Asked for: use HG's "SCM Material Org" sheet (tab "Dept. Organogram", supplied as a CSV) for the team and person data, with their
responsibilities; record that the head of SCM is Satish Kumar Sharma; and an organisation chart on its own route, as a list and a tree, that can
be edited.

### What changed

- **The team is HG's own.** The ten invented members are gone. The 25 people the organogram names are the SCM team: Satish Kumar Sharma (Sr.
  Vice President - SCM, Head of SCM, countersigns above ₹5 Cr), the GMs Shree Dutt Anand, Varun Joshi and Sambhav Kumar, the AGM Urvik Patel,
  Gautam Jha (Manager - SCM, no team on the sheet) and their 19 people. The sheet is copied as supplied to `dummy_data/hg_organogram.csv` and
  written by `make data` to `data/sheets/SCM Material Organogram.csv`. Step 04 reads its drawing (head, one lead per column block, numbered
  cells, desk labels carried down merged rows, "(TBF)" as an open post) and checks the sheet's own total (24 under the head) against the people
  it names. The recipe's answers add what the sheet does not say: purchasing groups, verticals, SAP user, DoA limit and duties. Names,
  designations, reporting lines, desks and responsibilities are HG's; groups, SAP users, e-mail addresses and limits are invented.
- **Purchasing groups are desks.** 22 groups (A00-A02 aggregate by site, C01 cement, E01-E02 engineering items, S01 TMT, P00-P02 mechanical and
  petroleum, L01-L03 railway, BESS and lines, T01 switchgear and T&D, U01 structures and containers, N01 solar, X01 logistics, W01 site services,
  G01-G02, M01 MIS, H00). The generator's flows still split documents as the first cast's desks did; each PR and PO line's SAP group is chosen
  at write time from its material (and site, for aggregate), with no random draw, and the ten telephone draws of the old T024 export are kept.
  **Every PR, PO, receipt, ledger row, amount and document number is unchanged** (checked row by row against the previous `data/`); only the
  purchasing group, the PO's Created By, the export stamps' user and the names in the CS tracker and the mails differ. A PR can now carry lines of
  several desks (SAP keeps the group per PR item); a PO takes the group of its largest line.
- **The mails go to the desk that owns the material**: the late cable and the IPS to Rohit Jain (S&T), the MFC, inspection, ABG and rail fittings
  to Deepanshu Jain (transformers, P-Way), the PV claim and masts to Vishnu Mudgal, the TMT notice and the bank-change fraud to Shubham Sharma,
  the cement offer to Govind Gupta, Tumkur and the quarry closure to Jitender Swami, the fund mails and the urgent-transfer fraud to Sudeep
  Singh (MIS), the GIS offer and the Gaya short-close to Sambhav Kumar, the LC to Urvik Patel, the DG warranty to Shree Dutt Anand.
- **Who decides what follows the organogram.** `buyers` gains designation, reports_to and duties. `lookups.leads()` is now "the members someone
  reports to"; `lead_of()` and `under()` are new; `gm()` is gone: the vendor library and cross-project rate spreads are Varun Joshi's duties,
  roads' decisions too, railway, BESS, solar and T&D Sambhav Kumar's, the MIS sheets Sudeep Singh's. Above a member's own limit the second
  signature is the person they report to (was: a lead sharing a vertical, else the GM). An MFC case is owned by the buyer's lead first, then the
  buyer, because the DoA has the vertical lead issue MFCs (the ₹16.2 Cr Aurangabad MFC: Sambhav signs, Satish countersigns). Today still has 27
  cases, split as before; their owners are the new desks.
- **Team page.** Grouped and ordered as the organogram draws the team (the Head, then each lead followed by their people), never by a figure.
  The Head sees everyone, a lead their own team (new scope "team"), anyone else their own page; a 403 names who may see it. A lead's Daily brief
  covers their team's lines. Each member's row and page carry what the chart says of them: designation (and in full), reports to, desk, work.
- **Organisation page** (`/org`, Insights → Organisation): the chart as a tree (the head, one column per lead, each team under its desk labels,
  open posts dashed, deeper levels nested) or a list (search, team filter). Anyone on the team can edit a box (name, designation, reports to,
  desk, portfolio, responsibilities, open post), add someone, remove someone (their people move up to their lead), undo the last edit or go back
  to the sheet. API: `GET /api/org`, `POST /api/org/people`, `PATCH`/`DELETE /api/org/people/{id}`, `POST /api/org/undo`, `POST /api/org/reset`.
  Edits are a ledger (`org_edits`, created outside the build's schema so a rebuild carries it over like the approval ledger) laid over the
  sheet's rows when the chart is read; each records who, when and the box's name. Edits change the chart and how the Team page groups and
  describes people; purchasing groups, signing limits and who may see whose page stay the recipe's answers.
- **Data page**: one new issue, `team.open_posts` (3, leave): AM/DM (SCM) - T&D, AM/DM (SCM) - BESS, Sr. Manager / Manager (Logistics) -
  International. 27 data issues.
- **Real-name hygiene.** `test_no_real_names.py` still fails on any person from the review repo, except the people the organogram names: the user
  supplied it to be used as it is. Satish Kumar Sharma and Sambhav Kumar also appear in the review repo. Invented names (vendor contacts,
  planners) that share a first name with a team member (Harish, Jitendra, Ankit) were left as drawn, so the random sequence stays.

### Worth knowing

- Every figure shown against a team member (open PRs, POs, savings, waits, cancelled lines) comes from the dummy records, not from their work.
  DEMO.md says so, in its opening and in the line to say out loud. Shown to HG's Head of SCM, those figures sit next to real people's names.
- Desk assignments beyond what the sheet says are mine: aggregate sites the sheet names for nobody stay on Varun Joshi's own desk (A00); Ishan
  Derashri and Ankesh Jha have the same words on the sheet, so bearings, pre-stress, crash barrier and slope protection went to Ishan (E01) and
  hume pipe and shuttering to Ankesh (E02); switchgear and T&D stay with Sambhav Kumar while the T&D and BESS posts are open; Rajesh, Lokesh Yadav
  and Ankit Solanki own no group. DoA limits by designation are invented (GM/AGM ₹5 Cr; Manager, DM, AM ₹1 Cr; executives, engineers, MT ₹25 L;
  MIS, accounts and the supervisor nothing).
- DATA.md said the 1 Sep rebuild drops 2,270 rows; it drops 2,269, as it did before this change. Corrected.

### Checks (22 Oct)

`make build-data`: 78 of 78 load checks, 27 data issues; `AS_OF=2026-09-01`: 73 of 73. Backend tests: 106 passed, 1 failed, and the failure is
not this change: `test_the_committed_contract_lists_every_route_the_server_serves` fails on `/api/ask/everywhere`, a route another session is
adding (regenerate `api/openapi.yaml` with `backend/.venv/bin/python backend/dev/contract.py`, then `cd frontend && npm run types`, once that
route settles). `make numbers`: 429 figures, 0 mismatches. `make scenarios`: 0 failed. `make hindsight`: 39 cases over 4 days, 0 failures.
`npm run check:ui`: tokens, no sideways scroll on 56 routes at 390 and 1440 px (with `/org` and `/org?view=list`), keys, Today/Approvals
consistency for 25 members, buyer, unit tests: all ok. DEMO.md walked again on fresh databases; its nine screenshots retaken.

## Change after Phase 5: the header and Ask (22 Oct)

The user asked for the header search to go, for Ask to move from the foot of the page to the top centre of every page, for Ask to answer
from the company's records, and for a better header.

- **Header** (`frontend/src/shell/Shell.tsx`, `shell.css`): three parts on one row. On the left, where the data stands: a dot (amber when
  a source is stale), the data date and the stale count, opening Data. In the centre, the command bar. On the right, who you are (initials,
  name, role from `/api/people`) with a menu to switch person. The sides shorten by the header's own width (a container query), so a page
  beside the answer panel keeps one row. `--top` is now 64 px.
- **Command bar** (`shell/CommandBar.tsx`, which replaces `SearchBar.tsx` and the docked `AskComposer`): one field for asking and finding,
  focused by ⌘K or `/`. Empty, it offers the questions about this page, then across the company (`GET /api/ask/everywhere`), then the
  person's last questions (kept in localStorage, a convenience only). Typing puts *Ask Lookout: "…"* first (Enter), then known questions
  that contain the words, then matching records from `/api/search` grouped as vendors, projects, POs, PRs, materials, cases, messages and
  people. The scope chip picks this page or Everything. On a phone it is a full-screen sheet, opened from the header's button or the tab
  bar's Ask. The answer panel keeps its follow-up composer. `--composer` is 0: nothing is reserved at the foot any more.
- **The planner** (`backend/app/organism/planner.py`, called from `ask.py` after the case's own questions and PR/PO numbers): it reads a
  question for what it names and what it wants. A vendor is named by a word only its name has (never a material's or a project's word,
  and a misspelling of five letters or more still finds it) or by its code. A project is named by its name, an alias, its id or "plant NNNN".
  A material is named by its code or the words of its description. The question can also name a vertical, a team member, "my", "top N",
  or a window ("this week", "next 30 days", "this year"). The page's record narrows the question unless the question names its own; on
  a case, "this vendor" means the case's vendor. The planner answers about: vendors by open or ordered value, the library, delivery
  record; open and past-due PO lines; open PRs (oldest, waiting on a function); cases; projects ranked and one project's overview; rates
  by site and sites above the median; MSME dues; LCs and BGs; long-lead items; work fronts; the inbox (held, not answered); spend by
  vertical, vendor or project; the team's load; your approvals. Every lookup is a step (specialist, tool, why, what it found), streamed
  as `child.started`/`tool.called`/`tool.result` like a case run. Every row carries a link, every table a *See them all* link to the
  filtered list, and each answer three follow-ups. A question that names nothing searches the records and says what Ask can answer.
  The old vendor matching (whole name only) and material matching (any shared word: "with" found a rail screw) are gone.
- **Suggestions**: `GET /api/ask/examples` takes the page's record (`ctx_type`, `ctx_id`, `ctx_label`), so a project, vendor, material or
  member page suggests questions about it. Record pages (vendor, material, PR, PO) now set the Ask context.
- **Answer panel**: rows open their record, a step list folds open ("4 lookups by the site planner and the sourcing analyst"), follow-ups
  ask in one click, and the running steps show each lookup's reason. On a case page the panel now lies over the right edge as it does on a
  list. Before, on a case page it fell into the sidebar's grid column and the page went blank; the bottom composer had the same fault.
- **API contract**: regenerated with `backend/dev/contract.py`; UI types with `npm run types`.

### Checks (22 Oct, after the header change)

Backend tests: 113 passed (6 new in `tests/hg/test_ask_planner.py`, each checked against the API's own lists, no names written in).
`make numbers`: 429 figures, 0 mismatches. `npm run check:ui`: tokens, no sideways scroll on 56 routes at 390 and 1440 px, keys,
Today/Approvals consistency for 25 members, buyer, unit tests: all ok. Screenshots at 1024, 1280, 1440, 1920 and 390 px (kept outside the
repo).

