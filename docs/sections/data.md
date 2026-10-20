# The data: what Halden's files held and what the build did about it

`make build-data` replays `recipes/halden/steps/` over `data/` and writes `backend/lookout.db`. Nothing in `data/` is edited; every
step is a script whose docstring names the defect, the rule and the consequence; every raw row is kept in a `raw_*` table, and a
cleaned column that changed a value keeps the source value beside it in `<field>_raw`. The load gate stops the build if a raw row is
neither kept nor dropped with a reason, a raw value was lost, an inferred value is unlabelled, an alias was merged, or a reference does
not resolve without a counted issue. The Data screen lists every defect with its count, handling and owner.

The files in one paragraph: 71 supplier records for 60 companies (ten legacy ids copied into the new ERP, one rename); 502 parts with
origin in 33 spellings, five HTS formats and one letter O; 359 BOM rows with one repeat, one unit mismatch, one orphan and one obsolete
part still in use; 2,622 PO lines from two ERPs (6 exact repeats, 3 returns, 78 short closes, 9 blank currencies, ten spellings of five
units, KPCS priced per thousand, three orders open for over a year); a 36-row forecast that names robots, not part numbers; 15 messages
that move dates and prices and two that must not be believed; three PDFs; a tariff advisory; 23 news items.

What the data cannot answer, and the build says so: on-hand stock, safety stock, freight, the pack size of a BOX, and the origin of
22 parts. Each is an `Unknown` with an owner, never a zero.

## Importing again, with a person in the loop
`GET /api/imports/questions` returns a short deck (seven cards) built from the recipe's own decisions: link ten legacy supplier ids, link the BCX rename, infer
nine blank currencies, leave five origins unknown, drop six repeated rows, link three possible duplicate parts, and ask for a stock count (`PART=QTY` pairs; the ERP export has no on-hand data, so without a count a part with nothing on order is unknown). Each card has the entries it covers,
up to three examples and a proposed answer; one answer settles every entry. `POST /api/imports/answers` accepts, changes or skips (answers wait in
`lookout.db.pending`); `GET /api/imports/dry-run` runs the recipe on a copy with those answers and returns rows in and out per file and every
load-gate check; `POST /api/imports/approve` refuses (409) if the answers changed since that dry run, otherwise writes them into the recipe
(`recipes/halden/decisions.yaml`, with who answered, when and who approved) and rebuilds the database, so `make build-data` gives the same result
afterwards. A model is not involved: the Data steward asks the same questions for files nobody has seen, and runs the steps it writes in
`app.domain.imports.sandbox` (an allowlist, a separate process, no network, writes only to scratch, CPU and time limits).
