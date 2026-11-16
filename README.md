# Lookout for HG Infra

**Lookout tells H.G. Infra's supply-chain team what will cost money or stop a work front if nobody acts, and drafts what to do about it.**

A concept built on dummy data: the SCM department as of **20 Oct 2026**. Project names, plant codes, verticals, materials, units and sheet
layouts are HG's own; every person, vendor, amount and mail is invented. The Head of SCM, the GM, the vertical leads, the buyers and MIS each
see their own work.

**What it is.**

1. **A system of record.** HG's SAP exports (ME5A, ME2N, MB51, FBL1N, the vendor and material masters), the hand-built sheets (the 3-month material
   requirement, the fund requirement, the payment projection, the long-lead look-ahead, the vendor library), the trackers (RFQ/CS, expediting,
   LC/BG, the MIS turnaround report) and the SCM inbox, rebuilt by a recipe in code into one linked database. No model builds it; every figure
   traces to its source row. 26 defects found in the files are listed on the Data page with what was done about each.
2. **Today.** Twenty-one detectors in code raise one case per cause (27 on 20 Oct): requirement, after-PO, price, payments, vendor risk, held mail,
   and what nobody knows yet. Each has its ₹ at stake with the rule behind it, its act-by date, its owners, whose move it is (SCM, Projects,
   Finance, QA, Vendor, Management) and the work fronts that stop if nothing is done.
3. **A person decides, and signs.** Each kind of case has a code table of routes. The owner chooses; the draft follows: a letter to the vendor's
   contact on file or a note to the person on file who owns the function, in HG's house style. The owner signs the exact text; above the
   delegation-of-authority threshold the Head of SCM countersigns the same text before anything goes out (simulated).
4. **Insights** (Team, Projects, Pricing, Estimates, a Daily brief per person), read-only, every figure linked to its rows. Team measures where work
   waited and on whom, never people against each other.

**No model is connected on this machine.** Runs are drafted by code (labelled "drafted by code, no model"), two runs are replays of mocked
recordings (written by hand, labelled as mocked), and Ask answers from the records by rule. See `docs/hg/NOTES.md`.

## Run it

Python 3.12+ and Node 20+ (this Mac: `make` picks `python3.14`).

```
make setup        # venv, npm install, writes data/ if missing, builds backend/lookout.db
make run          # http://127.0.0.1:8001 (the original Halden app stays on :8000 from ~/Downloads/lookout-main)
```

Choose who you are (any of the ten SCM members); Today opens on your own cases.

| Command | What it does |
|---|---|
| `make data` | write the dummy dataset into `data/` (fixed seed: byte-identical every run) |
| `make build-data` | rebuild the database from `data/` by the recipe (`AS_OF=2026-09-01` rebuilds the world as it stood that day) |
| `make demo-state` | reset the demo database (no drafts, no runs); `make run` then works every case by code and replays the recordings |
| `make simulate-replies` | demo only: a marked simulated reply to every letter or note that went out |
| `make test` | backend tests, including the HG behaviour tests in `backend/tests/hg` |
| `make numbers` | the figures on the Data page, Today, Records (vendors) and Insights against an independent pandas oracle over `data/` (needs `make run`) |
| `make hindsight` | the records rebuilt on 1 Sep, 1 Oct, 14 Oct and 20 Oct: each case appears the day its evidence arrives |
| `make then` | serve the records as they stood on 1 Sep on :8002, beside today's (`THEN=` another date) |
| `make scenarios` | the MFC case signed and countersigned, the cement injection and the bank-change fraud held, through the API on a copy |
| `make check-ui` | design tokens, no sideways scroll at 390 and 1440 px, keyboard, consistent counts, plain words (needs `make run`) |

## Where to read more

- [`docs/hg/DEMO.md`](docs/hg/DEMO.md): a 10-minute walkthrough for the Head of SCM.
- [`docs/hg/PLAN.md`](docs/hg/PLAN.md): the plan (data, detectors, routes, ledger, agents, Insights) and [`docs/hg/MAPPING.md`](docs/hg/MAPPING.md): every
  Lookout feature and what it became for HG.
- [`docs/hg/DATA.md`](docs/hg/DATA.md): the dataset, the stories planted in it and the defects.
- [`docs/hg/NOTES.md`](docs/hg/NOTES.md): every deviation from the plan, every removed piece with its reason, and the checks at each phase.

The code is the original Lookout platform (records with provenance, the load gate, trust rules for mail, the approval ledger, the case page) with
its customer layer replaced. The previous customer's README, recipe and code are in the `baseline` commit.
