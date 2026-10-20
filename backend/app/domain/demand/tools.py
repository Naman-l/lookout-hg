"""Agent tool over the demand service: the shortage by month for one or several parts."""

from __future__ import annotations

from claude_agent_sdk import tool

from ...organism.context import RunContext
from ...organism.toolkit import READ, date_words, month_words, qty_number, reply


def make_tools(ctx: RunContext, svc):
    def one(part: str):
        tp = svc.shortage(part)
        numbers, data = [], []
        for bkt in tp.buckets:
            data.append({"month": bkt.month, "requirements": str(bkt.requirements.value), "scheduled_receipts": str(bkt.scheduled_receipts.value),
                         "under_disruption": str(bkt.under_disruption.value), "short": str(bkt.short.value) if bkt.short else None,
                         "backlog": str(bkt.backlog.value) if bkt.backlog else None})
            if bkt.short is not None and len(numbers) < 6:  # the first three short months, each with its requirement; the rest stay in the data
                numbers.append(qty_number(f"shortage:{part}:{bkt.month}:short", f"Units short in {month_words(bkt.month)} for {part}", bkt.short))
                numbers.append(qty_number(f"req:{part}:{bkt.month}", f"Requirements for {month_words(bkt.month)} for {part}", bkt.requirements))
                if bkt.backlog is not None and bkt.backlog.value > bkt.short.value:      # earlier months' unmet need is carried in: a separate figure, never this month's
                    numbers.append(qty_number(f"backlog:{part}:{bkt.month}", f"Unmet need carried in from earlier months, cumulative to the end of {month_words(bkt.month)}, for {part}", bkt.backlog))
        if tp.unmet_after_all_open_orders is not None:
            numbers.append(qty_number(f"unmet_after_open_orders:{part}", f"Need for {part} still not covered when every open order has landed", tp.unmet_after_all_open_orders))
        summary = f"Shortage for {part}: first short month {month_words(tp.first_short_month)}" if tp.first_short_month else f"Shortage for {part}: none raised"
        info = {"part": part, "first_short_month": tp.first_short_month, "unmet_after_all_open_orders": str(tp.unmet_after_all_open_orders.value) if tp.unmet_after_all_open_orders else None, "disrupted": tp.disrupted, "recovery": {"as_the_supplier_said": tp.recovery_text, "latest_by": tp.recovery_by, "latest_by_words": date_words(tp.recovery_by) if tp.recovery_by else None,
                     "note": "The supplier gave the range in its own words; the date is code's upper bound (notice date plus the longest figure), not a date the supplier gave. Write: '<their words> (about <latest_by_words> at the latest)'."},
                "per_unit": tp.per_unit, "months": data[:4], "short_months_not_listed": max(0, sum(1 for m in data if m["short"]) - sum(1 for m in data[:4] if m["short"]))}
        return summary, info, numbers, [tp.on_hand] if tp.on_hand else []

    @tool(
        "shortage_for_parts",
        "Time-phased view for one or several parts: requirements, scheduled receipts and the shortage by month, with the first short month. `short` is that month's own shortage, at most "
        "what the month needs; `backlog` is the cumulative unmet need to the end of that month, carried in from earlier months: never call it a month's shortage. A shortage is raised only where supply "
        "is disrupted. On-hand stock is not in the data and comes back as an open question with its owner; never estimate it. Give one part, or every part a supplier notice disrupts. "
        "Use open_supply, not this, to see which order lines are on the way.",
        {"type": "object", "properties": {"part_numbers": {"type": "array", "items": {"type": "string"}}}, "required": ["part_numbers"]},
        annotations=READ,
    )
    async def shortage_for_parts(args):
        results = [one(p) for p in args["part_numbers"]]
        numbers = [n for r in results for n in r[2]]
        unknowns = [u for r in results for u in r[3]]
        return reply(ctx, f"Shortage for {len(results)} parts: " + "; ".join(r[0].removeprefix("Shortage for ") for r in results), [r[1] for r in results], numbers, unknowns)

    return [shortage_for_parts]
