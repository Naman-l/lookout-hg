"""Link consigned material to the part it is built into, from the recipe's cited answers.

Defect: some material is Halden's own and sits at a contract manufacturer, which builds it into a Halden part (the bare boards a PCBA maker populates).
Nothing in the item master, the orders or the BOM says so: the bare board and the assembly look unrelated, so a slip in the boards delays an
assembly that appears nowhere in the board's supplier's notice.
Rule: `answers.yaml` (consignments) lists each case with the message that says it; this step checks that the material, the holder and the part it
goes into exist and stores the link (method 'stated': a person's answer, bootstrapped from the cited evidence). Nothing is inferred from names.
Consequence if ignored: three weeks of slip on the bare boards reads as a small PCB problem and never reaches the safety controller in every robot.
"""
import pandas as pd


def run(ctx):
    parts = set(ctx.t["parts"].part_number)
    holders = set(ctx.t["supplier_identities"].id)
    rows = []
    for c in ctx.answers.get("consignments") or []:
        assert c["material"] in parts and c["into"] in parts, f"consignment names a part the master does not hold: {c}"
        assert c["holder"] in holders, f"consignment names a supplier the master does not hold: {c}"
        rows.append(dict(id=len(rows) + 1, material_part=c["material"], holder_identity=c["holder"], into_part=c["into"], evidence=c["evidence"], method="stated"))
    ctx.t["consignments"] = pd.DataFrame(rows, columns=["id", "material_part", "holder_identity", "into_part", "evidence", "method"])
    ctx.issue("parts.consigned_material", "answers.yaml", "Material Halden owns at a contract manufacturer, built into one of its parts", len(rows), "link",
              "Linked from a cited answer: the material, the supplier that holds it and the part it goes into.",
              "A slip in the material delays the assembly built from it, and nothing in the item master or the orders says the two are related.",
              "; ".join(f"{r['material_part']} -> {r['into_part']} at {r['holder_identity']}" for r in rows), "@parts:" + ",".join(r["material_part"] for r in rows))
