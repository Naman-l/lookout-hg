"""Real names in the review repo (~/Downloads/scm-departmental-review, the source of HG facts), read at test time and never written here.

People: every "Name <address>" the repo writes, the deck's presenter, and the owner of any personal OneDrive or SharePoint link. Vendors: every
party in a payment projection the repo carries ("Party Name"), except ordinary words (written in lower case in the repo or the HG data), a project or plant name (HG's own, carried on purpose), or a
code of three letters or fewer. Also the company's real mail domain and personal file links. Only project names, plant codes, materials, units,
rates and sheet layouts were taken from the repo; none of what this module reads may appear in the HG build, with one exception: the SCM team. The
user supplied HG's SCM organogram on 21 Oct 2026 to be used as it is (dummy_data/hg_organogram.csv), so a person the organogram names is HG's own on
purpose, like the project names, and is not a hit.
"""

from __future__ import annotations

import csv
import re
from functools import cache
from pathlib import Path

from tests import customer_terms

REVIEW = Path.home() / "Downloads" / "scm-departmental-review"


def _texts():
    for p in sorted((REVIEW / "src").rglob("*")):
        if p.is_file() and p.suffix in {".ts", ".tsx", ".csv", ".md", ".json"}:
            yield p, p.read_text(encoding="utf-8", errors="ignore")


@cache
def terms() -> dict[str, frozenset[str]]:
    people, vendors, domains = set(), set(), set()
    for p, text in _texts():
        for name, addr in re.findall(r"([A-Z][a-z]+(?: [A-Z][a-z]+){1,3}) <([^>@\s]+@[^>\s]+)>", text):
            people.add(name)
            domains.add(addr.split("@")[1].lower())
        people |= set(re.findall(r"presenter:\s*'([^']+)'", text))
        people |= {f"{a} {b}".title() for a, b in re.findall(r"personal/([a-z]+)_([a-z]+)_", text)}
        if p.suffix == ".csv":
            rows = list(csv.reader(text.splitlines()))
            for i, r in enumerate(rows):
                if "Party Name" in r:
                    j = r.index("Party Name")
                    vendors |= {x[j].strip() for x in rows[i + 1:] if len(x) > j and x[j].strip()}
    generic = set(customer_terms.generic_words())      # and any word the review repo itself writes in lower case in running text
    for _, text in _texts():
        generic |= set(re.findall(r"(?<![\w\-/.:@])[a-z]{3,}(?![\w\-/:@]|\.\w)", re.sub(r"\S+@\S+|https?://\S+", " ", text)))
    ours = {n.lower() for n in customer_terms.names()[0]} | set(customer_terms.names()[1])      # HG's project and plant names were carried on purpose
    vendors = {v for v in vendors if len(re.sub(r"[^A-Za-z]", "", v)) > 3 and v.lower() not in ours
               and not all(w.lower() in generic for w in re.findall(r"[A-Za-z]+", v))}
    return {"people": frozenset(people - organogram_people()), "vendors": frozenset(vendors), "domains": frozenset(domains), "people_read": frozenset(people)}


@cache
def organogram_people() -> frozenset[str]:
    """The names HG's SCM organogram writes ("Mr Satish Kumar Sharma", "1. Mohan Bahadur-(Manager)"), read from the sheet the user supplied."""
    sheet = Path(__file__).resolve().parents[2] / "dummy_data" / "hg_organogram.csv"
    out = set()
    for row in (csv.reader(sheet.open(encoding="utf-8", newline="")) if sheet.exists() else []):
        for cell in row:
            first = cell.strip().split("\n")[0]
            m = re.match(r"^Mr\.?\s+(.+?)\s*$", first) or re.match(r"^\d+\.\s*([A-Z][A-Za-z ]+?)\s*(?:-?\s*\(|\s-)", first)
            if m:
                out.add(m.group(1).strip())
    return frozenset(out)


def pattern() -> re.Pattern:
    t = terms()
    names = sorted(t["people"] | t["vendors"], key=len, reverse=True)
    links = [re.escape(d) for d in t["domains"]] + [r"sharepoint\.com", r"1drv\.ms", r"onedrive\.live"]
    return re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(n) for n in names) + r")(?![\w-])|(?i:" + "|".join(links) + ")")
