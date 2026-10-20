"""Shared helpers for the tool wrappers under domain/*/tools.py.

Every tool answers with compact JSON: a one-line summary, the data, `numbers` (each with a stable id the
Recommendation cites) and `unknowns` (each with an owner). The wrapper registers the numbers in the run's
evidence register so the verifier can match them later. Tools never do arithmetic of their own.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Iterable

from claude_agent_sdk import ToolAnnotations

from ..domain.common import AS_OF, Money, Provenance, Quantity, Unknown
from .context import RunContext
from .schemas import Number

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
STAGE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def qty_number(number_id: str, name: str, q: Quantity) -> Number:
    value = q.ea if q.ea is not None else q.value
    return Number(id=number_id, name=name, value=value, unit="EA" if q.ea is not None else q.uom, provenance=q.provenance)


def money_number(number_id: str, name: str, m: Money) -> Number:
    value = m.usd if m.usd is not None else m.amount
    return Number(id=number_id, name=name, value=value, unit="USD" if m.usd is not None else m.currency, provenance=m.provenance)


_SOURCE = {"cover": "po_lines and bom", "supply": "po_lines", "delivery": "closed po_lines with a promise and a receipt date", "tariff": "po_lines and tariff rules", "bom": "bom", "phases": "the stage rules over po_lines", "build": "the stage rules over po_lines", "import": "the incoming file", "option": "the options (orders, quotes and tariff rules)"}


def plain_number(number_id: str, name: str, value: Decimal | int, unit: str) -> Number:
    """A count or total the tool computed. Its provenance names the table it was counted from and the rule (what the number says), so the click-through never ends in nothing."""
    prov = Provenance(method="computed", source=_SOURCE.get(number_id.split(":")[0], "the records"), row=number_id, rule=name, by="agent tools")
    return Number(id=number_id, name=name, value=Decimal(value), unit=unit, provenance=prov)


def cover_numbers(ctx, extra: list[Number]) -> list[Number]:
    """Robots a part's open orders cover, written by code once both figures are in the run (open qty from open_supply, per robot from
    where_used_for_parts, in either order): floor(open qty / per robot), before stock on hand. So 'up to N robots' is a tool figure, never the model's arithmetic."""
    import math  # noqa: PLC0415

    have = {**getattr(ctx, "evidence", {}), **{n.id: n for n in extra}}
    out = []
    for nid, n in have.items():
        parts = nid.split(":")
        if parts[0] != "bom" or len(parts) != 4 or parts[3] != "per_robot" or not n.value:
            continue
        part, product = parts[1], parts[2]
        qty = have.get(f"supply:{part}:open_qty")
        cid = f"cover:{part}:{product}:robots_on_order"
        if qty is None or cid in have:
            continue
        robot = n.name.split(" per ", 1)[1] if " per " in (n.name or "") else product
        out.append(plain_number(cid, f"{robot} robots that the open orders of {part} cover if all of it goes to the {robot} ({qty.value:.0f} on order, {n.value:.0f} per robot), before stock on hand; "
                                     "a part used in several robots has one such figure per robot, never to be added",
                                math.floor(qty.value / n.value), "robots"))
    return out


def _num(n: Number) -> dict:
    d = {"id": n.id, "name": n.name, "value": str(n.value), "unit": n.unit}
    if n.say:
        d["say"] = n.say
    return d


def _unk(u: Unknown) -> dict:
    return {"what": u.what, "owner": u.owner, "question": u.question, "why_it_blocks": u.why_it_blocks}


def reply(ctx: RunContext, summary: str, data: Any, numbers: Iterable[Number] = (), unknowns: Iterable[Unknown] = (), *, capped: bool = True) -> dict:
    numbers, unknowns = list(numbers), list(unknowns)
    ctx.register(numbers)
    ctx.unknowns.extend(unknowns)
    body = {"summary": summary, "data": data, "numbers": [_num(n) for n in numbers], "unknowns": [_unk(u) for u in unknowns]}
    return {"content": [{"type": "text", "text": _compact(body, capped)}]}


MAX_REPLY_CHARS = 10_000  # about 2,500 tokens: past this a tool's answer is cut with a note on how to ask for less


def _compact(body: dict, capped: bool = True) -> str:
    """Compact JSON (fewer tokens, nothing lost; an empty list or a null is an answer, so none are dropped), capped with a steering note."""
    text = json.dumps(body, default=str, separators=(",", ":"), ensure_ascii=False)
    if not capped or len(text) <= MAX_REPLY_CHARS:
        return text
    lean = {**body, "data": None}
    note = "Result too long to show in full: its data was left out; the summary and numbers above are complete. Ask for fewer parts, or one part at a time."
    return json.dumps({**lean, "note": note}, default=str, separators=(",", ":"), ensure_ascii=False)


def refuse(message: str) -> dict:
    return {"content": [{"type": "text", "text": json.dumps({"error": message})}], "is_error": True}


def fmt(n) -> str:
    """1140.0 -> '1,140'; 2.5 -> '2.5'. For the one-line summaries buyers read."""
    n = Decimal(str(n))
    return f"{int(n):,}" if n == n.to_integral_value() else f"{n.normalize():,}"


_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def month_words(ym: str) -> str:
    """'2026-10' -> 'October'; 'YYYY-MM' of another year keeps its year ('January 2027'). The snapshot year is the data date's."""
    y, m = ym.split("-")[:2]
    return _MONTHS[int(m) - 1] + ("" if int(y) == AS_OF.year else f" {y}")


def date_words(iso: str) -> str:
    """'2026-09-22' -> '22 September'."""
    y, m, d = iso.split("-")[:3]
    return f"{int(d)} {_MONTHS[int(m) - 1]}" + ("" if int(y) == AS_OF.year else f" {y}")


def plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def money_words(usd) -> str:
    """How a buyer says a dollar figure: $1.54M, $552K, $188.99, $8,009.32, $0.2406. Code does the rounding, so the model never does."""
    v = Decimal(str(usd))
    a = abs(v)
    sign = "-" if v < 0 else ""
    if a >= 1_000_000:
        return f"{sign}${(a / 1_000_000):.2f}M"
    if a >= 10_000:
        return f"{sign}${round(a / 1000):,}K"
    if a >= 1:
        text = f"{a:,.2f}"
        return f"{sign}${text[:-3] if text.endswith('.00') else text}"
    return f"{sign}${a.quantize(Decimal('0.0001')).normalize():f}"
