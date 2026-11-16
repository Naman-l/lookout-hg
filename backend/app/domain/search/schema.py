from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Highlight(BaseModel):
    start: int  # UTF-16 index into matched_text
    end: int


class Hit(BaseModel):
    """One thing a search found: what it is, which record, what to show, where the words matched, and the route that shows it."""

    type: Literal["item", "message", "supplier", "project", "material", "pr", "po", "person"]
    ref: str
    label: str
    sublabel: str
    matched_text: str
    highlight: Highlight
    url: str
    score: int

    model_config = {"title": "SearchHit"}
