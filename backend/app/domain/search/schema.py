from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Highlight(BaseModel):
    start: int  # UTF-16 index into matched_text, as a browser counts
    end: int


class Hit(BaseModel):
    """One thing a search found: what it is, which record, what to show, where the words matched, and where the screen for it is."""

    type: Literal["item", "message", "supplier", "part", "po_line", "person"]
    ref: str  # the record id: an item key, a message id, a supplier id, a part number, a PO line id, a buyer id or 'supplier id/contact name'
    label: str  # name first
    sublabel: str
    matched_text: str  # the text around the match
    highlight: Highlight  # the match inside matched_text
    url: str  # the route that shows it
    score: int

    model_config = {"title": "SearchHit"}
