"""Agent tools over the BOM service."""

from __future__ import annotations

from claude_agent_sdk import tool

from ...organism.context import RunContext
from ...organism.toolkit import READ, cover_numbers, plain_number, reply


def make_tools(ctx: RunContext, svc):
    @tool(
        "where_used_for_parts",
        "The same as where_used, for several parts in one call.",
        {"type": "object", "properties": {"part_numbers": {"type": "array", "items": {"type": "string"}}}, "required": ["part_numbers"]},
        annotations=READ,
    )
    async def where_used_for_parts(args):
        name = lambda r: r.product.label or r.product.id  # noqa: E731
        numbers, data = [], []
        for part in args["part_numbers"]:
            rows = svc.where_used(part)
            numbers += [plain_number(f"bom:{part}:{r.product.id}:per_robot", f"{part} per {name(r)}", r.qty_per_robot, "EA") for r in rows]
            data.append({"part": part, "used_in": [{"product": name(r), "product_id": r.product.id, "qty_per_robot": str(r.qty_per_robot)} for r in rows]})
        numbers += cover_numbers(ctx, numbers)
        return reply(ctx, f"Where used: {len(data)} parts checked", data, numbers)

    return [where_used_for_parts]
