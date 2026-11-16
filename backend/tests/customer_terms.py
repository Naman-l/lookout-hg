"""The customer's proper names and id shapes, read from the recipe's configuration and the raw data, never written here.

Read at test time: the company (answers.yaml `company`, `company_short`, `internal_domain`), the SCM team and the people on file by function
(answers.yaml `team`, `functions`), the project directory (project names, SAP plant names, project heads and planners) and the vendor master (each
vendor's full name, the brand word its mail domain starts with, its contact person). Ordinary words are learned from the data itself: a word the
mails, the material master or the sheets write in lower case in running text is not a name. Used by the scans that keep these facts out of code.
"""

from __future__ import annotations

import collections
import csv
import re
from functools import cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RECIPE = ROOT / "recipes" / "hg"
DATA = ROOT / "data"
LEGAL = {"pvt", "private", "ltd", "limited", "llp", "co", "company", "and", "the", "of", "india", "m", "s", "industries", "enterprises", "works"}
SHAPES = ("pr", "pr_line", "po", "po_line", "mat_doc")      # not the vendor code (any six digits from 1) or the material (any eight from 11): too common in code to scan for


def _words(text: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[A-Za-z]+", text or "")]


def _rows(path: Path) -> list[dict]:
    """A SAP export or a sheet: the stamp line, if any, is skipped."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = 1 if lines and " | " in lines[0] and "," not in lines[0].split(" | ")[0] else 0
    return list(csv.DictReader(lines[start:]))


def _person(name: str, email: str) -> bool:
    """A person, whose address carries their first name; a mailbox such as 'Accounts' or 'Office of the Managing Director' is not."""
    first = (name or "").split(" ")[0].lower()
    return (name or "").count(" ") >= 1 and bool(first) and first in re.split(r"[._-]", (email or "").split("@")[0].lower())


@cache
def generic_words() -> frozenset[str]:
    corpus = [p.read_text(encoding="utf-8", errors="ignore") for p in (DATA / "inbox").glob("*.eml")] + [(RECIPE / "answers.yaml").read_text()]
    corpus += [r.get("Material Description", "") for r in _rows(DATA / "sap" / "material_master.csv")]
    corpus += [p.read_text(encoding="utf-8", errors="ignore") for p in (DATA / "sheets").glob("*.csv") if p.name != "Project Directory.csv"]
    out: set[str] = set()
    for text in corpus:
        text = re.sub(r"\S+@\S+|https?://\S+", " ", text)      # an address spells a name in lower case: it does not make the name an ordinary word
        out |= set(re.findall(r"(?<![\w\-/.:@])[a-z]{3,}(?![\w\-/:@]|\.\w)", text))
    return frozenset(out)


@cache
def names() -> tuple[frozenset[str], frozenset[str]]:
    """(single words matched as whole words, phrases matched whole), all lower case."""
    answers = yaml.safe_load((RECIPE / "answers.yaml").read_text())
    generic = generic_words()
    words: set[str] = set()
    phrases: set[str] = {str(answers["company"]).lower().rstrip("."), str(answers["company_short"]).lower()}
    words.add(str(answers["internal_domain"]).split(".")[0].lower())
    words |= {w for w in _words(answers["company_short"]) if len(w) >= 4 and w not in LEGAL and w not in generic}      # the word the company is called by
    for m in answers.get("team") or []:
        phrases.add(m["name"].lower())
        words |= {str(m["id"]).lower(), str(m.get("sap_user") or "").lower()}      # the team's first names (the ids the recipe uses) and SAP user names
    for f in (answers.get("functions") or {}).values():
        if _person(f.get("name", ""), f.get("email", "")):
            phrases.add(f["name"].lower())
    for r in _rows(DATA / "sheets" / "Project Directory.csv"):
        name = r["Project"].strip()
        if " " in name or "-" in name or name.lower() not in generic:
            (phrases if " " in name or "-" in name else words).add(name.lower())
        phrases.add(r["SAP Plant Name"].strip().lower())
        for who, mail in (("Project Head", "Head Email"), ("Planner", "Planner Email")):
            if _person(r[who], r[mail]):
                phrases.add(r[who].strip().lower())
    vendors = _rows(DATA / "sap" / "vendor_master.csv")
    domains_of = collections.defaultdict(set)      # a word one or two companies' names use is a brand; a word many share is ordinary
    for r in vendors:
        for w in _words(r["Name 1"]):
            domains_of[w].add(r["E-Mail Address"].split("@")[-1].lower())
    for r in vendors:
        domain = r["E-Mail Address"].split("@")[-1].split(".")[0].lower()
        for w in _words(r["Name 1"]):
            if len(w) >= 5 and w not in LEGAL and w not in generic and len(domains_of[w]) <= 2 and domain.startswith(w):
                words.add(w)
        clean = [w for w in re.findall(r"[A-Za-z'-]+", r["Name 1"]) if w.lower() not in LEGAL]
        if len(clean) >= 2:
            phrases.add(" ".join(clean).lower())
        if _person(r["Contact Person"], r["E-Mail Address"]):
            phrases.add(r["Contact Person"].strip().lower())
    words.discard("")
    return frozenset(words), frozenset(p for p in phrases if p)


@cache
def pattern() -> re.Pattern:
    words, phrases = names()
    shapes = yaml.safe_load((RECIPE / "answers.yaml").read_text())["id_shapes"]
    alts = [re.escape(x) for x in sorted(words | phrases, key=len, reverse=True)]
    ids = "|".join(f"(?:{shapes[k]})" for k in SHAPES if shapes.get(k))
    return re.compile(r"(?i)(?<![\w-])(?:" + "|".join(alts) + r")(?![\w-])|(?<![\w/])(?:" + ids + r")(?![\w])")
