# The HG dummy dataset

H.G. Infra's SCM department as of **20 Oct 2026** (records from Nov 2025; look-ahead to Mar 2027). Written by `make data`
(`dummy_data/generate_hg.py`, fixed seed: byte-identical on every run) and read only by the recipe (`make build-data`, `recipes/hg/`).
Project names, verticals, materials, units and sheet layouts are HG's; plant codes and SAP plant names are HG's own, from its MB51 exports
(FY25-26 and FY26-27); the SCM team (names, designations, reporting lines and desks) is HG's own, from the SCM organogram the user supplied on
21 Oct 2026. Every other person, and every vendor, amount and mail, is invented, as are the team's purchasing groups, SAP users and DoA limits.

## Files

| File | Rows | | File | Rows |
|---|---:|---|---|---:|
| sap/ME5A_purchase_requisitions.csv | 2,051 | | sheets/RFQ CS Tracker (19.10.26).csv | 2,117 |
| sap/ME2N_purchase_orders.csv | 1,807 | | sheets/Expediting Tracker (17.10.26).csv | 26 |
| sap/MB51_goods_receipts.csv | 5,944 | | sheets/LC BG Tracker (16.10.26).csv | 35 |
| sap/FBL1N_vendor_line_items.csv | 3,188 | | sheets/Payment Projection Oct-26 (14.10.26).csv | 43 |
| sap/vendor_master.csv | 89 | | sheets/SCM Fund Requirement Oct / Nov / Dec-26 | 34 / 28 / 28 |
| sap/material_master.csv | 101 | | sheets/Roads Major Material Requirement Oct-Dec 26 | 142 |
| sap/purchasing_groups.csv | 22 | | sheets/Railway Material Quantity Summary Q3 | 62 |
| sheets/Project Directory.csv | 30 | | sheets/Look Ahead Long Lead Items (15.10.26).csv | 20 |
| sheets/SCM Material Organogram.csv | 17 lines | | | |
| sheets/Vendor Library (03.10.26).csv | 351 | | sheets/PR PO TAT Report Aug-Sep 26 (03.10.26).csv | 13 |
| sheets/budget_rates.csv | 175 | | sheets/doa.csv | 9 |
| external/commodity_index.csv | 171 | | inbox/*.eml | 23 |

Records: 584 PRs (2,051 lines), 1,266 POs (1,807 lines), 5,838 goods receipts before 88 reversals and returns, 2,117 quotes in the CS tracker.
SAP exports carry their stamp line (`ME2N - … | Exported 20.10.2026 08:15:09 | User …`) and dd.mm.yyyy dates; the hand-built sheets keep
their real layouts (Qty/Rate/Amount triplets, ₹ Cr fund heads by project with subtotal bands, title rows).

## Projects (30)

| Vertical | Projects (SAP plant) |
|---|---|
| Roads | Tumkur (1138), JH-10 (1142), JH-13 (1143), JEC (1147), Tirupati (1148), Ayodhya (1151), Narol (1152), Pune-Shirur (none yet), KD-01 (1131), KD-02 (1132), AP-01 (1133), Karnal (1141), GEW-05 (1145) |
| Railway | RVNL (1902), Kanpur (1903), Dhule (1904), Aurangabad (1905), Gaya (1906), NDLS (1907), Thane (2002), Anuppur (1908), DLF (1153) |
| BESS | Banaskantha (2109), Dholera (2110), BESS Chorniya (none yet) |
| Solar | Bikaner (2104), Jodhpur (2108) |
| T&D | TBCB Angul (2501), UPPTCL Mirzapur-Chunar (none yet), Jamshedpur 400 kV (none yet) |

Each plant code and its SAP name ("Neelmangala-Tumkur", "GAYA-SON NAGAR-RVNL", "NVVN1/BESS-01 185 MW") is as HG's MB51 exports print it, the
FY26-27 export first. Four projects are in neither export, which ends in May 2026 (Pune-Shirur shows by name in the review repo's September MB51 pivot, but
no file here gives its code): the directory leaves their plant blank, they have no PRs, POs or
receipts, and the Data page lists them (`projects.no_sap_plant`); their fund lines, look-ahead items and mail stand. Two matches rest on public
sources rather than the export: 2109 ("NVVN1/BESS-01 185 MW") is Banaskantha, the NVVN award held by HG's Banaskantha BESS company; 2501
("TRANSMISSION PROJECT (ERGS-I)") is the Angul-Sundargarh 765 kV line. Dholera is taken to be 2110 ("GUVNL/BESS/PHASE-IV 250 MW"), the other
BESS plant in the export; no public source names its site. DLF is a highway plant in SAP; SCM plans it with the railway jobs, as the railway
sheet does. The head-office plant is 1001 (HO Jaipur).

## The SCM team (HG's organogram)

`sheets/SCM Material Organogram.csv` is HG's "SCM Material Org" sheet (tab "Dept. Organogram"), copied as it was supplied
(`dummy_data/hg_organogram.csv`), typing errors included ("Tumur", "Slop protection", "GGSB"). Step 04 reads its layout: the head under the
title, one lead per column block, each numbered cell under a lead with the desk label beside it carried down the merged rows, and "(TBF)" as an
open post. Its own "Total Employee" (24) is checked against the people it names under the head. The recipe's answers add what the sheet does not
say: purchasing groups, verticals, SAP user, DoA limit, and the department-wide duties (a vertical's decisions, the vendor library, rate spreads,
the MIS sheets).

| Team | People (designation; SAP purchasing group) | Signs up to |
|---|---|---|
| Head of SCM | **Satish Kumar Sharma** (Sr. Vice President - SCM; H00): countersigns every commitment above ₹5 Cr, per the DoA, and sees every Team page | no limit |
| Shree Dutt Anand (GM - SCM; P00, mechanical spares) | Mohan Bahadur (Manager; P01 bitumen), Sudeep Singh (AM; M01 MIS), Harish Kumar (DM; P02 HSD and retail), Lokesh Yadav (Supervisor) | GM ₹5 Cr |
| Varun Joshi (GM - SCM; A00, aggregate at sites the sheet names for nobody) | Jitender Swami (AM; A01 aggregate: Dhule, Aurangabad, Gaya, Tumkur, JH-10, JH-13), Neeraj (Sr. Exc.; A02 aggregate: GEW-05, NDLS, Anuppur, Thane), Govind Gupta (AM; C01 cement, fly ash, GGBS, admixture), Ishan Derashri (DM; E01 bearings, expansion joints, HT strand, crash barrier, geosynthetics), Ankesh Jha (Sr. Engg.; E02 hume pipe and engineering items), Jitendra Shekhawat (Manager; G01), Kanhaiya Khoda (Exc.; G02), Jagdish Vyas (AM; X01 logistics, crane hire), Rajesh (Sr. Exc.), open post: Sr. Manager / Manager (Logistics) - International | GM ₹5 Cr |
| Sambhav Kumar (GM - SCM; T01, switchgear and T&D) | Rohit Jain (AM; L01 railway S&T), Vishnu Mudgal (AM; L03 OHE, BESS, solar inverters, TBCB lines), Deepanshu Jain (Sr. Engg.; L02 P-Way, cables, transformers), Harigraraj D (MT; N01 solar), open posts: AM/DM (SCM) - T&D and AM/DM (SCM) - BESS | GM ₹5 Cr |
| Urvik Patel (AGM - SCM; U01, solar structure and BESS containers) | Shubham Sharma (AM; S01 TMT and structural steel), Ankit Solanki (Jr. Exc.) | AGM ₹5 Cr |
| Gautam Jha (Manager - SCM; W01, site services NOA) | no team on the sheet | ₹1 Cr |

Managers, DMs and AMs sign to ₹1 Cr; Sr. Engg., Sr. Exc., Exc. and MT to ₹25 L; MIS, accounts and the supervisor sign nothing. Duties: Varun Joshi
holds roads' decisions, the vendor library and cross-project rate spreads; Sambhav Kumar holds railway, BESS, solar and T&D; Sudeep Singh the MIS
sheets. A purchasing group is a desk, as the organogram splits the work: the generator assigns each PR and PO line's group by its material (and,
for aggregate, its site), after the flows have drawn every document, so every document number and amount is the same as with the first, invented
cast. A PR document can carry lines of several desks (SAP's purchasing group is per PR item); a PO's group is that of its largest line.

## Stories and where each is planted

| Story | Planted in |
|---|---|
| Late cable PR | ME5A PR 1000204034 (Kanpur, 18 km signalling cable, raised 13 Oct, needed 3 Nov, material lead 70 days); 3 quotes in the CS tracker; planner's mail 13 Oct |
| PRs cancelled after the RFQ | ME5A: 32 Gaya lines in 3 PRs deleted 15 Oct; CS tracker: RFQ out 29 Sep–3 Oct, 18 lines quoted by 4 vendors (≈ ₹3.43 Cr enquiry); two mails 14 Oct |
| MFC vs PO validity | ME2N PO 4500120768 (Aurangabad, 2 traction transformers, ₹16.2 Cr, firm, valid to 31 Oct); expediting: MFC asked 20 Aug, not issued; vendor mail 15 Oct: MFC by 25 Oct or +₹1.4 Cr. Visible already on a 1 Sep rebuild |
| Inspection before the site is ready | PO 4500121346 (Gaya TSS transformer): inspection 28 Oct, 15 days' free storage then ₹18,000/day; tracker: plinth 15 Dec |
| PV claim on the wrong base | PO 4500121087 (Angul ACSR Zebra, IEEMA base Jan 2026); vendor claims ₹52,94,689 on a Dec 2025 base; on the PO's base it is ₹43,56,293 |
| Price notice | TMT +₹2,500/MT from 1 Nov (orders acknowledged by 31 Oct keep the old rate); mail 16 Oct |
| Quote lapsing, with a PV formula | 220 kV GIS for BESS Chorniya, ₹9.65 Cr per lot, valid 30 days (to 7 Nov), only in mail; a ₹10.2 Cr/lot quote in the tracker |
| L1 above the last price | Tumkur aggregate quotes ₹720 / 745 / 760 per MT (mail only) against the last PO ₹650 and the budget ₹690 |
| Two frauds and an injection | Bank-detail change from a look-alike of a steel vendor's domain with a free-mail reply-to (₹42,49,224); "urgent transfer" of ₹2.75 Cr from a look-alike of the company's own domain; a cement spot offer from a stranger with text aimed at automated systems |
| Renamed vendor | Vendor master: old code 100231 and new code 100512 (created 10 Sep, new GSTIN); open lines on the old code; mail 2 Oct |
| LC deadline / ABG expiry | PO 4500123578 (Dholera, 48 BESS containers, ₹320 Cr) LC by 30 Oct, pending with Finance; ABG ₹2.64 Cr on PO 4500120419 expires 31 Oct, IDT not delivered |
| Work order cable failed QA | WO 4500122442 (Kanpur, contractor-supplied cable received Aug–Sep); QA mail 14 Oct |
| Supply stops | Jharkhand quarries closed from 25 Oct for 30 days (JH-10, JH-13 aggregate, GSB, dust); Gujarat transporters' strike from 22 Oct (Narol, Dholera, Banaskantha) |
| Warranty before commissioning | Kanpur DG set (PO 4500087611, older than the ME2N export) supplied May 2025, warranty ends 12 Nov; extension ₹15 L; mail 6 Oct |
| Fund vs requirement | Nov fund sheet disagrees with the Q3 requirement for Gaya, Aurangabad, Narol and JH-13; Pune-Shirur funded with no requirement; Finance mail 17 Oct |
| Schedules slipping | Gaya OHE masts 6 → 20 Nov (needed 12 Nov); a rail-fittings vendor's last 4 receipts late (+6 to +14 days) after six on time, its line due 19 Oct not yet received, and Dhule ERC/GRSP moved into December |
| PR waiting on Projects | Aurangabad IPS PR released 18 Sep, RFQ 22 Sep, technical spec awaited from Projects since 27 Sep; vendor chases 19 Oct |
| Long-lead PV items not ordered | Look-ahead: UPPTCL Mirzapur-Chunar transformers, towers, conductor awaiting funding while IEEMA and LME rise |
| Rate spread | Aggregate 10 mm on POs from ₹500 (Anuppur) to ₹1,550 (Gaya) per MT |

## An export the recipe has not seen

`data/incoming/ME2N_site_office_Oct26.csv` (39 rows) is the railway site office's own ME2N download for September and October: columns renamed
("PO Number", "Qty Ordered", "Rate (Rs.)", "Site"), slash dates, digit-group commas, and the plant written as the site's name, one of them as
"Arurangabad". The build never reads it; on Import the Data steward reads it, maps it to ME2N, and asks a person before anything links or loads.

## Defects planted (all listed on the Data page)

| Defect | Data issue | Count | Handling |
|---|---|---:|---|
| The same project under other names | projects.name_variants / projects.unresolved_names | 22 / 6 | link / leave |
| ₹, lakh and crore in one sheet | fund.mixed_units / projection.mixed_units | 3 / 2 | fix |
| Cement in bags and tonnes | po.cement_bags_and_tonnes | 59 (30 PO + 29 PR lines) | fix |
| One vendor under two codes | vendors.two_codes | 1 | link |
| PRs with no project | prs.no_project | 14 | leave |
| POs with no PR | po.no_pr | 25 | flag |
| PR keyed in on the PO's day | prs.same_day_po | 39 | flag |
| TAT 0 meaning "none closed" | tat.zero_means_none | 6 | fix |
| MB51 exported twice | mb51.duplicate_rows | 18 | drop |
| Reversals and returns | mb51.reversals | 88 | fix |
| Price per 1,000 pieces | po.price_per_1000 | 16 | fix |
| Fund vs requirement | fund.disagrees_with_requirement | 8 | flag |
| Stale sources | sources.stale | 3 | flag |
| A project with no SAP plant yet | projects.no_sap_plant | 4 | leave |
| Posts the organogram marks TBF | team.open_posts | 3 | leave |
| Also found | library.not_in_sap 322, library.ordered_outside 10, requirements.sheet_errors 21, budget.missing_rates 7, cs.rfq_before_pr 20, expediting.po_not_in_export 1, inbox.held 3, inbox.unknown_senders 1, quotes.only_in_mail 5, inbox.facts_in_prose 73 | | |

Build: 27 data issues, 18 rows dropped with a reason, 78 of 78 load checks passed. `AS_OF=2026-09-01 make build-data` rebuilds the same
world as of 1 Sep (sheets built later not read, trackers cut row by row, 2,269 rows dropped with a reason, 73 checks passed).
