"""Why each tool is called, in the buyer's words, written by code.

The model does not explain its lookups (thinking is off and the constitution asks it to stay quiet), so the reason a buyer reads
beside each step comes from here: what the lookup is for, how many things it covers. It is deterministic and true to the call,
because it is built from the tool's name and arguments. Tools with no entry say what kind of lookup they are instead of nothing.
"""

from __future__ import annotations

from typing import Any, Callable


def _n(args: dict, key: str) -> int:
    v = args.get(key)
    return len(v) if isinstance(v, (list, tuple)) else (1 if v else 0)


def _parts(args: dict, key: str = "part_numbers") -> str:
    n = _n(args, key)
    return "the part" if n == 1 else f"{n} parts"


PURPOSE: dict[str, Callable[[dict], str]] = {
    "get_item": lambda a: "Read what the system already worked out for this item: its finding, dates and figures.",
    "list_items": lambda a: "Find which item on the Action list the question is about.",
    "supplier_delivery": lambda a: "Rank the suppliers by how often they delivered late, from their closed lines, so the answer names who and how many lines.",
    "requests_for": lambda a: "Read the requests to suppliers the approval ledger holds, so the answer says what is waiting, approved or sent.",
    "disrupted_supply": lambda a: "List every open order line this supplier can no longer ship, so each affected part is covered.",
    "open_supply": lambda a: "Find what is on order for the part and what is stuck." if a.get("part_number") else "Find the open order lines with this supplier and which are due before the date that matters.",
    "shortage_for_parts": lambda a: f"Work out, month by month, what the builds need against what is coming for {_parts(a)}, and when each first runs short.",
    "where_used_for_parts": lambda a: f"Find which robots use {_parts(a)}, so the shortage is stated per build.",
    "get_phases": lambda a: "Show where the order or part stands between need and stock, and which steps no record can show.",
    "build_readiness": lambda a: "Check how many of a robot's parts are covered for the month, arrive late, or have no open order.",
    "exposure_for_part": lambda a: "Work out the duty on this part, net and gross, who pays it, and which lines enter in time.",
    "exposure_for_parts": lambda a: f"Work out the duty on {_parts(a)} in one step: net and gross, who pays it, and which lines enter in time.",
    "compare_offers": lambda a: "Put each offer beside the current supplier at landed cost, keeping the conditions that go with every price.",
    "read_message": lambda a: "Read the supplier's message and its thread, with who sent it and what it changes.",
    "inbox_overview": lambda a: "List the inbox as the system classified it, to find the message the question is about.",
    "find_suppliers": lambda a: "Check the supplier master for the company, including renamed and legacy records.",
    "get_handoffs": lambda a: "Read what the earlier steps found, with the figures their lookups returned.",
    "draft_supplier_request": lambda a: "Prepare the request to the supplier for the buyer to approve. Nothing is sent.",
    "amend_draft": lambda a: "Add a paragraph to the request already waiting for approval, so it also asks what this item needs. Its owner signs the new text.",
    "log_buyer_question": lambda a: "Leave a question for the buyer who owns the answer. An internal note; nothing leaves {co}.",
    "propose_supplier_alias": lambda a: "Propose linking two supplier records as one company, with the evidence. A person decides; nothing is merged.",
    "stage_decision": lambda a: "Stage the decision the buyer asked for on this case, for the owner's signature. Approving records it; nothing is sent.",
    "drift_report": lambda a: "Compare the new file with the export the system already knows, column by column.",
    "column_facts": lambda a: "Count blanks and value shapes in one column, to put a number behind a finding.",
    "try_step": lambda a: "Try a cleaning step on a copy of the data in a sandbox; the real data is untouched.",
    "add_finding": lambda a: "Record what is wrong in the file, with how many rows and what it would cost left alone.",
    "add_question": lambda a: "Ask the buyer the one thing only a person can decide, with a proposed answer.",
}


STATUS = {
    "open_supply": "checking the open orders", "disrupted_supply": "finding the lines under the notice", "supplier_delivery": "ranking suppliers by on-time delivery", "requests_for": "checking which requests were staged or sent", "shortage_for_parts": "checking what runs short",
    "where_used_for_parts": "finding which builds use the part", "get_phases": "reading the build phases", "build_readiness": "checking build readiness",
    "get_item": "reading the item", "list_items": "listing the items", "exposure_for_part": "working out the duty exposure", "exposure_for_parts": "working out the duty exposure",
    "compare_offers": "comparing the offers", "inbox_overview": "scanning the inbox", "read_message": "reading the message", "find_suppliers": "finding the supplier",
    "draft_supplier_request": "drafting the request", "amend_draft": "adding to the waiting request", "log_buyer_question": "logging a question for the buyer",
    "propose_supplier_alias": "proposing a supplier link", "stage_decision": "staging a decision for signature", "drift_report": "comparing the file's columns", "column_facts": "reading the file's values", "try_step": "testing a mapping step",
}


def status(label: str, tool: str) -> str:
    """One line for the live status under a running workflow: who, and what they are doing, with no narration."""
    return f"{label}: {STATUS.get(tool, 'working')}"


def why(tool: str, args: dict[str, Any] | None = None, db_path=None) -> str:
    """The reason for a call, in a sentence; an unknown tool gets a plain statement of what it is. {co} is the company's short name from the build."""
    from .company import names  # noqa: PLC0415

    try:
        return PURPOSE[tool](args or {}).replace("{co}", names(db_path)[1])
    except KeyError:
        return "Look something up in the records for this item."
