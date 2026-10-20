from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Span(BaseModel):
    """One thing a text mentions, matched against the records. `start` and `end` are JavaScript string indices (UTF-16 code units) into the text it was found in;
    `text` is the matched substring, so a renderer can check the span and drop it if the text it holds has changed."""

    start: int
    end: int
    type: Literal["part", "supplier", "supplier_claimed", "supplier_lookalike", "person", "po_line", "money", "date", "quantity", "duration"]
    ref: str  # the record id (a part number, a supplier id, a buyer id, a PO line id), or the normalised value (money, date, quantity), or the address of a look-alike sender
    label: str  # what to show on the chip, name first
    text: str


class Annotate(BaseModel):
    text: str
    held: bool = False  # the text is from a message the code holds (a look-alike sender, a bank-detail change): names in it are claims, never records
