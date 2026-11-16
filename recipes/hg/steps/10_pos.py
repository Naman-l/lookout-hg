"""Purchase and work orders from ME2N: vendor, project, owner, dates, the price-variation clause and the terms of payment.

Defect: the PV clause is one text field ("IEEMA-ACSR | Base 01/2026 | Variable 75%"), and the document type says whether a line is a supply PO,
a work order or an import PO.
Rule: the vendor's company is its record's identity; the project is the plant's; the owner is the purchasing group's member; the PV clause is read
into its index, base month and variable share (raw kept); dates to ISO (raw kept). The rate per base unit and the value are set from the net
price as SAP holds it, per price unit (step 11) and per order unit (step 12).
Consequence if ignored: a PV claim cannot be checked against its own clause, and a work order's supply reads like a service.
"""
import re

import pandas as pd

from app.domain.imports.helpers import iso, parse_dmy


def _pv(raw: str) -> tuple:
    if not raw.strip():
        return None, None, None
    idx = re.match(r"\s*([A-Z0-9-]+)", raw).group(1).replace("-", "_")
    base = re.search(r"Base (\d{2})/(\d{4})", raw)
    share = re.search(r"Variable (\d+)%", raw)
    return idx, f"{base.group(2)}-{base.group(1)}" if base else None, int(share.group(1)) / 100 if share else None


def run(ctx):
    r = ctx.t["raw_me2n"]
    ident = dict(zip(ctx.t["supplier_records"].record_id, ctx.t["supplier_records"].identity_id))
    by_plant = {p.plant: p.project_id for p in ctx.t["project_plants"].itertuples()}
    owner = dict(zip(ctx.t["purchasing_groups"].code, ctx.t["purchasing_groups"].person_id))
    base = dict(zip(ctx.t["materials"].code, ctx.t["materials"].base_uom))
    d = lambda col: r[col].map(lambda s: iso(parse_dmy(s)))  # noqa: E731
    pv = r["PV Index"].map(_pv)
    qty, price = r["Order Quantity"].astype(float), r["Net Price"].astype(float)
    po = pd.DataFrame(dict(id=r["Purchasing Document"] + "/" + r.Item, po_no=r["Purchasing Document"], item=r.Item.astype(int), doc_type=r["Document Type"],
                           record_id=r.Supplier, identity_id=r.Supplier.map(ident), material=r.Material, short_text=r["Short Text"], qty=qty,
                           qty_raw=r["Order Quantity"], uom=r["Order Unit"], uom_raw=r["Order Unit"], qty_base=qty, base_uom=r.Material.map(base),
                           net_price=price, net_price_raw=r["Net Price"], price_unit=r["Price Unit"].astype(int), price_unit_raw=r["Price Unit"],
                           rate_base=price, currency=r.Currency, value=qty * price, doc_date=d("Document Date"), doc_date_raw=r["Document Date"],
                           delivery_date=d("Delivery Date"), delivery_date_raw=r["Delivery Date"], plant=r.Plant, project_id=r.Plant.map(by_plant),
                           purch_group=r["Purchasing Group"], buyer_id=r["Purchasing Group"].map(owner), created_by=r["Created By"],
                           pr_no=r["Purchase Requisition"].replace("", None), pr_item=r["Item of Requisition"].map(lambda s: int(s) if s.strip() else None),
                           pr_line_id=None, validity_end=d("Validity Per. End"), validity_end_raw=r["Validity Per. End"],
                           pv_clause=(r["PV Clause"] == "Y").astype(int), pv_index=pv.str[0], pv_base_month=pv.str[1], pv_variable_share=pv.str[2],
                           pv_raw=r["PV Index"].replace("", None), payment_terms=r["Terms of Payment"], received_base=0.0, open_base=qty, open_value=qty * price,
                           status="open", flags="", src_row=r.src_row))
    unknown = po[po.identity_id.isna()]
    assert unknown.empty, f"PO lines whose vendor is not in the master: {unknown.id.head().tolist()}"
    ctx.t["po_lines"] = po
