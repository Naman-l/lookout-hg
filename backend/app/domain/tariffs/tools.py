"""Agent tools over the tariffs service: the new duty by part, line and rule. The service computes every figure
(net first, gross beside it); these wrappers shape them for the Tariff analyst and give each a stable id."""

from __future__ import annotations

from decimal import Decimal

from claude_agent_sdk import tool

from ...organism import company
from ...organism.context import RunContext
from ...organism.schemas import Number
from ...organism.toolkit import READ, date_words, money_number, plain_number, reply
from ..common import AS_OF, Unknown

_PART = {"part_number": str}


def _unknowns(*xs):
    return [x for x in xs if x is not None]


def make_tools(ctx: RunContext, svc):
    co = company.names(ctx.db_path)[1]  # the company's short name, from the recipe

    def _exposure(part):
        e = svc.exposure_for_part(part)
        numbers: list[Number] = []
        if e.net is not None:
            what = "if the origin is China (not known)" if e.status == "unknown_origin" else "owed (what to act on)"
            numbers.append(money_number(f"tariff:{part}:net", f"New duty on {part}, {what}", e.net))
        if e.conditional is not None:
            numbers.append(money_number(f"tariff:{part}:conditional", f"New duty on {part} owed only if its open orders ship late (in transit)", e.conditional))
        if e.gross is not None:
            numbers.append(money_number(f"tariff:{part}:gross", f"New duty on {part}, gross (every open line and the full forecast)", e.gross))
        if e.rate is not None:
            numbers.append(plain_number(f"tariff:{part}:rate", f"Duty rate on {part}, percent", Decimal(str(e.rate)) * 100, "%"))
        if e.effective_date is not None:  # the days to the duty date are the tool's figure, never the model's subtraction
            from datetime import date  # noqa: PLC0415

            numbers.append(plain_number(f"tariff:{part}:days_to_effective", f"Days from the data date to the duty date for {part}", (date.fromisoformat(e.effective_date) - AS_OF).days, "days"))
        numbers.append(plain_number(f"tariff:{part}:uncovered_qty", f"12-month requirement of {part} not covered by open supply", Decimal(str(e.uncovered_qty)), "EA"))
        if e.reference_price is not None:
            numbers.append(money_number(f"tariff:{part}:reference_price", f"Price used for {part} where no order exists", e.reference_price))
        if e.pass_through is not None:
            numbers.append(money_number(f"tariff:{part}:pass_through", f"Duty on {part} the supplier pays as importer of record", e.pass_through))
        lines, unrated = [], []
        for l in e.open_lines:
            ld = svc.duty_for_line(l.po_line.id)
            if l.po_line in e.lines_without_rate and ld.unknown is not None:
                unrated.append(ld.unknown)
            if l.open_value.usd is not None:
                numbers.append(money_number(f"tariff:{part}:{l.po_line.id}:open_value", f"Open value of {l.po_line.id}", l.open_value))
            if ld.duty is not None:
                numbers.append(money_number(f"tariff:{part}:{l.po_line.id}:duty", f"New duty on {l.po_line.id}", ld.duty))
            lines.append({"po_line": l.po_line.id, "exposed": l.exposed, "bucket": l.bucket, "importer": l.importer, "duty_status": ld.status, "why": l.why})
        skipped = f" (excludes {len(e.lines_without_rate)} line{'s' if len(e.lines_without_rate) != 1 else ''} without an exchange rate)" if e.lines_without_rate else ""
        if e.open_value_total is not None:
            numbers.append(money_number(f"tariff:{part}:open_value", f"Open order value of {part}{skipped}", e.open_value_total))
        if e.open_duty_total is not None:
            numbers.append(money_number(f"tariff:{part}:open_lines_duty", f"New duty on the open lines of {part}{skipped}", e.open_duty_total))
        rule = e.tariff.rule
        data = {
            "part": part, "status": e.status, "listed": e.tariff.status, "origin": e.coo.coo, "origin_status": e.coo.status,
            "rule": None if rule is None else {"description": rule.description, "tranche": rule.tranche, "hts_prefix": rule.hts_prefix,
                                                "effective": e.effective_date, "effective_words": date_words(e.effective_date) if e.effective_date else None,
                                                "in_transit_rule": rule.in_transit},
            "rule_sentences": e.rule_sentences,
            "lines": lines,
        }
        summary = f"Tariff exposure for {part}: {e.status.replace('_', ' ')}" + (f", net {int(e.net.usd):,} USD" if e.net is not None and e.net.usd is not None else "")
        late = [l for l in e.open_lines if l.bucket == "conditional"]
        in_transit = None
        if late:  # the duty on these lines is owed only if they ship and enter in time: no file holds a ship date, so the date is a question with an owner
            n = len(late)
            in_transit = Unknown(
                what=f"whether the late {'line' if n == 1 else 'lines'} of {part} {'ships' if n == 1 else 'ship'} before the duty date",
                why_it_blocks=f"{'this line owes' if n == 1 else 'these lines owe'} the duty only if {'it ships' if n == 1 else 'they ship'} and enter{'s' if n == 1 else ''} in time{'' if e.effective_date is None else ', before ' + date_words(e.effective_date)}, and no record holds a ship date",
                owner=svc.buyer_of(part), question=f"When will {'the late line' if n == 1 else 'each late line'} of {part} ship, and will {'it' if n == 1 else 'it'} enter before the duty window closes?", refs=[l.po_line for l in late])
        return summary, data, numbers, _unknowns(e.unknown, e.tariff.unknown, e.coo.unknown, in_transit, *unrated)

    @tool(
        "exposure_for_part",
        "The new US duty on one part: whether it is listed (by HTS code and country of ORIGIN, never by shipping "
        "country), the rate and effective date, who is importer of record on each open PO line (FOB, FCA, EXW and DAP "
        f"mean {co} pays; DDP means the supplier does), which lines enter before the effective date, the duty on the "
        "open lines, the 12-month requirement not covered by open supply, and the duty in three buckets, each with its "
        "one-sentence rule: OWED (certain; what to act on), CONDITIONAL (owed only if an open order ships after the in-transit "
        "window; never add it to owed) and, for an unknown origin, the figure IF CHINA (never add it either). Gross comes beside. "
        "An unknown origin or HTS code comes back as an open question with its owner.",
        _PART,
        annotations=READ,
    )
    async def exposure_for_part(args):
        return reply(ctx, *_exposure(args["part_number"]))

    @tool(
        "exposure_for_parts",
        "The new US duty on several parts at once (up to 8): the same answer as exposure_for_part for each part, in one call. Use it for a roll-up or whenever you would call "
        "exposure_for_part more than twice: one call instead of many, one turn instead of many.",
        {"type": "object", "properties": {"part_numbers": {"type": "array", "items": {"type": "string"}}}, "required": ["part_numbers"]},
        annotations=READ,
    )
    async def exposure_for_parts(args):
        parts = list(dict.fromkeys(args["part_numbers"]))[:8]
        got = [(p, *_exposure(p)) for p in parts]
        numbers = [n for _, _, _, ns, _ in got for n in ns]
        unknowns = [u for _, _, _, _, us in got for u in us]
        return reply(ctx, f"Tariff exposure for {len(parts)} parts: " + "; ".join(s for _, s, _, _, _ in got), [d for _, _, d, _, _ in got], numbers, unknowns)

    return [exposure_for_part, exposure_for_parts]
