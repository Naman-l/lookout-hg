"""Read the price lists out of the quotes (emails and their PDFs) into offers, with the conditions that come with each price.

Defect: prices sit in free text and PDF tables in six formats: per piece and per 1,000 in one document, euros with decimal commas,
several quantity breaks per part, a lead time that holds only after an event ("60 days after PPAP approval"), a duty clause
outside the price, and a correction that replaces an older number still quoted below it.
Rule: a quote is turned into offers by an extractor, and the extractor's work is a record file, `extractions/<message>.yaml`, one
offer per entry with the exact line of the document it was read from. This step replays those files with no model and no key,
and **checks every price in code**: the cited line must be in the document, the raw price must be on it, and the offer's part (or
the supplier's model number) must stand within 40 lines before it (or in the email's subject). A record names the supplier only when the document
writes a name the master does not hold (a rename, a sender not yet in the master); that name must be in the document. Otherwise the master's name is used. A record that fails stops the build, naming the line. Per-1,000
prices are divided; a stated correction supersedes the quoted original (kept, marked superseded_by); an offer from a blocked
message is kept with trust 'blocked' and never compared. A quote with no record file is not turned into offers. A record produced
by the model-assisted extractor (`python -m app.domain.imports.extract`) is not loaded until a person has marked it reviewed.
A record may also carry an `alternative_site` (the site, a sentence that says what it makes and from when, and the exact email lines it is read from): the lines are checked in the email on every build and the site is added to the offer's conditions, so a comparison shows where else the supplier could build it.
Consequence if ignored: a per-1,000 price read as per piece; a corrected price still used; a Vietnam price compared with a
Yunzhan one without the 60 days after PPAP and the magnets that come from China.
"""
import re
from pathlib import Path

import pandas as pd
import yaml

from app.domain.imports.context import examples
from app.domain.imports.extraction import document_lines, verify
from app.domain.inbox import trust as trust_rules

COLS = ["message_id", "source", "line_ref", "quote_no", "identity_id", "supplier_name", "part_number", "supplier_model", "qty_break",
        "price_raw", "price", "currency", "price_basis", "unit_price_each", "incoterm", "incoterm_place", "origin_claim", "origin_iso",
        "lead_time", "lead_time_condition", "lead_time_days", "validity_date", "moq", "annual_qty", "tooling_usd", "surcharge_pct", "surcharge_included", "payment_terms", "prepayment", "available_from",
        "conditions", "superseded_by", "trust"]


# A message that quotes prices: it carries a quotation as an attachment, or states two or more amounts in money.
MONEY = re.compile(r"(?:USD|EUR|US\$|\$|€)\s*\d[\d,.]*\d")


def looks_like_a_quote(row) -> bool:
    return (isinstance(row.attachments, str) and "quot" in row.attachments.lower()) or len(MONEY.findall(row.body or "")) >= 2


def run(ctx):
    msgs = ctx.t["messages"].set_index("id")
    master = ctx.t["supplier_identities"].set_index("id").name.to_dict()      # a supplier is called what the master calls it, unless the document names it differently
    rows, waiting, recorded = [], [], set()
    for path in sorted((Path(__file__).resolve().parent.parent / "extractions").glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        mid = doc["message"]
        if mid not in msgs.index:       # the message was never read (it is after the data horizon): nothing to extract
            continue
        if doc.get("by") != "transcribed" and not doc.get("reviewed"):
            waiting.append(mid)
            continue
        first = len(rows)
        recorded.add(mid)
        for rec in doc["offers"]:
            problem = verify(rec, document_lines(ctx.data, rec["source"], msgs.loc[mid, "body"]), msgs.loc[mid, "subject"] if rec["source"] == "email" else "")
            assert problem is None, f"{path.name}: {problem}"
            if rec.get("annual_qty"):      # the supplier's own estimate of a year's use, printed in its table: it must be in the document next to the part
                doc = document_lines(ctx.data, rec["source"], msgs.loc[mid, "body"])
                assert f"{int(rec['annual_qty']):,}" in doc, f"{path.name}: the annual quantity {rec['annual_qty']:,} is not in the document"
            alt = rec.get("alternative_site")
            if alt:      # another site the supplier says it builds at or is qualifying: the lines it is read from must be in the email, checked on every build
                body_lines = {" ".join(l.split()) for l in (msgs.loc[mid, "body"] or "").splitlines()}
                missing = [l for l in alt["lines"] if " ".join(l.split()) not in body_lines]
                assert not missing, f"{path.name}: the alternative site is not on the lines it cites: {missing}"
                rec = {**rec, "conditions": (rec.get("conditions", "").rstrip() + " " if rec.get("conditions") else "") + f"Alternative site: {alt['note']}"}
            row = dict.fromkeys(COLS)
            row.update({k: v for k, v in rec.items() if k in COLS and k != "superseded_by"})
            row["supplier_name"] = rec.get("supplier_name") or master.get(msgs.loc[mid, "identity_id"])
            assert row["supplier_name"], f"{path.name}: the sender is not in the supplier master, so the record must give the supplier's name as the document writes it"
            row.update(message_id=mid, identity_id=msgs.loc[mid, "identity_id"] if pd.notna(msgs.loc[mid, "identity_id"]) else None, trust=msgs.loc[mid, "trust"],
                       price_basis=rec.get("price_basis", "each"), currency=rec.get("currency", "USD"))
            row["unit_price_each"] = row["price"] / 1000 if row["price_basis"] == "per_1000" else row["price"]
            row["_replaced_by"] = rec.get("superseded_by")
            rows.append(row)
        for r in rows[first:]:          # a correction: the quoted original points at the offer that replaces it
            want = r.pop("_replaced_by")
            r["superseded_by"] = None
            if want:
                hit = [i for i, o in enumerate(rows[first:], first + 1) if o["part_number"] == want["part_number"] and o["qty_break"] == want["qty_break"] and o["price_raw"] == want["price_raw"]]
                assert len(hit) == 1, f"{path.name}: the correction {want} is not one of the offers"
                r["superseded_by"] = hit[0]
    df = pd.DataFrame(rows, columns=COLS)
    df.insert(0, "id", range(1, len(df) + 1))
    df["superseded_by"] = df.superseded_by.astype("Int64")
    ctx.t["offers"] = df

    # A price far above what Halden last paid for the part is a reason to look, whoever sent it (inbox.trust). Dollars each only, so the units agree.
    last_paid = ctx.t["reference_prices"].set_index("part_number").usd_each.to_dict()
    mt = ctx.t["messages"]
    for r in df[(df.currency == "USD") & df.part_number.notna()].itertuples():
        if trust_rules.price_far_above_history(r.unit_price_each, last_paid.get(r.part_number)):
            i = mt.index[mt.id == r.message_id][0]
            flags = [f for f in (mt.at[i, "trust_flags"] or "").split(",") if f]
            if "price_far_above_history" not in flags:
                flags.append("price_far_above_history")
                mt.at[i, "trust_flags"] = ",".join(flags)
                mt.at[i, "trust"] = trust_rules.verdict(flags)

    ctx.issue("quotes.prices_in_free_text", "quotes/", "Prices and conditions that exist only in emails and PDFs, in six formats (each, per 1,000, EUR with decimal commas, quantity breaks)",
              len(df), "infer", "Each offer is a record in recipes/halden/extractions/ with the exact line it was read from. The build replays the records with no model and checks every price in code: "
              "the line is in the document, the raw price is on it, and the part stands before it. Per-1,000 prices are divided; a lead time keeps its condition.",
              "No price list exists in the ERP: without this, comparing two suppliers' quotes has nothing to compare, and a per-1,000 price reads as per-piece.",
              examples(df.supplier_name + " " + df.part_number.fillna("?") + " " + df.price_raw, 3, " | "), "@parts:" + ",".join(sorted(set(df.part_number.dropna()))))
    unread = [r.Index for r in msgs.itertuples() if r.Index not in recorded and r.Index not in waiting and looks_like_a_quote(r)]
    ctx.issue("quotes.not_extracted", "quotes/", "Messages that quote prices but have no extraction record", len(unread), "flag",
              "Not turned into offers: a quote becomes offers only through an extraction record. Run `python -m app.domain.imports.extract <message id>`, read the record against the document, set reviewed: true.",
              "A supplier's quote that no one read into the system is invisible to every comparison and every expiry date.", examples(unread), "ERP admin")
    ctx.issue("quotes.extraction_awaiting_review", "quotes/", "Extraction records produced by the model that no person has reviewed yet", len(waiting), "leave",
              "Not loaded: a record with `by: model` becomes offers only after a person sets `reviewed: true`.",
              "A price the model misread would be compared as if the supplier had said it.", examples(waiting), "ERP admin")
    sup = df[df.superseded_by.notna()]
    ctx.issue("quotes.corrected_price", "quotes/", "A price corrected in a later message while the old number stays quoted below it", len(sup), "flag",
              "The correction becomes the offer; the quoted original is kept with superseded_by pointing at it.",
              "Using the quoted line instead of the correction misstates the price by the difference of the two numbers.",
              examples(sup.part_number + " at " + sup.qty_break.astype(str) + ": " + sup.price_raw + " -> " + df.set_index("id").loc[sup.superseded_by.astype(int)].price_raw.values),
              "@parts:" + ",".join(sorted(set(sup.part_number.dropna()))))
    cond = df[df.conditions.fillna("").str.contains("duty|Duty|duties")]
    ctx.issue("quotes.duty_outside_price", "quotes/", "Quotes whose headline price leaves out the new duty", len(cond), "flag",
              "The condition is stored beside each price (conditions) and the landed cost adds the duty by tariff rule and Incoterm.",
              "The cheaper headline price can cost more landed: a Chinese-origin offer plus the duty is not comparable with another origin plus none.",
              examples(cond.supplier_name.unique()), "@parts:" + ",".join(sorted(set(cond.part_number.dropna()))))
