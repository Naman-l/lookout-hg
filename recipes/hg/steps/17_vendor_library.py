"""The approved-vendor library (an Excel outside SAP), linked to the SAP vendor records; vendors ordered from outside it flagged.

Defect: the library and SAP share no key. Most library rows carry no SAP code (a vendor approved but never created in SAP, or a code never
written back); some carry a GSTIN. And in the verticals the library covers, some POs go to vendors it does not list.
Rule: a row is linked to a SAP record by the code it carries, else by GSTIN, else by the same name once legal words are set aside; a row with no
match stays unlinked (approved, not in SAP). A company is in the library when any of its records is linked to a row of the vertical. A PO line of
a covered vertical, for a material category the library approves vendors for there (answers.yaml), to a company the library does not list for that
vertical is flagged `not_in_library`.
Consequence if ignored: the library cannot say who is approved for what, and an order to an unapproved vendor goes unseen.
"""
import pandas as pd

from app.domain.imports.helpers import add_flag, iso, norm_name, parse_dmy


def run(ctx):
    lib = ctx.t["raw_vendor_library"]
    rec = ctx.t["supplier_records"]
    codes, by_gstin = set(rec.record_id), dict(zip(rec.gstin.dropna(), rec.record_id))
    by_name = dict(zip(rec.name.map(norm_name), rec.record_id))
    linked, method = [], []
    for code, gstin, name in zip(lib["SAP Vendor Code"], lib.GSTIN, lib["Vendor Name"]):
        if code and code in codes:
            linked.append(code), method.append("sap_code")
        elif gstin and gstin in by_gstin:
            linked.append(by_gstin[gstin]), method.append("gstin")
        elif norm_name(name) in by_name:
            linked.append(by_name[norm_name(name)]), method.append("name")
        else:
            linked.append(None), method.append("none")
    out = pd.DataFrame(dict(id=lib["Sr. No."].astype(int), vertical=lib.Vertical, sub_vertical=lib["Sub Vertical"], name=lib["Vendor Name"], category=lib.Category,
                            city=lib.City.replace("", None), state=lib.State, gstin=lib.GSTIN.replace("", None), approved_on=lib["Approved On"].map(lambda s: iso(parse_dmy(s))), status=lib.Status,
                            record_id=linked, link_method=method, sap_code_raw=lib["SAP Vendor Code"].replace("", None), src_row=lib.src_row))
    ctx.t["vendor_library"] = out
    ident = dict(zip(rec.record_id, rec.identity_id))
    covered = ctx.answers["library_verticals"]
    listed = {(ident[r], covered[v]) for r, v in zip(out.record_id, out.vertical) if r}
    po = ctx.t["po_lines"]
    vert = dict(zip(ctx.t["projects"].id, ctx.t["projects"].vertical))
    cat = dict(zip(ctx.t["materials"].code, ctx.t["materials"].category))
    cats = ctx.answers["library_categories"]
    mask = po.apply(lambda l: vert.get(l.project_id) in cats and cat.get(l.material) in cats[vert.get(l.project_id)]
                    and (l.identity_id, vert.get(l.project_id)) not in listed, axis=1)
    add_flag(po, mask, "not_in_library")
    names = dict(zip(rec.record_id, rec.name))
    outside = sorted({names[r] for r in po[mask].record_id})
    ctx.issue("library.not_in_sap", "sheets/Vendor Library", "Library vendors with no SAP vendor record", int((out.link_method == "none").sum()), "leave",
              "Kept as approved-but-not-registered; linked when a code, GSTIN or name ties them.", "The library cannot say which approved vendors SAP can order from.",
              "; ".join(out[out.link_method == "none"].name.head(3)), "Varun")
    ctx.issue("library.ordered_outside", "sap/ME2N_purchase_orders.csv", "PO lines to vendors the library does not list for the vertical", int(mask.sum()), "flag",
              "Flagged `not_in_library` on each line; the vendors are named for the vertical lead.", "An order to an unapproved vendor goes unseen.",
              "; ".join(outside[:4]), "@groups:" + ",".join(sorted(set(po[mask].purch_group))))
