"""Name the buyer who owns each part, so every open question has an owner.

Defect: the item master has no buyer column; the data README names buyers by category.
Rule: a part's buyer is the one who placed most of its PO lines (ties: the most recent); a part with no lines takes
its category's buyer from the README (answers.yaml). Both are marked buyer_method 'inferred'. A finished good or
sub-assembly has no buyer.
Consequence if ignored: 'unknown origin' has no one to ask.
"""


def run(ctx):
    parts, po = ctx.t["parts"], ctx.t["po_lines"].sort_values("order_date")

    def modal(s):
        vc = s.value_counts()
        tied = set(vc[vc == vc.max()].index)
        for b in reversed(list(s)):
            if b in tied:
                return b

    by_part = po.groupby("part_number").buyer_id.agg(modal)
    default = parts.category.map(ctx.answers["category_buyer"])
    parts["buyer_id"] = parts.part_number.map(by_part).fillna(default)
    parts["buyer_method"] = ["inferred" if b == b and b is not None else None for b in parts.buyer_id]
    parts.loc[parts.kind != "purchased", ["buyer_id", "buyer_method"]] = None
