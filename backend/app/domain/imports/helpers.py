"""Tested helpers every recipe step may call: parse once, test once.

Pure functions, no I/O. A step decides *what* to do about a defect; these decide *how* a value is read: SAP dates (dd.mm.yyyy), a sheet's
accounting-format numbers ("  51,485 ", "  -   "), amounts written in rupees, lakh or crore, Indian digit grouping ("1,00,00,000"), and the stamp
line a SAP list export starts with.
"""

from __future__ import annotations

import re
from datetime import date, datetime

LAKH, CRORE = 1e5, 1e7


def parse_dmy(raw: str | None) -> date | None:
    """'20.10.2026' (SAP's dd.mm.yyyy), '20/10/2026' or '2026-10-20' -> date. Blank -> None. Anything else raises: the build stops rather than guessing."""
    s = (raw or "").strip()
    if not s:
        return None
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unreadable date: {raw!r}")


def iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def parse_number(raw: str | None) -> float | None:
    """A number as a sheet or an export writes it: '  51,485 ', '1,00,00,000', '-381.880', '0.82'. Blank, '-' and '  -   ' (accounting zero) -> None.
    An Excel error ('#DIV/0!', '#REF!') raises ValueError so the caller can count it."""
    s = (raw or "").strip()
    if not s or s in ("-", "–"):
        return None
    if s.startswith("#"):
        raise ValueError(f"spreadsheet error value: {raw!r}")
    s = s.replace(",", "").replace(" ", "")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    v = float(s)
    return -v if neg else v


def parse_inr(raw: str | None, unit: str = "rupee") -> tuple[float | None, str]:
    """(amount in rupees, the unit it was written in) for a cell whose column is in `unit` ('rupee' or 'cr'): '2.64 Cr' -> 26,400,000 ('cr');
    '45 L' or '45 Lakh' -> 4,500,000 ('lakh'); '23,50,000' typed as text in a crore sheet -> 2,350,000 ('rupee'); '12.5' in a crore column -> 125,000,000.
    The unit the text names wins over the column's; a figure with Indian lakh grouping is rupees."""
    s = (raw or "").strip()
    if not s:
        return None, ""
    m = re.fullmatch(r"(?i)(?:rs\.?|inr|₹)?\s*([\d,]*\.?\d+)\s*(cr|crore|crores|l|lakh|lakhs|lac|lacs)?", s)
    if not m:
        raise ValueError(f"unreadable amount: {raw!r}")
    num = float(m.group(1).replace(",", ""))
    word = (m.group(2) or "").lower()
    if word.startswith("cr"):
        return num * CRORE, "cr"
    if word.startswith("l"):
        return num * LAKH, "lakh"
    if re.fullmatch(r"\d{1,2}(,\d\d)+,\d{3}", m.group(1)):      # Indian grouping (12,34,567): rupees, whatever the column says
        return num, "rupee"
    return (num * CRORE, "cr") if unit == "cr" else (num, "rupee")


def in_group(n: float) -> str:
    """12345678 -> '1,23,45,678' (Indian digit grouping, whole rupees)."""
    s = str(int(round(abs(n))))
    head, tail, parts = s[:-3], s[-3:], []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ("-" if n < 0 else "") + ",".join(parts + [tail])


def parse_export_stamp(line: str) -> dict:
    """The first line of a SAP list export: 'ME2N - Purchasing ... | Exported 20.10.2026 08:15:09 | User JDOE | Variant ...' ->
    {'title', 'exported_at' (ISO), 'user'}. A line with no stamp gives the title only."""
    parts = [p.strip() for p in (line or "").split("|")]
    out = {"title": parts[0] if parts else "", "exported_at": None, "user": None}
    for p in parts[1:]:
        m = re.match(r"(?i)exported\s+(\d{2}\.\d{2}\.\d{4})(?:\s+(\d{2}:\d{2}(?::\d{2})?))?", p)
        if m:
            d = datetime.strptime(m.group(1), "%d.%m.%Y")
            out["exported_at"] = (d.date().isoformat() + ("T" + m.group(2) if m.group(2) else ""))
        m = re.match(r"(?i)user\s+(\S+)", p)
        if m:
            out["user"] = m.group(1)
    return out


def stamp_in_name(name: str) -> date | None:
    """'SCM Fund Requirement November-26 (16.10.26).csv' -> 2026-10-16: the date a hand-built sheet carries in its name."""
    m = re.search(r"\((\d{2})\.(\d{2})\.(\d{2,4})\)", name)
    if not m:
        return None
    y = int(m.group(3))
    return date(y + 2000 if y < 100 else y, int(m.group(2)), int(m.group(1)))


def norm_name(s: str | None) -> str:
    """A company or project name compared loosely: lower case, '&' as 'and', no punctuation, no legal suffix."""
    t = (s or "").lower().replace("&", " and ")
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    t = re.sub(r"\b(pvt|private|ltd|limited|llp|co|company|the|m s)\b", " ", t)
    return " ".join(t.split())


def add_flag(df, mask, flag: str) -> None:
    """Append `flag` to the comma-separated `flags` column of the rows in `mask` (in place)."""
    df.loc[mask, "flags"] = df.loc[mask, "flags"].map(lambda f: f"{f},{flag}" if f else flag)


def slug(name: str | None) -> str:
    """'PKG-07' -> 'pkg-07'; 'North Ring Road Phase-2' -> 'north-ring-road-phase-2': a stable id made from a printed name."""
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


MONTHS3 = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def month_label(raw: str | None) -> str | None:
    """"Oct'26", "Oct''26", "October-26", "Nov-26" -> '2026-10' / '2026-11'; anything else -> None."""
    m = re.match(r"(?i)\s*([a-z]{3})[a-z]*\W*(\d{2,4})\b", raw or "")
    if not m or m.group(1).lower() not in MONTHS3:
        return None
    y = int(m.group(2))
    return f"{y + 2000 if y < 100 else y:04d}-{MONTHS3.index(m.group(1).lower()) + 1:02d}"
