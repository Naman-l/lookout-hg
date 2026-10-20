"""The product's clock is frozen at 2026-09-25 (the data snapshot). Prose from the agent must keep to it.

Two rules, applied to every agent case:
  1. Nothing may claim a "today" other than 2026-09-25: no "today is 10 October", no "as of 2026-10-10", and no
     calling a tool's figure stale or out of date, which is what reading the wall clock sounds like.
  2. Nothing may state days left that the tool did not give: a number of days "left" or "remaining" must be one
     the item already carries; code does the arithmetic and the prose repeats it.
Dates that are not claims about today (a supplier's revised date, a deadline) are fine.
"""
from __future__ import annotations

import re
from datetime import date

AS_OF = date(2026, 9, 25)
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}
_MON = "|".join(sorted(MONTHS, key=len, reverse=True)) + "|" + "|".join(m[:3] for m in MONTHS)
DATE = (rf"(?:\d{{4}}-\d{{2}}-\d{{2}})|(?:\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{_MON})\.?(?:,?\s+\d{{4}})?)|(?:(?:{_MON})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?)")
# cues that can only mean "today". A bare "as of <date>" or "it is <date>" is left alone: "as of 1 November the duty applies" is an effective date.
_BEFORE = re.compile(rf"(?:today(?:'s date)?\s+is|the (?:current )?date today is|today[,:]?\s*\(|the current date is|current date[:\s]|it is now|it's now|now is|as of today[,:]?\s*\(?)\s*(?:the\s+)?({DATE})", re.I)
_AFTER = re.compile(rf"({DATE})\s*(?:\(today\)|,?\s*(?:which is\s+)?today\b|is today\b)", re.I)
_OLD = r"(?:stale|out\s?of\s?date|outdated)"
# a figure, number, date or count called stale. Orders or data rows called stale ("three stale orders", "the lines look stale") are about the records, not the clock.
_STALE = re.compile(rf"\b(?:figures?|numbers?|counts?|dates?|days?|deadlines?|estimates?|calculations?)\b(?:\s+\S+){{0,3}}?\s+(?:looks?|seems?|is|are|appears?|may be|might be)\s+{_OLD}|wall[- ]clock|system (?:clock|date)|real(?:-world)? (?:date|time)", re.I)
_DAYS = re.compile(r"(\d+)[-\s]days?\s+(?:left|remaining|to go)|(?:with|only)\s+(\d+)\s+days?\s+(?:left|remaining)", re.I)


def parse(text: str) -> date | None:
    t = text.strip().lower().replace(",", " ")
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    m = re.fullmatch(rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MON})\.?(?:\s+(\d{{4}}))?", t)
    if m:
        return date(int(m[3] or 2026), MONTHS[next(k for k in MONTHS if k.startswith(m[2][:3]))], int(m[1]))
    m = re.fullmatch(rf"({_MON})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:\s+(\d{{4}}))?", t)
    if m:
        return date(int(m[3] or 2026), MONTHS[next(k for k in MONTHS if k.startswith(m[1][:3]))], int(m[2]))
    return None


def violations(texts: list[str], days_allowed: set[int] | None = None) -> list[str]:
    """Every breach of the two rules in the given prose. Empty means the clock was respected."""
    out: list[str] = []
    allowed = days_allowed or set()
    for text in texts:
        for rx in (_BEFORE, _AFTER):
            for m in rx.finditer(text):
                d = parse(m.group(1))
                if d and d != AS_OF:
                    out.append(f"claims today is {d.isoformat()} (the data is as of {AS_OF.isoformat()}): '{m.group(0).strip()[:60]}'")
        for m in _STALE.finditer(text):
            out.append(f"calls a figure stale or reads the clock: '{m.group(0).strip()[:50]}'")
        for m in _DAYS.finditer(text):
            n = int(m.group(1) or m.group(2))
            if n not in allowed:
                out.append(f"states {n} days left, but the tool gave {sorted(allowed) or 'none'}")
    return list(dict.fromkeys(out))
