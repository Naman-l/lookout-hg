"""The verifier and the Reviewer, in code, for every run (drafted by code, replayed, or live).

Verifier (a failure blocks a quiet approval): every figure the Recommendation cites is one a tool returned in the run, with the same value; the
recommended route is one the case's code table lays out; every draft goes to a contact on file and mentions no bank details; a draft that commits
money above the DoA threshold carries the countersign.
Reviewer (a grade, 0-100): the checks a senior buyer makes on the work: figures cited, an owner for every open question, the letter in house style
(a reply-by date; rights reserved where it answers a claim or a notice), nothing in a letter commits the company beyond the route chosen (no award,
no MFC, no payment promise), an internal memo commits no money.
"""

from __future__ import annotations

import re
from decimal import Decimal

from sqlalchemy.orm import Session

from app.domain import lookups
from app.domain.actions.letters import FORBIDDEN, RESERVE


def check(session: Session, d, rec: dict, numbers: dict, drafts: list, routes: list) -> dict:
    fails: list[str] = []
    cited = [n for n in rec.get("numbers") or []]
    for n in cited:
        got = numbers.get(n["id"])
        if got is None:
            fails.append(f"a figure cites {n['id']}, which no lookup in this run returned")
        elif abs(Decimal(str(got.value)) - Decimal(str(n["value"]))) > Decimal("0.01"):
            fails.append(f"{n.get('name') or n['id']} reads {n['value']}, the lookup says {got.value}")
    r = rec.get("recommended") or {}
    if r and r.get("kind") not in {x.kind for x in routes}:
        fails.append(f"the recommended route '{r.get('kind')}' is not one this case lays out")
    for i in r.get("number_ids") or []:
        if i not in numbers:
            fails.append(f"the reason cites {i}, which no lookup returned")
    on_file = {(c.email or "").lower() for c in lookups.contacts(session).values()} | {(x.contact_email or "").lower() for x in lookups.records(session).values()} \
        | {(b.email or "").lower() for b in lookups.team(session).values()}
    for a in drafts:
        if a.recipient and a.recipient.lower() not in on_file:
            fails.append(f"a draft goes to {a.recipient}, which is not on file")
        if FORBIDDEN.search(f"{a.subject or ''} {a.body or ''}"):
            fails.append("a draft mentions bank details or a payment to an account")
        ch = a.change or {}
        if ch.get("commits_inr") and ch.get("doa_line") and "also needs" in ch["doa_line"] and not ch.get("countersign"):
            fails.append("a draft commits money above the DoA threshold with no countersign")
    checked = len(cited) + (1 if r else 0) + len(r.get("number_ids") or []) + 3 * len(drafts)
    return {"passed": not fails, "checked": max(checked, 1), "failures": fails, "numbers_checked": len(cited), "numbers_from_tools": len(numbers)}


_COMMIT = re.compile(r"\b(we (?:hereby )?award|we will pay|payment will be released|we confirm the order|issue the manufacturing clearance|pleased to issue)\b", re.I)


def review(session: Session, d, rec: dict, drafts: list, routes: list) -> dict:
    checks: list[tuple[str, bool, str]] = []
    checks.append(("figures cited", all(n.get("id") for n in rec.get("numbers") or []), "every figure carries the id of the lookup it came from"))
    checks.append(("owners for open questions", all((q.get("owner") if isinstance(q, dict) else q.owner) for q in rec.get("open_questions") or []), "every open question names who can answer it"))
    chosen = {x.kind: x for x in routes}
    for a in drafts:
        route = chosen.get((a.change or {}).get("option_kind") or "")
        commits = bool(route and route.commits) or bool((a.change or {}).get("commits_inr"))      # one letter per contact can carry another case's committing route
        if a.type == "supplier_request":
            checks.append(("reply-by date", "Kindly confirm by" in (a.body or ""), "the letter asks for an answer by a date"))
            answers_claim = d.kind in ("pv-claim", "schedule-slip", "late-streak", "supply-stop", "mfc-validity") and (route is None or route.kind in ("reply_computed", "ask_evidence", "hold_original", "firm_dates", "ld_reminder", "alt_supply", "extend_validity"))
            if answers_claim:
                checks.append(("rights reserved", RESERVE in (a.body or ""), "a letter that answers a claim or a notice keeps the company's rights"))
            checks.append(("commits only what the route commits", commits or not _COMMIT.search(a.body or ""), "no award, MFC or payment promise unless that is the route"))
        if a.type == "internal_note":
            checks.append(("a memo commits no money", not _COMMIT.search(a.body or ""), "a note inside the company asks; it promises no award, order or payment by itself"))
            checks.append(("memo style", (a.body or "").startswith("To: "), "To / From / Date / Subject, then the ask and its date"))
    passed = sum(1 for _, ok, _ in checks if ok)
    failed = [{"name": n, "reason": why} for n, ok, why in checks if not ok]
    return {"reviewer_score": round(100 * passed / len(checks)) if checks else None, "checks_passed": passed, "checks_total": len(checks),
            "summary": "all checks passed" if not failed else "; ".join(f["name"] for f in failed), "failed_checks": failed, "revised": False}
