"""Read the customs broker's advisory into tariff rules and exclusions, by rule, from the markdown tables.

Defect: the rules exist only as prose and two tables in a markdown advisory (docket FICT-2026-0301): a prefix covers
every longer code; the duty follows origin, not the export country; stacking counts only the new duty; goods in transit
when the duty starts are exempt in the tranches the notice names (its "goods in transit" item), and not in the others; two
exclusions beat the prefixes.
Rule: parse the rule table and the exclusions into rows; the origin is CN for every rule; the in-transit window (exported
before, entered before) is read from the notice's own sentence and stored as two dates on the rules of the tranche it names.
The advisory is read only from the day it was issued: a build dated earlier has no rules and no exclusions. The build stops if an
issued advisory has no rules or exclusions, or if the notice names an in-transit window it cannot parse.
Consequence if ignored: 'does this part owe the new duty' is answered from memory.
"""
import re

import pandas as pd


def run(ctx):
    text = (ctx.data / "external" / "tariff_notice.md").read_text(encoding="utf-8")
    issued = re.search(r"Issued (\d{4}-\d{2}-\d{2})", text)
    if issued and issued.group(1) > ctx.as_of.isoformat():   # not published yet: no rules, no exclusions
        ctx.t["tariff_rules"] = pd.DataFrame(columns=["id", "tranche", "hts_prefix", "hts_prefix_raw", "description", "rate", "effective_date", "origin",
                                                      "in_transit", "exported_before", "entered_before", "source_line", "advisory_no", "issued", "exclusion_contact_by"])
        ctx.t["tariff_exclusions"] = pd.DataFrame(columns=["hts_prefix", "hts_prefix_raw", "description"])
        return
    advisory = re.search(r"Advisory ([A-Z0-9-]+)", text)
    window = {}
    for m in re.finditer(r"Tranche (\d) goods exported from [\w ]+? before (\d{4}-\d{2}-\d{2}) and entered before (\d{4}-\d{2}-\d{2})", text):
        window[int(m.group(1))] = (m.group(2), m.group(3))
    assert ("in transit" not in text.lower()) or window, "the notice mentions goods in transit but no window could be read"
    rules = []
    for m in re.finditer(r"^\|\s*(\d)\s*\|\s*([\d.]+)\s*\|\s*(.+?)\s*\|\s*(\d+)%\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|", text, re.M):
        tr, prefix, desc, rate, eff = m.groups()
        exported, entered = window.get(int(tr), (None, None))
        rules.append(dict(id=len(rules) + 1, tranche=int(tr), hts_prefix=re.sub(r"\D", "", prefix), hts_prefix_raw=prefix,
                          description=desc, rate=int(rate) / 100, effective_date=eff, origin="CN",
                          in_transit=(f"Exported from China before {exported} and entered before {entered}: not subject." if exported else "No in-transit provision."),
                          exported_before=exported, entered_before=entered, source_line=" ".join(m.group(0).split()), advisory_no=advisory.group(1) if advisory else None,
                          issued=issued.group(1) if issued else None))
    excl = [dict(hts_prefix=re.sub(r"\D", "", p), hts_prefix_raw=p, description=d.strip())
            for p, d in re.findall(r"^- ([\d.]+): (.+)$", text, re.M)]
    contact = re.search(r"before (\d{4}-\d{2}-\d{2}) if you want to discuss exclusion", text)
    for r in rules:
        r["exclusion_contact_by"] = contact.group(1) if contact else None
    assert rules and excl, (len(rules), len(excl))
    ctx.t["tariff_rules"] = pd.DataFrame(rules)
    ctx.t["tariff_exclusions"] = pd.DataFrame(excl)
