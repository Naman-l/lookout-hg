"""Clean the item master: origin, HTS code, category, kind, preferred supplier, lead time.

Defect: country of origin in 33 spellings (China alone in 5) and blank on 22 parts; HTS in 5 formats, blank on 44,
and one letter O typed for a zero (HR-51120: 85O4.40.9580, a tranche-1 DC-DC converter); 41 category labels for
about 30 categories; preferred supplier pointing at a legacy, inactive or on-hold record; planned lead time blank.
Rule: origin -> ISO alpha-2; HTS -> digits only (a repaired O is marked 'flagged'); category -> one label
(answers.yaml); kind from the category; preferred supplier -> the record and its identity. Blank origin, HTS and
lead time stay unknown with an owner: tariff is decided by origin and code, so a guess would put a wrong number on
the Action list. Same-MPN pairs are linked as possible duplicates, never merged.
Consequence if ignored: a prefix match on raw HTS misses HR-51120; 'China' and 'PRC' count as different origins; the
duty on five blank-origin parts is shown as zero.
"""
import pandas as pd

from app.domain.imports.context import examples
from app.domain.imports.helpers import hts_digits, iso_country


def run(ctx):
    raw = ctx.t["raw_parts"]
    rec = ctx.t["supplier_records"].set_index("record_id")
    cat_map = ctx.answers["categories"]
    df = pd.DataFrame({"src_row": raw.src_row, "part_number": raw.part_number.str.strip()})
    df["mpn"] = raw.mpn.replace("", None)
    df["manufacturer"] = raw.manufacturer.replace("", None)
    df["description"] = raw.description
    df["category_raw"] = raw.category
    df["category"] = raw.category.map(lambda c: cat_map.get(c, c))
    df["kind"] = df.category.map({"Finished Good": "finished", "Sub-assembly": "subassembly"}).fillna("purchased")
    df["uom"] = raw.uom
    df["coo_raw"] = raw.country_of_origin
    df["coo"] = raw.country_of_origin.map(iso_country)
    df["coo_method"] = ["stated" if isinstance(c, str) else None for c in df.coo]
    action, value = ctx.decision("origin:unknown-on-listed-codes")   # change: "HR-40220=CN,HR-13103=TW" - the person says where those are made
    if action == "change" and value:
        for pair in value.replace(" ", "").split(","):
            part, _, iso = pair.partition("=")
            if part in set(df.part_number) and iso:
                df.loc[df.part_number == part, ["coo", "coo_method"]] = [iso_country(iso), "answered"]
    h = raw.hts_code.map(hts_digits)
    df["hts_raw"] = raw.hts_code
    df["hts"] = h.map(lambda x: x[0])
    df["hts_method"] = [("unknown" if d is None else "flagged" if rep else "stated") for d, rep in h]
    pref = raw.preferred_supplier_id.str.strip()
    df["preferred_record_id"] = pref.replace("", None)
    df["preferred_identity_id"] = df.preferred_record_id.map(rec.identity_id)
    df["planned_lead_time_days"] = pd.to_numeric(raw.planned_lead_time_days.replace("", None)).astype("Int64")
    df["status"] = raw.status
    ctx.t["parts"] = df
    buys = df[df.kind == "purchased"]

    changed = df[(df.coo_raw != "") & (df.coo_raw != df.coo)]
    ctx.issue("parts.coo_spellings", "parts.csv", "Country of origin typed 33 ways (China, PRC, P.R. China, CN, China (PRC))",
              len(changed), "fix", "Map to ISO alpha-2; raw text kept in coo_raw. An unmapped spelling stops the build.",
              "Tariff duty follows origin; a part whose 'PRC' did not match 'CN' would escape the 25% duty.",
              examples(changed.coo_raw + " -> " + changed.coo), "ERP admin")
    blank = df[df.coo.isna() & (df.kind == "purchased")]
    ctx.issue("parts.coo_blank", "parts.csv", "Country of origin blank", len(blank), "leave",
              "Stays unknown ('unknown · ask <buyer>'). Never inferred from the supplier's country: a supplier in one country can make in another.",
              "Whether the new China duty applies cannot be computed; the exposure is shown as a range, not a zero.",
              examples(blank.part_number), "@parts:" + ",".join(blank.part_number))
    fmt = df[df.hts.notna() & (df.hts_raw != df.hts)]
    ctx.issue("parts.hts_formats", "parts.csv", "HTS code in five formats (####.##.####, ##########, ####.##, ######)",
              len(fmt), "fix", "Keep digits only (6 or 10); raw kept in hts_raw. A rule's prefix matches on digits.",
              "A prefix match against the tariff table misses every dotted or short code.",
              examples(fmt.hts_raw + " -> " + fmt.hts), "ERP admin")
    letter = df[df.hts_method == "flagged"]
    ctx.issue("parts.hts_letter_o", "parts.csv", "HTS code has the letter O where a zero belongs", len(letter), "flag",
              "Read the O as 0, mark hts_method 'flagged' and keep the raw text.",
              "A letter O in a tariff code hides a part from a naive prefix match, including one that sits on a listed code.",
              examples(letter.part_number + " " + letter.hts_raw + " -> " + letter.hts), "@parts:" + ",".join(letter.part_number))
    nohts = df[df.hts.isna() & (df.kind == "purchased")]
    tariffish = nohts[nohts.category.isin(["Motors", "Motor Drives", "Batteries", "Power Electronics", "Gears & Gearboxes", "Bearings", "Connectors", "Cables & Harnesses"])]
    ctx.issue("parts.hts_blank", "parts.csv", "HTS code blank", len(nohts), "leave",
              "Stays unknown. Parts in tariff-type categories with a China origin are raised as their own unknowns.",
              "Exposure cannot be computed for a part with no code. Listed here for tariff-type categories: " + examples(tariffish.part_number + " (" + tariffish.coo.fillna("?") + ")", 6),
              examples(nohts.part_number), "@parts:" + ",".join(nohts.part_number))
    cats = df[df.category_raw != df.category]
    ctx.issue("parts.category_labels", "parts.csv", "Category labels with aliases (CONN / Connector / Connectors; Sheetmetal / Sheet Metal; HARDWARE)",
              len(cats), "fix", "Map aliases to the label most parts use (answers.yaml); raw kept in category_raw.",
              "Spend and open supply by category split across aliases; a buyer's category view misses rows.",
              examples(cats.category_raw + " -> " + cats.category), "ERP admin")
    lt = buys[buys.planned_lead_time_days.isna()]
    ctx.issue("parts.lead_time_blank", "parts.csv", "Planned lead time blank", len(lt), "leave",
              "Stays unknown. No default lead time is invented.",
              "A reorder-date calculation for these parts has no basis; they are left out of any lead-time rule.",
              examples(lt.part_number), "@parts:" + ",".join(lt.part_number))

    stale = df[df.preferred_record_id.notna()].copy()
    stale["status_r"] = stale.preferred_record_id.map(rec.status)
    stale["system"] = stale.preferred_record_id.map(rec.system)
    bad = stale[(stale.system == "legacy") | (stale.status_r != "Active")]
    ctx.issue("parts.preferred_supplier_stale", "parts.csv",
              "Preferred supplier is a legacy id or a record that is Inactive or On hold", len(bad), "flag",
              "Kept as found; the identity is resolved through the alias link, and status is shown.",
              "A buyer routing by the preferred supplier sends orders to a record that is no longer active.",
              examples(bad.part_number + " -> " + bad.preferred_record_id + " (" + bad.status_r + ")"), "@parts:" + ",".join(bad.part_number))
    nopref = buys[buys.preferred_record_id.isna()]
    ctx.issue("parts.preferred_supplier_blank", "parts.csv", "Bought part with no preferred supplier", len(nopref), "leave",
              "Left blank.", "No default source to route a shortage to.", examples(nopref.part_number), "@parts:" + ",".join(nopref.part_number))
    missing = df[df.preferred_record_id.notna() & ~df.preferred_record_id.isin(rec.index)]
    ctx.issue("parts.preferred_unresolved", "parts.csv", "Preferred supplier id not in the supplier master", len(missing), "flag",
              "Kept as found.", "The part has no resolvable source.", examples(missing.part_number), "ERP admin")

    # same physical part under two numbers
    key = buys.dropna(subset=["mpn", "manufacturer"]).assign(k=lambda d: d.mpn.str.upper().str.replace(r"[^A-Z0-9]", "", regex=True) + "|" + d.manufacturer.str.lower())
    pairs = []
    for k, g in key.groupby("k"):
        nums = sorted(g.part_number)
        for i in range(len(nums)):
            for j in range(i + 1, len(nums)):
                pairs.append(dict(part_a=nums[i], part_b=nums[j], kind="same_mpn",
                                  evidence=f"same manufacturer part number {g.mpn.iloc[0]} from {g.manufacturer.iloc[0]}"))
    if ctx.decision("possible-duplicate:parts")[0] == "skip":
        pairs_kept = []   # the person does not want them linked; the defect is still reported
    else:
        pairs_kept = pairs
    ctx.t["part_links"] = pd.DataFrame(pairs_kept, columns=["part_a", "part_b", "kind", "evidence"])
    ctx.issue("parts.duplicate_parts", "parts.csv", "One physical part under two part numbers (same manufacturer and MPN)",
              len(pairs), "link", "Linked as possible duplicates in part_links; not merged, because open orders and BOMs use both numbers.",
              "Demand and stock for one part are split across two numbers; both were ordered on HPO-26-00408.",
              examples(f"{p['part_a']} = {p['part_b']}" for p in pairs), "@parts:" + ",".join(p["part_a"] for p in pairs))
