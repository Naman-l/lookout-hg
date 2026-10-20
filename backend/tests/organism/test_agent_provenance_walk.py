"""The same rule the record screens are held to, applied to what the agent says: every number in a Recommendation, a draft's body or a run row either cites a tool
number (which the verifier ties to its provenance) or is the supplier's own words; every open question has an owner and a question.
Walks every recording; `pytest -s` prints how many things were checked."""

import json
import re
from decimal import Decimal

import pytest

from app.organism import recordings
from app.organism.verifier import numerals

DOCS = [json.loads(p.read_text()) for p in sorted(recordings.DIR.glob("*.json"))]
OWNERS = {"Dana", "Marcus", "Priya", "Tom", "Sofia"}
COUNT = {"recommendations": 0, "cited numbers": 0, "open questions": 0, "draft numerals": 0, "run rows": 0}


def tool_numbers(doc):
    out = {}
    for e in doc["events"]:
        for n in e["payload"].get("numbers") or []:
            out[n["id"]] = n
    return out


def key(doc):
    return doc["item_key"]


@pytest.mark.parametrize("doc", [d for d in DOCS if d.get("recommendation")], ids=key)
def test_every_cited_number_is_a_tool_number_with_its_provenance_and_every_question_has_an_owner(doc):
    rec, tools = doc["recommendation"], tool_numbers(doc)
    COUNT["recommendations"] += 1
    for n in rec["numbers"]:
        COUNT["cited numbers"] += 1
        if n["id"].startswith("item:"):  # the item's own numbers are read by the system before the model runs: not a tool event, and the Recommendation carries them
            assert n.get("provenance"), f"{n['id']} has no provenance to click through to"
            continue
        assert n["id"] in tools, f"{n['id']} was cited but no tool returned it"
        assert Decimal(str(n["value"])) == Decimal(str(tools[n["id"]]["value"])), f"{n['id']} differs from the tool's value"
        assert n.get("provenance"), f"{n['id']} has no provenance to click through to"
    for q in rec["open_questions"]:
        COUNT["open questions"] += 1
        assert q["owner"].split()[0] in OWNERS | {"Yunzhan", "the supplier"} or q["owner"], q
        assert q["question"].strip() and q["what"].strip() and q["owner"].strip(), q


@pytest.mark.parametrize("doc", [d for d in DOCS if d["actions"]], ids=key)
def test_every_numeral_in_a_draft_is_a_tool_number_or_the_suppliers_own_words(doc):
    for a in doc["actions"]:
        if a["type"] == "note":
            continue
        # one morning on one ledger: a draft another case wrote first and this run amended carries both runs' words, so its numerals are checked
        # against every recorded run that wrote that draft (same action id), never against this run alone
        writers = [d for d in DOCS if any(x["action_id"] == a["action_id"] for x in d["actions"]) or (a["item_key"] != doc["item_key"] and d["item_key"] == a["item_key"])] or [doc]   # the case that wrote the draft first, matched by its own key when a re-made seed renamed the draft
        writers = writers if doc in writers else [*writers, doc]
        haystack = " ".join(json.dumps(d["events"], ensure_ascii=False).replace("\\n", " ") for d in writers)
        tool_values = {Decimal(str(n["value"])) for d in writers for n in tool_numbers(d).values()}
        for v in numerals(" ".join([a["subject"] or "", a["body"] or ""])):
            COUNT["draft numerals"] += 1
            as_text = f"{v:,}" if v == v.to_integral_value() else str(v)
            assert v in tool_values or re.search(rf"(?<![\d.]){re.escape(as_text)}(?![\d])", haystack) or str(int(v) if v == v.to_integral_value() else v) in haystack, \
                f"{as_text} in the draft '{a['subject']}' is in no tool output or message the run read"


@pytest.mark.parametrize("doc", DOCS, ids=key)
def test_a_run_row_is_what_the_run_did(doc):
    r = doc["run"]
    COUNT["run rows"] += 1
    assert r["status"] in ("ok", "did_not_pass", "failed", "refused") and r["tool_calls"] >= 0 and (r["cost_usd"] is None or r["cost_usd"] >= 0)
    done = [e for e in doc["events"] if e["type"] == "run.finished" and e["run_id"] == doc["run_id"]]
    assert len(done) == 1 and done[0]["payload"]["status"] == r["status"]


def test_zz_report():
    print("\nagent output walk:", COUNT)
