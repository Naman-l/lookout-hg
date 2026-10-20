"""Dates and months the way a buyer says them. Data fields keep ISO; every title, finding, next action and question uses these."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def local_date(stamp: str | None) -> str:
    """The calendar date of a timestamp where the buyers are (LOOKOUT_TZ, Pacific by default): a send at 6 pm on Oct 11 there is Oct 11, not the UTC Oct 12."""
    if not stamp:
        return ""
    try:
        t = datetime.fromisoformat(stamp)
    except ValueError:
        return stamp[:10]
    t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    return t.astimezone(ZoneInfo(os.environ.get("LOOKOUT_TZ") or "America/Los_Angeles")).date().isoformat()


def md(iso: str | None, with_year: bool = False) -> str:
    """'2026-10-13' -> 'Oct 13' (or 'Oct 13, 2026')."""
    if not iso:
        return ""
    d = date.fromisoformat(iso[:10])
    return f"{MONTHS[d.month - 1][:3]} {d.day}" + (f", {d.year}" if with_year else "")


def count(n: int, noun: str) -> str:
    """'1 order', '3 orders': the noun agrees at the source, so no text ever says 'order(s)'."""
    return f"{n} {noun}" + ("" if n == 1 else "s")


def days(n: int) -> str:
    """'1 day', '2 days'."""
    return f"{n} day" + ("" if n == 1 else "s")


def sentence(text: str) -> str:
    """A capital at the start of every sentence and a full stop at the end."""
    import re

    t = text.strip()
    if not t:
        return t
    t = re.sub(r"(?<=[.!?] )([a-z])", lambda m: m.group(1).upper(), t)
    t = t[0].upper() + t[1:] if t[0].isalpha() else t
    return t if t[-1] in ".!?" else t + "."


def month(ym: str | None) -> str:
    """'2026-10' or '2026-10-01' -> 'October'."""
    return MONTHS[int(ym[5:7]) - 1] if ym else ""


def month_year(iso: str | None) -> str:
    """'2025-02-14' -> 'Feb 2025'."""
    return f"{MONTHS[int(iso[5:7]) - 1][:3]} {iso[:4]}" if iso else ""


def humanize(text: str) -> str:
    """Rewrite any ISO date left in a sentence the way a buyer says it: '... by 2026-12-15' -> '... by Dec 15'. A month alone (2026-10) becomes 'October'."""
    import re

    text = re.sub(r"\b(20\d\d)-(\d\d)-(\d\d)\b", lambda m: md(m.group(0)), text)
    return re.sub(r"\b(20\d\d)-(\d\d)\b", lambda m: month(m.group(0)), text)
