"""Record when each source was exported or built, by its own stamp, and say which are older than the recipe allows.

Defect: the sources were taken on different days. SAP exports carry their stamp in the first line; hand-built sheets in the file name (the
October fund requirement was built on 18 Sep, a month before the SAP exports it is set against); the vendor library was last saved on 3 Oct.
Rule: the stamp is read from the file (never its modified time); age = data date minus stamp; a source the recipe judges (not a reference table
such as the DoA or the project directory) is stale when older than `stale_after_days` (7). Stale sources are shown with their date wherever their
figures appear; nothing is dropped.
Consequence if ignored: a fund figure built a month ago is read as this week's, beside SAP numbers from today.
"""
from datetime import date, datetime

import pandas as pd

from app.domain.imports.helpers import parse_export_stamp, stamp_in_name


def run(ctx):
    limit = int(ctx.answers.get("stale_after_days", 7))
    rows = []
    for f in ctx.t["_files"].itertuples():
        raw, by = None, None
        when = None
        if f.stamp == "header":
            st = parse_export_stamp(f.first_line)
            raw, by = f.first_line, st["user"]
            when = st["exported_at"]
            if not when:      # an index file's own line: "compiled 15.10.2026"
                import re
                m = re.search(r"(\d{2}\.\d{2}\.\d{4})", f.first_line)
                when = datetime.strptime(m.group(1), "%d.%m.%Y").date().isoformat() if m else None
        elif f.stamp == "name":
            d = stamp_in_name(f.file.split("/")[-1])
            raw, when = f.file.split("/")[-1], d.isoformat() if d else None
        day = date.fromisoformat(when[:10]) if when else None
        age = (ctx.as_of - day).days if day else None
        judged = int(f.kind != "reference")
        rows.append(dict(file=f.file, key=f.key, kind=f.kind, title=f.title, stamped_at=when, stamp_raw=raw, stamped_by=by, rows=int(f.rows), age_days=age,
                         judged=judged, stale=int(bool(judged and age is not None and age > limit))))
    inbox = ctx.find(ctx.answers["sources"]["inbox"]["glob"])
    rows.append(dict(file="inbox/", key="inbox", kind="inbox", title=ctx.answers["sources"]["inbox"]["title"], stamped_at=None, stamp_raw=None, stamped_by=None,
                     rows=len(inbox), age_days=None, judged=0, stale=0))
    df = pd.DataFrame(rows)
    df["age_days"] = df.age_days.astype("Int64")
    ctx.t["sources"] = df
    stale = df[df.stale == 1]
    ctx.issue("sources.stale", "sheets", f"Sources older than {limit} days at the data date (a fund sheet older than the SAP exports)", len(stale), "flag",
              f"Kept and marked stale: each figure from them shows the date its source was built.",
              "A month-old fund or library figure is read as current, beside today's SAP exports.",
              "; ".join(f"{r.title} {r.stamped_at} ({r.age_days} days)" for r in stale.sort_values("age_days", ascending=False).head(3).itertuples()), "Sudeep")
