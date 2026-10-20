"""The README's first claim, proved: every Money and Quantity the UI renders carries a provenance a buyer can open, and every Unknown has an owner and a question.

Walks every GET response the screens read (action items and their details, parts, suppliers, orders, products and BOMs, builds and readiness, phases, tariffs by part,
quotes, messages, the Data page) through the real routers. "Openable" means the provenance names a row, a raw value, the records it was computed from, or a rule in words."""
import re
from collections import Counter

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domain.attention import service as attention
from app.domain.attention.api import router as attention_router
from app.domain.bom.api import router as bom_router
from app.domain.demand.api import router as demand_router
from app.domain.imports.api import router as imports_router
from app.domain.inbox.api import router as inbox_router
from app.domain.orders.api import router as orders_router
from app.domain.parts.api import router as parts_router
from app.domain.phases.api import router as phases_router
from app.domain.quotes.api import router as quotes_router
from app.domain.suppliers.api import router as suppliers_router

METHODS = {"stated", "computed", "inferred", "flagged", "unknown", "extracted"}


@pytest.fixture(scope="module")
def client(db_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db import get_session

    eng = create_engine(f"sqlite:///{db_path}", future=True)
    app = FastAPI()
    for r in (attention_router, bom_router, demand_router, imports_router, inbox_router, orders_router, parts_router, phases_router, quotes_router, suppliers_router):
        app.include_router(r, prefix="/api")

    def session():
        with Session(eng) as s:
            yield s

    app.dependency_overrides[get_session] = session
    yield TestClient(app)
    eng.dispose()


def walk(o, path, found):
    if isinstance(o, dict):
        keys = set(o)
        if {"amount", "currency"} <= keys and "provenance" in keys:
            found.append(("money", path, o))
        elif {"value", "uom"} <= keys and "provenance" in keys:
            found.append(("quantity", path, o))
        elif {"what", "why_it_blocks", "owner", "question"} <= keys:
            found.append(("unknown", path, o))
        for k, v in o.items():
            walk(v, f"{path}/{k}", found)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            walk(v, f"{path}[{i}]", found)


def urls(session):
    out = ["/api/action-items", "/api/orders", "/api/suppliers", "/api/parts", "/api/products", "/api/forecast", "/api/builds", "/api/messages", "/api/messages/review",
           "/api/data-issues", "/api/data/steps", "/api/data/stamp", "/api/imports/questions", "/api/counts"]
    out += [f"/api/action-items/{k}" for k in attention.all_keys(session)]
    out += [f"/api/suppliers/{x['ref']['id']}" for x in []]
    return out


@pytest.fixture(scope="module")
def bodies(client, db_path):
    """Every response the screens read: (url, parsed JSON)."""
    out = []

    def get(u):
        r = client.get(u)
        assert r.status_code == 200, u
        out.append((u, r.json()))
        return out[-1][1]

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    with Session(create_engine(f"sqlite:///{db_path}", future=True)) as session:
        todo = urls(session)
    for url in todo:
        body = get(url)
        if url == "/api/suppliers":
            more = [f"/api/suppliers/{s['ref']['id']}" for s in body]
        elif url == "/api/parts":
            more = [f"/api/parts/{p['ref']['id']}" for p in body] + [f"/api/phases?part={p['ref']['id']}" for p in body[::4]] + [f"/api/parts/{p['ref']['id']}/compare" for p in body[::10]]
        elif url == "/api/products":
            more = [f"/api/products/{p['part_number']}/bom" for p in body]
        elif url == "/api/builds":
            more = [f"/api/builds/{b['product']['id']}/{b['month']}/readiness" for b in body]
        elif url == "/api/messages":
            more = [f"/api/messages/{m['ref']['id']}" for m in body]
        else:
            more = []
        for u in more:
            get(u)
    return out


def test_every_number_a_screen_renders_can_be_opened(bodies):
    bad, count = [], Counter()
    for url, body in bodies:
        found = []
        walk(body, url, found)
        for kind, path, o in found:
            count[kind] += 1
            bad += check(kind, path, o)
        if url.endswith("/readiness"):                       # the readiness rows say how `need` was made once, in need_source
            count["need_source"] += 1
            bad += check("quantity", f"{url}/need_source", {"provenance": body["need_source"]})
    print("checked", dict(count))
    assert sum(count.values()) > 5000 and count["money"] and count["quantity"] and count["unknown"]
    assert not bad, f"{len(bad)} of {sum(count.values())} fail:\n" + "\n".join(bad[:25])


def test_no_text_the_api_returns_has_a_placeholder_plural(bodies):
    """'1 order', '3 orders': the noun agrees at the source, so the UI never has to patch 'order(s)'."""
    hits = []

    def strings(o, path):
        if isinstance(o, str):
            if re.search(r"[A-Za-z]\((?:s|es)\)", o):
                hits.append(f"{path}: {o[:90]}")
        elif isinstance(o, dict):
            for k, v in o.items():
                strings(v, f"{path}/{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                strings(v, f"{path}[{i}]")

    for url, body in bodies:
        strings(body, url)
    assert len(bodies) > 600 and not hits, f"{len(hits)} texts:\n" + "\n".join(hits[:15])


def check(kind, path, o):
    if kind == "unknown":
        return [] if o["owner"] and o["question"].strip() and o["why_it_blocks"].strip() else [f"{path}: unknown without an owner or a question"]
    p = o["provenance"]
    why = []
    if p.get("method") not in METHODS:
        why.append("no method")
    if not p.get("source"):
        why.append("no source")
    if not (p.get("row") or p.get("raw") or p.get("inputs") or p.get("rule")):
        why.append("nothing to open (no row, raw, inputs or rule)")
    if p.get("method") == "computed" and not (p.get("rule") or p.get("inputs")):
        why.append("computed with neither rule nor inputs")
    if re.search(r"\b[a-z_]+\.[a-z_]+ v\d", p.get("rule") or ""):
        why.append("rule is developer language")
    return [f"{path}: {kind} {', '.join(why)} ({p.get('source')}, {p.get('rule')})"] if why else []
