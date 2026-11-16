"""Entity annotation: what a text mentions, matched against the records. Deterministic; no model.

Projects by name, any alias a person answered for and plant code (a misspelt site name or a city name finds the project it was answered for); materials by code;
vendors by name or code; people on file by name; PR and PO numbers (and "PO ... item 10"); rupee amounts as the team writes them (Rs. 1,40,00,000,
₹3.2 Cr, 15 L, INR 320 crore); dates (28 October 2026, 28.10.2026); quantities with units. The longest match wins and matches never overlap. In a held
message a vendor's name is a claim: it is never resolved to the vendor."""

from __future__ import annotations

import re
from datetime import date

from sqlalchemy.orm import Session

from app.domain import lookups
from app.domain.annotate.schema import Span
from app.domain.cache import memo
from app.domain.fmt import dmy, inr, qty_text

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
DATE_LONG = re.compile(r"(?<!\w)(\d{1,2})(?:st|nd|rd|th)?\s+(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?,?\s+(\d{4})(?!\w)", re.I)
DATE_DOT = re.compile(r"(?<![\w.])(\d{2})\.(\d{2})\.(\d{4})(?![\w.])")
MONEY = re.compile(r"(?:(?:Rs\.?|INR|₹)\s?(\d[\d,]*(?:\.\d+)?)(?:\s?(crore|cr|lakh|lac|l)\b)?|(?<![\w.])(\d+(?:\.\d+)?)\s?(crore|cr|lakh|lac|l)\b)", re.I)
QTY = re.compile(r"(?<![\w.,])(\d[\d,]*(?:\.\d+)?)\s?(nos\.?|no\.?|km|mt|sets?|bags?|rm|sqm|lots?)(?!\w)", re.I)
PR = re.compile(r"(?<!\d)(10\d{8})(?:\s*/\s*(\d{1,3}))?(?!\d)")
PO = re.compile(r"(?<!\d)(45\d{8})(?:\s*/\s*(\d{1,3})|(?:[^.\n]{0,40}?\bitem\s+(\d{1,3})))?(?!\d)")


def _utf16(text: str) -> list[int]:
    out, n = [], 0
    for ch in text:
        out.append(n)
        n += 2 if ord(ch) > 0xFFFF else 1
    out.append(n)
    return out


@memo
def lexicon(session: Session) -> list[tuple[re.Pattern, str, str, str]]:
    """(pattern, type, id, label), longest names first."""
    terms: list[tuple[str, str, str, str]] = []
    for p in lookups.projects(session).values():
        terms.append((p.name, "project", p.id, p.name))
        for a in lookups.aliases(session).get(p.id, []):
            if a.method != "unresolved" and len((a.project_ids or "").split(",")) == 1 and a.alias.lower() != p.name.lower():
                terms.append((a.alias, "project", p.id, f"{p.name} ({a.alias})"))
    for code, pl in lookups.plants(session).items():
        if pl.project_id:
            terms.append((code, "plant", pl.project_id, f"{lookups.project_name(session, pl.project_id)} (plant {code})"))
    for code, m in lookups.materials(session).items():
        terms.append((code, "material", code, m.description))
    for ident in lookups.identities(session):
        terms.append((lookups.vendor_name(session, ident), "supplier", ident, lookups.vendor_name(session, ident)))
        for r in lookups.records_of(session).get(ident, []):
            terms.append((r.name, "supplier", ident, lookups.vendor_name(session, ident)))
            terms.append((r.record_id, "supplier", ident, f"{lookups.vendor_name(session, ident)} ({r.record_id})"))
    for b in lookups.team(session).values():
        terms.append((b.name, "person", b.id, f"{b.name}, {b.role}"))
    for c in lookups.contacts(session).values():
        if c.name and " " in c.name:
            terms.append((c.name, "person", c.id, f"{c.name}, {(c.title or c.function.replace('_', ' '))}"))
    seen, out = set(), []
    for t, typ, i, label in sorted(terms, key=lambda x: -len(x[0])):
        if (t.lower(), typ) in seen or len(t) < 3:
            continue
        seen.add((t.lower(), typ))
        pat = re.compile(rf"(?<![\w-]){re.escape(t)}(?![\w-])" if not t.isdigit() else rf"(?<!\d){re.escape(t)}(?!\d)", re.I)
        out.append((pat, typ, i, label))
    return out


def _amount(num: str, unit: str | None) -> float:
    v = float(num.replace(",", ""))
    u = (unit or "").lower()
    return v * 1e7 if u in ("crore", "cr") else v * 1e5 if u in ("lakh", "lac", "l") else v


def annotate(session: Session, text: str | None, held: bool = False) -> list[Span]:
    if not text:
        return []
    u = _utf16(text)
    taken: list[tuple[int, int]] = []
    out: list[Span] = []

    def add(s: int, e: int, typ: str, ref: str, label: str):
        if any(not (e <= a or s >= b) for a, b in taken):
            return
        taken.append((s, e))
        out.append(Span(start=u[s], end=u[e], type=typ, ref=ref, label=label, text=text[s:e]))

    for m in PO.finditer(text):
        item = m.group(2) or m.group(3)
        if item:
            add(m.start(), m.end(1) if m.group(3) else m.end(), "po_line", f"{m.group(1)}/{item}", f"PO {m.group(1)} item {item}")
        else:
            add(m.start(), m.end(), "po", m.group(1), f"PO {m.group(1)}")
    for m in PR.finditer(text):
        if m.group(2):
            add(m.start(), m.end(), "pr_line", f"{m.group(1)}/{m.group(2)}", f"PR {m.group(1)} item {m.group(2)}")
        else:
            add(m.start(), m.end(), "pr", m.group(1), f"PR {m.group(1)}")
    for m in MONEY.finditer(text):
        num, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        try:
            v = _amount(num, unit)
        except ValueError:
            continue
        add(m.start(), m.end(), "money", f"{v:.2f}", inr(v))
    for m in DATE_LONG.finditer(text):
        mon = next(i for i, x in enumerate(MONTHS, 1) if x.startswith(m.group(2).lower()[:3]))
        try:
            d = date(int(m.group(3)), mon, int(m.group(1))).isoformat()
        except ValueError:
            continue
        add(m.start(), m.end(), "date", d, dmy(d))
    for m in DATE_DOT.finditer(text):
        try:
            d = date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            continue
        add(m.start(), m.end(), "date", d, dmy(d))
    for pat, typ, i, label in lexicon(session):
        for m in pat.finditer(text):
            if held and typ == "supplier":
                continue      # a held message's vendor name is the sender's claim
            add(m.start(), m.end(), typ, i, label)
    for m in QTY.finditer(text):
        unit = m.group(2).rstrip(".").upper().replace("NOS", "NO")
        add(m.start(), m.end(), "quantity", f"{m.group(1).replace(',', '')} {unit}", qty_text(float(m.group(1).replace(",", "")), unit))
    return sorted(out, key=lambda s: s.start)
