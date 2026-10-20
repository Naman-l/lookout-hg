"""Flag lines placed on supplier records the ERP marks Inactive or On hold.

Defect: 31 lines sit on non-active records (16 Saltmarsh, On hold; 14 legacy Quenvara, Inactive; 1 Kettleby, Inactive).
Rule: flag non_active_supplier; the record's status is shown next to the line. The lines are real purchases and stay.
Consequence if ignored: a record that should not be used looks like a normal source, and Saltmarsh, the sender of
the spot offer aimed at AI assistants, looks like an established supplier.
"""
from app.domain.imports.context import examples
from app.domain.imports.helpers import add_flag


def run(ctx):
    df = ctx.t["po_lines"]
    rec = ctx.t["supplier_records"].set_index("record_id")
    bad = df.record_id.map(rec.status) != "Active"
    add_flag(df, bad, "non_active_supplier")
    b = df[bad]
    ctx.issue("po.non_active_supplier", "purchase_orders.csv", "Lines on supplier records that are Inactive or On hold", len(b), "flag",
              "Flag non_active_supplier; kept.", "Orders placed with suppliers the ERP says not to use.",
              examples(b.record_id.map(rec.name) + " (" + b.record_id.map(rec.status) + ")"), "@suppliers:" + ",".join(sorted(set(b.identity_id))))
