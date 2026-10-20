"""Entity annotation: the things a text mentions, found by matching it against the records. Deterministic; no model.

A phrase that means two records is dropped, never guessed (two parts with the same description are found by their number only). The longest match wins and
matches never overlap. A sender domain that imitates a supplier's is returned as `supplier_lookalike` and never resolves to that supplier."""

from __future__ import annotations

import re
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import naming
from app.domain.annotate.schema import Span
from app.domain.bom.service import where_used
from app.domain.cache import memo
from app.domain.common import AS_OF
from app.domain.demand.model import Product
from app.domain.inbox import trust
from app.domain.orders.model import PoLine
from app.domain.parts.model import Buyer, Part
from app.domain.suppliers.model import SupplierIdentity, SupplierRecord

LEGAL = re.compile(r"[,\s]+(?:co\.?,?\s*ltd\.?|co\.?|ltd\.?|gmbh|inc\.?|llc|s\.a\.(?:\s*de\s*c\.v\.)?|s\.p\.a\.?|ag|bv|b\.v\.|oy|ab|jsc|plc|srl|sdn\.?\s*bhd|corp\.?|corporation|limited|pte\.?\s*ltd\.?)$", re.I)
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
MONTH = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
ISO_DATE = re.compile(r"(?<![\w-])(\d{4})-(\d{2})-(\d{2})(?![\w-])")
MD_DATE = re.compile(rf"(?<![\w])({MONTH})\.?\s+(\d{{1,2}})(?:,?\s+(\d{{4}}))?(?![\w])")
DM_DATE = re.compile(rf"(?<![\w])(\d{{1,2}})\s+({MONTH})\.?(?:,?\s+(\d{{4}}))?(?![\w])")
PO_FULL = re.compile(r"(?<![\w-])[A-Z]{2,4}-\d{2}-\d{5}/\d{1,3}(?![\w/])")
PO_SHORT = re.compile(r"(?<![\w-])PO\s*#?\s*(\d{3,5})\s*/\s*(\d{1,3})(?![\w/])")
PART_NO = re.compile(r"(?<![\w-])[A-Z]{1,4}-\d{4,6}(?![\w-])")
EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
DOMAIN = re.compile(r"(?<![\w@.-])([a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:[a-z]{2,24}))(?![\w-])", re.I)
CUR = r"(?:USD|EUR|CNY|RMB|GBP|JPY|CHF|US\$|\$|€|£)"
NUM = r"\d[\d,]*(?:\.\d+)?"
MONEY = re.compile(rf"(?<![\w$€£]){CUR}\s?{NUM}(?:\s?[kKmM](?![\w]))?|(?<![\w.,]){NUM}\s?(?:USD|EUR|CNY|RMB|GBP)(?![\w])")
DURATION = re.compile(r"(?<![\w.,/-])(\d+(?:\.\d+)?)(?:\s?(?:to|-|–)\s?(\d+(?:\.\d+)?))?\s?(weeks?|days?|months?|hours?|wks?)(?![\w])", re.I)
INCOTERM_PLACE = re.compile(r"\b(?:FOB|FCA|EXW|DDP|DAP|CIF|CFR|CPT|CIP|FAS|DPU)\s+([A-Z][\w.-]*(?:\s[A-Z][\w.-]*)?)")
BANK_LINE = re.compile(r"(?im)^[ \t]*(?:beneficiary|account\s*(?:name|holder|no\.?|number)|bank(?:\s*name)?|iban|swift|bic|routing|sort\s*code|remit(?:tance)?\s*to|pay(?:ment)?\s*to)\b[^\n]*$")
QTY = re.compile(rf"(?<![\w.,$€£-])({NUM})\s?(pcs|pieces|piece|units|unit|EA|KPCS|robots|boards|sets|metres|meters|ft|feet|m)(?![\w])", re.I)


def _utf16(text: str) -> list[int]:
    """The UTF-16 index of every code point of `text` (plus the end), since JavaScript counts a character outside the basic plane as two."""
    out, n = [], 0
    for ch in text:
        out.append(n)
        n += 2 if ord(ch) > 0xFFFF else 1
    out.append(n)
    return out


class Lexicon:
    def __init__(self, session: Session):
        self.parts = {p.part_number: p for p in session.scalars(select(Part))}
        fam = {p.part_number: p.family for p in session.scalars(select(Product))}
        self.hint: dict[str, str] = {}
        for pn in self.parts:
            made = sorted({fam.get(w.product.id, w.product.id) for w in where_used(session, pn)})
            self.hint[pn] = " and ".join(made)
        named: dict[str, set[str]] = {}
        for pn, p in self.parts.items():
            for phrase in (p.description or "", naming.part_name(p.description)):
                if len(phrase) >= 6:
                    named.setdefault(phrase.lower(), set()).add(pn)
        self.part_phrases = {k: next(iter(v)) for k, v in named.items() if len(v) == 1}      # a description two parts share is found by number only
        self.part_labels = {pn: sorted({(p.description or "").lower(), naming.part_name(p.description).lower()} - {""}, key=len, reverse=True) for pn, p in self.parts.items()}
        sup: dict[str, set[str]] = {}
        self.supplier_names: dict[str, str] = {}
        self.domains: dict[str, str] = {}
        self.contacts: dict[str, set[tuple[str, str]]] = {}
        for i in session.scalars(select(SupplierIdentity)):
            self.supplier_names[i.id] = naming.supplier_name(session, i.id)
            for phrase in (i.name, LEGAL.sub("", i.name), self.supplier_names[i.id], self.supplier_names[i.id].split(" (formerly")[0]):
                if len(phrase) >= 4:
                    sup.setdefault(phrase.lower(), set()).add(i.id)
        for r in session.scalars(select(SupplierRecord)):
            for phrase in (r.name, LEGAL.sub("", r.name)):
                if len(phrase) >= 4:
                    sup.setdefault(phrase.lower(), set()).add(r.identity_id)
            if r.email_domain:
                self.domains.setdefault(r.email_domain.lower(), r.identity_id)
            if r.contact_name and len(r.contact_name) >= 5:
                self.contacts.setdefault(r.contact_name.lower(), set()).add((r.identity_id, r.contact_name))
        self.cities = {(r.city or "").strip().lower() for r in session.scalars(select(SupplierRecord)) if r.city}
        # a place is not a company: a name that is only a city (a port, a town) is not a supplier
        self.supplier_phrases = {k: next(iter(v)) for k, v in sup.items() if len(v) == 1 and k not in self.cities}
        mpn: dict[str, set[str]] = {}
        for pn, p in self.parts.items():
            if p.mpn and len(p.mpn) >= 6:
                mpn.setdefault(p.mpn.lower(), set()).add(pn)
        self.mpn_phrases = {k: next(iter(v)) for k, v in mpn.items() if len(v) == 1}      # a manufacturer part number two parts share is not guessed
        self.mpn_re = _alt(self.mpn_phrases)
        people: dict[str, set[tuple[str, str]]] = {}
        for b in session.scalars(select(Buyer)):
            for phrase in (b.name, b.id):
                if len(phrase) >= 4:
                    people.setdefault(phrase.lower(), set()).add(("buyer", b.id))
        for phrase, who in self.contacts.items():
            if len({w[0] for w in who}) == 1:
                people.setdefault(phrase, set()).add(("contact", next(iter(who))[0] + "/" + next(iter(who))[1]))
        self.buyers = {b.id: b.name for b in session.scalars(select(Buyer))}
        self.people = {k: next(iter(v)) for k, v in people.items() if len(v) == 1}
        self.po_lines = {l for l in session.scalars(select(PoLine.id))}
        short: dict[tuple[int, int], set[str]] = {}
        for l in self.po_lines:
            m = re.match(r".*-(\d{5})/(\d+)$", l)
            if m:
                short.setdefault((int(m.group(1)), int(m.group(2))), set()).add(l)
        self.po_short = {k: next(iter(v)) for k, v in short.items() if len(v) == 1}
        self.part_re = _alt(self.part_phrases)
        self.supplier_re = _alt(self.supplier_phrases)
        self.person_re = _alt(self.people)


def _alt(phrases) -> re.Pattern | None:
    ordered = sorted(phrases, key=len, reverse=True)
    return re.compile(r"(?<![\w])(?:" + "|".join(re.escape(p) for p in ordered) + r")(?![\w])", re.I) if ordered else None


@memo
def lexicon(session: Session) -> Lexicon:
    return Lexicon(session)


def _iso(y: int, m: int, d: int) -> str | None:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def _year_for(m: int, d: int) -> int:
    """A date written without a year is the next one on or after about half a year before the data date."""
    y = AS_OF.year
    try:
        return y + 1 if date(y, m, d) < AS_OF - timedelta(days=180) else y
    except ValueError:
        return y


def _money_norm(text: str) -> tuple[str, str]:
    cur = next((c for c in ("USD", "EUR", "CNY", "RMB", "GBP", "JPY", "CHF") if c in text.upper()), "USD" if "$" in text else "EUR" if "€" in text else "GBP" if "£" in text else "")
    num = re.search(NUM, text).group(0).replace(",", "")
    mult = 1000 if re.search(r"\d\s?[kK]\b", text) else 1_000_000 if re.search(r"\d\s?[mM]\b", text) else 1
    amount = float(num) * mult
    shown = f"{amount:,.0f}" if amount == int(amount) else f"{amount:,.2f}"
    return f"{cur} {amount:.2f}".strip(), f"{cur} {shown}".strip()


def annotate(session: Session, text: str | None, *, held: bool = False) -> list[Span]:
    """The spans of `text` that match a record, left to right. No span overlaps another; of two overlapping matches the longer wins.

    `held`: the text is from a message the code holds (a look-alike sender, a bank-detail change, a reply-to on free mail). A name in it is a claim, not a record: a supplier's name
    or address becomes `supplier_claimed` with no reference to the real company, and a contact's name is not matched. A beneficiary or bank line is never a supplier or a person."""
    if not text:
        return []
    lx = lexicon(session)
    cands: list[tuple[int, int, str, str, str]] = []      # start, end (code points), type, ref, label

    for m in PO_FULL.finditer(text):
        if m.group(0) in lx.po_lines:
            cands.append((m.start(), m.end(), "po_line", m.group(0), m.group(0)))
    for m in PO_SHORT.finditer(text):
        hit = lx.po_short.get((int(m.group(1)), int(m.group(2))))
        if hit:
            cands.append((m.start(), m.end(), "po_line", hit, hit))
    for m in PART_NO.finditer(text):
        pn = m.group(0)
        if pn not in lx.parts:
            continue
        s, e = m.start(), m.end()
        before = text[:s].lower()
        for lab in lx.part_labels[pn]:          # "Motor, BLDC (PN-12345)": the label and the number are one mention
            if before.endswith(lab + " (") and text[e:e + 1] == ")":
                s, e = s - len(lab) - 2, e + 1
                break
        name = naming.part_name(lx.parts[pn].description)
        cands.append((s, e, "part", pn, f"{name} ({pn})" + (f" · {lx.hint[pn]}" if lx.hint.get(pn) else "")))
    if lx.mpn_re:
        for m in lx.mpn_re.finditer(text):
            pn = lx.mpn_phrases[m.group(0).lower()]
            cands.append((m.start(), m.end(), "part", pn, f"{naming.part_name(lx.parts[pn].description)} ({pn})" + (f" · {lx.hint[pn]}" if lx.hint.get(pn) else "") + " · by MPN"))
    if lx.part_re:
        for m in lx.part_re.finditer(text):
            pn = lx.part_phrases[m.group(0).lower()]
            cands.append((m.start(), m.end(), "part", pn, f"{naming.part_name(lx.parts[pn].description)} ({pn})" + (f" · {lx.hint[pn]}" if lx.hint.get(pn) else "")))
    if lx.supplier_re:
        for m in lx.supplier_re.finditer(text):
            ident = lx.supplier_phrases[m.group(0).lower()]
            cands.append((m.start(), m.end(), "supplier", ident, lx.supplier_names[ident]))
    for m in EMAIL.finditer(text):
        _domain(lx, m.group(1).lower(), m.start(), m.end(), m.group(0), cands)
    for m in DOMAIN.finditer(text):
        if "@" not in text[max(0, m.start() - 1):m.start()]:
            _domain(lx, m.group(1).lower(), m.start(), m.end(), m.group(1), cands)
    if lx.person_re:
        for m in lx.person_re.finditer(text):
            kind, ident = lx.people[m.group(0).lower()]
            if kind == "contact" and held:
                continue
            if kind == "buyer":
                cands.append((m.start(), m.end(), "person", ident, lx.buyers[ident]))
            else:
                sid, name = ident.split("/", 1)
                cands.append((m.start(), m.end(), "person", ident, f"{name} ({lx.supplier_names.get(sid, sid)})"))
    for m in MONEY.finditer(text):
        ref_, label = _money_norm(m.group(0))
        cands.append((m.start(), m.end(), "money", ref_, label))
    for m in ISO_DATE.finditer(text):
        iso = _iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if iso:
            cands.append((m.start(), m.end(), "date", iso, iso))
    for m in MD_DATE.finditer(text):
        mo, d = MONTHS[m.group(1)[:3].lower()], int(m.group(2))
        iso = _iso(int(m.group(3)) if m.group(3) else _year_for(mo, d), mo, d)
        if iso:
            cands.append((m.start(), m.end(), "date", iso, iso))
    for m in DM_DATE.finditer(text):
        d, mo = int(m.group(1)), MONTHS[m.group(2)[:3].lower()]
        iso = _iso(int(m.group(3)) if m.group(3) else _year_for(mo, d), mo, d)
        if iso:
            cands.append((m.start(), m.end(), "date", iso, iso))
    for m in QTY.finditer(text):
        n = m.group(1).replace(",", "")
        unit = m.group(2).lower()
        unit = {"piece": "pcs", "pieces": "pcs", "unit": "units", "meters": "m", "metres": "m", "feet": "ft"}.get(unit, unit)
        cands.append((m.start(), m.end(), "quantity", f"{n} {unit}", f"{float(n):,.0f} {unit}" if float(n) == int(float(n)) else f"{n} {unit}"))

    for m in DURATION.finditer(text):
        unit = {"wk": "week", "wks": "week", "week": "week", "weeks": "week", "day": "day", "days": "day", "month": "month", "months": "month", "hour": "hour", "hours": "hour"}[m.group(3).lower()]
        lo, hi = m.group(1), m.group(2)
        plural = "s" if (hi or lo) != "1" else ""
        cands.append((m.start(), m.end(), "duration", f"{lo}-{hi} {unit}s" if hi else f"{lo} {unit}{plural}", f"{lo} to {hi} {unit}s" if hi else f"{lo} {unit}{plural}"))
    # who a text can name as a company: never a place after an Incoterm, never a line of bank details; in a held message, only as a claim
    no_company = [(m.start(1), m.end(1)) for m in INCOTERM_PLACE.finditer(text)] + [(m.start(), m.end()) for m in BANK_LINE.finditer(text)]
    cands = [c for c in cands if not (c[2] in ("supplier", "supplier_lookalike", "person") and any(a <= c[0] and c[1] <= b for a, b in no_company))]
    if held:
        cands = [(s, e, "supplier_claimed", f"claimed:{text[s:e].lower()}", f"claimed: {label} (unverified)") if t == "supplier" else (s, e, t, r, label) for s, e, t, r, label in cands]
    # longest match wins; a tie goes to the more specific record (an id over a name over a value)
    rank = {"po_line": 0, "part": 1, "supplier_lookalike": 2, "supplier_claimed": 3, "supplier": 3, "person": 4, "money": 5, "date": 6, "quantity": 7, "duration": 8}
    taken: list[tuple[int, int]] = []
    chosen = []
    for c in sorted(cands, key=lambda c: (-(c[1] - c[0]), rank[c[2]], c[0])):
        if all(c[1] <= a or c[0] >= b for a, b in taken):
            taken.append((c[0], c[1]))
            chosen.append(c)
    idx = _utf16(text)
    return [Span(start=idx[s], end=idx[e], type=t, ref=r, label=l, text=text[s:e]) for s, e, t, r, l in sorted(chosen)]


def _domain(lx: Lexicon, domain: str, s: int, e: int, shown: str, cands: list) -> None:
    ident = lx.domains.get(domain)
    if ident:
        cands.append((s, e, "supplier", ident, lx.supplier_names[ident]))
        return
    hit = trust.imitated_domain(domain, set(lx.domains))
    if hit:
        cands.append((s, e, "supplier_lookalike", shown if "@" in shown else domain, f"{shown}: imitates {lx.supplier_names[lx.domains[hit[0]]]}'s domain, not {lx.supplier_names[lx.domains[hit[0]]]}"))
