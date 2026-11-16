"""Why each tool is called, in the buyer's words, written by code from the tool's name and arguments: deterministic and true to the call."""

from __future__ import annotations

from typing import Any, Callable

PURPOSE: dict[str, Callable[[dict], str]] = {
    "get_item": lambda a: "Read what the code already found on this case: its figures, its dates and what nobody knows yet.",
    "list_items": lambda a: "Find which case on Today the question is about.",
    "open_prs": lambda a: "List the open PRs" + (f" for {a['project']}" if a.get("project") else "") + ", with their age and need date.",
    "pr_ladder": lambda a: f"Walk PR line {a.get('pr_line')} from need to payment: each step's date, its source row, and whose move each wait was.",
    "open_pos": lambda a: "List the open PO lines" + (f" with vendor {a['vendor']}" if a.get("vendor") else "") + ", with their due and revised dates.",
    "po_ladder": lambda a: f"Walk PO line {a.get('po_line')} from need to payment: MFC, inspection, dispatch, receipt, invoice, payment.",
    "requirement_for": lambda a: f"Put the 3-month requirement for {a.get('project')} beside what the open POs bring and what was received, month by month.",
    "site_impact": lambda a: "Name the work fronts that stop if the material is late, and from when (up to: site stock is not in the data).",
    "workfront_readiness": lambda a: f"Check {a.get('project')}'s work fronts month by month: covered in time, late, under a disruption, or with no PO.",
    "compare_quotes": lambda a: "Put every quote beside L1, the last PO rate at that plant and the budget rate, with each one's validity and terms.",
    "rate_history": lambda a: "Read what each site paid for the material over the year, to see the spread and who could explain it.",
    "vendor_record": lambda a: "Read the vendor's record: on-time receipts against the PO dates, its late streak, MSME dues and library approval.",
    "pv_cost": lambda a: f"Work out the price variation PO {a.get('po')} owes on its own clause: base month, variable share, index.",
    "index_series": lambda a: f"Read {a.get('index')} month by month, to see how fast it is rising.",
    "lookahead": lambda a: "Read the long-lead items not yet ordered, their order-by dates and what each month's wait costs.",
    "inbox_overview": lambda a: "List the inbox as the code classified it, to find the message the question is about.",
    "read_message": lambda a: "Read the message as quoted data: who sent it, whether it can be trusted, the dates and lines it changes.",
    "find_vendors": lambda a: "Check the vendor master for the company, its codes and any renamed record.",
    "get_handoffs": lambda a: "Read what the earlier steps found, with the figures their lookups returned.",
    "draft_vendor_request": lambda a: "Draft the letter to the vendor's contact on file, in house style, for the owner to sign.",
    "draft_internal_note": lambda a: "Draft the note to the person on file who owns the function, for the owner to sign.",
    "stage_decision": lambda a: "Stage the decision on record, with its reason, for the owner to sign.",
}


def why(tool: str, args: dict[str, Any] | None = None, db_path=None) -> str:
    f = PURPOSE.get(tool)
    try:
        return f(args or {}) if f else f"Look up {tool.replace('_', ' ')}."
    except Exception:  # noqa: BLE001  a reason is a nicety; it never breaks a run
        return f"Look up {tool.replace('_', ' ')}."
