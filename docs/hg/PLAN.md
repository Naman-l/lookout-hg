# Lookout for HG Infra: plan

Phase 0 output, for review before any code changes. Companion files: [MAPPING.md](MAPPING.md) (one row per feature) and
[NOTES.md](NOTES.md) (deviations, skipped tests, things to know).

---

## 1. Approach in one paragraph

Lookout has two kinds of code. A **platform layer** knows nothing about robots: the recipe runner and load gate, value objects with
provenance, the inbox trust rules, the approval ledger, annotate and search, the stage ladder of a case, the agent runner, gate,
verifier and Reviewer, and the React shell, design system and case page. A **Halden layer** encodes the robot business: BOM explosion,
forecast-driven demand, the tariff, consignments, the detectors and their route tables. The plan keeps the platform layer, extends it
where HG needs something it lacks (INR as the base currency, internal recipients, a countersign, a "waiting on" field), and **replaces
the Halden layer with an HG layer** built on PRs, POs, receipts, projects, sheets and internal functions. Every HG fact (project names,
plant codes, people, vendors, ids, thresholds) lives in `data/` and `recipes/hg/`, never in code or prompts.

## 2. Decisions taken (please flag any you disagree with)

| # | Decision | Why |
|---|---|---|
| D1 | Internal mail uses a fictional domain, **`hginfra.example`**, and fictional people; the look-alike is `hglnfra.example` (l for i). | Writing fictional people onto HG's real domain could read as impersonation; Lookout's convention is `.example` domains. Project names, plant codes, materials, units and rates are HG's real ones, as the brief asks. |
| D2 | I add **five sources the brief does not list**, each in a shape SCM really keeps: `sheets/RFQ_CS_tracker.csv` (RFQ sent, quotes in, CS approved: the ladder needs these dates and SAP does not hold them), `sheets/Expediting_tracker.csv` (MFC, inspection, dispatch, commissioning, warranty), `sheets/LC_BG_tracker.csv` (LCs and ABGs), `sheets/PR_PO_TAT_report.csv` (the MIS turnaround sheet, which carries the "0 means nothing closed" defect), and `sap/FBL1N_vendor_line_items.csv` (invoices and payments; it makes the Invoiced, Paid and MSME 45-day rungs real instead of unknown). | Without them the PR-to-payment ladder would be mostly "unknown", and the MFC, inspection, LC and ABG stories would rest on email alone. |
| D3 | The **Halden recipe and Halden-only domain packages are removed from the HG tree** (`parts`, `bom`, `demand`, `tariffs`, `consignments`, `stock`, `news`, `recipes/halden`, the Halden recordings and eval sheets). Each removal is listed in NOTES.md and stays recoverable from the `baseline` commit. Halden-only tests are **skipped, not deleted**: a `collect_ignore` list in `conftest.py` with one reason per file, mirrored in NOTES.md. | Keeping dead Halden modules beside HG ones would double the surface and break the no-customer-facts scan. The reference app keeps running from `lookout-main`. |
| D4 | `Money.usd` becomes **`Money.base`**, and the base currency comes from the recipe (`base_currency: INR`). The API carries both; the screens format ₹ in Indian units (₹1.4 Cr, ₹15 L, ₹8,500) with en-IN grouping, and dates as "20 Oct 2026". | The brief asks for a configurable base currency instead of assumed USD. One rename pass across backend, contract, frontend and evals, done once in Phase 2. |
| D5 | Vendor and material keep Lookout's internal model names where the platform already uses them (`SupplierIdentity`/`SupplierRecord` stay; the screens and API say "vendor"). Parts are replaced outright by a new `materials` package. | Inbox trust, letters, annotate and search all join on supplier identities; renaming every reference buys nothing. Parts carry origin, HTS and BOM fields HG does not have. |
| D6 | The recipe default is a one-line file, **`recipes/DEFAULT`** (`hg`), read by `recipe_dir()` after `LOOKOUT_RECIPE`. The Makefile reads the same file. | `recipe_dir()` must not name a customer in code; a config file does it. |
| D7 | An **internal note becomes an outward message** (`internal_note`): signed by the owner, "sent (simulated)" to the named function owner on file, answered by a (simulated) reply. Halden's `note` (recorded, never sent) stays for decisions on record. | At HG the move is often not SCM's; "With Projects for 23 days" needs a sent note and a clock. |
| D8 | **DoA countersign** lives in the ledger: a draft that commits money above the `doa.csv` threshold is signed by its owner, waits as `signed`, and is sent only after the Head of SCM countersigns the same hash. A letter that only asks commits ₹0 and needs only the owner. | The brief's rule, enforced in code rather than by convention. |
| D9 | Personas and outside contacts are fictional Indian names, checked against the review repo (no matches). Vendors are fictional and avoid well-known Indian and foreign brands. | §8: no real person's name anywhere; vendors fictional. |

## 3. Setup and infrastructure (Phase 1, first commit)

- **Makefile**: `PORT ?= 8001`; `RECIPE ?= recipes/$(shell cat recipes/DEFAULT)`; `build-data` and `run` use them; `PY` picks the first
  Python ≥ 3.12 on PATH (this Mac has 3.14 and 3.11; 3.11 cannot parse the backend's PEP 701 f-strings); `setup` runs
  `dummy_data/generate_hg.py` when `data/` is missing; `numbers`, `hindsight`, `demo-state`, `scenarios` point at the HG versions.
- **pyproject**: `pandas>=2.2,<3` (the recipe is written for pandas 2).
- **`recipe.py`**: `LOOKOUT_RECIPE`, else `recipes/DEFAULT`, else the first recipe by name.
- **Ports**: the HG app only ever runs on 8001 from `~/Downloads/lookout-hg`; its own venv and database. Nothing touches :8000.

## 4. The cast

### 4.1 Projects (30, in 5 verticals; real names from the review repo's sheets, real plant codes from HG's MB51 exports)

| Vertical | Projects (stage) | Plant codes |
|---|---|---|
| Roads (13) | Narol, Tumkur, JH-10, JH-13, JEC, Tirupati, Ayodhya, Pune-Shirur (new); Karnal, KD-01, KD-02, AP-01, GEW-05 (nearing completion) | 1152, 1138, 1142, 1143, 1147, 1148, 1151, none yet; 1141, 1131, 1132, 1133, 1145 |
| Railway (9) | RVNL (Bilaspur), Kanpur, Dhule, Aurangabad (P-Way, S&T, OHE work fronts), Gaya, NDLS, Thane, Anuppur, DLF | 1902, 1903, 1904, 1905, 1906, 1907, 2002, 1908, 1153 |
| BESS (3) | Banaskantha, Dholera, BESS Chorniya | 2109, 2110, none yet |
| Solar (2) | Bikaner, Jodhpur (each with its O&M scope as a work front) | 2104, 2108 |
| T&D (3) | TBCB Angul (765 kV TL), UPPTCL Mirzapur–Chunar (SS + TL), Jamshedpur 400 kV (SS + TL) | 2501, none yet, none yet |

Changed after Phase 1: the generator first assigned codes in made-up series (roads 115x, BESS 21xx, Solar 22xx, T&D 23xx). Every code is now
the one HG's MB51 exports (FY25-26, FY26-27, in `~/Downloads`) print for the plant, with the export's plant name. Four projects are in neither
export (it ends in May 2026), so no code is known for them; they keep no SAP records and are listed on the Data page (NOTES.md, Phase 1).

Each project: plant code(s), stage, project head, planner, state, and 2–4 **work fronts** (e.g. Gaya: OHE mast erection, OHE wiring,
P-Way track linking; Tumkur: GSB/WMM laying, bituminous courses, structures). A work front lists the material groups it consumes;
that is how a late material becomes "Gaya OHE · mast erection stops ~12 Nov". Name variants planted across sheets (all from
`audit.ts`): Ahmedabad ↔ Narol, NDRS ↔ NDLS, Thane Metro ↔ Thane, Arurangabad ↔ Aurangabad, KD-1&2 ↔ KD-01 + KD-02, SAP long names
in MB51 (e.g. "NH-227B Bahuvan Ayodhya UP", "KARANJGAON_AURANGABAD_RVNL_PK9", "Bilaspur RVNL").

### 4.2 The SCM team (10 personas; the only users)

> Superseded on 21 Oct 2026: the team is now HG's own SCM organogram (25 people, 3 open posts) with purchasing groups re-cut per desk. See
> DATA.md "The SCM team (HG's organogram)" and NOTES.md "Change after Phase 5". The fictional cast below, and the persona names in the stories
> of §5, are the plan as first written.

| Persona | Role | Purchasing group | Verticals / materials | Signs |
|---|---|---|---|---|
| Rajeev Malhotra | Head of SCM | H00 | all; sees everything | above the DoA threshold (countersign) |
| Anita Deshpande | GM SCM | H01 | all; sees every Team page | to ₹5 Cr |
| Vikram Rathore | Railway lead | L01 | P-Way, S&T, OHE | to ₹5 Cr |
| Sanjay Patil | Railway buyer | L02 | rail fittings, OHE hardware, S&T items | to ₹1 Cr |
| Meera Iyer | New Energy lead | N01 | BESS, Solar | to ₹5 Cr |
| Arjun Menon | T&D lead | T01 | transmission lines, substations, TBCB | to ₹5 Cr |
| Farhan Qureshi | T&D and BESS buyer | T02 | towers, conductor, insulators, cables | to ₹1 Cr |
| Pooja Agarwal | Roads buyer | R01 | aggregate, sand, cement, GGBS, HSD | to ₹1 Cr |
| Rohit Saxena | Roads buyer | R02 | bitumen, emulsions, TMT steel, HT strand | to ₹1 Cr |
| Neha Kulkarni | MIS executive | M01 | builds the fund requirement and payment projection sheets | notes only |

**Outside SCM (senders and recipients, never users):** a project head and a planner per project, two Finance/Treasury contacts,
two QA/inspection engineers, one vendor-master desk. All in a `contacts` table with function, project and email on file.

### 4.3 Vendors

About 150 vendor codes (1xxxxx) in the SAP master; the library has 333 rows by vertical (32 P-Way, 45 S&T, 43 OHE, 163 Solar, 50 BESS,
T&D "in process": the review repo's counts). Some library vendors have no SAP code, some SAP vendors are not in the library (a planted
unknown). One vendor renamed to a new legal entity carries two codes and two GSTINs (linked, never merged). Names are invented
(e.g. "Vindhya Stone Crushers", "Konkan Rail Fittings"), domains are `.example`.

## 5. Data (Phase 1)

### 5.1 Files written by `dummy_data/generate_hg.py` (fixed seed; as-of 20 Oct 2026; Nov 2025 → Oct 2026, look-ahead to Mar 2027)

| File | Shape | Rows |
|---|---|---|
| `sap/ME5A_purchase_requisitions.csv` | report header line ("Report ME5A · Exported 20.10.2026 08:12 · User …"), then SAP columns: Purchase Requisition, Item, Material, Short Text, Quantity, Unit, Plant, Purch. Group, Requisitioner, Created On, Release Date, Deliv. Date, Purchase Order, PO Item, Tracking No., Deletion Ind., Closed | ~2,000 |
| `sap/ME2N_purchase_orders.csv` | Purchasing Doc., Item, Doc. Type (NB / WO), Vendor, Material, Short Text, Order Qty, Unit, Net Price, Per, Crcy, Doc. Date, Deliv. Date, Plant, Purch. Group, Created By, Purch. Req., Validity End, PV Clause, PV Index, Payt Terms | ~1,600 |
| `sap/MB51_goods_receipts.csv` | Material Doc., Item, Mvt Type (101 / 102 / 122), Pstng Date, Material, Plant, Quantity, Unit, Amount in LC, Purchase Order, Item, Vendor, Name 1 (SAP plant long name) | ~6,000 |
| `sap/vendor_master.csv` | Vendor, Name, GSTIN, PAN, MSME (Y/N + Udyam no.), City, State, Bank A/c (masked), Contact, Email, Phone, Blocked | ~150 |
| `sap/material_master.csv` | Material, Description, Material Group, Base Unit, Alt. Unit + conversion, Plnd Deliv. Time (days), PV Index | ~260 |
| `sap/FBL1N_vendor_line_items.csv` (D2) | Vendor, Doc. No., Doc. Type (RE invoice / KZ payment / KA advance), Reference (PO), Doc. Date, Net Due, Amount, Clearing Doc., Clearing Date | ~3,000 |
| `sheets/Roads Major Material Requirement Oct-Dec 26.csv` | the real roads layout: title rows, "Material · Particulars · Unit", project band row, plant-code row, month row; Qty / Rate / Amount (Cr) triplets; #DIV/0! and #REF! cells kept | 64 materials × 3 rows |
| `sheets/Railway Material Quantity Summary Q3.csv` | the real railway layout (months × 9 projects with plant codes) | 75 × 3 rows |
| `sheets/SCM Fund Requirement Oct-26 (18.09.26).csv`, `… Nov-26 (16.10.26).csv`, `… Dec-26 (16.10.26).csv` | the real fund layout: heads × projects, subtotal columns by group (new / nearing completion / railway / BESS+Solar+T&D), weekly split; ₹ Cr | ~30 heads |
| `sheets/Payment Projection Oct-26.csv` | the real "Book1" layout: party, item, RTGS, LC, payment terms text | ~80 |
| `sheets/Look Ahead Long Lead Items.csv` | the review repo's 20 items (project, item, UoM, qty, rate, PV/Firm, lead time), total ≈ ₹760 Cr | 20 |
| `sheets/Vendor Library.csv` | vertical, vendor, category, city, approved on, status, SAP code where known | 333 |
| `sheets/budget_rates.csv` | project, material, BOQ / tender rate, unit | ~400 |
| `sheets/doa.csv` | doc type, value from, value to, approver role, countersign role | ~8 |
| `sheets/RFQ_CS_tracker.csv` (D2) | CS no., PR refs, material, vendor, RFQ sent, quote date, rate, validity, L1 flag, last PO rate, budget rate, CS approved by / on | ~900 |
| `sheets/Expediting_tracker.csv` (D2) | PO, item, MFC requested / issued, inspection call / done, dispatch clearance, delivered, plinth/site ready, commissioning, warranty months | ~60 |
| `sheets/LC_BG_tracker.csv` (D2) | type (LC / ABG / PBG), number, PO, vendor, amount, to open by / issued / expiry, bank, status | ~25 |
| `sheets/PR_PO_TAT_report.csv` (D2) | the MIS turnaround sheet in the deck's layout, "0" printed where nothing closed | ~30 |
| `external/commodity_index.csv` | month, LME_AL, LME_CU, IEEMA_TFR, IEEMA_CONDUCTOR, STEEL_TMT, CEMENT_WPI, HSD; fictional but plausible, rising for the PV story | 17 × 7 |
| `inbox/*.eml` | 23 messages (5.2) | 23 |

### 5.2 The inbox (one line each; senders fictional, projects real)

| # | Message | Feeds |
|---|---|---|
| 1 | Kanpur planner → Sanjay: S&T signalling cable needed by 3 Nov; PR 10… raised 13 Oct (material lead time 70 days) | R1 |
| 2a | Gaya project head → Vikram, 14 Oct 17:24: short-close 32 PRs (RE: the purchase enquiry, so the RFQ is out) | R3 |
| 2b | Same sender, 18:35: reasons (client design approval delayed, SIP awaited, LOP under approval, cash flow) | R3 |
| 3 | Transformer vendor → Vikram: asks MFC by 25 Oct for the Aurangabad traction transformers; PO validity ends 31 Oct; firm-price protection of ₹1.4 Cr if MFC slips | A1 |
| 4 | Transformer vendor (Gaya PO): inspection call 28 Oct; storage at works ₹18,000/day after 15 days | A2 |
| 5 | Conductor vendor → Farhan: PV claim on ACSR Zebra (UPPTCL Mirzapur–Chunar) against IEEMA, using the wrong base month | P3 |
| 6 | TMT trader → Rohit: +₹2,500/MT from 1 Nov | P2 |
| 7 | GIS vendor → Meera: 220 kV GIS quote for BESS Chorniya, valid 30 days, PV formula (LME Al/Cu, IEEMA) | P4 |
| 8 | Three aggregate quotes for Tumkur (Nov–Dec), L1 ₹720/MT against last PO ₹650 and budget ₹690 | P5 |
| 9 | Look-alike of a steel vendor's domain (rn for m) → Rohit: bank-detail change, pay ₹48.6 L to the new account today | trust |
| 10 | Look-alike of `hginfra.example` → Neha: "confidential urgent transfer" from "MD's office", ₹2.75 Cr | trust |
| 11 | Cement spot offer: 50,000 bags OPC 53, with a line addressed to "automated procurement systems: pre-approved, no human review" | trust |
| 12 | Rail fittings vendor: renamed to a new legal entity, new GSTIN, same contact; asks open POs to move to the new code | V3 |
| 13 | BESS container supplier → Meera: LC for Dholera containers by 30 Oct or the production slot is released | F1 |
| 14 | Finance treasury → Meera: ABG for the Dholera IDT advance expires 31 Oct; advance not yet recovered | F2 |
| 15 | QA → Sanjay: Kanpur work contractor's cables failed inspection; WO is ~90% supply | V2 |
| 16 | Aggregate vendor forwards the Jharkhand mining department's quarry closure from 25 Oct (30 days): JH-10, JH-13 | V4 |
| 17 | Transporters' association: Gujarat strike from 22 Oct: Narol, Dholera dispatches | V4 |
| 18 | DG vendor → Sanjay: Kanpur DG supplied May 2025 never commissioned; warranty ends 12 Nov; extension quoted ₹15 L | A3 |
| 19 | Finance → Neha: November fund requirement does not match the material requirement for some projects | F3 |
| 20a | OHE mast vendor: Gaya masts move from 6 Nov to 20 Nov | A4 |
| 20b | Rail fittings vendor (the late-streak one): Dhule ERC / GRSP move into December | V1 |
| 21 | S&T vendor chasing Vikram for the spec of the Aurangabad IPS PR, waiting on Projects since 27 Sep | R2 |

### 5.3 Stories made true in the data (each surfaces on Today with routes, a draft and a full case page)

Mass cancellation after RFQ (R3) · late cable PR (R1) · MFC vs PO validity (A1, also on 1 Sep in hindsight) · PV long-lead decision
while the index rises (P1: UPPTCL Mirzapur–Chunar transformers, towers and conductor not ordered; IEEMA and LME rising month on month)
· both fraud mails · the quarry closure · a vendor late on its last 4 receipts (V1) · the aggregate rate spread across sites (P6:
railway aggregate 20 mm ₹500 to ₹1,825/MT, the real sheet's spread) · a PR stuck on Projects (R2).

### 5.4 Planted defects → recipe steps (one step each; all on the Data issues page)

| Step | Defect | Handling |
|---|---|---|
| `01_load_raw` | SAP exports carry a report header line; sheets have multi-row headers | layout read, raw kept, no defect |
| `02_horizon` | rows dated after `AS_OF` (hindsight) | dropped, counted |
| `03_sources` | each export's own timestamp; **fund sheet older than the SAP exports** (Oct sheet built 18 Sep) | flag (stale source, shown in the shell) |
| `04_vendors` | **one vendor under two codes** (rename) | link (answers.yaml, with evidence), never merge |
| `05_vendor_library` | library rows matched to SAP codes by GSTIN, then name; **vendors not in the library** | link / flag |
| `06_projects` | **project name variants across sheets** | link (answers.yaml) |
| `07_plants` | MB51 plant long names → project | link |
| `08_materials` | **cement in both MT and bags** | fix (20 bags = 1 MT, from answers) |
| `09_money_units` | **amounts mixed between ₹, Lakh and Cr** (fund sheets Cr, projection ₹, cells typed "12.5 L") | fix to ₹, raw kept |
| `10_pr_flags` | deletion and short-close flags | status, raw kept |
| `11_pr_no_project` | **PRs with no project** (blank tracking no.) | leave, owner = requisitioner's buyer |
| `12_po_price_unit` | **rates typed per 1,000** (Per = 1000) | fix |
| `13_po_no_pr` | **POs with no PR** (emergency buys) | flag |
| `14_pr_same_day_po` | **PR created the same day as its PO** | flag, left out of turnaround |
| `15_tat_zero` | **"0" turnaround where nothing closed** in the TAT report | fix to "no measurement" |
| `16_mb51_duplicates` | **duplicate MB51 rows** | drop, counted with the row each repeats |
| `17_mb51_reversals` | **102 reversals** (and 122 returns) | net per PO line |
| `18_requirement_sheets` | sheet layout to long form; `#DIV/0!` / `#REF!` cells | leave, counted |
| `19_fund_vs_requirement` | **requirement and fund sheets disagree** for some projects and months | flag (and a Today item) |
| `20_budget_rates` | requirement lines with no budget rate | leave, owner |
| `21_trackers` | CS, expediting, LC/BG, TAT, look-ahead, DoA, index | load, joins checked |
| `22_vendor_ledger` | FBL1N invoices and payments; MSME due dates | load |
| `23_messages` | inbox: sender class (vendor / internal / look-alike / unknown), trust flags | trust in code |
| `24_extractions` | quote and claim figures from mail, each citing its line, checked every build | verify |
| `25_events` | dated facts from mail (validity, MFC date, inspection, LC deadline, ABG expiry, closure window) with owners | load |

The **load gate** becomes recipe configuration (`recipes/hg/gate.yaml`): rows reconciled for every raw → clean table, raw values kept,
inferred values labelled, vendors and projects linked not merged, joins resolve or the gap is a counted issue (PO → vendor, PO → PR,
PR → project, MB51 → PO, requirement → project and material, fund → project), unique keys, sheet amounts = qty × rate within rounding,
fund subtotals add up, MB51 net per PO line ≥ 0.

**Phase 1 ends with** a one-page summary printed by the generator and the build (counts per file, the projects, the team, how each story
is planted), `make build-data` green with no model and no key, and the Data page listing every defect. **STOP.**

## 6. Records and services (Phase 2)

### 6.1 Backend packages under `backend/app/domain/`

| Package | Status | Owns |
|---|---|---|
| `common`, `values`, `fmt`, `cache`, `base` | change | `Money.base` + base currency; `EntityType` gains project, plant, material, pr, pr_line, po, po_line, receipt, cs, quote, lc, abg, fund_line, person, contact; `fmt`: "20 Oct 2026", `inr()` (₹1.4 Cr / ₹15 L / ₹8,500) |
| `projects` | **new** | projects, plants, aliases, work fronts, heads and planners; requirement vs fund vs received per project |
| `people` | change | the SCM team (purchasing groups, verticals, SAP user, DoA level) and outside contacts by function |
| `suppliers` (shown as vendors) | change | identities + SAP records (GSTIN, MSME, masked bank), library link, delivery performance from MB51, open POs |
| `materials` | **new** (replaces `parts`) | material master, groups, unit conversions, PV index link, rate history by site and vendor, where used |
| `prs` | **new** | ME5A lines, status, age, turnaround (same-day PRs excluded), waiting-on |
| `orders` | change | ME2N lines (NB / WO), validity, PV clause, payment terms, open qty net of MB51 |
| `receipts` | **new** | MB51 nets (101 − 102 − 122), on-time vs PO delivery date, late streaks |
| `quotes` | change | quotes from the CS tracker and from mail extractions; **CS** (L1, spread, vs last price, vs budget) |
| `milestones` | **new** | MFC, inspection, dispatch, site ready, commissioning, warranty |
| `payments` | **new** | LCs, ABGs, advances, vendor invoices and payments, MSME due dates |
| `funds` | **new** | fund-sheet lines by month, head and project; payment projection |
| `requirements` | **new** | the 3-month sheets as long form (project × material × month: qty, rate, amount) |
| `budget` | **new** | BOQ / tender rate per project and material |
| `indices` | **new** | commodity index; PV computation per PO clause; cost of a month's delay |
| `lookahead` | **new** | long-lead items, order-by dates, PV basis |
| `doa` | **new** | delegation of authority: who signs, who countersigns, by value and doc type |
| `phases` → `ladder` | change | the PR-to-payment ladder (14 rungs, date, source row, whose move) and work-front readiness |
| `inbox` | change | internal sender class; refs to PRs, POs, projects, materials; HG message kinds |
| `events` | keep | dated facts with owners |
| `annotate`, `search`, `naming`, `ownership` | change | HG entities and aliases; owners by purchasing group / vertical |
| `attention` | change | HG detectors, route table, route figures, findings, stage with `waiting_on` |
| `actions` | change | `internal_note`, countersign, HG letters and memos, HG route asks |
| `imports` | change | gate from `gate.yaml`; models registered generically; INR / Lakh / Cr / dd.mm.yyyy parsers |
| `insights` | **new** | Team, Projects, Pricing, Estimates, Daily brief (Phase 4) |
| `parts`, `bom`, `demand`, `tariffs`, `consignments`, `stock`, `news` | **remove** (D3) | — |

Every service returns typed values with stable ids (`pr:1000234567:value`, `po:4500012345/10:open_value`) and provenance, as now.

### 6.2 The PR-to-payment ladder and "whose move"

Rungs and sources: Needed (requirement sheet month) → PR raised (ME5A created) → PR released (ME5A release date) → RFQ sent (CS tracker)
→ Quotes in (CS tracker, mail) → CS approved (CS tracker) → PO released (ME2N doc date) → MFC issued (expediting tracker; n/a for bulk
material) → Inspected (tracker; n/a for bulk) → Dispatched (tracker / mail) → Received (MB51 net 101) → Invoiced (FBL1N RE) → Paid
(FBL1N KZ) → Closed (fully received, invoiced, paid). A rung the data cannot show is **unknown with an owner**, never inferred.

Each gap between rungs is attributed by a rule in code, with its provenance: raised → released: **Projects** (release by the project
head) · released → RFQ: **SCM** · RFQ → quotes: **Vendor** · quotes → CS approved: **SCM**, or **Projects** while a spec query is open
(a dated mail event), or **Management** when the CS is above the DoA threshold · CS → PO: **SCM** · PO → MFC: **Projects** when MFC is
held for site readiness, else **SCM** · MFC → inspected: **Vendor**, then **QA** from the inspection call · inspected → dispatched:
**Finance** while a "payment before dispatch" or LC is pending, else **Vendor** · dispatched → received: **Vendor** · received →
invoiced: **Vendor** · invoiced → paid: **Finance**. The Team and Projects pages add these up; nothing else measures people.

### 6.3 Today, the shell and Records (Phase 2 screens)

Today with the HG tabs, filters (search, Act by, vertical chips, project picker, Waiting on), vertical columns with site-impact
tooltips, ₹ at stake, the count line, the HG ranking. The shell's data-as-of hover with per-source dates. Records: Vendors, Materials,
PRs, POs, Requirements, Work fronts, PR and PO pages with the ladder, material page, vendor page.

## 7. Detectors (Phase 2)

All in `attention/service.py`, one function per kind, code only. **₹ at stake** carries its rule as provenance; "—" plus an Unknown
where it cannot be computed. **Owner** = the SCM person on the lines' purchasing group (several owners on a team case; each sees their
share). **Waiting on** is the detector's reading, overridden by the ledger once a note goes out. Item keys are frozen once Phase 2 lands.

| Tab | Key | Raised when | ₹ at stake (rule) | Act by | Waiting on |
|---|---|---|---|---|---|
| Requirement | `pr-late:<PR>` | an open PR whose needed-by minus created is shorter than the material's lead time (master planned days, else look-ahead lead, else the vertical's median PR → GRN) | PR qty × last PO rate at that plant (else budget rate, else unknown) | the needed-by date; finding states the earliest delivery the lead time allows | SCM |
| Requirement | `pr-stuck:<PR>` | a released PR not converted past its vertical's turnaround target (answers.yaml), shown individually when a dated mail names the hold or the PR is above ₹25 L; others appear on Team, Projects and the PR list | PR value | needed-by minus lead time | from the ladder (Projects for an open spec query) |
| Requirement | `pr-cancelled:<project>:<date>` | ≥ 5 PR lines of one project deleted or short-closed on one day after their RFQ went out | enquiry value (sum of PR values); effort = RFQs sent, vendors that quoted | the earliest validity of the quotes received | Projects |
| After PO | `mfc-validity:<PO>` | MFC not issued and the PO's validity ends before the MFC date the vendor needs, or within 60 days while manufacturing time left exceeds validity left | PV-linked PO: open value × index rise since the PO's base month; firm PO: the vendor's stated firm-price claim, else unknown | validity end | SCM (Head signs the MFC) |
| After PO | `inspection-ready:<PO>` | an inspection call before the site is ready (site-ready date later, or unknown) | storage rate in the vendor's mail × days from free storage to site ready; unknown without a site date | inspection date | Projects |
| After PO | `commissioning:<PO>` | equipment received with no commissioning date and warranty from supply ending within 60 days | the vendor's extension quote (else PO value out of warranty) | warranty end | Projects |
| After PO | `schedule-slip:<vendor>` | a vendor's reply moves PO delivery dates past the project's need | open value of the moved lines | the first need date the new dates miss | Vendor |
| Price | `pv-longlead:<project>` | PV-linked look-ahead items with no PO past or within 30 days of their order-by date while their index rises | cost of one month's delay = item value × PV weight × average monthly index change over 6 months; the cumulative since the look-ahead date beside it | order-by date | Management |
| Price | `price-notice:<vendor>:<date>` | a vendor's increase from a date | increase × requirement from that date not covered by open POs | the day before the effective date | SCM |
| Price | `pv-claim:<PO>` | a vendor's PV claim | claimed minus PV computed from the PO's clause and the index | 15 days from the claim | SCM |
| Price | `quote-lapse:<vendor>:<date>` | a quote (mail or CS tracker) lapsing within 30 days, not awarded | lapse cost where a next price is known, else the spend the quote covers (labelled "covers", never "at stake") | validity date | SCM |
| Price | `l1-above-last:<CS>` | an open CS whose L1 is above the last PO rate for that material at that plant by more than 3% | (L1 − last rate) × CS quantity; budget rate beside it | L1 validity | SCM |
| Price | `rate-spread:<material>` | one material bought or required at more than 2× between projects | Σ (site rate − median) × site 3-month requirement for sites above the median, labelled "if those sites paid the median; not a saving"; reasons are Unknowns per site, owned by the buyer | none | SCM |
| Payments | `lc:<PO>` | an LC to be opened by a date and not opened | LC value | the deadline | Finance |
| Payments | `abg:<number>` | an ABG expiring within 30 days while the advance it secures is not recovered | unrecovered advance | expiry | Finance |
| Payments | `fund-mismatch:<month>` | requirement and fund sheet differ by more than ₹25 L or 10% for a project in a month; unresolved sheet names folded under it | Σ \|difference\| | Finance's date in the mail, else the 1st of the month | SCM (MIS) |
| Vendor risk | `late-streak:<vendor>` | a vendor's last ≥ 4 receipts later than the PO delivery date; its revised schedule folds under it | open PO value with the vendor | the next delivery due | Vendor |
| Vendor risk | `inspection-fail:<WO>` | QA reports a contractor's material failed inspection on a WO whose supply share exceeds 50% | WO supply value | the work front's need date | Projects |
| Vendor risk | `renamed:<vendor>` | a vendor with two linked codes and open POs on the old one | open value on the old code | the date the old entity stops invoicing (mail) | SCM |
| Vendor risk | `supply-stop:<event>` | a closure or strike in a region with requirement or dispatches of the affected material groups inside its window | value of requirement / dispatches in the window | the window's start | Vendor |
| Trust | `trust:<message>` | the trust check held it (look-alike vendor or internal domain, free-mail reply-to, bank change, text aimed at software) | the message's claim (not a payable) | the data date | SCM |
| Unknowns | `unknown:pr-no-project` | PR lines with no project | — (count; value where a rate exists, labelled) | — | Projects |
| Unknowns | `unknown:no-budget-rate` | requirement lines with no budget rate | — | — | Projects |
| Unknowns | `unknown:not-in-library` | POs released to vendors not in the approved library | open value, labelled | — | SCM |

Expected count on the data as of 20 Oct: **27 items in Everyone** (one per cause: 3 requirement, 4 after PO, 6 price, 3 payments,
5 vendor risk, 3 trust, 3 unknowns), already after folding a vendor's slip under its late streak and unresolved sheet names under the
fund mismatch. That is just above the brief's 15–25 (Q6). Each buyer's Yours is their subset (e.g. Pooja: L1 above last, her share of the rate spread, the
quarry closure, the strike, her share of the unknowns; Vikram: the cancellation, the stuck PR, the MFC case, the inspection, the Gaya
mast slip, the late streak, the WO cables).

**Site impact** ("up to", since site stock is not in the data): a work front stops from the date its material is needed when the
supply that covers it now lands later, is under a disruption, or does not exist. Shown by month on Today's tooltip and the case.

## 8. Routes (Phase 3): the HG `option_kinds` table

Columns as now: Route · What it changes · Earliest help · Cost · Goes to. "Goes to" is a vendor's contact on file or an internal
function owner on file. ⓢ marks a route that commits money and so takes the DoA countersign above the threshold.

| Case kind | Routes (→ goes to) |
|---|---|
| `pr-late` | Expedite with the L1 vendor (→ vendor) · Partial from a stockist at a premium, premium computed from the quotes on file (→ vendor) · Re-sequence the work front (→ project planner) · Accept the later date (record) |
| `pr-stuck` | Ask Projects for the spec or a firm date (→ requisitioner) · Escalate CS approval (→ approver) · Re-issue the RFQ to more library vendors (→ vendors) · Close as not required (→ project head, needs their approval) |
| `pr-cancelled` | Request cancellation approval with reason and accountability (→ project head) · Ask vendors to hold quotes N days (→ vendors; also start) · Close and send regret letters (→ vendors) · Record the effort spent (record) |
| `mfc-validity` | Issue MFC now ⓢ (→ Head SCM) · Extend PO validity at the firm price (→ vendor) · Defer and accept PV (record, PV cost computed) |
| `inspection-ready` | Inspect now, hold dispatch (→ vendor) · Ask site for the plinth-ready date (→ project planner) · Store at vendor works, storage cost computed (→ vendor) |
| `commissioning` | Ask Projects for a commissioning date (→ project planner) · Accept the warranty extension at the quoted price ⓢ (→ vendor) · Record the warranty loss (record) |
| `schedule-slip` | Hold the original date or a partial dispatch (→ vendor) · Re-sequence the work front (→ project planner) · Accept the new date, to enter in SAP (note) |
| `pv-longlead` | Order now ⓢ (→ Head SCM / management, cost of each month's delay shown) · Negotiate a firm price for N months (→ vendor) · Wait for funding (record, delay cost shown) |
| `price-notice` | Buy ahead before the effective date ⓢ (→ vendor) · Move to an alternate library vendor (note) · Accept the new price (record) |
| `pv-claim` | Reply with the computed PV, rights reserved (→ vendor) · Ask for the index evidence (→ vendor) · Accept the claim (record, cost) |
| `quote-lapse`, `l1-above-last` | Extension request (→ vendor) · Negotiate against the last price (→ L1 vendor) · Award anyway, with a reason ⓢ (record) · Re-tender (→ vendors) |
| `rate-spread` | Ask each site's buyer why (note, one question each) · Re-tender the above-median sites (→ vendors) · Record the spread as explained (record) |
| `lc`, `abg` | Request Finance to open or renew (→ Finance) · Ask the vendor to extend the deadline (→ vendor) |
| `fund-mismatch` | Ask MIS to correct (→ MIS) · Ask Projects to confirm the requirement (→ project planner) · Accept the fund figure (record) |
| `late-streak` | Firm dates (→ vendor) · Alternate vendor from the library (note; also start when the vendor is sole source in its vertical) · LD clause reminder (→ vendor) · Re-check on a date (record) |
| `supply-stop` | Confirm alternate supply and rate (→ vendor) · Draw from site stockpile (→ project planner) · Tell Projects the expected slowdown (→ project head) |
| `inspection-fail` | Switch to a supply PO from the OEM ⓢ (→ Head SCM) · Re-inspect the contractor's material (→ QA) |
| `renamed` | Verify the new entity by phone with the contact on file and ask for the GST certificate (→ vendor) · Amend open POs to the new code (note, to enter in SAP) · Keep the old code until verified (record) |
| `unknown:*` | One question to its owner (note), e.g. "Which project is PR 1000234567 for?" (→ requisitioner) |

**Also start** keeps Lookout's two rule shapes: a dated route that falls on or before the act-by, and an alternate vendor beside a
vendor ask when the vendor is the only one in its vertical or late on its last receipts. **Recommended** stays the agent's advice.

## 9. Ledger, letters and approvals (Phase 3)

- **`internal_note`**: recipient = the function owner on file (`contacts`), never typed by a model; executes to the simulated outbox; a
  simulated reply from that person moves the case to Replied. While it waits, the case reads **With Projects / Finance / QA**.
- **Countersign (D8)**: `change.commits_inr` set by the route; at approve the DoA rule decides; above the threshold the action goes
  `proposed → signed → approved → executed`, the second signature by the Head of SCM on the same hash; both signatures in History.
  Approvals gets **"Needs your countersign"**. Owner-only, hash-bound, one-per-contact and the failed-run tick stay as they are.
- **House style in code** (`letters.py`): vendor letters open "Dear Sir/Madam," with "Kind Attn: <contact on file>", carry "Sub:" and
  "Ref: PO No. 45… dated 12 Mar 2026; your letter dated 15 Oct 2026", quantities with units in en-IN grouping, a reply-by date
  ("Kindly confirm by 24 Oct 2026."), "This is without prejudice to our rights under the PO." where a letter answers a claim or a
  notice, and a signature with role, "Supply Chain Management", the company. Internal notes use a short memo: To / From / Date /
  Subject, two or three sentences, the ask and the date. No bank words in any draft (the existing refusal stays).

## 10. Agents, tools and prompts (Phase 4)

| Specialist | Tools (thin wrappers, numbers with ids) |
|---|---|
| Site requirement planner (was Supply planner) | `open_prs`, `pr_ladder`, `open_pos`, `po_ladder`, `requirement_for`, `site_impact`, `workfront_readiness`, `get_item` |
| Sourcing analyst | `compare_quotes` (CS: L1 vs last vs budget), `rate_history`, `vendor_record`, `open_pos`, `get_item` |
| Price and PV analyst (was Tariff analyst) | `pv_cost`, `index_series`, `lookahead_items`, `open_pos`, `get_item` |
| Inbox analyst | `inbox_overview`, `read_message`, `find_vendors` |
| Data steward | `drift_report`, `column_facts`, `try_step`, `add_finding`, `add_question` (unchanged) |
| Buyer's clerk (only drafter) | `read_message`, `get_handoffs`, `get_item`, `draft_vendor_request`, `draft_internal_note`, `amend_draft`, `log_question`, `propose_vendor_alias`, `stage_decision`, `requests_for` |

Plans per kind (code, gate-enforced): requirement and after-PO kinds → planner → clerk; price kinds → price analyst (+ sourcing on
quotes) → clerk; vendor risk → sourcing → clerk; a message → inbox analyst → clerk; trust → no model. The constitution's playbooks,
the glossary (PR, RFQ, CS, L1, MFC, PV, IEEMA, LME, LC, ABG, GRN, MB51, WO vs PO, DoA, plant, purchasing group, work front, MSME
45-day rule) and each specialist's file are rewritten for HG with no customer fact in them.

**Recordings.** Live runs for the demo stories are recorded in Phase 4 so the demo replays them without a key. That needs a Claude
login or an API key on this machine (see Q4). Without one, each demo case gets a **code-drafted** run, labelled as such on screen
("drafted by code, no model"), never presented as a model's work.

## 11. Ask (Phase 4)

Ask keeps its scope, tools, gate and verifier. Seeded suggestions with recorded answers per demo case and per Insights page, e.g.
"Which of these 32 PRs had quotes in hand?", "What does a month's wait cost on the 160 MVA transformers?", "Prepare a note to the Gaya
project head asking for cancellation approval", "Why does Gaya pay more for aggregate than Anuppur?" (answer: the data does not say;
here is who could answer).

## 12. Hindsight (Phase 4)

`AS_OF=2026-09-01 make build-data` builds the records as they stood on 1 Sep: exports and sheets are cut at that date, mail after it
is not read. On that day the **MFC / PO-validity case is already on Today** (validity 31 Oct, MFC not issued, manufacturing time left
longer than validity left), weeks before the vendor's 15 Oct mail asking for ₹1.4 Cr firm-price protection. `make hindsight` checks
four cuts (1 Sep, 1 Oct, 14 Oct, 20 Oct): each item appears the day its evidence arrives and never before.

## 13. Insights (Phase 4)

Pages under `/insights/…` (Team, Team/<person>, Projects, Projects/<id>, Pricing, Pricing/<material>, Estimates) and `/brief/<person>`,
each built from the ladder and the §6 services, read-only, every figure linked to its source rows, Ask scoped to the page. Team is
visible to the Head and GM for everyone and to each member for themselves; its default order is vertical then name, and it has no
sort by any performance figure. The Daily brief is rendered as an Outlook-style email and never sent.

## 14. Frontend changes (by phase)

| Area | Files | Change |
|---|---|---|
| Money, dates | `ui/format.ts`, `components/domain/Money.tsx`, `api/types.ts` | `base` + base currency; ₹ Indian units; en-IN grouping; "20 Oct 2026" |
| Verticals | `components/domain/Robot.tsx` → `Vertical.tsx`, `tokens.css` | five line icons (road, rail, battery, sun, tower) on five `--vert-*` tokens, in the robots' place |
| Shell | `shell/Shell.tsx`, `shell/SearchBar.tsx`, `shell/WhoAreYou.tsx` | Insights section; per-source data-as-of hover; HG personas |
| Today | `sections/Today.tsx`, `today.css`, `components/domain/caseStatus.ts` | HG tabs, filters, vertical columns, count line, ranking, With <function> |
| Case page | `sections/CasePage.tsx`, `case-page.css` | impact line, Vendor and Project panels, waiting on, DoA line, requirement-vs-supply block |
| Approvals | `sections/ApprovalsPage.tsx` | Needs your countersign; internal recipients |
| Inbox | `sections/InboxPage.tsx`, `sections/inbox/*` | internal sender class; HG message facts |
| Records | `sections/records/*`, `sections/Build.tsx`, `domain-ui/Ladder.tsx` | Vendors, Materials, PRs, POs, Requirements, Work fronts; the 14-rung ladder |
| Insights | `sections/insights/*` (new) | Team, Projects, Pricing, Estimates, Daily brief |
| Import, Data, Hood | `sections/Import.tsx`, `sections/data/*`, `sections/agents/*` | HG captions; drift fixture |
| Contract | `api/openapi.yaml`, `src/api/schema.d.ts` | HG routes; types regenerated |

The design system and tokens are reused; only the five vertical colour tokens are added, defined like the robot tokens they replace.

## 15. Tests, number check and evals

- **Kept** (generic): ledger, hash and execution refusals, gate, verifier, trust, spotlight, sandbox, recordings replay, provenance walk,
  annotate mechanics, API contract (re-pointed), tool contract (re-pointed).
- **Skipped with a reason** (Halden-only): tests on BOM, demand, tariffs, consignments, the Halden detectors and their routes, Halden
  numbers; each listed in NOTES.md and in `conftest.py`.
- **New**: recipe build and gate, one test per planted defect, one per detector (each story fires; nothing fires before its evidence
  in hindsight), DoA countersign end to end, internal note and simulated reply, waiting-on, INR formatting, owner shares, the
  no-customer-facts scan reading `recipes/hg` and `data/`, and a check that no person or vendor name from the review repo appears in
  the app (runs only where the review repo exists).
- **`make numbers`**: a new pandas oracle (`evals/hg_oracle.py`) reads `data/` directly, shares no code with the app, and the sweep
  compares every figure on Today, the case pages, Records and Insights. 0 mismatches is the bar at the end of every phase.
- **UI**: `check:ui` scripts re-pointed at HG routes; screenshots of each changed screen at 1440 and 390 every phase.

## 16. Phases and checkpoints

| Phase | Delivers | Ends with |
|---|---|---|
| 0 | reading, the :8000 walk, MAPPING, PLAN, NOTES | **STOP (now)** |
| 1 | §3 setup, generator, recipe, HG models, gate, Data page | summary + build green; **STOP** |
| 2 | §6 records and services, §7 detectors, Today, shell, Records, `Money.base`, search, numbers | tests, numbers, screenshots, report |
| 3 | §8 routes, §9 ledger / letters / approvals / DoA, inbox internal class, case page panels, code drafts (no key) | same |
| 4 | §10 agents and recordings, §11 Ask, §13 Insights, Import drift, §12 hindsight, Under the hood, phone pass | same |
| 5 | `docs/hg/DEMO.md`: a 10-minute walkthrough for the Head of SCM, three personas, one hindsight moment, screenshots | same |

**Status, 21 Oct 2026:** all six phases are built. Phases 0 and 1 stopped for review; on 21 Oct the user waived the remaining STOPs ("implement
all the phases of the plan, no review required"), so Phases 2-5 ran back to back, each ending with its checks. What changed from this plan,
and why, is in NOTES.md ("Phases 2-4" and "Phase 5").

## 17. Risks

1. **Size.** Phases 2–4 replace most of the domain layer and touch about 40 frontend files. The platform layer imports Halden modules in
   places (inbox, letters, approvers, annotate, search); each is re-pointed in Phase 2 with its tests, so the tree builds at every commit.
2. **The OpenAPI contract is hand-kept** and the UI's types are generated from it. Every new route is added to the YAML in the same
   commit as the route.
3. **Live recordings need a model** (Q4). The fallback is honest but less impressive: code-drafted runs, labelled.
4. **Real-data hygiene.** The review repo contains real names, real vendor names, HG's real domain and a OneDrive link. Only project,
   plant, material, unit and rate facts are taken; a test fails if a person or vendor name from it appears in the app.
5. **Messy layouts.** The generator must reproduce the multi-row headers faithfully enough that the recipe's parsing is a real test, not
   a round trip of a clean table. The parse logic follows the review repo's `parse.ts` rules (Material header row, project band, plant
   row, month row, Qty / Rate / Amount triplets).
6. **Item count.** One item per cause gives 27 items on 20 Oct, just above the brief's 15–25, after folding a vendor's slip under its
   late streak and unresolved names under the fund mismatch. Getting under 25 means dropping a story from Today (for example, the
   budget-rate unknown to the Estimates page only), which I would rather not do without your say (Q6).
7. **Hindsight.** Every export, sheet and tracker row needs a date the horizon step can cut on; a sheet's "built on" date decides
   whether it exists on a cut day at all.
8. **The `usd` → `base` rename** touches the verifier, evals and frontend; done in one pass, behind the number sweep.

## 18. Questions (defaults chosen; say if you want otherwise)

| # | Question | Default |
|---|---|---|
| Q1 | Fictional `hginfra.example` for internal mail, or HG's real domain? | fictional (D1) |
| Q2 | Add the five sources in D2? | yes |
| Q3 | Remove the Halden recipe and Halden-only packages from the HG tree (recoverable from `baseline`)? | yes (D3) |
| Q4 | Will a Claude login or `ANTHROPIC_API_KEY` be available on this machine for Phase 4 recordings? | if not, code-drafted runs, labelled |
| Q5 | The ten persona names in §4.2? | as listed |
| Q6 | 27 items on Today for the Head of SCM (every story and every tab), just above the 15–25 range? | yes; otherwise the budget-rate unknown and the renamed vendor move off Today (to Estimates and the Vendors list) |
