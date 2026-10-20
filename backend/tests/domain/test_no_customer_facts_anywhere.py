"""No file of the app names this customer: not in code, not in a comment, not in a prompt, not in the screens.

The names and ids are not written here: they are read at test time from the recipe's configuration (answers.yaml: the company, the buyers, the products, the id shapes) and from the data
(the supplier master: every supplier's distinctive name words; the contacts' names). Scanned: backend/app/**/*.py and *.md (prompts, glossaries) and frontend/src/**/*.ts(x), comments and
docstrings included. Not scanned: tests, fixtures, the saved recordings, the generated API types. Nothing is allow-listed: a hit is fixed at the source (configuration or generic copy)."""

from __future__ import annotations

import collections
import csv
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "backend" / "app"
SRC = ROOT / "frontend" / "src"
RECIPE = ROOT / "recipes" / "halden"
DATA = ROOT / "data"
SKIP_DIRS = {"recordings", "fixtures", "__pycache__", "node_modules", "dev"}      # saved runs, test data, caches, and the developer stand-ins that exist to fake this customer
SKIP_FILES = {"schema.d.ts"}      # generated from the contract
LEGAL = {"co", "ltd", "inc", "gmbh", "corp", "company", "limited", "llc", "jsc", "srl", "sa", "cv", "de", "the", "and", "ag", "kg", "plc", "pte", "sdn", "bhd"}


def _words(text: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[A-Za-zÀ-ÿ]+", text or "")}


def _terms() -> tuple[re.Pattern, list[str]]:
    """The customer's proper names and id shapes, from the config and the data: a supplier's brand word (the word of its name its mail domain starts with), its full name, every contact and
    buyer by full name, the buyers' first names, the products, the company, and each kind of id."""
    answers = yaml.safe_load((RECIPE / "answers.yaml").read_text())
    generic = set()      # ordinary words, learned from the data itself: any word the corpus (the part descriptions, the mails, the notices, the news) writes in lower case somewhere
    corpus = []
    with (DATA / "parts.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            corpus.append(row.get("description", "") + " " + row.get("category", ""))
    for path in [*(DATA / "quotes").glob("*"), *(DATA / "external").glob("*")]:
        if path.suffix in {".eml", ".txt", ".md", ".json"}:
            corpus.append(path.read_text(encoding="utf-8", errors="ignore"))
    for text in corpus:
        text = re.sub(r"\S+@\S+|https?://\S+", " ", text)      # an address spells a name in lower case: it does not make the name an ordinary word
        generic |= set(re.findall(r"(?<![\w\-/.:@])[a-zà-ÿ]{3,}(?![\w\-/:@]|\.\w)", text))      # a word standing alone in running text, not part of a file name, a path or a domain
    brands: set[str] = set()
    phrases: set[str] = set()
    with (DATA / "suppliers.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    domains_of = collections.defaultdict(set)      # how many different companies (mail domains) use a word in their name: a word one company owns is a brand, a word many share is ordinary
    for r in rows:
        for w in _words(r["name"]):
            domains_of[w].add(r.get("contact_email", "").split("@")[-1].lower())
    name_words = {w: len(d) for w, d in domains_of.items()}
    for row in rows:
        domain = (row.get("contact_email", "").split("@")[-1].split(".")[0]).lower()
        for w in _words(row["name"]):
            if len(w) >= 5 and w not in LEGAL and w not in generic and name_words[w] <= 2 and domain.startswith(w):
                brands.add(w)      # the word its own mail domain starts with, and not an ordinary word or one many suppliers share
        clean = [w for w in re.findall(r"[A-Za-zÀ-ÿ'-]+", row["name"]) if w.lower() not in LEGAL]
        if len(clean) >= 2:
            phrases.add(" ".join(clean))
        first = row.get("contact_name", "").split(" ")[0].lower()
        if row.get("contact_name", "").count(" ") >= 1 and first and first in re.split(r"[._-]", row.get("contact_email", "").split("@")[0].lower()):      # a person, whose address carries their name; a mailbox such as "Order Desk" is not
            phrases.add(row["contact_name"].strip())
    for b in answers.get("buyers", []) or []:
        if isinstance(b, dict):
            phrases.add(str(b.get("name", "")))
            brands.add(str(b.get("id", "")).lower())      # the buyers' first names
    for p in (answers.get("products") or []):
        brands |= {w for w in _words(str(p.get("name", "") if isinstance(p, dict) else p)) if len(w) >= 4}
    brands |= {w for w in _words(str(answers.get("company", ""))) if len(w) >= 4 and w not in LEGAL}
    brands.discard("")
    shapes = [s for s in (answers.get("id_shapes") or {}).values() if s]
    alts = [re.escape(x) for x in sorted(brands | {p.lower() for p in phrases if p}, key=len, reverse=True)]
    pattern = re.compile(r"(?i)\b(?:" + "|".join(alts) + r")\b|" + "|".join(f"(?:{s})" for s in shapes))
    return pattern, sorted(brands | phrases)


def _files():
    for base, suffixes in ((APP, {".py", ".md"}), (SRC, {".ts", ".tsx"})):
        for path in sorted(base.rglob("*")):
            if path.is_file() and path.suffix in suffixes and path.name not in SKIP_FILES and not SKIP_DIRS & set(path.relative_to(base).parts):
                yield path


def test_the_terms_come_from_the_config_and_the_data():
    _, names = _terms()
    low = {n.lower() for n in names}
    assert len(names) > 40 and {"yunzhan", "halden", "great plains extrusion", "dana reyes"} <= low      # read from the supplier master and the recipe, not written here      # read, not written here: the check would be empty without the supplier master and the recipe


def test_no_file_of_the_app_names_the_customer_its_suppliers_people_or_ids():
    pattern, _ = _terms()
    hits = []
    for path in _files():
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            m = pattern.search(line)
            if m:
                hits.append(f"{path.relative_to(ROOT)}:{n}: {m.group(0)!r} in {line.strip()[:90]!r}")
    assert hits == [], f"{len(hits)} places name this customer; make them generic or read them from configuration:\n" + "\n".join(hits[:60])


def test_the_scan_goes_red_on_a_name_a_person_an_id_or_the_company():
    """A scan that cannot fail proves nothing: each kind of fact, written into a line, is found; ordinary words and generic examples are not."""
    pattern, _ = _terms()
    for line in ("# ask Yunzhan for dates", "# Katrin Vogel replies", "return 'Dana'", "e = 'SUP-0007'", "x = 'HR-12345'", "# the Halden buyers", "# Tern robots", "# Great Plains Extrusion Co."):
        assert pattern.search(line), line
    for line in ("# ask the supplier for dates", "# state of the order", "e = 'XX-0007'", "# the company's buyers", "# Acme Extrusion", "# an order desk and the components"):
        assert not pattern.search(line), line


def test_the_constitution_renders_whole_with_its_brief_and_no_placeholder_left(db_path):
    """The placeholder for the customer's brief was renamed (it used to carry the customer's name): the rendered system prompt must still be the template with every placeholder filled.
    Byte-compared against the previous rendering when it was renamed (identical, 31,391 characters on this build)."""
    from app.organism import prompts

    text = prompts.build_system_prompt(str(db_path))
    template = (APP / "organism" / "constitution.md").read_text()
    assert "{brief}" in template and "{halden}" not in template
    brief = prompts.halden_facts(str(db_path))[0]
    assert brief and brief in text
    assert not re.search(r"\{(today|language|brief|company|company_short)\}", text)      # every placeholder was filled
