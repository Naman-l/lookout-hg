"""Agent tools over the stage ladder: where an order or a part is between need and stock, and whether a robot build is clear.

DOMAIN builds both from records only and says "unknown" where no record exists; these wrappers keep that: an unknown stage comes back as an open question with
who to ask, grouped by person so the answer does not list nine of them, and a verdict is counts, never a percent."""

from __future__ import annotations

from collections import defaultdict

from claude_agent_sdk import tool

from ...organism import id_shapes
from ...organism.context import RunContext
from ...organism.schemas import Number
from ...organism.toolkit import READ, plain_number, plural, refuse, reply
from ..common import EntityRef, Unknown

def _owner(name: str) -> str:
    return name or "unassigned"


def _rung(r) -> dict:
    d = {"stage": r.label, "state": r.state, "date": r.date, "detail": r.detail, "source": r.source.id if r.source else None, "flag": r.flag}
    if r.unknown:
        d["ask"] = {"owner": r.unknown.owner, "question": r.unknown.question}
    return d


def unknown_stages(subject: str, rungs, is_po_line: bool = False) -> list[Unknown]:
    """One open question per person to ask, naming the stages they would answer, instead of one per stage."""
    by_owner: dict[str, list] = defaultdict(list)
    for r in rungs:
        if r.state == "unknown" and r.unknown:
            by_owner[r.unknown.owner].append(r)
    out = []
    for owner, rs in by_owner.items():
        names = ", ".join(r.label.lower() for r in rs)
        out.append(Unknown(what=f"Where {subject} is in: {names}", why_it_blocks="; ".join(r.unknown.what for r in rs)[:240], owner=_owner(owner),
                           question=" ".join(r.unknown.question for r in rs)[:300], refs=[EntityRef(type="po_line" if is_po_line else "part", id=subject)]))
    return out


def make_tools(ctx: RunContext, svc):
    @tool(
        "get_phases",
        "Where one part, or one purchase-order line, is in its life: need, quote, ordered, promised, acknowledged, at the supplier, shipped, in transit, customs, received, "
        "inspected, stocked, kitted. Each stage is done or expected (with the date and the record it comes from), late, disrupted by a supplier's notice, or UNKNOWN because "
        "nothing in the data says; an unknown stage comes with who to ask. Never infer shipping, customs or inspection from a received date. The verdict is counts. "
        "Give a part number or a PO line (its id as other tools return it), not both.",
        {"type": "object", "properties": {"part_number": {"type": "string"}, "po_line": {"type": "string"}}},
        annotations=READ,
    )
    async def get_phases(args):
        part, line = args.get("part_number"), args.get("po_line")
        if bool(part) == bool(line):
            return refuse("give exactly one of part_number or po_line")
        ladder = svc.part_phases(part) if part else svc.line_phases(line)
        if ladder is None:
            return refuse(f"nothing on record for {part or line}")
        sid = ladder.subject.id
        numbers: list[Number] = [plain_number(f"phases:{sid}:{state}", f"Stages of {sid} that are {state.replace('na', 'not applicable')}", n, "stages") for state, n in ladder.counts.items() if n]
        data = {"subject": sid, "kind": ladder.kind, "verdict": ladder.verdict, "stages": [_rung(r) for r in ladder.rungs if r.state != "na"],
                "open_lines": [{"po_line": ln.subject.id, "qty": str(ln.qty.ea if ln.qty and ln.qty.ea is not None else ln.qty.value) if ln.qty else None,
                        "promised": None if ln.promised is None else {"now": ln.promised.date, "erp": ln.promised.erp_date}, "verdict": ln.verdict,
                        "late_or_disrupted": [r.label for r in ln.rungs if r.state in ("late", "disrupted")]} for ln in ladder.lines]}
        return reply(ctx, f"{sid}: {ladder.verdict}", data, numbers, unknown_stages(sid, ladder.rungs, bool(id_shapes.pattern(ctx.db_path, "po_line", whole=True).match(sid))))

    def _readiness(product, month):
        b = svc.build_readiness(product, month)
        if b is None:
            return None
        pid = f"{b.product.id}:{b.month}"
        numbers = [plain_number(f"build:{pid}:units", f"{b.product.label or b.product.id} robots needed in {b.month}", b.units, "robots")]
        numbers += [plain_number(f"build:{pid}:{state}", f"Parts of the {b.product.label or b.product.id} {b.month} build: {state.replace('_', ' ')}", n, "parts") for state, n in b.counts.items() if n]
        problems = [p for g in b.groups for p in g.parts if p.state in ("short", "past_due", "disrupted", "after_build", "short_after_stock")]  # after_build is a problem too: the supply lands after the month ends
        unknown_by_owner: dict[str, list] = defaultdict(list)
        for g in b.groups:
            for p in g.parts:
                if p.state == "no_order" and p.ask:
                    unknown_by_owner[p.ask.owner].append(p)
        unknowns = [Unknown(what=f"Whether {plural(len(ps), 'part')} with no open order are in stock for the {b.product.label or b.product.id} {b.month} build", why_it_blocks=b.stock_note,
                            owner=_owner(o), question=f"How many of these are on the shelf: {', '.join(p.part.id for p in ps[:6])}{' and others' if len(ps) > 6 else ''}?") for o, ps in unknown_by_owner.items()]
        data = {"product": b.product.label or b.product.id, "month": b.month, "robots": b.units, "verdict": b.verdict, "stock_note": b.stock_note,
                "by_assembly": [{"assembly": g.assembly.label or g.assembly.id, "counts": g.counts} for g in b.groups],
                "needing_attention": [{"part": p.part.id, "state": p.state, "detail": p.detail, "need": str(p.need.value), "arrives": p.arrives, "supplier": p.supplier.id if p.supplier else None,
                                       "notice": p.cause.id if p.cause else None} for p in problems[:10]],
                "more_needing_attention": max(0, len(problems) - 10)}
        named = []  # the verdict is counts; the parts behind the problem counts are named, per state, so nobody reads 'not flagged' where a part is flagged (F2.2: after_build)
        for state in ("disrupted", "after_build", "past_due", "short", "short_after_stock"):
            ps = [p for p in problems if p.state == state]
            if ps:
                named.append(f"{state.replace('_', ' ')}: " + ", ".join((p.part.label or p.part.id) + f" ({p.part.id})" for p in ps[:5]) + (f" and {len(ps) - 5} more" if len(ps) > 5 else ""))
        label = f"{b.product.label or b.product.id} {b.month}"
        return f"{label}: {b.verdict}" + (" · " + " · ".join(named) if named else ""), data, numbers, unknowns

    @tool(
        "build_readiness",
        "Is a robot build clear? For one product (its name as the forecast spells it, or its part number) and one month (YYYY-MM): every bought part of the build, in what state "
        "(covered by dated supply in the month, arrives after the month, past due, under a supplier's force-majeure notice, no open order) rolled up by sub-assembly. The "
        "verdict is counts. A part with no open order is UNKNOWN unless a stock count exists, never 'covered'. Use it to answer 'is the <product> <month> build clear?'. For several months or products pass `months` / `products` in ONE call (up to 12 combinations): never one call per month.",
        {"type": "object", "properties": {"product": {"type": "string"}, "month": {"type": "string", "description": "YYYY-MM"},
                                                                                                                  "products": {"type": "array", "items": {"type": "string"}, "description": "several products at once"},
                                                                                                                  "months": {"type": "array", "items": {"type": "string"}, "description": "several months at once (YYYY-MM): one call for a whole horizon"}}},
        annotations=READ,
    )
    async def build_readiness(args):
        products = list(dict.fromkeys([*([args["product"]] if args.get("product") else []), *(args.get("products") or [])]))
        months = list(dict.fromkeys([*([args["month"]] if args.get("month") else []), *(args.get("months") or [])]))
        pairs = [(p, m) for p in products for m in months][:12]
        if not pairs:
            return refuse("give a product and a month, or lists of them")
        got = [(p, m, _readiness(p, m)) for p, m in pairs]
        missing = [f"{p} {m}" for p, m, r in got if r is None]
        done = [r for _, _, r in got if r is not None]
        if not done:
            return refuse(f"no such product or no forecast for {', '.join(missing)}")
        if len(pairs) == 1:
            return reply(ctx, *done[0])
        return reply(ctx, "; ".join(r[0] for r in done) + (f" (no forecast for {', '.join(missing)})" if missing else ""), [r[1] for r in done], [n for r in done for n in r[2]], [u for r in done for u in r[3]])

    return [get_phases, build_readiness]
