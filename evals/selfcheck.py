"""Grades the answer sheets against the oracle: proves every key is re-derivable from the raw files."""
from __future__ import annotations

from pathlib import Path

from . import graders, oracle


def measured_from_oracle(data_dir: Path) -> dict:
    o = oracle.compute(data_dir)
    return {
        "counts": {
            "po_rows_raw": o["po_rows_raw"],
            "po_exact_duplicate_rows_dropped": o["po_duplicates_dropped"],
            "po_lines_open_or_partial": o["open_lines"],
            "po_lines_past_due_raw": o["past_due_raw"],
            "po_lines_stale_unknown": o["stale_lines"],
            "po_lines_past_due": o["past_due"],
            "force_majeure_open_qty": int(o["fm_open_qty"]),
            "force_majeure_hr40110_open_qty": int(o["fm_hr40110_open_qty"]),
            "unknown_origin_on_listed_codes": o["unknown_origin_parts"],
        },
        "facts": {
            "tariff_t1_owed_usd": o["t1_owed"], "tariff_t1_conditional_usd": o["t1_conditional"], "tariff_t1_gross_usd": o["t1_gross"],
            "tariff_t2_owed_usd": o["t2_owed"], "tariff_t2_conditional_usd": o["t2_conditional"], "tariff_t2_gross_usd": o["t2_gross"],
            "tariff_t2_pass_through_gross_usd": o["t2_pass_through_gross"],
            "unknown_origin_net_usd": o["unknown_origin_net"], "unknown_origin_gross_usd": o["unknown_origin_gross"],
            **{f"tariff_t1_net_usd:{p}": v for p, v in o["t1_per_part"].items()},
        },
    }


def run(cases: dict[str, dict], data_dir: Path) -> dict[str, list[dict]]:
    m = measured_from_oracle(data_dir)
    out = {}
    counts = cases["det-counts"]["expected"]["counts"]
    out["det-counts"] = [graders.grade_counts({k: v for k, v in counts.items() if k in m["counts"]}, m["counts"])]
    facts = [f for f in cases["det-tariff-top"]["expected"]["facts"] if f["name"].startswith("tariff_t")
             and (f["name"] + (":" + f["part"] if f.get("part") else "")) in m["facts"]]
    unk = cases["control-unknown-origin"]["expected"]["at_stake_if_china_usd"]
    facts_unk = [{"name": "unknown_origin_net_usd", "value": unk["net"]["value"], "tolerance": unk["net"]["tolerance"]},
                 {"name": "unknown_origin_gross_usd", "value": unk["gross"]["value"], "tolerance": unk["gross"]["tolerance"]}]
    out["det-tariff-top"] = [graders.grade_facts(facts, m["facts"])]
    out["control-unknown-origin"] = [graders.grade_facts(facts_unk, m["facts"])]
    return out


def unchecked(cases: dict[str, dict], data_dir: Path) -> dict[str, list[str]]:
    """Expected values the oracle does not compute, per sheet: named, not silently dropped. Other sheets are re-derived in evals/tests/test_new_keys.py."""
    m = measured_from_oracle(data_dir)
    out = {}
    counts = (cases.get("det-counts") or {}).get("expected", {}).get("counts", {})
    out["det-counts"] = sorted(k for k in counts if k not in m["counts"])
    facts = (cases.get("det-tariff-top") or {}).get("expected", {}).get("facts", [])
    out["det-tariff-top"] = sorted(f["name"] + (":" + f["part"] if f.get("part") else "") for f in facts
                                   if (f["name"] + (":" + f["part"] if f.get("part") else "")) not in m["facts"])
    return {k: v for k, v in out.items() if v}
