"""Vendor records from the SAP vendor master; one identity per company, a renamed company's two codes linked, never merged.

Defect: one vendor is in the master twice: Sai Krupa Rail Fittings (its old code, with open orders) and SKR Railtech Pvt Ltd, created on 10 Sep
2026 when the firm became a company, with a new GSTIN. Nothing in SAP ties the two codes.
Rule: every record is kept as SAP has it (MSME, block and dates normalised, raw kept); each record is its own company unless a person's answer
links it to an existing one (with the evidence). The identity keeps the first code; its name is the newest record's.
Consequence if ignored: the company's spend, delivery record and open orders are split across two vendors, and a mail from the new entity reads
as a stranger's.
"""
import pandas as pd

from app.domain.imports.helpers import iso, parse_dmy


def run(ctx):
    v = ctx.t["raw_vendor_master"]
    links = {a["record"]: a for a in ctx.answers.get("vendor_aliases") or []}
    links.update({str(l["supplier_b"]): {"identity": str(l["supplier_a"]), "evidence": l.get("evidence") or "approved in the ledger"} for l in ctx.answers.get("approved_links") or []})
    rec = pd.DataFrame(dict(record_id=v.Vendor, identity_id=[links[c]["identity"] if c in links else c for c in v.Vendor],
                            identity_method=["answer" if c in links else "stated" for c in v.Vendor],
                            identity_evidence=[links[c]["evidence"] if c in links else None for c in v.Vendor],
                            name=v["Name 1"], gstin=v.GSTIN.replace("", None), pan=v.PAN.replace("", None), msme=(v.MSME == "Y").astype(int), msme_raw=v.MSME,
                            udyam=v["Udyam Reg. No."].replace("", None), city=v.City, region=v.Region, bank_masked=v["Bank Account"], contact_name=v["Contact Person"],
                            contact_email=v["E-Mail Address"].str.lower(), email_domain=v["E-Mail Address"].str.split("@").str[1].str.lower(),
                            phone=v.Telephone, blocked=(v["Payment Block"].str.strip() != "").astype(int),
                            created_on=v["Created On"].map(lambda s: iso(parse_dmy(s))), created_on_raw=v["Created On"], src_row=v.src_row))
    ctx.t["supplier_records"] = rec
    newest = rec.assign(_d=rec.created_on.fillna("")).sort_values("_d").groupby("identity_id").last()
    ident = pd.DataFrame(dict(id=newest.index, name=newest.name.values, n_records=rec.groupby("identity_id").size().reindex(newest.index).values))
    ctx.t["supplier_identities"] = ident
    two = rec[rec.identity_method == "answer"]
    ctx.issue("vendors.two_codes", "sap/vendor_master.csv", "One vendor under two codes (a firm renamed to a new company)", len(two), "link",
              "Linked by a person's answer with the evidence; both codes and both GSTINs are kept, nothing is merged.",
              "Spend, delivery record and open orders split across two vendors; a mail from the new entity reads as a stranger's.",
              "; ".join(f"{r.record_id} {r.name} -> {r.identity_id}" for r in two.itertuples()), "Deepanshu")
