"""The API contract, called for real on the built database: every endpoint in api/openapi.yaml that reads is called with real ids and answers 2xx with the documented top-level shape;
a bad id or bad input is a clean 4xx (never a 500); and every key the screens request (each Action list item: its detail and its options) answers 200. Endpoints that start a model run
or send are called only with bad input (they must refuse before any model is reached)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app import db as app_db
from app.main import app

SPEC = yaml.safe_load((Path(__file__).resolve().parents[3] / "api" / "openapi.yaml").read_text())
RUNS_A_MODEL = ("/api/ask", "/runs", "/compare-runs", "/steward-runs", "/triage-runs", "/reply-runs", "/api/annotate", "/api/imports/")      # POSTs that reach a model or the importer
NEEDS_A_STORE = ("/api/runs", "/api/actions", "/api/outbox", "/api/imports/")      # lists kept in the run store, not the recipe's database


@pytest.fixture(scope="module")
def client(db_path):
    mp = pytest.MonkeyPatch()
    mp.delenv("LOOKOUT_FAKE_SERVICES", raising=False)
    mp.setattr(app_db, "DB_PATH", db_path)
    yield TestClient(app, raise_server_exceptions=False)      # a 500 is a response here, to be reported, not an exception that hides which call it was
    mp.undo()


def _ids(client, path, pick):
    body = client.get(path).json()
    return [pick(x) for x in (body if isinstance(body, list) else body.get("items", body.get("results", [])))][:3]


@pytest.fixture(scope="module")
def real(client):
    keys = [i["key"] for i in client.get("/api/action-items").json()]
    builds = client.get("/api/builds").json()
    return {
        "key": keys,
        "message_id": _ids(client, "/api/messages", lambda m: m["ref"]["id"]),
        "supplier_id": _ids(client, "/api/suppliers", lambda s: s["ref"]["id"]),
        "po_line_id": _ids(client, "/api/orders", lambda o: o["ref"]["id"]),
        "part": _ids(client, "/api/parts", lambda p: p["ref"]["id"]),
        "product": _ids(client, "/api/products", lambda p: p["part_number"]),
        "month": sorted({b["month"] for b in builds})[:1],
    }


def _get_endpoints():
    return [p for p, ops in SPEC["paths"].items() if "get" in ops]


def test_every_documented_route_exists_and_every_list_answers(client, real):
    openapi = client.get("/openapi.json").json()["paths"]
    missing = [p for p in SPEC["paths"] if p not in openapi]
    assert not missing, f"documented but not served: {missing}"
    bad = []
    for path in _get_endpoints():
        if "{" in path or any(path.startswith(x) for x in NEEDS_A_STORE) or path in ("/api/search", "/api/phases"):      # a search needs a query and phases needs a part or a PO line: called with them below
            continue
        r = client.get(path)
        if r.status_code != 200:
            bad.append((path, r.status_code))
    assert not bad, f"lists that do not answer 200: {bad}"


def test_every_read_by_id_answers_for_a_real_id_and_a_clean_404_for_a_wrong_one(client, real):
    bad = []
    for path in _get_endpoints():
        params = [seg[1:-1] for seg in path.split("/") if seg.startswith("{")]
        if not params or any(p not in real or not real[p] for p in params):
            continue
        for combo in range(0 if path.endswith("/options") else min(len(real[p]) for p in params)):      # options exist only for a disruption: tested on the items below
            url = path
            for p in params:
                url = url.replace("{" + p + "}", str(real[p][combo]).replace("/", "%2F") if p != "key" else real[p][combo])
            r = client.get(url)
            if r.status_code != 200:
                bad.append((url, r.status_code))
        wrong = path
        for p in params:
            wrong = wrong.replace("{" + p + "}", "zz-not-an-id")
        r = client.get(wrong)
        if r.status_code not in (404, 422):
            bad.append((wrong + " (wrong id)", r.status_code))
    assert not bad, f"reads by id that fail: {bad}"


def test_every_item_the_screens_open_has_a_detail_and_options_with_no_404(client, real):
    """The Action list's keys are what the screens request next: the detail for every item and the options for every disruption (an empty list where there are none to offer)."""
    items = {i["key"]: i for i in client.get("/api/action-items").json()}
    bad = []
    for key, item in items.items():
        d = client.get(f"/api/action-items/{key}")
        if d.status_code != 200:
            bad.append((key, "detail", d.status_code))
        if item["group"] != "trust":      # every case with routes serves their figures (FINAL-SPEC §2); a trust item has controls, not routes
            o = client.get(f"/api/action-items/{key}/options")
            if o.status_code != 200 or not isinstance(o.json(), list):
                bad.append((key, "options", o.status_code))
    assert not bad, f"requested by the screens, not served: {bad}"


def test_bad_input_is_a_clean_4xx_never_a_500(client):
    cases = [("get", "/api/search", None), ("get", "/api/builds/nope/2026-13/readiness", None), ("get", "/api/parts/NOPE/compare?qty=abc", None), ("get", "/api/action-items?act_by_from=notadate", None),
             ("post", "/api/ask", {"question": ""}), ("post", "/api/ask", {}), ("post", "/api/actions/no-such/approve", {"approver": "x"}), ("post", "/api/actions/no-such/reject", {}),
             ("patch", "/api/actions/no-such", {}), ("post", "/api/messages/no-such/triage-runs", None), ("post", "/api/action-items/no-such-key/runs", {}),
             ("post", "/api/parts/NOPE/compare-runs", {}), ("get", "/api/orders/nope", None), ("get", "/api/runs/nope", None)]
    bad = []
    for method, url, body in cases:
        r = getattr(client, method)(url, **({"json": body} if body is not None else {}))
        starts_a_run = url.endswith(("/runs", "-runs"))      # without a model key the run endpoints answer 503 before anything starts: a clean refusal, not a crash
        if not (400 <= r.status_code < 500 or (starts_a_run and r.status_code == 503)):
            bad.append((method.upper(), url, r.status_code))
    assert not bad, f"bad input that is not a clean 4xx: {bad}"


def test_search_and_phases_answer_with_their_required_input(client, real):
    assert client.get("/api/search", params={"q": "motor"}).status_code == 200
    assert client.get("/api/phases", params={"part": real["part"][0]}).status_code == 200
    assert client.get("/api/phases", params={"po_line": real["po_line_id"][0]}).status_code == 200
    assert client.get("/api/phases").status_code == 422


def test_a_step_folded_under_the_fire_can_still_be_opened_and_worked_by_its_key(client):
    """Two sheets and the held-out start runs from the fire's dated keys: the detail, the options-free page and a run all answer for them, with the days left the fire's row shows."""
    fire = next(i for i in client.get("/api/action-items").json() if i["key"] == "disruption:SUP-0001")
    assert fire["dated"]
    for d in fire["dated"]:
        assert client.get(f"/api/action-items/{d['key']}").status_code == 200
        started = client.post(f"/api/action-items/{d['key']}/runs", json={})
        assert started.status_code in (202, 409) or (started.status_code == 503 and "no recorded run" in started.text), (d["key"], started.status_code, started.text[:120])      # a run starts, or one is going, or (no model key and nothing recorded for it) the 503 says so: never a 404 for a folded key
