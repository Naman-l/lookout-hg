"""Read a stock count a person gave on the Import screen: how many of a part are on the shelf.

Defect: the ERP export holds no on-hand quantity, so no part can be called covered by stock; a part with nothing on order is unknown.
Rule: the card `stock:count` takes pairs `PART=QTY` (one per line or separated by semicolons; a comma or tab also works between the two). A part number is
normalised like every other; a number that is not a plain non-negative quantity, or a part that does not exist, is a counted issue and is left out. The latest
pair for a part wins. The date and the name are the answerer's, never guessed; an answer that was not given loads no counts.
Consequence if ignored: with no count every part without an open order stays unknown, which is the truth; with a wrong count a short part reads as covered.
"""
import re

import pandas as pd

from app.domain.imports.context import examples
from app.domain.imports.helpers import norm_part_number

COLS = ["part_number", "qty_on_hand", "uom", "qty_raw", "counted_on", "counted_by"]


def run(ctx):
    action, value = ctx.decision("stock:count")
    d = (ctx.answers.get("decisions") or {}).get("stock:count") or {}
    on = (d.get("at") or "2026-09-25")[:10]
    by = d.get("by") or "unknown"
    parts = ctx.t["parts"].set_index("part_number")
    rows, bad, missing = {}, [], []
    if action == "change" and value:
        for token in re.split(r"[\n;]+", value):
            token = token.strip()
            if not token:
                continue
            bits = re.split(r"\s*[=,\t:]\s*", token)
            if len(bits) != 2:
                bad.append(token)
                continue
            pn = norm_part_number(bits[0])
            if pn not in parts.index:
                missing.append(bits[0])
                continue
            q = bits[1].replace(",", "")
            if not re.fullmatch(r"\d+(\.\d+)?", q):
                bad.append(token)
                continue
            rows[pn] = dict(part_number=pn, qty_on_hand=float(q), uom=parts.loc[pn, "uom"], qty_raw=bits[1], counted_on=on, counted_by=by)
    ctx.t["stock_counts"] = pd.DataFrame(list(rows.values()), columns=COLS)
    ctx.issue("stock.pair_not_read", "stock count", "pairs in the stock count that are not PART=QTY with a plain quantity", len(bad), "flag",
              "a pair that does not read as a part and a plain non-negative quantity is left out", "that part stays unknown, not zero", examples(bad), by if by != "unknown" else "ERP admin")
    ctx.issue("stock.part_unknown", "stock count", "part numbers in the stock count that are not in the part master", len(missing), "flag",
              "a part number the master does not know is left out", "a count for an unknown part cannot be used", examples(missing), by if by != "unknown" else "ERP admin")
