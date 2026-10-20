"""The record routes, against the contract's shapes."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domain.attention.api import router as attention_router
from app.domain.bom.api import router as bom_router
from app.domain.demand.api import router as demand_router
from app.domain.imports.api import router as imports_router
from app.domain.inbox.api import router as inbox_router
from app.domain.orders.api import router as orders_router
from app.domain.parts.api import router as parts_router
from app.domain.quotes.api import router as quotes_router
from app.domain.suppliers.api import router as suppliers_router


@pytest.fixture()
def client(db_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    eng = create_engine(f"sqlite:///{db_path}", future=True)
    app = FastAPI()
    from app.domain.people.api import router as people_router
    from app.domain.consignments.api import router as consignments_router
    from app.domain.annotate.api import router as annotate_router
    from app.domain.search.api import router as search_router

    for r in (attention_router, bom_router, demand_router, imports_router, inbox_router, orders_router, parts_router, people_router, consignments_router, annotate_router, search_router, quotes_router, suppliers_router):
        app.include_router(r, prefix="/api")

    def session():
        with Session(eng) as s:
            yield s

    from app.db import get_session

    from app import db as _db

    monkeypatch.setattr(_db, "DB_PATH", db_path)      # the runs and the ledger are read from the test database, never the developer's
    app.dependency_overrides[get_session] = session
    yield TestClient(app)
    eng.dispose()


def test_counts(client):
    c = client.get("/api/counts").json()
    assert (c["suppliers"], c["parts"], c["open_po_lines"], c["inbox"]) == (60, 502, 182, 15) and 9 <= c["action_items"] <= 24 and c["data_issues"] >= 50


def test_action_items_and_detail(client):
    items = client.get("/api/action-items").json()
    assert items[0]["key"] == "disruption:SUP-0001" and items[0]["group"] == "disruption"
    assert {"key", "group", "severity", "title", "owner"} <= set(items[0])
    d = client.get("/api/action-items/disruption:SUP-0001").json()
    assert len(d["po_lines"]) == 10 and d["time_phased"]["part"]["id"] == "HR-40110" and d["unknowns"]
    assert d["short_names"] == {"SUP-0001": "Yunzhan"}      # UX SL-7: the header and rail say the name a buyer says
    assert client.get("/api/action-items/unknown:PO-10711/1").status_code == 200
    assert client.get("/api/action-items/nope").status_code == 404
    assert all(i["owner"] for i in client.get("/api/action-items?owner=Priya").json())


def test_records(client):
    assert len(client.get("/api/orders").json()) == 185
    assert all(o["buyer"] == "Dana Reyes" for o in client.get("/api/orders?buyer=Dana").json())
    assert len(client.get("/api/suppliers").json()) == 60
    assert client.get("/api/suppliers/SUP-0001").json()["contact"]["email"] == "li.wei@yunzhan-motor.example"
    assert client.get("/api/suppliers/NOPE").status_code == 404
    parts = client.get("/api/parts").json()
    assert next(p for p in parts if p["ref"]["id"] == "HR-40220")["coo"]["owner"] == "Dana"
    assert {f["product"] for f in client.get("/api/forecast").json()} == {"Tern T2", "Porter P5", "Heron H1"}


def test_messages_and_detail(client):
    ms = client.get("/api/messages").json()
    assert "from" in ms[0] and {m["trust"] for m in ms} == {"on_file", "new_sender", "suspicious"}
    fm = next(m for m in ms if m["kind"] == "force majeure")["ref"]["id"]
    d = client.get(f"/api/messages/{fm}").json()
    assert d["related_item"] == "disruption:SUP-0001" and d["highlights"] and d["changes"][0]["label"].startswith("Cannot ship")
    assert client.get("/api/messages/nope").status_code == 404


def test_data_screen(client):
    issues = client.get("/api/data-issues").json()
    assert {"issue", "file", "count", "handling", "consequence", "example", "owner", "step"} <= set(issues[0])
    assert client.get("/api/data/stamp").json()["gate_failed"] == 0 and client.get("/api/data/steps").json()[0]["seq"] == 1


def test_deadlines_the_buyer_must_not_miss(client):
    keys = {i["key"] for i in client.get("/api/action-items").json()}
    assert {"deadline:SUP-0041:2026-10-15", "deadline:quotes"} <= keys
    assert not {"deadline:SUP-0001:2026-10-10", "deadline:SUP-0001:2026-10-13"} & keys      # the fire's own dates are not rows of their own
    fire = next(i for i in client.get("/api/action-items").json() if i["key"] == "disruption:SUP-0001")
    assert {d["key"] for d in fire["dated"]} == {"deadline:SUP-0001:2026-10-01", "deadline:SUP-0001:2026-10-10", "deadline:SUP-0001:2026-10-13"}      # ... they sit under it, soonest first
    assert [d["act_by"] for d in fire["dated"]] == sorted(d["act_by"] for d in fire["dated"])
    for d in fire["dated"]:      # and each still opens by its own key with the same days left
        got = client.get(f"/api/action-items/{d['key']}").json()
        assert got["key"] == d["key"] and got["days_left"] == d["days_left"] and got["act_by"] == d["act_by"]
    rolled = client.get("/api/action-items/deadline:quotes").json()
    assert "Oct 31" in rolled["title"] and any(n["value"]["date"] == "2026-10-31" for n in rolled["numbers"])
    assert client.get("/api/action-items/deadline:SUP-0002:2026-10-31").status_code == 200


def test_counts_equal_list_lengths(client):
    c = client.get("/api/counts").json()
    assert c["action_items"] == len(client.get("/api/action-items").json()) and c["inbox"] == len(client.get("/api/messages").json())
    assert c["suppliers"] == len(client.get("/api/suppliers").json()) and c["parts"] == len(client.get("/api/parts").json())
    live = client.get("/api/orders?include_stale=false").json()
    assert c["open_po_lines"] == len(live) and c["stale_po_lines"] == len(client.get("/api/orders").json()) - len(live) == 3 and c["data_issues"] == len(client.get("/api/data-issues").json())


def test_inferred_values_carry_their_method(client):
    v = client.get("/api/orders/HPO-25-00014/10").json()
    assert v["unit_price"]["provenance"]["method"] == "inferred" and v["raw"]["currency"] is None


def test_record_routes_are_fast_once_warm(client):
    import time

    for path in ("/api/action-items", "/api/orders", "/api/suppliers", "/api/parts", "/api/messages", "/api/data-issues", "/api/counts"):
        client.get(path)
        t = time.perf_counter()
        client.get(path)
        assert time.perf_counter() - t < 0.2, path


def test_offers_and_bid_tab_routes(client):
    offers = client.get("/api/parts/HR-40110/offers").json()
    assert {o["supplier_name"][:5] for o in offers} == {"Vinh ", "Shenz"} and all(o["unit_price_usd"]["provenance"]["method"] == "computed" for o in offers)
    tab = client.get("/api/parts/HR-40110/compare?qty=500").json()
    assert [c["is_current"] for c in tab["columns"]].count(True) == 1 and tab["columns"][0]["label"].startswith("Vinh Phuc")
    assert client.get("/api/parts/NOPE/offers").status_code == 404 and client.get("/api/parts/NOPE/compare").status_code == 404


def test_part_page(client):
    d = client.get("/api/parts/HR-40110").json()
    assert d["part"]["ref"]["id"] == "HR-40110" and d["raw"]["country_of_origin"] == "CN" and d["where_used"][0]["product"]["label"] == "Tern T2"
    assert d["buyer"] == "Dana Reyes" and d["buyer_method"] == "inferred" and d["exposure"]["rate"] == 0.25 and d["open_lines"] == 3 and d["reference_price"]["provenance"]["rule"]
    assert d["tariff"]["status"] == "listed" and d["origin"]["status"] == "china"
    u = client.get("/api/parts/HR-40220").json()
    assert u["origin"]["status"] == "unknown" and u["origin"]["unknown"]["owner"] == "Dana" and u["exposure"]["status"] == "unknown_origin"
    assert client.get("/api/parts/HR-51120").json()["raw"]["hts_code"] == "85O4.40.9580"            # the source value beside the clean one
    assert [l["id"] for l in client.get("/api/parts/HR-20103").json()["linked_parts"]] == ["HR-20146"]
    assert client.get("/api/parts/NOPE").status_code == 404


def test_the_review_queue_route(client):
    rev = client.get("/api/messages/review").json()
    assert len(rev) == 4 and {r["decision"] for r in rev} == {"blocked", "review"} and all(r["reason"] for r in rev)
    assert client.get("/api/messages/2026-09-22_NOTICE_OF_FORCE_MAJEURE_-_Shenzhen_Yunzhan_Precision_Motor_Co_Ltd").status_code == 200       # the route order keeps /review first


def test_stale_lines_are_one_rule_everywhere(client):
    rows = client.get("/api/orders").json()
    stale = [r for r in rows if r.get("stale")]
    assert sorted(r["ref"]["id"] for r in stale) == ["PO-10710/1", "PO-10711/1", "PO-10788/1"] and rows[-3:] == stale          # quietly last
    assert all("days_past_due" not in r and r["unknown"]["owner"] for r in stale)                                   # no past-due days, an Unknown with an owner
    y = client.get("/api/suppliers/SUP-0001").json()
    mine = [r for r in rows if r["supplier"]["id"] == "SUP-0001"]
    assert y["open_lines"] == len([r for r in mine if not r.get("stale")]) == 10 and y["stale_lines"] == len([r for r in mine if r.get("stale")]) == 2
    assert y["past_due_lines"] == len([r for r in mine if r.get("days_past_due")]) == 4                                # the page and the list agree


def test_bom_views(client):
    w = client.get("/api/parts/HR-40110/where-used").json()
    assert w[0]["product"] == {"type": "product", "id": "HR-90020", "label": "Tern T2"} and float(w[0]["qty_per_robot"]) == 2 and w[0]["paths"][0][0] == "HR-90020"
    t = client.get("/api/products/HR-90020/bom").json()
    assert t["product"]["label"] == "Tern T2" and t["rows"][0]["level"] == 1 and t["rows"][1]["level"] == 2 and t["defects"] == {"obsolete_child": 1, "orphan_child": 1, "second_placement": 2}
    bad = {r["part"]["id"]: r for r in t["rows"] if r["defects"]}
    assert bad["HR-52010"]["obsolete"] and bad["HR-77190"]["in_master"] is False and bad["HR-10033"]["defects"] == ["second_placement"]
    assert client.get("/api/parts/NOPE/where-used").status_code == 404 and client.get("/api/products/HR-40110/bom").status_code == 404
    assert [p["name"] for p in client.get("/api/products").json()] == ["Tern T2", "Porter P5", "Heron H1"]


def test_item_detail_carries_the_decisions_taken(client, tmp_path, monkeypatch):
    """The ledger's decided actions come back on the item, newest first, in a sentence a buyer would say."""
    import app.db as appdb
    from app.domain.actions import ledger
    from app.domain.common import EntityRef

    db = tmp_path / "ledger.db"
    monkeypatch.setattr(appdb, "DB_PATH", db)
    key = "disruption:SUP-0001"
    sup = EntityRef(type="supplier", id="SUP-0001")
    a = ledger.propose(db, type="supplier_request", item_key=key, run_id="r1", target=sup, recipient="li.wei@yunzhan-motor.example", subject="Dates", body="Please send the dates")
    ledger.reject(db, a.action_id, "wrong contact", "Dana Reyes")
    ledger.propose(db, type="supplier_request", item_key=key, run_id="r2", target=sup, recipient="li.wei@yunzhan-motor.example", subject="Dates", body="Please send the revised dates")
    ledger.propose(db, type="supplier_request", item_key=key, run_id="r3", target=sup, recipient="li.wei@yunzhan-motor.example", subject="Waiting", body="Still waiting")   # not decided: not shown
    ledger.record_app_action(db, type="note", item_key=key, target=sup, body="called Li Wei", by="Dana Reyes")
    d = client.get(f"/api/action-items/{key}").json()
    texts = [x["text"] for x in d["decisions"]]
    # no wall-clock date in a sentence: `at` carries the time
    assert len(texts) == 2 and any(t == "Dana rejected the request to li.wei@yunzhan-motor.example: wrong contact" for t in texts)
    assert any(t == "Dana left a note: called Li Wei" for t in texts)
    assert {x["state"] for x in d["decisions"]} == {"rejected", "recorded"}
    assert client.get("/api/action-items/tariff:all").json()["decisions"] == []


def test_people_are_the_buyers_table_with_their_desk(client):
    people = client.get("/api/people").json()
    assert {p["id"] for p in people} == {"Dana", "Marcus", "Priya", "Tom", "Sofia"}              # the buyers table, nothing typed in the service
    assert [p["open_value"]["usd"] for p in people] == sorted((p["open_value"]["usd"] for p in people), key=float, reverse=True)
    marcus = next(p for p in people if p["id"] == "Marcus")
    assert marcus["name"] == "Marcus Chen" and marcus["open_lines"] > 40 and marcus["categories"] and marcus["parts"] > 0
    assert all(p["initials"] and p["open_value"]["provenance"]["inputs"] is not None for p in people)


def test_the_api_carries_the_stage_on_the_list_and_the_item(client):
    row = next(i for i in client.get("/api/action-items").json() if i["key"] == "disruption:SUP-0001")
    assert row["stage"]["key"] == "found" and row["stage"]["step"] == 1 and row["stage"]["of"] == 7 and row["category"] == "Purchasing"
    item = client.get("/api/action-items/disruption:SUP-0001").json()
    assert item["stage"]["label"] == "Found" and item["stage"]["next_act"]


def test_options_route_serves_every_route_of_the_case_in_its_table_order(client):
    r = client.get("/api/action-items/disruption:SUP-0001/options")
    table = [o["kind"] for o in client.get("/api/action-items/disruption:SUP-0001/option-kinds").json()]
    assert r.status_code == 200 and [o["kind"] for o in r.json()] == table and {"allocation", "air_freight", "resequence", "second_source"} <= set(table)
    assert [o["kind"] for o in client.get("/api/action-items/tariff:all/options").json()] == [o["kind"] for o in client.get("/api/action-items/tariff:all/option-kinds").json()]   # every kind has its routes' figures (FINAL-SPEC §2)
    assert client.get("/api/action-items/disruption:SUP-0001").status_code == 200        # the item itself still resolves beside it


def test_consigned_material_shows_what_a_slip_in_it_reaches(client):
    (c,) = client.get("/api/consignments").json()
    assert (c["material"]["id"], c["holder"]["label"], c["into"]["id"], c["method"]) == ("HR-30110", "Alderpoint Electronics", "HR-31110", "stated")
    assert [(l["po_line"]["id"], l["promised"], l["now"], l["days_later"]) for l in c["material_lines"]] == [("HPO-26-00629/10", "2026-09-25", "2026-10-16", 21)]
    assert c["slip_days"] == 21 and {r["product"]["label"] for r in c["reaches"]} == {"Tern T2", "Porter P5", "Heron H1"}
    assert "consigned" in c["evidence"] and all(r["qty_per_robot"] for r in c["reaches"])


def test_the_sender_address_is_on_the_list_and_the_detail_exactly_as_written(client):
    ms = client.get("/api/messages").json()
    assert all("from_email" in m for m in ms) and sum(1 for m in ms if m["from_email"]) >= 12
    fraud = next(m for m in ms if m["trust"] == "suspicious" and "remittance" in m["ref"]["id"].lower())
    d = client.get(f"/api/messages/{fraud['ref']['id']}").json()
    assert d["summary"]["from_email"] == fraud["from_email"] and "@" in fraud["from_email"]
    assert not fraud["from_email"].lower().endswith("yunzhan-motor.example")                    # a look-alike shows as the look-alike, not as the supplier's own domain
    fm = next(m for m in ms if "FORCE_MAJEURE" in m["ref"]["id"])
    assert fm["from_email"].endswith("yunzhan-motor.example") and fm["supplier"]["id"] == "SUP-0001"


def test_the_annotate_route(client):
    r = client.post("/api/annotate", json={"text": "HR-40110 by 2026-10-13"})
    assert r.status_code == 200 and [(s["type"], s["ref"]) for s in r.json()] == [("part", "HR-40110"), ("date", "2026-10-13")]
    assert set(r.json()[0]) == {"start", "end", "type", "ref", "label", "text"}


def js_slice(text, start, end):
    units = text.encode("utf-16-le")
    return units[2 * start:2 * end].decode("utf-16-le")


def test_the_inbox_is_searched_by_sender_subject_body_facts_and_numbers(client):
    def find(q, **kw):
        return client.get("/api/messages", params={"q": q, **kw}).json()

    ids = lambda rows: [r["ref"]["id"][:10] + r["ref"]["id"][10:30] for r in rows]       # noqa: E731
    fm = "2026-09-22_NOTICE_OF_FORCE_MAJEURE"
    rows = find("Yunzhan")
    assert rows[0]["ref"]["id"].startswith(fm) and rows[0]["matches"][0]["field"] == "subject"             # best field first: the subject names it
    assert {r["ref"]["id"][:10] for r in rows} == {"2026-09-22", "2026-09-23", "2026-08-14"}               # the notice, the look-alike mail (sender), the quote
    assert find("HR-40110")[0]["matches"][0]["field"] == "refs"                                           # a part number the message names
    assert find("450/10")[0]["ref"]["id"].startswith(fm) and find("PO 450/10")[0]["ref"]["id"].startswith(fm)  # the 'PO 450/10' form and the bare one
    r = find("187,420")
    assert len(r) == 1 and r[0]["matches"][0]["field"] == "facts" and "187,420" in r[0]["matches"][0]["snippet"]        # an extracted fact
    assert [x["ref"]["id"][:10] for x in find("li wei")] and all(x["matches"][0]["field"] in ("from", "supplier") for x in find("Li Wei"))
    assert find("force majeure notice")[0]["ref"]["id"].startswith(fm) and find("zzzz nothing") == []        # every word must be found
    assert find("lidar")[0]["matches"][0]["field"] == "body"
    for row in find("remittance"):
        for m in row["matches"]:
            assert js_slice(m["snippet"], m["start"], m["end"]).lower() in ("remittance",)                  # the span holds the matched word, in UTF-16 indices
    assert all(r["matches"] == [] for r in client.get("/api/messages").json())                              # no search, no matches


def test_the_inbox_filters(client):
    allrows = client.get("/api/messages").json()
    assert {r["kind"] for r in client.get("/api/messages", params={"kind": "force majeure"}).json()} == {"force majeure"}
    sus = client.get("/api/messages", params={"trust": "suspicious"}).json()
    assert sus and all(r["trust"] == "suspicious" for r in sus) and len(sus) < len(allrows)
    y = client.get("/api/messages", params={"supplier": "SUP-0001"}).json()
    assert y and all(r["supplier"]["id"] == "SUP-0001" for r in y)
    window = client.get("/api/messages", params={"date_from": "2026-09-20", "date_to": "2026-09-23"}).json()
    assert window and all("2026-09-20" <= r["date"][:10] <= "2026-09-23" for r in window)
    both = client.get("/api/messages", params={"q": "Yunzhan", "trust": "suspicious"}).json()
    assert len(both) == 1 and both[0]["trust"] == "suspicious"                                              # a search and a filter together
    assert client.get("/api/messages", params={"trust": "nope"}).status_code == 422


def test_the_search_is_fast(client):
    import time

    client.get("/api/messages", params={"q": "warm"})
    t = time.perf_counter()
    for q in ("Yunzhan", "HR-40110", "450/10", "force majeure"):
        client.get("/api/messages", params={"q": q})
    assert (time.perf_counter() - t) / 4 < 0.1                                                              # under 100 ms a search on the built database


def test_the_global_search_resolves_names_numbers_and_people_first(client):
    def hits(q, **kw):
        r = client.get("/api/search", params={"q": q, **kw})
        assert r.status_code == 200
        return r.json()

    first = lambda q: (hits(q)[0]["type"], hits(q)[0]["ref"])      # noqa: E731
    assert first("Yunzhan") == ("supplier", "SUP-0001") and first("HR-40110") == ("part", "HR-40110") and first("PO 450/10") == ("po_line", "HPO-26-00450/10")
    assert first("Li Wei") == ("person", "SUP-0001/Li Wei") and first("Dana") == ("person", "Dana")
    assert {h["type"] for h in hits("Yunzhan")} >= {"supplier", "message", "item"}                          # one search across the kinds
    assert hits("450/10")[0]["ref"] == "HPO-26-00450/10"                                                    # the bare form too
    lidar = hits("lidar")
    assert lidar[0]["type"] == "part" and "Lidar" in lidar[0]["label"] and {h["type"] for h in lidar} >= {"part", "item"}
    h = hits("Yunzhan")[0]
    assert set(h) == {"type", "ref", "label", "sublabel", "matched_text", "highlight", "url", "score"} and h["url"] == "/suppliers/SUP-0001"
    assert h["matched_text"].encode("utf-16-le")[2 * h["highlight"]["start"]:2 * h["highlight"]["end"]].decode("utf-16-le").lower() == "yunzhan"
    assert {x["type"] for x in hits("Yunzhan", types="message,item")} == {"message", "item"}
    assert len(hits("Yunzhan", types="po_line", limit=50)) == 50 and len(hits("Yunzhan")) <= 30         # one kind of record does not fill a mixed list
    assert hits("zzzz nothing") == [] and client.get("/api/search").status_code == 422


def test_the_search_is_fast_across_everything(client):
    import time

    client.get("/api/search", params={"q": "warm"})
    t = time.perf_counter()
    for q in ("Yunzhan", "HR-40110", "450/10", "Li Wei", "lidar", "gearbox porter"):
        client.get("/api/search", params={"q": q})
    assert (time.perf_counter() - t) / 6 < 0.1


def test_the_lists_filter(client):
    items = client.get("/api/action-items").json()
    assert {i["group"] for i in client.get("/api/action-items", params={"kind": "deadline"}).json()} == {"deadline"}
    win = client.get("/api/action-items", params={"act_by_from": "2026-10-01", "act_by_to": "2026-10-16"}).json()
    assert win and all("2026-10-01" <= i["act_by"] <= "2026-10-16" for i in win) and len(win) < len(items)
    assert client.get("/api/action-items", params={"kind": "nope"}).status_code == 422
    assert all("Tom" in i["owner"] for i in client.get("/api/action-items", params={"owner": "Tom"}).json())
    orders = client.get("/api/orders").json()
    late = client.get("/api/orders", params={"past_due": True}).json()
    assert late and all(o["days_past_due"] > 0 and not o.get("stale") for o in late) and len(client.get("/api/orders", params={"past_due": False}).json()) == len(orders) - len(late)
    assert {o["supplier"]["id"] for o in client.get("/api/orders", params={"supplier": "SUP-0001"}).json()} == {"SUP-0001"}
    assert {o["status"].upper() for o in client.get("/api/orders", params={"status": "partial"}).json()} == {"PARTIAL"}
    assert all(o["buyer"].startswith("Tom") for o in client.get("/api/orders", params={"buyer": "Tom"}).json())
    cn = client.get("/api/suppliers", params={"country": "CN"}).json()
    assert cn and {s["country"] for s in cn} == {"CN"}
    risky = client.get("/api/suppliers", params={"risk": True}).json()
    allof = client.get("/api/suppliers").json()
    assert {s["ref"]["id"] for s in risky} == {s["ref"]["id"] for s in allof if s["risk"]} and {"SUP-0002", "SUP-0019"} <= {s["ref"]["id"] for s in risky}      # every supplier with a warning: a quote, the news, its delivery record, its terms
    assert len(client.get("/api/suppliers", params={"risk": False}).json()) == len(allof) - len(risky)



def test_a_buyer_hunting_finds_items_by_what_they_refer_to(client):
    """Five hunts: a PO line, a part, a place, 'fraud' and a supplier. The Action list is found by its refs, not only by its title."""
    def found(q, types="item,message"):
        return client.get("/api/search", params={"q": q, "types": types}).json()

    def refs(q, kind):
        return [h["ref"] for h in found(q) if h["type"] == kind]

    for q in ("450/10", "PO 450/10", "HPO-26-00450"):                                     # 1. a PO line: the fire item that holds it, and the notice that names it
        assert "disruption:SUP-0001" in refs(q, "item") and any(r.startswith("2026-09-22_NOTICE_OF_FORCE_MAJEURE") for r in refs(q, "message")), q
    assert {"disruption:SUP-0001", "tariff:HR-40110"} <= set(refs("HR-40110", "item"))   # 2. a part: every item that refers to it
    assert "deadline:quotes" in refs("Penang", "item") and any("QV-Q-2609" in r for r in refs("Penang", "message"))      # 3. a place: the roll-up of three quotes finds Quenvara by where its offer builds
    for word in ("fraud", "scam", "phishing"):                                           # 4. 'fraud' and its neighbours are the held / look-alike tag
        assert {r[:16] for r in refs(word, "item")} == {"trust:2026-09-23", "trust:2026-09-12"}, word
        assert {r[:10] for r in refs(word, "message")} == {"2026-09-23", "2026-09-12"}, word      # the held messages only: a message "for review" is not fraud
    assert {"disruption:SUP-0001", "deadline:SUP-0001:2026-10-13"} <= set(refs("Yunzhan", "item")) and len(refs("Yunzhan", "message")) >= 3         # 5. a supplier, by any of its names
    hit = next(h for h in found("Penang") if h["type"] == "message")
    assert hit["matched_text"].encode("utf-16-le")[2 * hit["highlight"]["start"]:2 * hit["highlight"]["end"]].decode("utf-16-le").lower() == "penang"


def test_a_message_is_found_by_the_records_its_text_mentions(client):
    # "Yunzhan Precision Motor" is named in the force-majeure notice's body under its own name; the search resolves the query to the record and finds every message that mentions it
    assert len([h for h in client.get("/api/search", params={"q": "Shenzhen Yunzhan Precision Motor", "types": "message"}).json()]) >= 2


def test_option_kinds_come_from_the_code_table_per_kind_of_case(client):
    """plan-13 item 2: label, button, where it leads and to whom, fixed by code per kind of case."""
    fire = client.get("/api/action-items/disruption:SUP-0001/option-kinds").json()
    assert [o["kind"] for o in fire] == ["allocation", "alternate_on_file", "second_source", "air_freight", "resequence", "wait"]
    siam = fire[1]                                                                                          # a second source already on a PO line for HR-40120, named first (F102)
    assert "Siam Motion" in siam["label"] and "HR-40120" in siam["label"] and siam["leads_to"] == "request" and siam["changes"] == "October unchanged; HR-40120 only"
    assert all(o["changes"] for o in fire) and fire[0]["changes"] == "known by Oct 10 (Yunzhan's quantity)"
    gp = client.get("/api/action-items/deadline:SUP-0041:2026-10-15/option-kinds").json()
    assert gp[0]["kind"] == "buy_ahead" and gp[0]["leads_to"] == "request" and gp[0]["erp"]                 # the acknowledgement the clerk drafts (F102 #2)
    assert "bridge" in {o["kind"] for o in client.get("/api/action-items/risk:SUP-0002/option-kinds").json()}
    cons = client.get("/api/action-items/consignment:HR-30110/option-kinds").json()
    assert [o["kind"] for o in cons] == ["earlier_date", "cm_partial", "direct_air", "cm_stock"] and "Alderpoint" in cons[1]["to"] and "Lanxin" in cons[0]["label"]
    assert "order_before" in {o["kind"] for o in client.get("/api/action-items/disruption:SUP-0013/option-kinds").json()}
    assert fire[0] == {"kind": "allocation", "label": "Allocation request · Yunzhan", "leads_to": "request", "to": "Li Wei (Yunzhan)", "button": "Write the email", "erp": False, "changes": "known by Oct 10 (Yunzhan's quantity)", "also_start": True, "by": None, "refs": [], "also_why": "Yunzhan still owes revised dates and allocation for the 10 lines; asking keeps your rights"}
    assert all(len(o["label"].replace("·", " ").split()) <= 6 for o in fire)                                # content-spec §4: a noun phrase of at most 6 words
    duty = client.get("/api/action-items/tariff:all/option-kinds").json()
    assert duty and all(o["leads_to"] != "request" for o in duty)                                          # a roll-up has no clerk: no email can exist
    ruilian = client.get("/api/action-items/incident:SUP-0018/option-kinds").json()
    assert ruilian[0]["kind"] == "confirm_dates_hold" and ruilian[0]["leads_to"] == "request"
    assert fire[-1]["leads_to"] == "record" and fire[-1]["to"] == "" and fire[-1]["button"] == "Record decision"
    risk = client.get("/api/action-items/risk:SUP-0002/option-kinds").json()
    assert "air_freight" not in {o["kind"] for o in risk} and not any("survived" in o["label"] for o in risk)    # nothing burned at an insolvent supplier
    assert client.get("/api/action-items/trust:2026-09-23_URGENT_Updated_remittance_details_following_plant_incident/option-kinds").json() == []
    assert client.get("/api/action-items/nope:1/option-kinds").status_code == 404


def test_options_for_a_case_are_only_the_kinds_its_table_has(client):
    """plan-13 item 4: /options for a supplier at risk no longer offers air freight of what survived; the slip's air freight is the delayed lines."""
    risk = client.get("/api/action-items/risk:SUP-0002/options").json()
    assert [o["kind"] for o in risk] == ["open_terms", "bridge", "second_source", "recheck"]      # its table's routes, nothing that 'survived' (FINAL-SPEC §2: every route has its figures)
    assert not any("survived" in o["label"] or "other capacity" in o["label"] for k in ("incident:SUP-0018", "risk:SUP-0029") for o in client.get(f"/api/action-items/{k}/options").json())
    slip = {o["kind"]: o for o in client.get("/api/action-items/disruption:SUP-0013/options").json()}
    assert slip["air_freight"]["label"] == "Air-ship the delayed lines"


def test_findings_are_served_per_case(client):
    fire = client.get("/api/action-items/disruption:SUP-0001/findings").json()
    assert fire[0]["key"] == "no_alt_quote" and fire[0]["template_meaning"]
    assert [f["key"] for f in client.get("/api/action-items/unknown:hts/findings").json()] == ["no_hts"]
    assert client.get("/api/action-items/nope:1/findings").status_code == 404
