"""Quotes that exist only in mail, read into records that cite their line, checked against the line on every build.

Defect: three quotes are only in the inbox, not in the CS tracker: the Tumkur site's three crusher quotes, the 220 kV GIS offer for BESS Chorniya
(validity 30 days from the offer, price variation by formula), and a cement spot offer from a sender not in the master.
Rule: each offer is a record in recipes/<customer>/extractions/<message>.yaml, transcribed once and marked reviewed, citing the line its price is on.
On every build code checks that the message exists, that the cited line holds the price as written, and (for a validity counted in days) dates it
from the message. A record that fails stops the build, naming the line. The offer's vendor is its SAP code where it has one; a held message's
offer is kept as its claim.
Consequence if ignored: a quote the CS never saw is missing from L1 and from the comparison with the last price; or a price is read from the wrong line.
"""
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yaml

HERE = Path(__file__).resolve().parents[1] / "extractions"


def run(ctx):
    msgs = ctx.t["messages"].set_index("id")
    rec = ctx.t["supplier_records"]
    ident = dict(zip(rec.record_id, rec.identity_id))
    projects = dict(zip(ctx.t["projects"].name, ctx.t["projects"].id))
    rows, n = [], 0
    for f in sorted(HERE.glob("*.yaml")):
        doc = yaml.safe_load(f.read_text())
        if doc["message"] not in msgs.index:
            continue      # a message after the data date: its offers do not exist yet
        assert doc.get("reviewed"), f"{f.name}: not reviewed by a person; it is not loaded"
        m = msgs.loc[doc["message"]]
        lines = m.body.splitlines()
        sent = date.fromisoformat(m.date[:10])
        for o in doc["offers"]:
            k = int(o["line"][1:])
            assert 0 < k <= len(lines) and o["raw"] in lines[k - 1], f"{f.name}: {o['raw']!r} is not on line {o['line']}"
            if "validity_days" in o:
                vk = int(o["validity_line"][1:])
                assert str(o["validity_days"]) in lines[vk - 1], f"{f.name}: '{o['validity_days']} days' is not on line {o['validity_line']}"
                valid = (sent + timedelta(days=int(o["validity_days"]))).isoformat()
            else:
                valid = o.get("validity")
            n += 1
            rows.append(dict(id=f"M{n}", source="mail", cs_no=None, project_id=projects.get(o.get("project")), pr_no=None, pr_item=None, pr_line_id=None,
                             material=o.get("material"), record_id=o.get("record_id"), identity_id=ident.get(o.get("record_id")), vendor_name=o["vendor_name"],
                             rfq_sent=None, quote_date=sent.isoformat(), qty=o.get("qty"), uom=o.get("uom"), rate=float(o["rate"]), rate_raw=o["raw"], validity=valid,
                             price_basis=o.get("price_basis"), pv_formula=o.get("pv_formula"), l1=0, last_po_rate_printed=None, budget_rate_printed=None,
                             cs_status="Not in a CS yet", approved_by=None, approved_on=None, buyer_id=None, remarks=f"from the mail of {sent.isoformat()}",
                             message_id=doc["message"], line_ref=o["line"], src_row=None))
    if rows:
        ctx.t["quotes"] = pd.concat([ctx.t["quotes"], pd.DataFrame(rows).dropna(axis=1, how="all")], ignore_index=True)      # a column the mail has no value for stays empty
    ctx.issue("quotes.only_in_mail", "inbox", "Quotes that exist only in mail, not in the CS tracker", len(rows), "infer",
              "Read into records that cite their line (transcribed, reviewed); the price is checked on its line on every build.",
              "A quote the CS never saw is missing from L1 and from the comparison with the last price.",
              "; ".join(f"{r['vendor_name']} {r['rate_raw']}" for r in rows[:3]), "Varun")
