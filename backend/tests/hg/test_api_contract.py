"""Every GET route answers a bad id or bad input with a clean 4xx (or an empty answer), never a 500; and the served contract is the committed one."""

import re

import yaml


def test_every_get_route_survives_a_bad_id(client):
    from app.main import app

    fails = []
    for r in app.routes:
        if "GET" not in getattr(r, "methods", set()) or not r.path.startswith("/api/") or r.path.endswith("/events"):
            continue
        path = re.sub(r"\{[^}]+\}", "nope", r.path)
        res = client.get(path)
        if res.status_code >= 500:
            fails.append(f"{path} -> {res.status_code}")
    assert fails == [], fails


def test_bad_dates_and_filters_are_refused_plainly(client):
    assert client.get("/api/action-items?act_by_from=31-10-2026").status_code == 422
    assert client.get("/api/action-items?project=Atlantis").status_code == 422
    assert client.get("/api/ladder").status_code == 422


def test_the_committed_contract_lists_every_route_the_server_serves():
    from pathlib import Path

    from app.main import app

    committed = yaml.safe_load((Path(__file__).resolve().parents[3] / "api" / "openapi.yaml").read_text())["paths"]
    served = app.openapi()["paths"]
    assert sorted(set(served) - set(committed)) == [], "regenerate api/openapi.yaml and the UI's types (see README)"
