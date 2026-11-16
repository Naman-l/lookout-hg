from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Span(BaseModel):
    """One thing a text mentions, matched against the records. `start` and `end` are JavaScript string indices (UTF-16 code units) into the text;
    `text` is the matched substring, so a renderer can check the span and drop it if the text has changed."""

    start: int
    end: int
    type: Literal["project", "plant", "material", "supplier", "supplier_lookalike", "person", "pr", "pr_line", "po", "po_line", "money", "date", "quantity"]
    ref: str  # the record id, or the normalised value (money in rupees, an ISO date, a quantity), or the look-alike address
    label: str  # what the chip shows, name first
    text: str


class Annotate(BaseModel):
    text: str
    held: bool = False  # the text is from a held message: names in it are claims, never records
