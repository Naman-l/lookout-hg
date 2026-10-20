# Live end-to-end runs of every workflow

The bench in [`report.md`](report.md) grades the agent on fixed cases. This page is the other half: the workflows run the way a buyer runs them, against a fresh database and the live model, with every figure in the answer checked by hand against the raw files in `data/`. Raw per-run records are in [`e2e/results.jsonl`](e2e/results.jsonl): one line per run with the run id, tool-call count, answer, cost, time, queue counts before and after, and the verifier's failures.

**How each row was tested.** Start from an empty database. Open the item as its buyer and click "Work this with the agent". Wait for the run to end, then read the page at 3, 10, 20 and 40 seconds without reloading. Compare every number, date and name in the answer with the order, supplier and quote files. A run passes only if the draft or decision is right *and* it is on screen without a reload.

## The runs

12 live runs, 2.31 USD in total, 33 to 70 seconds each. "To sign" is the count of drafts waiting in Approvals.

| Workflow | Buyer | Run | What the agent did | Figures against the data | Cost / time | Verdict |
|---|---|---|---|---|---|---|
| Undated orders | Marcus | run-5615d239 | 16 tool calls; five requests, one to each supplier with an undated line | all right | 0.13 USD / 39 s | **Pass.** Approve button on screen at 3 s; to sign 0 → 5 |
| Supplier fire, first request | Dana | run-15589ba4 | 10 calls; one request to the supplier contact for revised dates and allocation | "Four lines past due" is right (promised 26, 25, 28 August and 23 September; one more due today) | 0.16 USD / 47 s | **Pass.** 5 → 6 |
| Fire, rejected with a reason, then redrafted | Dana | run-fa89fc0e | new draft asks only what the reason asked: the October allocation for two parts and a date for one order line | right | 0.19 USD / 51 s | **Fail (checker).** The run was marked "did not pass" over a correct sentence: the checker tied a Tern figure (364) to the Porter. The draft was right |
| Past-due chase, first build | Marcus | run-fa5720cd | requests to two suppliers; a third line added to an open request for the same supplier (one open request per contact) | right | 0.22 USD / 36 s | **Partial.** 3 of 16 past-due lines were asked; the other 13 were only "passed to their buyers" in words |
| Consigned board | Marcus | run-3fd9bb2f | one request to the supplier's sales contact | right | 0.19 USD / 52 s | **Pass.** 8 → 9 |
| New duty | Priya | run-af28e961 | no draft; one named decision | the dollar figures were right; the answer said "eleven parts" where the item covers 17 | 0.13 USD / 33 s | **Fail (wrong count).** Not re-tested on a later build |
| Plant closure | Tom | run-de47eb2e | one request to the supplier | right (two lines 29 and 28 days late, one 1 day, two due in November) | 0.15 USD / 35 s | **Pass.** 9 → 10 |
| Price-rise hold | Tom | run-3ef1f3ee | request drafted | right | 0.26 USD / 55 s | **Fail (checker).** Marked "did not pass" for "the text says today is 15 October", from a delivery date |
| Past-due chase after the coverage fix | Marcus | run-f35b0f10 | 11 requests, one to each of the 11 suppliers with listed lines; one request names its 5 lines exactly | right | 0.23 USD / 55 s | **Pass** on coverage; to sign 0 → 11 |
| Price-rise hold on the open request | Tom | run-fed855f2 | amended the open request to add the price acknowledgement for two lines inside the lock window | right | 0.22 USD / 70 s | **Fail (checker).** Marked "did not pass" for "deliveries to 15 December". The answer is right |
| Past-due chase, final build | Tom | run-c0b1fde2 | 11 requests, one per supplier; each draft is owned and signed by the buyer of its lines (Tom 4, Marcus 3, Priya 2, Dana 2) | right | 0.23 USD / 55 s | **Pass** |
| Price-rise hold, final build | Tom | run-79373234 | the ask was added to the chase's draft, so there is no duplicate; the 5 open lines, the 721 units still owed and both dates after 15 October match the order data | right | 0.20 USD / 49 s | **Pass.** Passes its checks |

Three of the 12 runs ended "did not pass" in the checker, and in all three the answer was correct: the checker misread a sentence. That is a checker problem counted against the evaluation, not hidden: the item page now says when a run did not pass and why, instead of dropping the checks block.

## The automations

| Flow | What happened | Verdict |
|---|---|---|
| Morning run on a fresh start | 5 items worked without a click, 5 requests to the contacts on file, 0.91 USD, 4 min 18 s; every result shows on Today and on its item on load | Pass. One wrong count ("three past due" for four) was fixed on a later build |
| Payment-change mail from a look-alike domain | Blocked in code before any model read it. The note says what not to do (do not pay, do not change the vendor record), the one safe step (confirm by phone with the contact on file) and who to tell. No draft to the sender, 0 USD | Pass |
| Spot offer with an instruction aimed at the AI | Blocked in code. "Do not order: the open order already covers the part". The embedded instruction was ignored. $38.50 against a last price of $2.85 (13.5 times) is right | Pass |
| Bank-details rename from a new sender | The triage flags the new address and says to verify by phone first, but says the mail "names no part numbers" while 11 quoted parts are on file, so it misses the duty consequence | Partial |
| Quote from a new, unvetted sender | First build: "the quote could not be read". Later build: "Not a safe October alternative yet: the supplier is unvetted and its 60-day lead time starts after PPAP approval". The reply is held until the sender is vetted; no clerk, no draft | Fail, then pass |
| Import: seven question cards | Accept all, preview, approve and load. Supplier records resolved by contact domain; 3,590 rows in, 7 exact duplicates removed, 3,583 out; 35 of 35 checks | Pass |
| Import page reopened after loading | At first all seven cards showed unanswered. Later build: answers persist across reloads | Fail, then pass |
| Import: the same rows with renamed columns and day-first dates | The steward saw the order lines, the date format and five unit spellings but compared the file with the wrong export, so nothing was proposed | Fail: it describes the file but does not solve it. Open |

## Follow-ups and the Ask box

| Test | Result |
|---|---|
| "Which of those will owe the new duty?" after the duty item | The three Yunzhan motors that owe the 25% duty from 1 November are named with the right dollar figures; restart on 3 November. Pass |
| Ask about the unvetted quote | "Not a safe October alternative yet", as above. Pass |
| Compare quotes for the HR-50110 battery pack | No stray "Shenzhen" origin; $1,444.01 landed against Penang $1,530.65 if ruled China; Penang available from 1 February 2027. Pass |

## Signing and the screen

- Another buyer cannot sign your draft: the server returns 403 on approve, reject and edit of someone else's draft; the screen shows no Approve button on it. Pass.
- The Approvals page once judged "yours" by the item's owners, so one buyer saw all 11 chase drafts under "To sign". Found and fixed in the same round.
- No dead control on 17 screens at 1512 and 390 pixels wide (460 and 423 controls). No sideways scroll at 390.

## Still open at the time of writing

- One no-key draft shows no owner in the list although the server enforces the right buyer.
- The README states who signs in two places and the two lines disagree.
- The no-key run list shows the recorded durations (43 to 55 s) for replays.
- The renamed-columns import (above) is described but not mapped.
- The checker should accept "by <date>" and "deliveries to <date>" without reading them as a claim about today.
