"""The vendor ledger from FBL1N: invoices, payments and advances, each tied to its vendor and its PO.

Defect: none planted. FBL1N writes an invoice as a credit to the vendor (a negative amount) and keeps the PO only in the Assignment field.
Rule: each row kept as exported (dates to ISO, the signed amount as a number, raw kept); the PO is the Assignment.
Consequence if ignored: an MSME invoice's due date and a vendor's open balance cannot be read, and an advance cannot be tied to its guarantee.
"""
import pandas as pd

from app.domain.imports.helpers import iso, parse_dmy


def run(ctx):
    f = ctx.t["raw_fbl1n"]
    d = lambda col: f[col].map(lambda s: iso(parse_dmy(s)))  # noqa: E731
    ctx.t["vendor_ledger"] = pd.DataFrame(dict(id=f.src_row, record_id=f.Supplier, doc_no=f["Document Number"], doc_type=f["Document Type"], reference=f.Reference,
                                               po_no=f.Assignment.replace("", None), doc_date=d("Document Date"), net_due=d("Net Due Date"),
                                               amount=f["Amount in Local Currency"].astype(float), amount_raw=f["Amount in Local Currency"],
                                               clearing_doc=f["Clearing Document"].replace("", None), clearing_date=d("Clearing Date"), text=f.Text, src_row=f.src_row))
