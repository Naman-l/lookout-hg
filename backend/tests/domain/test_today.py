"""Today (FINAL 02): the robots each item touches (B1), a buyer's words on every row (B2) and the viewer's own slice of a team row (B3)."""

from app.domain.attention import service as attention

CODE = {"HR-90020": "T2", "HR-90050": "P5", "HR-90110": "H1"}


def robots(i) -> str:
    return " ".join(CODE[r.id] for r in i.robots)


def test_every_row_names_the_robots_whose_bom_uses_its_parts(session):
    by = {i.key: i for i in attention.what_needs_attention(session)}
    want = {
        "disruption:SUP-0001": "T2 P5", "disruption:SUP-0013": "T2 P5 H1", "incident:SUP-0018": "T2 P5", "consignment:HR-30110": "T2 P5 H1",
        "risk:SUP-0029": "T2 P5", "risk:SUP-0011": "T2 P5 H1", "risk:SUP-0002": "P5", "deadline:SUP-0042:2026-09-28": "T2", "deadline:SUP-0041:2026-10-15": "P5 H1",
        "deadline:quotes": "T2 P5 H1", "deadline:SUP-0016:2026-12-31": "T2 P5 H1", "deadline:chase": "T2 P5 H1", "tariff:all": "T2 P5 H1",
        "unknown:undated": "T2 P5", "unknown:origin": "T2 P5 H1", "unknown:hts": "T2 H1", "unknown:stale-orders": "",
    }
    assert {k: robots(by[k]) for k in want} == want
    assert all(not i.robots for i in by.values() if i.group == "trust")      # a held message names nothing it can be trusted on


def test_each_row_has_a_short_title_and_one_line_of_facts(session):
    by = {i.key: i for i in attention.what_needs_attention(session)}
    fire = by["disruption:SUP-0001"]
    assert fire.title == "Yunzhan fire: Tern and Porter short of drive motors from October" and fire.summary == "182 T2 + 40 P5 short in Oct · 188 T2 + 42 P5 in Nov · 10 lines"
    assert by["risk:SUP-0002"].summary == "sole source of HR-12210, 80 a month for P5" and by["risk:SUP-0011"].summary == "sole source of HR-50110, 182 a month for T2"      # the robots the part goes into, not every robot the supplier serves
    fraud = next(i for i in by.values() if i.key.startswith("trust:2026-09-23"))
    assert fraud.title == "Bank-detail change from a look-alike Yunzhan domain: do not pay" and fraud.summary == "call back the contact on file"
    assert by["unknown:origin"].title == "5 parts missing country of origin (COO)" and by["unknown:origin"].summary == "+$115K duty if China"
    assert by["unknown:hts"].title == "2 parts missing HTS code" and by["unknown:hts"].summary is None
    assert by["unknown:stale-orders"].summary == "PO-10711, PO-10788 (Yunzhan) · PO-10710 (Vistaray)"
    assert all("unknown" not in i.title and " owed" not in i.title for i in by.values())
    assert by["incident:SUP-0018"].summary == "3 lines pushed out +32–57 d · 2 past due"


def test_yours_shows_the_viewers_own_slice_of_a_team_row(session):
    mine = attention.what_needs_attention(session, "Dana Reyes")
    keys = [i.key for i in mine]
    assert len(mine) == 9 and "deadline:quotes" not in keys and "deadline:SUP-0002:2026-10-31" in keys
    chase = next(i for i in mine if i.key == "deadline:chase")
    assert chase.title == "2 past-due lines, no updated promise" and chase.owner == "Dana Reyes" and round(float(chase.at_stake.usd)) == 80_805
    assert chase.summary.startswith("Dongguan Xinda HR-40320 30 d late · Hallerbeck HR-12210") and chase.summary.endswith("16 across the team")
    assert robots(chase) == "P5 H1" and chase.robot_notes == {"HR-90110": "HR-40320 30 d late", "HR-90050": "HR-12210 1 d late"}
    quote = next(i for i in mine if i.key == "deadline:SUP-0002:2026-10-31")
    assert quote.title == "Hallerbeck quote expiring" and quote.summary == "$483K of forecast demand · supplier in insolvency" and robots(quote) == "P5"
    team = next(i for i in attention.what_needs_attention(session) if i.key == "deadline:chase")      # Everyone keeps the whole row
    assert team.title == "16 past-due lines, no updated promise" and team.owner.count(" · ") == 3


def test_each_buyer_sees_their_own_aged_orders_and_quotes(session):
    marcus = {i.key: i for i in attention.what_needs_attention(session, "Marcus Chen")}
    assert marcus["unknown:stale-orders"].title.startswith("1 aged open PO:") and marcus["unknown:stale-orders"].summary == "PO-10710 (Vistaray)"
    assert marcus["deadline:SUP-0022:2026-10-16"].title == "Lanxin quote expiring" and marcus["deadline:SUP-0022:2026-10-16"].summary == "5 parts (bare PCB)"
    dana = {i.key: i for i in attention.what_needs_attention(session, "Dana Reyes")}
    assert dana["unknown:stale-orders"].summary == "PO-10711, PO-10788 (Yunzhan)"
