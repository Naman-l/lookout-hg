"""The declarative base every entity's `model.py` registers its tables on."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Tables are the canonical schema. Dates are ISO-8601 text (YYYY-MM-DD), prices are REAL, and a column
    named `<field>_raw` holds the value exactly as the source file had it."""
