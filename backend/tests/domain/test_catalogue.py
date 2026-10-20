"""The glossary pages (a glossary.md per entity folder, assembled into the agent's prompt) cannot drift from the schema or the data, and carry no customer's facts."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from app.domain.base import Base
from app.domain.common import Method
from app.domain.inbox import trust
from tests.domain.test_no_halden_logic import PATTERN

DOMAIN = Path(__file__).resolve().parents[2] / "app" / "domain"
TABLES = re.compile(r"<!--\s*tables:\s*(.*?)\s*-->")


def _entries():
    """One entry per glossary page: its folder, the tables it says it describes, and its text."""
    out = []
    for g in sorted(DOMAIN.glob("*/glossary.md")):
        raw = g.read_text(encoding="utf-8").strip()
        m = TABLES.search(raw)
        out.append(SimpleNamespace(key=g.parent.name, tables=[t.strip() for t in (m.group(1) if m else "").split(",") if t.strip()], text=TABLES.sub("", raw).strip()))
    return out


service = SimpleNamespace(entries=_entries, DOMAIN=DOMAIN)
LEDGER_TABLES = {"actions", "outbox", "run_actions", "supplier_links", "runs", "run_events"}      # created by the ledger and the run store, not by the build
RAW = re.compile(r"^raw_")
HELD = {"events", "deadlines", "consignments"}      # their glossary feeds the agent's prompt, which is frozen until round 6 of the evals is done; it lands with the news rows and the slip propagation (branches held-d7-news, held-d10)


def _text() -> str:
    return "\n".join(e.text for e in service.entries())


def test_every_table_the_build_makes_is_described_once():
    from app.domain.imports import build  # noqa: F401  (registers every model)

    named = [t for e in service.entries() for t in e.tables]
    assert len(named) == len(set(named)), "a table is described twice"
    built = set(Base.metadata.tables) - HELD
    assert built <= set(named), f"tables with no description: {sorted(built - set(named))}"
    assert set(named) <= built | LEDGER_TABLES, f"described but not in the schema: {sorted(set(named) - built - LEDGER_TABLES)}"


def test_every_flag_the_orders_carry_is_explained(db_path):
    flags = {f for (v,) in sqlite3.connect(db_path).execute("select flags from po_lines where flags is not null") for f in v.split(",") if f}
    orders = next(e for e in service.entries() if e.key == "orders").text
    assert flags and all(f"`{f}`" in orders for f in flags), sorted(f for f in flags if f"`{f}`" not in orders)


def test_every_provenance_method_and_every_trust_verdict_is_explained():
    common = next(e for e in service.entries() if e.key == "common").text
    assert all(f"`{m}`" in common for m in Method.__args__)
    inbox = next(e for e in service.entries() if e.key == "inbox").text
    assert all(f"`{v}`" in inbox for v in ("blocked", "review", "ok")) and all(w in inbox for w in ("look-alike", "bank details", "instruction aimed at software"))
    assert trust.BLOCK == {"sender_domain_lookalike", "reply_to_freemail", "bank_detail_change", "instruction_in_message"}      # the four things the glossary says block


def test_the_tariff_buckets_and_the_import_vocabulary_are_named():
    tariffs = next(e for e in service.entries() if e.key == "tariffs").text
    assert all(w in tariffs for w in ("**owed**", "**conditional**", "**if China**"))
    imports = next(e for e in service.entries() if e.key == "imports").text
    assert all(f"`{h}`" in imports for h in ("fix", "infer", "flag", "link", "leave", "drop"))


def test_no_customer_fact_is_written_in_the_glossary_pages():
    assert not PATTERN.findall(_text()), [m.group(0) for m in PATTERN.finditer(_text())]


def test_the_glossary_pages_do_not_name_the_company_it_says_the_company():
    """The company's name is configuration (answers.yaml `company`, build_meta), said once in the prompt; the glossary pages that go into every prompt never carry it."""
    named = [f"{p.parent.name}: {m.group(0)}" for p in sorted(service.DOMAIN.glob("*/glossary.md")) for m in re.finditer(r"\bHalden\b", p.read_text(encoding="utf-8"))]
    assert not named, named


def test_the_agent_is_given_the_same_text():
    from app.organism import prompts

    given = prompts.glossary()
    assert all(e.text in given for e in service.entries())

