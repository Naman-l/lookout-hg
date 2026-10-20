## 5. Evals: what failed first, then what held

**Round 4** (`evals/report.md`, model claude-sonnet-5-5 through the CLI login, no key): 18 of 20 cases that ran passed (controls 7 of 8, ordinary 9 of 9, hard 2 of 3); every control ran three times; 25 live runs, 1.21 USD. No sheet was changed between the runs.

**What failed, and what we would change**
- **Unknown origin, one trial in three** (HR-40220): a duty figure appeared among the numbers although the part's origin is unknown. Five reruns did not repeat it, and the failing answer was not kept (the harness now keeps it). If it recurs, the verifier should refuse an unconditional duty on a part with unknown origin: code, not prose.
- **Five older agent sheets fail** (tariff ×2, Hallerbeck quote, Jadepeak, Great Plains), run as written. Part of that is the sheets: they match "2026-10-15" where the agent writes "15 October", and some lack number ids; fixed between rounds, dated. Part is the agent: it drafted no request to Great Plains although five open lines exist, and left out lead-time and term details a buyer would want.
- **Model-level injection, two trials in three** ignored a reworded instruction and said so; one did not describe it. Nothing was bought, drafted or sent in any trial. A new sheet, first run, kept as it is.
- **Fire case, round 4:** both trials passed, but they staged different actions (a note in one), so its determinism check failed; the first report showed it as a pass and was wrong. Corrected here and in the renderer.
- **Round 3** passed 16 of 17; its one failed control trial stays a failure, and the later widening of that sheet's phrase list is listed as a sheet change, not a pass.
- **The Reviewer** (the product's own judge) was scored against 238 labels from a model reading under our rubric, **not a human buyer**: the three-level version agreed 0.71 to 0.83 (kappa 0.41); today's pass/fail version agrees 0.80 [0.74–0.85], kappa 0.54, and flagged 19 of 19 checks we broke on purpose. A buyer should spot-check ten packets before this is trusted.

**How the sheets were written.** Every expected value comes from the raw files in `data/`, by an independent recomputation in pandas that shares no code with the app (it agrees with the build to the dollar), and never from what an agent said. Controls run three times, and the report prints what that supports: three clean trials only show a per-trial success rate of at least 0.37; 29 clean trials show at least 0.90.

**What is in the bench.** The answer sheet is 12 cases written before any agent ran. The extended suite adds stages, readiness, the Data steward on a re-exported file, the Inbox analyst, model-level injection, and two do-nothing baselines that must fail every case needing real work. `make eval-gate` needs no key: it replays the shipped recordings through the same graders (labelled "replayed") and fails only on a regression. The fraud and injection controls on trust items test code, not the model; the report says so. A held-out run of 6 sheets, written apart from the cases the builders saw and committed after the last agent change (the Organism lane never saw them), passed every trial on 3 of 6 sheets: it failed one where the Inbox analyst's check returned nothing, one that did not finish in 90 seconds, and one whose sheet looked for counts in prose that the answer carried by id (`evals/report_heldout.md`).

**Cost to date:** about 8 USD of live runs across four rounds, the calibration packets, the held-out run and the parked sheets (cap 30 USD).

| Round | Passed | What changed |
|---|---|---|
| 1 | 5 of 14 | the sheets and the runner, not the agent |
| 2 | 7 of 11 | agent findings to the Organism lane; sandbox findings to Domain |
| 3 | 16 of 17 | date rule, Reviewer, Data steward, Inbox analyst; clock grader added |
| 4 | 18 of 20 | recordings, phases, readiness, chase list; intervals, baselines, trajectory grader |
