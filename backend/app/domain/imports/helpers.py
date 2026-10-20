"""Tested helpers every recipe step may call: parse once, test once.

Pure functions, no I/O. A step decides *what* to do about a defect; these decide *how* a value is read.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

COUNTRY_ISO = {
    "US": "US", "USA": "US", "U.S.A.": "US", "UNITED STATES": "US",
    "CN": "CN", "CHINA": "CN", "PRC": "CN", "P.R. CHINA": "CN", "CHINA (PRC)": "CN",
    "TW": "TW", "TAIWAN": "TW", "R.O.C.": "TW", "TAIWAN, ROC": "TW",
    "HK": "HK", "HONG KONG": "HK",
    "DE": "DE", "GERMANY": "DE", "DEUTSCHLAND": "DE",
    "JP": "JP", "JAPAN": "JP",
    "MX": "MX", "MEXICO": "MX",
    "MY": "MY", "MALAYSIA": "MY",
    "TH": "TH", "THAILAND": "TH",
    "PH": "PH", "PHILIPPINES": "PH",
    "KR": "KR", "SOUTH KOREA": "KR",
    "CH": "CH", "SWITZERLAND": "CH",
    "VN": "VN", "VIETNAM": "VN",
}


def iso_country(raw: str) -> str | None:
    """Map a free-text country to ISO alpha-2. Blank -> None. An unknown spelling raises: the build stops
    rather than guessing, and the spelling is added to the table with a reason."""
    s = (raw or "").strip()
    if not s:
        return None
    try:
        return COUNTRY_ISO[s.upper()]
    except KeyError:
        raise ValueError(f"unmapped country spelling: {raw!r}") from None


PART_FORMAT: dict = {}      # the customer's part-number format, from the recipe's answers (`part_number: {prefix, digits}`): set by the build, empty means "clean only the spaces and case"


def configure_part_format(answers: dict) -> None:
    PART_FORMAT.clear()
    PART_FORMAT.update(answers.get("part_number") or {})


def norm_part_number(raw: str) -> str:
    """'PN12345', 'pn-12345', ' PN-123O5 ' -> 'PN-12345' (for a recipe whose parts are the prefix 'PN-' and five digits). Upper case, no spaces, the hyphen after the prefix,
    a letter O in the digit block -> 0.

    Only the digit block is touched; anything that is not prefix + the digits is returned stripped and upper cased so the caller can report it as unresolved. The prefix and the
    number of digits come from the recipe (`part_number` in answers.yaml), not from this code."""
    s = (raw or "").strip().upper().replace(" ", "")
    prefix, digits = str(PART_FORMAT.get("prefix") or "").upper(), int(PART_FORMAT.get("digits") or 0)
    if not prefix or not digits:
        return s
    m = re.fullmatch(re.escape(prefix.rstrip("-")) + rf"-?([0-9O]{{{digits}}})", s)
    if not m:
        return s
    return prefix + m.group(1).replace("O", "0")


def hts_digits(raw: str) -> tuple[str | None, bool]:
    """Return (digits, repaired). '8504.40.9580' -> ('8504409580', False); '85O4.40.9580' -> ('8504409580', True)
    where the letter O stood for 0. Blank -> (None, False)."""
    s = (raw or "").strip().upper()
    if not s:
        return None, False
    repaired = "O" in s
    digits = re.sub(r"\D", "", s.replace("O", "0"))
    return digits, repaired


def parse_payment_terms(raw: str) -> dict:
    """'NET60', 'Net 45 days', 'NET 30' -> net_days with a canonical label; deposit and cash terms keep their
    own fields. {'label', 'net_days', 'prepay_pct'}; nothing recognised -> label None."""
    s = (raw or "").strip()
    if not s:
        return {"label": None, "net_days": None, "prepay_pct": None}
    m = re.fullmatch(r"net\s*(\d+)(\s*days)?", s, re.I)
    if m:
        d = int(m.group(1))
        return {"label": f"Net {d}", "net_days": d, "prepay_pct": 0}
    if re.fullmatch(r"cash in advance", s, re.I):
        return {"label": "Cash in advance", "net_days": 0, "prepay_pct": 100}
    m = re.match(r"(\d+)%\s*(deposit|t/t)", s, re.I)
    if m:
        return {"label": s, "net_days": None, "prepay_pct": int(m.group(1))}
    return {"label": None, "net_days": None, "prepay_pct": None}


def split_incoterm(raw: str) -> tuple[str | None, str | None]:
    """'FOB Shenzhen' -> ('FOB', 'Shenzhen'); 'FOB SZ' -> ('FOB', 'Shenzhen'); 'FOB Origin' -> ('FOB', 'Origin');
    'EXW' -> ('EXW', None); blank -> (None, None)."""
    s = (raw or "").strip()
    if not s:
        return None, None
    term, _, place = s.partition(" ")
    place = place.strip() or None
    if place == "SZ":
        place = "Shenzhen"
    return term.upper(), place


UOM_ALIASES = {"EA": "EA", "EACH": "EA", "PC": "EA", "PCS": "EA", "PIECE": "EA", "KPCS": "KPCS",
               "M": "M", "MM": "MM", "FT": "FT", "PK": "PK", "BOX": "BOX"}
UOM_TO_PART_UNIT = {"EA": ("EA", Decimal(1)), "KPCS": ("EA", Decimal(1000)), "FT": ("M", Decimal("0.3048")),
                    "M": ("M", Decimal(1)), "MM": ("M", Decimal("0.001")), "PK": ("PK", Decimal(1))}


def norm_uom(raw: str) -> str:
    s = (raw or "").strip().upper()
    try:
        return UOM_ALIASES[s]
    except KeyError:
        raise ValueError(f"unmapped unit of measure: {raw!r}") from None


def to_part_unit(qty: float, uom: str) -> tuple[float, str] | None:
    """Quantity in the unit the part master counts in. KPCS x1000 -> EA, FT x0.3048 -> M. BOX has no size
    in the data -> None (the caller keeps the quantity as 'unknown in each')."""
    if uom not in UOM_TO_PART_UNIT:
        return None
    unit, factor = UOM_TO_PART_UNIT[uom]
    return float(Decimal(str(qty)) * factor), unit


def parse_date_any(raw: str) -> date | None:
    """Legacy ERP MM/DD/YYYY and new ERP ISO. Blank -> None. A bad string raises."""
    s = (raw or "").strip()
    if not s:
        return None
    if "/" in s:
        return datetime.strptime(s, "%m/%d/%Y").date()
    return datetime.strptime(s, "%Y-%m-%d").date()


def parse_number(raw: str, decimal: str = ".") -> Decimal:
    """'389,50' with decimal=',' -> Decimal('389.50'); '1.234,50' -> 1234.50; '12,500.00' (decimal='.') -> 12500.00."""
    s = (raw or "").strip().replace(" ", "")
    if decimal == ",":
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    return Decimal(s)


def add_flag(df, mask, flag: str) -> None:
    """Append `flag` to the comma-separated `flags` column of the rows in `mask` (in place)."""
    df.loc[mask, "flags"] = df.loc[mask, "flags"].map(lambda f: f"{f},{flag}" if f else flag)
