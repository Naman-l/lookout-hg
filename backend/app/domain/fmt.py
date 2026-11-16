"""Dates, months and money the way a buyer says them. Data fields keep ISO and rupees; every title, finding, next action, letter and question
uses these: "28 Oct", "20 Oct 2026", "₹1.4 Cr", "₹15 L", "₹8,500", "1,28,000 MT" (Indian digit grouping)."""

from __future__ import annotations

import os
import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def local_date(stamp: str | None) -> str:
    """The calendar date of a timestamp where the team is (LOOKOUT_TZ, India by default): a send at 11 pm IST on 11 Oct is 11 Oct, not the UTC date."""
    if not stamp:
        return ""
    try:
        t = datetime.fromisoformat(stamp)
    except ValueError:
        return stamp[:10]
    t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    return t.astimezone(ZoneInfo(os.environ.get("LOOKOUT_TZ") or "Asia/Kolkata")).date().isoformat()


def md(iso: str | None, with_year: bool = False) -> str:
    """'2026-10-28' -> '28 Oct' (or '28 Oct 2026')."""
    if not iso:
        return ""
    d = date.fromisoformat(iso[:10])
    return f"{d.day} {MONTHS[d.month - 1][:3]}" + (f" {d.year}" if with_year else "")


def dmy(iso: str | None) -> str:
    """'2026-10-20' -> '20 Oct 2026'."""
    return md(iso, with_year=True)


def long_date(iso: str | None) -> str:
    """'2026-10-24' -> '24 October 2026': the form a letter uses."""
    if not iso:
        return ""
    d = date.fromisoformat(iso[:10])
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def count(n: int, noun: str, plural: str | None = None) -> str:
    """'1 order', '3 orders': the noun agrees at the source, so no text ever says 'order(s)'."""
    return f"{en_in(n)} {noun if n == 1 else (plural or noun + 's')}"


def days(n: int) -> str:
    """'1 day', '2 days'."""
    return f"{n} day" + ("" if n == 1 else "s")


def sentence(text: str) -> str:
    """A capital at the start of every sentence and a full stop at the end."""
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
    """Rewrite any ISO date left in a sentence the way a buyer says it: '... by 2026-12-15' -> '... by 15 Dec'. A month alone (2026-10) becomes 'October'."""
    text = re.sub(r"\b(20\d\d)-(\d\d)-(\d\d)\b", lambda m: md(m.group(0)), text)
    return re.sub(r"\b(20\d\d)-(\d\d)\b", lambda m: month(m.group(0)), text)


def en_in(n: float | int, places: int = 0) -> str:
    """Indian digit grouping: 4249224 -> '42,49,224'; 128000 -> '1,28,000'. `places` keeps that many decimals (dropped when they are zero)."""
    neg = n < 0
    n = abs(float(n))
    whole = int(round(n)) if places == 0 else int(n)
    frac = "" if places == 0 else f"{n - whole:.{places}f}"[1:]
    frac = frac.rstrip("0").rstrip(".") if frac else ""
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = ",".join(re.findall(r"\d{1,2}", head[::-1]))[::-1]
        s = f"{head},{tail}"
    return ("-" if neg else "") + s + frac


def inr(amount: float | int | None, exact: bool = False) -> str:
    """Rupees the way the team says them: ₹1.4 Cr (a crore and up), ₹15 L (a lakh and up), ₹8,500 below a lakh. `exact` writes every rupee
    with Indian grouping (₹42,49,224), as a letter or a claim does."""
    if amount is None:
        return "—"
    a = float(amount)
    sign = "-" if a < 0 else ""
    a = abs(a)
    if exact or a < 1e5:
        return f"{sign}₹{en_in(a, 0 if a >= 100 or a == int(a) else 2)}"
    if a >= 1e7:
        cr = a / 1e7
        return f"{sign}₹{cr:,.0f} Cr" if cr >= 100 else f"{sign}₹{_trim(cr, 2 if cr < 10 else 1)} Cr"
    lakh = a / 1e5
    return f"{sign}₹{_trim(lakh, 1 if lakh < 10 else 0)} L"


def _trim(x: float, places: int) -> str:
    s = f"{x:.{places}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def qty_text(value: float | int | None, uom: str | None = None) -> str:
    """'1,28,000 MT', '18 KM', '2.5 KM'."""
    if value is None:
        return "—"
    v = float(value)
    s = en_in(v) if v == int(v) else en_in(v, 2)
    return f"{s} {uom}".strip() if uom else s
