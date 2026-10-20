"""Agent tools over the orders service. Thin: the service computes, the tool shapes the answer."""

from __future__ import annotations

from decimal import Decimal

from claude_agent_sdk import tool

from ...organism.context import RunContext
from ...organism.toolkit import READ, cover_numbers, fmt, plain_number, refuse, reply


def make_tools(ctx: RunContext, svc):
    @tool(
        "open_supply",
        "Open purchase-order lines for a part: PO and line, supplier, quantity in each, promise date, revised "
        "promise and the notice that disrupted the line, if any. Use it to see what is on the way and what is "
        "stuck. Give a part number, or a supplier id to see every open line with that supplier (a price rise or a deadline names a supplier, not a part). Returns the stuck quantity and "
        "line count as numbers you can cite by id. For everything one supplier's notice disrupted, use disrupted_supply instead.",
        {"type": "object", "properties": {"part_number": {"type": "string"}, "supplier_id": {"type": "string", "description": "the supplier id as find_suppliers returns it"}}},
        annotations=READ,
    )
    async def open_supply(args):
        part, supplier = args.get("part_number"), args.get("supplier_id")
        if not part and not supplier:
            return refuse("give a part_number or a supplier_id")
        lines = svc.open_supply(part)
        if supplier:
            lines = [l for l in lines if l.supplier.id == supplier]
            part = part or supplier  # the numbers are named for what was asked
        asked = (lines[0].supplier.label if supplier and lines and lines[0].supplier.label else None) or part  # a supplier is named by name in a number a buyer reads; the id stays in the number's id
        each = lambda l: l.qty.ea if l.qty.ea is not None else l.qty.value  # noqa: E731  quantity in each, as the service gives it
        stuck = sum(each(l) for l in lines if l.disrupted_by)
        total = sum(each(l) for l in lines)
        numbers = [
            plain_number(f"supply:{part}:open_lines", f"Open PO lines for {asked}", len(lines), "lines"),
            plain_number(f"supply:{part}:open_qty", f"Quantity on open orders for {asked}", total, "EA"),
            plain_number(f"supply:{part}:stuck_qty", f"Quantity on disrupted lines for {asked}", stuck, "EA"),
            plain_number(f"supply:{part}:unaffected_qty", f"Quantity on open orders not disrupted for {asked}", total - stuck, "EA"),
        ]
        for l in lines:
            numbers.append(plain_number(f"supply:{part}:{l.po_line.id}:qty", f"Quantity on {l.po_line.id}", each(l), "EA"))
        live = [l for l in lines if not l.stale]      # what is still to arrive, in money: dollars, and in each order currency (the supplier invoices in it)
        dollars = sum((l.open_value.usd for l in live if l.open_value.usd is not None), Decimal(0))
        numbers.append(plain_number(f"supply:{part}:open_value_usd", f"Value still to arrive on open orders for {asked} (USD, at finance's rate for each order's month)", dollars.quantize(Decimal("0.01")), "USD"))
        for cur in sorted({l.open_value_own.currency for l in live if getattr(l, "open_value_own", None) and l.open_value_own.currency != "USD"}):
            own = sum((l.open_value_own.amount for l in live if getattr(l, "open_value_own", None) and l.open_value_own.currency == cur), Decimal(0))
            numbers.append(plain_number(f"supply:{part}:open_value_{cur.lower()}", f"Value still to arrive on open orders for {asked} ({cur}, as the orders are priced)", own.quantize(Decimal("0.01")), cur))
        data = [
            {
                "po_line": l.po_line.id, "supplier": l.supplier.id, "qty": str(each(l)), "promise": l.promise, "revised_promise": l.revised_promise,
                "days_past_due": l.days_past_due, "disrupted_by": l.disrupted_by.id if l.disrupted_by else None, "flags": l.flags,
                "under_notice": bool(l.notice_kind), "notice_kind": l.notice_kind, "stale": l.stale,      # a line under a notice and a stale legacy line are different things: never count one as the other
            }
            for l in lines
        ]
        under, stale = sum(1 for l in lines if l.notice_kind and not l.stale), sum(1 for l in lines if l.stale)
        kinds = sorted({l.notice_kind for l in lines if l.notice_kind and not l.stale})
        parts = [f"{under} under the notice" + (f" ({' and '.join(kinds)})" if kinds else "")] if under else []
        if stale:
            parts.append(f"{stale} stale legacy {'line' if stale == 1 else 'lines'} (probably not open)")
        rest = len(lines) - under - stale
        if rest and parts:
            parts.append(f"{rest} otherwise")
        numbers += cover_numbers(ctx, numbers)
        return reply(ctx, f"Open supply for {asked}: {len(lines)} lines, {fmt(total)} EA ({fmt(stuck)} EA on disrupted lines)" + (f"; {' · '.join(parts)}" if parts else ""), data, numbers)

    @tool(
        "disrupted_supply",
        "Every open PO line a supplier's notice has disrupted, across all parts, with the quantity stuck per part. A notice is a force majeure, an allocation, or a supplier's later "
        "date for a line (a slip): each line says which (`notice_kind`) and gives the notice and the revised date. Use it first on a supply disruption: it tells you which parts to examine next "
        "with `shortage_for_parts` and `where_used_for_parts`. For one order line or a part's whole life use get_phases.",
        {"supplier_id": str},
        annotations=READ,
    )
    async def disrupted_supply(args):
        sup = args["supplier_id"]
        each = lambda l: l.qty.ea if l.qty.ea is not None else l.qty.value  # noqa: E731
        hit = [l for l in svc.open_supply(None) if l.supplier.id == sup and l.notice_kind and not l.stale]      # force majeure, an allocation, or a later date from the supplier
        parts: dict[str, list] = {}
        for l in hit:
            parts.setdefault(l.part.id, []).append(l)
        who = (hit[0].supplier.label if hit and hit[0].supplier.label else None) or sup  # named by name; the id stays in the number's id
        numbers = [plain_number(f"supply:{sup}:disrupted_lines", f"Open PO lines disrupted for {who}", len(hit), "lines")]
        for part, ls in sorted(parts.items()):
            numbers.append(plain_number(f"supply:{part}:stuck_qty", f"Quantity on disrupted lines for {part}", sum(each(l) for l in ls), "EA"))
            numbers += [plain_number(f"supply:{part}:{l.po_line.id}:qty", f"Quantity on {l.po_line.id}", each(l), "EA") for l in ls]
        data = [
            {"part": part, "lines": [{"po_line": l.po_line.id, "qty": str(each(l)), "promise": l.promise, "revised_promise": l.revised_promise,
                                      "days_past_due": l.days_past_due, "notice_kind": l.notice_kind,
                                      "notice": (l.disrupted_by or l.revised_by).id if (l.disrupted_by or l.revised_by) else None} for l in ls]}
            for part, ls in sorted(parts.items())
        ]
        kinds = sorted({l.notice_kind for l in hit})
        terms_of = getattr(svc, "notice_terms", None)
        notices = []
        if terms_of:      # what each notice says beyond the dates: the lead time for new orders, where each family is made and the duty that brings, the shortage the new dates cause
            for mid in sorted({(l.disrupted_by or l.revised_by).id for l in hit if (l.disrupted_by or l.revised_by)}):
                notices.append(terms_of(mid, sorted({l.part.id for l in hit if (l.disrupted_by or l.revised_by) and (l.disrupted_by or l.revised_by).id == mid})))
        from datetime import date as _date

        for nt in notices:      # the shortage each new date causes, one number per part and month (never merged across months)
            for sh in (nt.get("next_shortage") or {}).get("all", []):
                month_words = _date.fromisoformat(sh["month"] + "-01").strftime("%B %Y")
                numbers.append(plain_number(f"notice:{nt['notice']}:shortage:{sh['part']}:{sh['month']}", f"{sh['part']} short in {month_words} because of the notice's new dates, before stock on hand", sh["qty"], "EA"))
        return reply(ctx, f"Disrupted supply for {who}: {len(hit)} lines across {len(parts)} parts ({', '.join(sorted(parts))})" + (f"; notice: {' and '.join(kinds)}" if kinds else ""),
                     {"parts": data, "notices": notices} if notices else data, numbers)

    @tool(
        "supplier_delivery",
        "Which suppliers deliver late most often, ranked worst first: each one's on-time share of its closed lines (a line is on time when received on or before its promise), the closed lines that share rests on, "
        "the open lines already past due and their value, and the parts the company buys from it most often. Use it for any question about suppliers' on-time performance or who is late most. "
        "Numbers are cited by id. `limit` is how many suppliers to rank (default 10).",
        {"type": "object", "properties": {"limit": {"type": "integer", "description": "how many suppliers to rank, worst first (1 to 30)"}}},
        annotations=READ,
    )
    async def supplier_delivery(args):
        try:
            limit = int(args.get("limit") or 10)
        except (TypeError, ValueError):
            return refuse("limit is a whole number of suppliers")
        rows = svc.supplier_delivery(max(1, min(limit, 30)))
        numbers = []
        for r in rows:
            sid, who = r["supplier"], r["name"]
            numbers += [
                plain_number(f"delivery:{sid}:on_time_pct", f"Share of {who}'s closed lines received on or before the promise", r["on_time_pct"], "%"),
                plain_number(f"delivery:{sid}:closed_lines", f"Closed lines with a promise and a receipt date for {who}", r["closed_lines"], "lines"),
                plain_number(f"delivery:{sid}:late_lines", f"Closed lines {who} delivered late", r["late"], "lines"),
                plain_number(f"delivery:{sid}:past_due_open_lines", f"Open lines of {who} already past due", r["past_due_open_lines"], "lines"),
                plain_number(f"delivery:{sid}:open_value_usd", f"Value still to arrive on open orders for {who} (USD)", r["open_value_usd"], "USD"),
            ]
            if r["avg_days_late"] is not None:
                numbers.append(plain_number(f"delivery:{sid}:avg_days_late", f"Average days late over {who}'s late closed lines", Decimal(str(r["avg_days_late"])), "days"))
        if not rows:
            return reply(ctx, "No supplier has a closed line with both a promise and a receipt date", [], [])
        worst = rows[0]
        return reply(ctx, f"{len(rows)} suppliers ranked by how often they deliver late; worst: {worst['name']}, on time on {worst['on_time_pct']}% of {worst['closed_lines']} closed lines", rows, numbers)

    return [open_supply, disrupted_supply, supplier_delivery]
