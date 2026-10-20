"""Parse both ERPs' date formats; keep the text; flag open lines with no promise date and received dates before the order.

Defect: the legacy ERP writes MM/DD/YYYY, the new one ISO; 5 open lines have no promised date at all; some closed lines
carry a received date earlier than their order date (a typo in the year, not a delivery before the order).
Rule: every date -> ISO text, the raw string kept beside it; a blank stays blank. An open line without a promise
date is flagged no_promise_date and is never counted as on time or late by date. A line received before it was
ordered is flagged received_before_ordered: the date is kept as typed, shown as unknown on the line's stages, and never
used as a delivery.
Consequence if ignored: '03/04/2025' read as 3 April instead of 4 March; the five lines never appear as past due; a
line shown as delivered a year before it was ordered.
"""
from app.domain.imports.context import examples
from app.domain.imports.helpers import add_flag, parse_date_any


def run(ctx):
    df = ctx.t["po_lines"]
    for c in ["order_date", "promised_date", "received_date"]:
        df[c] = df[c + "_raw"].map(lambda s: (d.isoformat() if (d := parse_date_any(s)) else None))
    slash = df[df.order_date_raw.str.contains("/")]
    ctx.issue("po.date_formats", "purchase_orders.csv", "Two date formats in one file (MM/DD/YYYY legacy, ISO new)", len(slash), "fix",
              "Parse both; ISO text in the clean column, the raw string in *_raw.", "Day and month swap, or a column that cannot be sorted by date.",
              examples(slash.order_date_raw + " -> " + slash.order_date), "ERP admin")
    open_ = df.status.isin(["OPEN", "PARTIAL"])
    nodate = open_ & df.promised_date.isna()
    add_flag(df, nodate, "no_promise_date")
    n = df[nodate]
    ctx.issue("po.no_promise_date", "purchase_orders.csv", "Open PO line with no promised date", len(n), "flag",
              "Kept; flagged no_promise_date. Treated as exposed in the tariff rule and listed for the buyer.",
              "It can never be late by date, so it never reaches a past-due list.", examples(n.id), "@parts:" + ",".join(n.part_number))
    early = df.received_date.notna() & df.order_date.notna() & (df.received_date < df.order_date)
    add_flag(df, early, "received_before_ordered")
    e = df[early]
    ctx.issue("po.received_before_ordered", "purchase_orders.csv", "Lines received before they were ordered", len(e), "flag",
              "Kept as typed; flagged received_before_ordered. The date is shown as unknown on the line and is not used as a delivery.",
              "A delivery cannot precede its order: the year of the received date is a typo, so any lead time or on-time figure that used it would be wrong.",
              examples(e.id + " ordered " + e.order_date + ", received " + e.received_date), "ERP admin")
