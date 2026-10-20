"""Find open orders that are probably not open: more than a year old and still unreceived.

Defect: three lines placed in 2024-2025 on the legacy ERP are still OPEN, 490-553 days past promise (Tern T1 motors
and a lidar). They may have been delivered and never closed, or cancelled and never marked.
Rule: an OPEN or PARTIAL line ordered more than 365 days before AS_OF is flagged stale_open. It stays in the data,
leaves open supply and the net tariff figure (it is counted in the gross figure), and is raised once as an unknown
with an owner, not as a past-due line.
Consequence if ignored: 150 phantom motors in HR-40010's supply, and three lines at the top of every past-due list.
"""
from datetime import timedelta

from app.domain.common import AS_OF
from app.domain.imports.context import examples
from app.domain.imports.helpers import add_flag

STALE_DAYS = 365


def run(ctx):
    df = ctx.t["po_lines"]
    cutoff = (AS_OF - timedelta(days=STALE_DAYS)).isoformat()
    stale = df.status.isin(["OPEN", "PARTIAL"]) & (df.order_date < cutoff)
    add_flag(df, stale, "stale_open")
    s = df[stale]
    ctx.issue("po.stale_open", "purchase_orders.csv", "Orders more than a year old that are still open", len(s), "flag",
              f"Flag stale_open (ordered more than {STALE_DAYS} days before 2026-09-25). They leave open supply and the net tariff figure; each is raised once as an unknown.",
              "They inflate supply and sit at the top of the past-due list, a year or more late.",
              examples(s.id + " " + s.part_number + " promised " + s.promised_date.fillna("?")), "@parts:" + ",".join(s.part_number))
