"""The October payment projection: party, project, RTGS and LC amounts in rupees, and what each payment term says.

Defect: the sheet is in rupees, but two amounts were typed with a unit ("2.64 Cr" for the IDT advance; "45 L" for engineering payments), and the
party is often the vendor's first word only ("Kalinga", "Huaxin").
Rule: each amount is read in the unit it names (raw kept); a party is the SAP vendor whose name starts with the same words when exactly one does,
else none; the term is read for an advance percentage, an ABG, an LC deadline (its date), payment before dispatch, or a PV payment.
Consequence if ignored: "2.64 Cr" read as ₹2.64 understates an advance by ten million times; a payment cannot be tied to its vendor or its LC.
"""
import re

import pandas as pd

from app.domain.imports.helpers import iso, norm_name, parse_dmy, parse_inr


def _vendor(party: str, names: dict) -> str | None:
    p = norm_name(party)
    hits = [code for n, code in names.items() if n == p or n.startswith(p + " ")]
    return hits[0] if len(hits) == 1 else None


def run(ctx):
    if "raw_payment_projection" not in ctx.t:      # built after the data date (step 02): not read
        return
    r = ctx.t["raw_payment_projection"]
    alias = {a.alias: a.project_ids for a in ctx.t["project_aliases"].itertuples() if a.source == "payment_projection"}
    names = {norm_name(n): c for n, c in zip(ctx.t["supplier_records"].name, ctx.t["supplier_records"].record_id)}
    odd, rows = [], []
    for _, x in r.iterrows():
        rt, ru = parse_inr(x.RTGS) if x.RTGS.strip() else (None, "")
        lc, lu = parse_inr(x.LC) if x.LC.strip() else (None, "")
        for raw, u in ((x.RTGS, ru), (x.LC, lu)):
            if u in ("cr", "lakh"):
                odd.append(f"{x['Project Name']} / {x['Party Name']}: '{raw.strip()}'")
        terms = x['Payment Terms'].strip()
        adv = re.search(r"(\d+)%\s*Advance", terms, re.I)
        lc_by = re.search(r"LC to be opened by (\d{2}/\d{2}/\d{4})", terms, re.I)
        kind = "lc" if (lc or lc_by) else "advance" if adv else "pv" if "PV" in terms else "before_dispatch" if "dispatch" in terms.lower() else "other"
        rows.append(dict(id=int(x["Sr. No."]), project_as_printed=x["Project Name"], project_ids=alias.get(x["Project Name"]) or None, party=x["Party Name"],
                         record_id=_vendor(x["Party Name"], names), item=x["Item Name"],
                         rtgs=rt, rtgs_raw=x.RTGS.strip() or None, lc=lc, lc_raw=x.LC.strip() or None, terms_raw=terms, terms_kind=kind,
                         advance_pct=float(adv.group(1)) if adv else None, against_abg=int("abg" in terms.lower()),
                         lc_by=iso(parse_dmy(lc_by.group(1))) if lc_by else None, src_row=int(x.src_row)))
    df = pd.DataFrame(rows)
    projects = dict(zip(ctx.t["projects"].name, ctx.t["projects"].id))
    df["project_ids"] = [p or projects.get(n) for p, n in zip(df.project_ids, df.project_as_printed)]
    ctx.t["payment_projection"] = df
    ctx.issue("projection.mixed_units", "sheets/Payment Projection", "Amounts typed in Cr or Lakh in a sheet that is in rupees", len(odd), "fix",
              "Each amount read in the unit it names; raw text kept.", "\"2.64 Cr\" read as ₹2.64; a projection total off by crores.", "; ".join(odd[:3]), "Sudeep")
