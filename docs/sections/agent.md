# The agent: Lookout, its specialists, tools, prompts and control flow

**What it is.** One orchestrator, **Lookout**, and specialists it asks for help, built on the Claude Agent SDK. A buyer presses *Work this*, *Compare quotes*, *Triage*, *Draft a reply*, *Import files* or types a question; Lookout reads the item, asks the right specialist(s), and ends with a **Recommendation**: a finding, the numbers it rests on (each with its source), assumptions, what would change the answer, open questions with owners, and any draft waiting for approval. Systems do the work; the agent chooses, explains and drafts.

| Specialist | Expertise | Tools (all Python over the domain services) |
|---|---|---|
| Supply planner | requirements against supply by month, the first short month, the builds hit | `disrupted_supply`, `open_supply`, `shortage_for_parts`, `where_used_for_parts`, `requirements`, `get_item` |
| Tariff analyst | duty by HTS code and origin (never the shipping country), importer of record, which lines enter in time, net beside gross | `exposure_for_part`, `coo_status`, `tariff_rule_for`, `open_supply`, `get_item` |
| Sourcing analyst | quotes as landed cost per piece, conditions kept beside each value | `compare_offers` |
| Inbox analyst | supplier mail: what it is, what it changes, who is really writing, the whole thread | `inbox_overview`, `read_message`, `find_suppliers` |
| Data steward | a file the standard pipeline has not seen: drift, one normaliser step in a sandbox, findings, questions | `drift_report`, `sample_rows`, `column_facts`, `try_step`, `add_finding`, `ask_user` |
| Buyer's clerk | the only one that drafts: a supplier request to the contact on file, a logged question for a Halden buyer, a proposed supplier-alias link | `read_thread`, `draft_supplier_request`, `ask_owner`, `propose_supplier_alias` |

**Control flow.** The workflow is Python and fixed per kind of item (`workflows/work_item.py`): code reads the item and registers its numbers and open questions before any model runs; Lookout is given a **plan** (ordered steps; specialists in one step work independently and are asked together; a step can be optional); each specialist ends with a typed handoff; code verifies; the run ends `ok` or `did_not_pass`. Plans: the fire and deadlines go to the Supply planner then the clerk; tariff and unknown-origin items to the Tariff analyst then the clerk; a portfolio view to the analyst alone; a message to the Inbox analyst (then the clerk if a reply or a link is warranted); a file to the steward. A sender that failed the trust checks is answered by code and no model ever reads the message. *Ask* is the one open case: Lookout finds the item on the Action list and chooses whom to ask, three at most, on a 0.50 USD cap.

**Prompts** are files, hashed on every run: the constitution (`organism/constitution.md`: the four truths, a playbook per kind, the rules), one `instructions.md` per specialist, and a grade sheet per kind (`organism/grades.yaml`). Every prompt states that today is Friday 25 September 2026, the data date.

**Code does the arithmetic.** Every number in a Recommendation is one a tool returned, cited by id (`shortage:HR-40110:2026-10:short`); dollar figures come with a code-made wording (`$1.54M`, `$188.99`). The model never adds, rounds or converts.

**Speed and cost, measured per run** (Claude Sonnet 5.5 for Lookout and the clerk, Haiku 5.5 for the planner and the analysts, thinking off, effort low): the first step shows in under 0.5 s (the system reading the item); the first model token in about 2 s; the fire takes 28-31 s and about 0.08-0.10 USD; a tariff item 25-30 s; Compare quotes 15 s; a trust item 0.4 s and nothing; the steward on a drifted export 23-25 s and 0.07 USD. The Reviewer's grade follows delivery by about 5 s.

**Evals.** `make eval` runs the cases with answer sheets written before any run; the controls (fraud, injection, unknown origin, bypass) must pass every trial.
