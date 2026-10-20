"""Link ERP supplier records that are the same company; keep every record; never merge.

Defect: 71 records, about 60 companies. Ten legacy V- ids were copied into the new ERP as SUP- records, and
Baycrest renamed itself BCX Interconnect (a third record). Look-alike names (Corvell Fasteners Inc, US, and Corvell
Fastener Co, Taiwan) are different companies and must stay apart.
Rule: a legacy record joins the SUP- record that shares its contact email domain; renames come from a person's
answer (answers.yaml, with the message that proves it). Domain equal is evidence, name similarity alone is not.
Every record stays; identity_method says whether the link was found by rule ('inferred') or answered ('stated').
Consequence if ignored: one supplier's spend, late lines and force-majeure exposure split across two or three ids
(Yunzhan: three records, two of them carrying open lines).
"""
import pandas as pd

from app.domain.imports.context import examples


def run(ctx):
    rec = ctx.t["supplier_records"].copy()
    new = rec[rec.system == "new"]
    by_domain = new.groupby("email_domain").record_id.apply(list).to_dict()
    ambiguous = {d: ids for d, ids in by_domain.items() if len(ids) > 1}
    assert not ambiguous, f"two SUP- records share a domain, needs a flashcard: {ambiguous}"

    action, value = ctx.decision("alias:legacy-ids")   # the person's answer: link all (accept), none (skip), or all but the listed records (change)
    keep_apart = set((value or "").replace(" ", "").split(",")) - {""} if action == "change" else set()
    identity, method, evidence = {}, {}, {}
    for r in rec.itertuples():
        if r.system == "new":
            identity[r.record_id], method[r.record_id] = r.record_id, "stated"
            evidence[r.record_id] = None
        else:
            match = by_domain.get(r.email_domain)
            assert match, f"legacy record {r.record_id} matches no SUP- record by domain"
            if action == "skip" or r.record_id in keep_apart:
                identity[r.record_id], method[r.record_id] = r.record_id, "stated"
                evidence[r.record_id] = f"left apart by the person's answer (same contact domain as {match[0]})"
            else:
                identity[r.record_id], method[r.record_id] = match[0], "inferred"
                evidence[r.record_id] = f"same contact domain {r.email_domain} as {match[0]}"
    if ctx.decision("alias:rename")[0] != "skip":
        for a in ctx.answers["supplier_aliases"]:
            identity[a["record"]], method[a["record"]], evidence[a["record"]] = a["identity"], "stated", a["evidence"]

    # Links a person approved in the ledger ("these two ids are one company"): the later of the two identities folds into the one from the new ERP
    # (lowest id when both are). Linked, never merged: every record and every PO stays as it is.
    system = rec.set_index("record_id").system
    unresolved = []
    for link in ctx.answers.get("approved_links") or []:
        a_, b_ = identity.get(link["supplier_a"]), identity.get(link["supplier_b"])
        if a_ is None or b_ is None:
            unresolved.append(f"{link['supplier_a']} / {link['supplier_b']}")
            continue
        if a_ == b_:
            continue
        keep, fold = sorted([a_, b_], key=lambda i: (system[i] != "new", i))
        for r_id, i in list(identity.items()):
            if i == fold:
                identity[r_id], method[r_id] = keep, "stated"
                evidence[r_id] = f"approved by {link.get('linked_by') or 'a person'} (action {link['action_id']}): {link.get('evidence') or 'no evidence recorded'}"
    ctx.issue("suppliers.approved_link_unresolved", "suppliers.csv", "An approved supplier link names an id that is not in the supplier master", len(unresolved), "flag",
              "Left out of identity resolution; the link stays in the ledger.", "A person's decision that two ids are one company has no effect until the ids exist.",
              examples(unresolved), "ERP admin")

    rec["identity_id"] = rec.record_id.map(identity)
    rec["identity_method"] = rec.record_id.map(method)
    rec["identity_evidence"] = rec.record_id.map(evidence)
    ctx.t["supplier_records"] = rec

    canon = rec[rec.record_id == rec.identity_id].set_index("record_id")
    n = rec.groupby("identity_id").size()
    ctx.t["supplier_identities"] = pd.DataFrame({
        "id": canon.index, "name": canon.name.values, "country": canon.country.values,
        "n_records": n.reindex(canon.index).values})

    linked = rec[rec.record_id != rec.identity_id]
    groups = linked.groupby("identity_id").record_id.apply(lambda s: ", ".join(s))
    ctx.issue("suppliers.duplicate_records", "suppliers.csv",
              "The same company under more than one supplier id (legacy V- copies, and a rename)",
              len(linked), "link",
              "Group records under one identity; keep every record and every PO on the id it was placed on. Domain match is 'inferred', a person's answer is 'stated'.",
              "Spend, past-due lines and disruption exposure are understated per id; a company's several records hide the full size of any disruption it has.",
              examples(f"{i} also {g}" for i, g in groups.items()), "@suppliers:" + ",".join(groups.index))

    # different companies with similar names: report, do not link
    stop = {"inc", "co", "ltd", "llc", "gmbh", "corp", "company", "the", "and", "of", "limited"}

    def tokens(name):
        words = [w.strip(".,()").lower() for w in name.split()]
        return {w.rstrip("s") for w in words if w and w not in stop}

    ident = ctx.t["supplier_identities"]
    toks = {r.id: tokens(r.name) for r in ident.itertuples()}
    ids = sorted(toks)
    pairs = [(a, b) for i, a in enumerate(ids) for b in ids[i + 1:]
             if len(toks[a] & toks[b]) / len(toks[a] | toks[b]) >= 0.6]
    nm = ident.set_index("id").name
    ctx.issue("suppliers.lookalike_names", "suppliers.csv",
              "Different companies with near-identical names",
              len(pairs), "flag", "Kept as separate identities: different contact domains, countries and terms.",
              "Merging by name would pool two suppliers' prices and delivery performance.",
              examples(f"{nm[a]} / {nm[b]}" for a, b in pairs), "@suppliers:" + ",".join(sorted({x for p in pairs for x in p})))

    blank = rec[rec.incoterm.isna()]
    ctx.issue("suppliers.incoterm_blank", "suppliers.csv", "Default Incoterm is blank", len(blank), "leave",
              "Leave unknown. The importer of record, and so who pays the new duty, cannot be told from the supplier master.",
              "A duty estimate for these suppliers' parts would assume Halden pays; it may be the supplier (DDP).",
              examples(blank.name), "@suppliers:" + ",".join(blank.record_id))
    noplace = rec[rec.incoterm.notna() & (rec.incoterm_place.isna() | (rec.incoterm_place == "Origin"))]
    ctx.issue("suppliers.incoterm_place_missing", "suppliers.csv",
              "Incoterm without a named place (FOB Origin, EXW, FOB)", len(noplace), "flag",
              "Keep the term (it decides who imports); the place stays unknown.",
              "Freight cost and the point where risk passes cannot be placed; the importer of record is still known.",
              examples(noplace.incoterms_raw), "ERP admin")
