"""Ask across the company's records, by the planner: each answer is checked against the API's own lists, never against a name written here (the
records name the vendors, projects and people). A question names what it asks about by a word only that record has; a page's record narrows it."""

from tests.hg.test_runs import wait


def ask(client, text, ctx=None, by=None):
    by = by or client.get("/api/people").json()[0]["name"]
    return wait(client, client.post("/api/ask", json={"question": text, "context": ctx, "asked_by": by}).json()["run_id"])


def amount(m):
    return float(m["amount"]) if isinstance(m, dict) else float(m or 0)


def test_the_largest_vendors_are_ranked_by_open_value_and_each_row_opens_its_record(client):
    vendors = sorted(client.get("/api/vendors").json(), key=lambda v: -amount(v["open_value"]))
    r = ask(client, "Which vendors have the most open PO value?")
    rec = r["recommendation"]
    rows = rec["tables"][0]["rows"]
    assert rows[0]["url"] == f"/vendors/{vendors[0]['ref']['id']}" and vendors[0]["name"] in rec["finding"]
    assert [x["agent"] for x in rec["plan"]][0] == "sourcing_analyst"
    assert any(e["type"] == "child.started" and e["agent"] == "sourcing_analyst" for e in r["events"])      # the steps stream like a case run's


def test_a_vendor_is_found_by_a_word_only_its_name_has_never_by_a_word_of_a_material(client):
    vendors = sorted(client.get("/api/vendors").json(), key=lambda v: -amount(v["open_value"]))
    names = [v["name"] for v in vendors]
    word = next(w for v in names for w in v.split() if len(w) >= 5 and w.isalpha() and sum(w.lower() in n.lower() for n in names) == 1)
    owner = next(v for v in vendors if word in v["name"])
    rec = ask(client, f"What is open with {word}?")["recommendation"]
    assert rec["finding"].startswith(owner["name"]) and "rate_history" not in [x["tool"] for x in rec["plan"]]


def test_past_due_pos_are_counted_as_the_po_list_counts_them(client):
    lines = client.get("/api/pos?status=open").json()
    late = [l for l in lines if l["days_past_due"]]
    rec = ask(client, "Which open POs are past due?")["recommendation"]
    assert rec["finding"].split()[0].replace(",", "") == str(len(late))
    assert all(row["url"].startswith("/pos/") for row in rec["tables"][0]["rows"])


def test_the_page_a_question_is_asked_from_narrows_it(client):
    projects = sorted(client.get("/api/projects").json(), key=lambda p: -p["open_po_lines"])
    p = projects[0]
    rec = ask(client, "Which open POs are past due?", {"type": "project", "id": p["ref"]["id"], "label": p["name"]})["recommendation"]
    assert f"on {p['name']}" in rec["finding"]
    open_prs = [l for l in client.get("/api/prs?status=open").json() if (l.get("project") or {}).get("id") == p["ref"]["id"]]
    rec = ask(client, f"How many open PRs does {p['name']} have?", None)["recommendation"]
    assert rec["finding"].startswith(f"{len(open_prs)} open PR lines") or (not open_prs and rec["finding"].startswith("No open PR line"))


def test_every_suggested_question_is_one_the_planner_answers(client):
    qs = [x["question"] for x in client.get("/api/ask/everywhere").json()] + [x["question"] for x in client.get("/api/ask/examples?page=vendor").json()]
    assert len(qs) >= 8
    for q in qs:
        rec = ask(client, q)["recommendation"]
        assert rec["plan"] and rec["plan"][0]["tool"] != "search", q      # answered from a lookup, not by the fallback's search


def test_a_question_that_names_nothing_says_what_ask_can_answer(client):
    rec = ask(client, "flibbertigibbet")["recommendation"]
    assert rec["finding"].startswith("I could not tell what to look up") and rec["follow_ups"]
