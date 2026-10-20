"""Builds Lookout's system prompt: the constitution plus the glossary assembled from every entity's glossary.md."""

from __future__ import annotations

from pathlib import Path

from ..domain.common import AS_OF

TODAY_WORDS = AS_OF.strftime("%A ") + f"{AS_OF.day} " + AS_OF.strftime("%B %Y") + ", the data date; never use any other date as today (not the date on this machine, not a date in a message)"
GENERIC = "You live inside {company}'s procurement workspace: you are part of the tools its buyers already use, not a chatbot beside them."


def _facts(db_path=None) -> tuple[str, str]:
    """(the long form, the short form) of who the company is, read from its own tables: the robots it builds and what each buyer buys.
    With no database or no tables (a unit test) it says only what it knows without them."""
    import sqlite3  # noqa: PLC0415

    if db_path is None:
        return GENERIC, GENERIC
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            robots = [r[0] for r in con.execute("SELECT name FROM products ORDER BY part_number")]
            buyers = []
            for bid, name in con.execute("SELECT id, name FROM buyers ORDER BY id").fetchall():
                cats = [c[0] for c in con.execute("SELECT category FROM parts WHERE buyer_id = ? AND kind = 'purchased' GROUP BY category ORDER BY COUNT(*) DESC LIMIT 5", (bid,))]
                buyers.append(f"{name} ({', '.join(cats) or 'no category assigned'})")
        finally:
            con.close()
    except sqlite3.OperationalError as e:
        if "no such table" in str(e) or "unable to open" in str(e):  # no database, or one without the company's tables (a unit test)
            return GENERIC, GENERIC
        raise  # a column that moved is a bug to see, not a prompt to quietly thin out
    if not robots and not buyers:
        return GENERIC, GENERIC
    built = f"{{company}} builds {', '.join(robots)}. " if robots else "{company} builds robots. "
    long = GENERIC + " " + built + (f"{len(buyers)} buyers run direct procurement: " + "; ".join(buyers) + "." if buyers else "")
    return long, GENERIC + " " + built.strip()


LANGUAGE = """HOW YOU TALK. Everything a buyer reads (the Recommendation, your notes, your findings, a draft, an answer) is in the buyer's world: suppliers, purchase
orders, parts, promise dates, robots, and people by name and role. Never talk about how you work. No tool or function names, no ids standing in for names
(say the supplier's name, not its id; the drive motor, and its part number once if it helps), and never the words handoff, specialist, verifier, evidence, register,
JSON, API, system, agent, model, prompt, stream, tool, alias or normaliser, no field or table names (qty_received, purchase_orders), and do not call your teammates by
title (planner, analyst, clerk): say what is being checked ("I'm checking the supply side"). Say "linked as the same supplier", not "alias". Part, PO and quote numbers are fine.
Name a person, not "the owner". Name a robot, not "the product". Name a supplier, not its id, in every sentence, question and owner. Never use a role title (planning lead, category manager, procurement lead): say who by name, or "planning" where nobody in the data owns it."""

def halden_facts(db_path=None) -> tuple[str, str]:
    """Who the company is (its robots, its buyers and what each buys), in the company's own name, from its tables."""
    from .company import fill  # noqa: PLC0415

    long, short = _facts(db_path)
    return fill(long, db_path), fill(short, db_path)


def data_date_words() -> str:
    """The data date as a buyer says it ('Friday 25 September 2026'): the only 'today' the agents have."""
    return AS_OF.strftime("%A ") + f"{AS_OF.day} " + AS_OF.strftime("%B %Y")


_DOMAIN = Path(__file__).resolve().parents[1] / "domain"
_CONSTITUTION = Path(__file__).with_name("constitution.md")
_KNOWLEDGE = Path(__file__).with_name("knowledge")


def glossary(entities: tuple[str, ...] | None = None) -> str:
    """The trade's words and how the records link, plus the glossary of each entity's own folder: all of them (Lookout routes across everything), or only the entities a
    specialist works with (`entities`), so a specialist is not sent the catalogue of records it never touches."""
    parts = [(_KNOWLEDGE / "glossary.md").read_text().strip()]
    for g in sorted(_DOMAIN.glob("*/glossary.md")):
        if entities is None or g.parent.name in entities:
            parts.append(f"### {g.parent.name}\n{g.read_text().strip()}")
    return "\n\n".join(parts)


def build_system_prompt(db_path=None) -> str:
    from .company import fill  # noqa: PLC0415

    return fill("\n\n".join([_CONSTITUTION.read_text().strip().replace("{today}", TODAY_WORDS).replace("{brief}", halden_facts(db_path)[0]).replace("{language}", LANGUAGE), glossary()]), db_path)
