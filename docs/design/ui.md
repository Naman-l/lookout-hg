# UI: the buyer's workspace

A React + TypeScript app (Vite, React Router, `fetch`; no UI kit, no state library) that a direct-materials
buyer opens and reads like their own ERP: what needs them, what the agent found and why, what waits for their
signature. `npm run build` writes `frontend/dist`; FastAPI serves it with the API on one port (`make run`).
Types come from `api/openapi.yaml` (`npm run types`); the client always reads the real API (no fixture mode).

## The main path
Four places: **Today · Approvals · Inbox · Records** (Suppliers, Parts and BOM, Orders, Forecast, Data). A quiet
footer holds Data issues, Agent runs and the Design system. First open asks "Who are you?" (the buyers table,
`/api/people`; remembered on this computer, no sign-in); every run, approval and answer is signed with that name.

## Rules every screen follows
- **Tokens only** (`src/tokens.css`; `npm run check:ds` fails a raw colour, size or radius). Inter for words, mono for numbers.
- **One look per thing** (table below), the same on every screen, named as the backend and the agent name it.
- **Names before numbers**: a part shows its name, then its number small; a PO line reads "PO 450/10".
- **Unknown is a word** ("unknown · ask Dana"), never 0 or a dash. Every figure opens its source (`Value`).
- **Sections by space, type and one soft tone**, not rules. **One action band per screen**, under the title.
- **Nothing on screen may lie**: a check strip prints only what the run reports (`checkFacts`).
- **No keyboard shortcut sends anything.** A draft whose run failed a check stays off until the buyer ticks it.

## One look per thing
| Thing | Component | Where |
|---|---|---|
| Person (buyer) | `Owners`, `WhoAreYou` (avatar + name; you ink, others grey) | Today, header, Approvals |
| Company (supplier, sender) | `CompanyRef`, `SupplierRef` (name + trust dot) | Inbox, item, drafts |
| Part | `PartRef` (name, number small after) | everywhere; number alone only on Records |
| PO line / build / message | `PoLineRef`, `BuildRef`, `MessageChip` | lines, drafts, item meta |
| Money, quantity, date, unknown | `Value` (`Money`, `Quantity`, `DateDue`, `UnknownValue`) | tiles, tables |
| Where it stands | `StageTrack` (full), `StageMini`, `HeldPill`, `AskingPill` | item, draft, Today rows |
| A decision to take | `Flashcard` (What · From · Value · Changes · the decision) | Inbox, Import |
| The one place to act | `.ds-act` band (`ActionBand` on the item) | Today, item, draft, Inbox |
| A message / the email | `.mail` paper (`Draft`); held ones carry a red edge | Approvals, Inbox |
| The agent's work | `RunPanel` (working), `RunFold` (finished), `RunTrace` | item, run page |
| Ask | `AskBox` (box at the foot), `AskPanel` (answer; sheet on a phone) | every page |

## Desktop → phone (760 px; lists go single-pane under 1024 px)
| Screen | Desktop | Phone |
|---|---|---|
| Header | breadcrumb, "You are …", data date | one 52 px row: Lookout, "data Sep 25", avatar + name ▾ |
| Navigation | sidebar of four, quiet footer | tab bar: Today, Approvals, Inbox, Ask, More |
| Today | table: item, owner, stake, act by, stage | title and next step full width; stake and date beneath |
| Item | work left, answer opened to 3 sentences, options in four columns | one column, same order, options stacked |
| Stage track | seven slots, current named with who has the move | seven slots, current named, "Now: …" line beneath |
| Approvals, Inbox | list left, the open thing right | list first; the thing full screen with a way back |
| Ask | labelled box at the foot; answer opens as a right panel | the Ask tab opens the sheet; no second box |
| Action band | text left, buttons right | text above, buttons full width |

## AI surfaces (one design: a bounded panel with the Lookout mark)
**Ask**: collapsed (the box, "About: …"), open (You asked → the answer as a record → follow-up; earlier questions fold
to one line), closed (Close or Esc). **Run** ("Ask the agent again"): working in place (steps ticking with their *why*,
the current one spinning), then folded to one line ("How the agent got here · N steps") that opens to every step and
the Reviewer's named misses. Nothing is sent from either.

## How it is checked
`npm run typecheck`, `build`, then `check:ui` against a running app on a fresh database (no key): `check:ds`
(tokens), `check:scroll` (no sideways scroll at 360/390/768/1440), `check:keys` (focus, Tab, Enter),
`check:consistency` (one look), `check:buyer` (the picker, plain pages, true strips, one-row phone header, no key
approves, no second Ask, the Ask box never covers a last line) and the stream unit tests. Each PR is also driven at
1440 and 390.

## Not done (said plainly)
An Edit-draft control; a Stop button on a run (no endpoint); dark mode; charts; draft ownership from the API
(the UI reads it from the item, and the API itself still lets any buyer sign); a bid tab for quote comparison.
