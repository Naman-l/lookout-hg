# The data layer in two minutes

For a founder or a buyer. The full reference for engineers is [domain.md](domain.md).

## What it is

One SQLite file, rebuilt from Halden's raw exports by a recipe of 26 small scripts, with no model and no key. Every number in it says
where it came from; everything the data cannot say is an **unknown with a name next to it**, never a zero. Python computes every sum; the
agent and the screens only read what it computed.

## The records, one meaning each

| Record | What it is | Today |
|---|---|---|
| Company, and its records | a supplier and the ERP ids it appears under: **linked, never merged** | 60 companies, 71 records |
| Part | bought, built in-house, or a finished robot; origin and tariff code as the master says, blank stays unknown | 502 |
| Bill of materials | how many of a child go into a parent; one sub-assembly sits in all three robots | 358 lines |
| PO line | ordered, promised and received are three dates; money converted at the order month's rate, the ERP's text kept beside | 2,616 |
| Offer | one price, with the conditions that come with it; read from a quote by a record that cites its line | 51 |
| Message | trust decided in code from the sender and the words, before anyone reads it | 15 |
| Event, deadline | what happened and what lapses, written down once with source, supplier and owner | 22 events, 12 deadlines |
| Tariff rule | prefix, rate, date, in-transit window, read from the notice | 8 rules, 2 exclusions |
| Buyer | owns parts by category, so owns the questions about them | 5 |
| Consigned material | Halden's own material at a contract manufacturer, linked to the part it becomes there | 1 |
| Data issue | a defect the build found: count, how it was handled, who owns it | 56 |

## How it is built, and why you can trust it

- **Raw beside clean.** Where a value changed, the source value stays next to it. Any figure traces to its row or its line.
- **One script per defect**, each saying the defect, the rule and the consequence if ignored. The replay stops at a **load gate** (35 checks):
  a raw row neither kept nor dropped with a reason, a lost value, an unlabelled guess, a merged record, or a broken reference fails the build.
- **Quotes are read by records, checked in code.** Each offer is a line in `recipes/halden/extractions/` that cites the exact line of the
  email or PDF; every build checks the price is on that line next to its part. A model can propose records (`python -m
  app.domain.imports.extract`); they are not used until a person has reviewed them.
- **Nothing is typed from this month.** The data date comes from the recipe (or `LOOKOUT_AS_OF`), owners from the buyers table, names from
  the master. A test scans the code for the customer's names, ids, dates and amounts; another rebuilds from **changed data** (a renamed
  supplier, a different fraud, a sixth buyer, a later date) and checks every detector fires on the new values.

## The rules that decide a number

- **Past due**: still not received after the promised date; a line promised on the data date is not yet past due.
- **Open**: ordered and not fully received. A line ordered over a year ago and still open is *probably closed*: left out of supply, raised as a question.
- **The new duty**, in three buckets, each with one sentence of rule: **owed** (25% of the price of China-origin parts that will enter on or
  after Nov 1: $1.43M, the need not yet on order, open orders due after Nov 30 and the burned plant's orders that cannot ship before Nov 1), **conditional** ($0.10M on open orders that owe nothing if
  shipped before Nov 1 and entered before Dec 1: the ship date is unknown) and **if China** ($0.11M on five parts whose origin is unknown).
  The headline is owed; the others sit beside it, never added in.
- **Trust**: a look-alike sender, a free-mail reply-to, a change of bank details, or an instruction aimed at software **blocks** a message.
  Nothing follows from it, whatever it says.

## What it will not guess

Stock on hand (there is no stock file), freight, the origin of 22 parts and the tariff code of 44, the pack size of parts bought by the box,
the promised date of five open orders (one of them $470K), when a late order will actually ship, and what a customs broker will rule about a
part made in one country from another's materials. Each is an unknown with an owner and the question to ask.

## Limits, said plainly

- Money is stored as a float and rounded to cents on the way out; fine for this size, not for a ledger.
- SQLite has one writer and the tables have only their primary keys; the recipe holds the tables in memory. At 1,000 times the data the
  first changes are a database server, indexes on part, supplier and status, and an incremental build.
- The recipe is Halden's. A different customer's export needs its own recipe; the Data steward drafts the steps, but a person approves them.
- A model-proposed quote record is checked for its price and its supplier's name, not for every condition: a person reads it before it counts.

## Where to look

`recipes/halden/` (steps, answers, extractions) · `backend/app/domain/<thing>/` (model, service, API, tools, `glossary.md`) ·
the Data screen (every defect). Each `glossary.md` is what a thing means, and is the text the agent is given.
