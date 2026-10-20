from __future__ import annotations

from pydantic import BaseModel

from app.domain.common import Money


class Person(BaseModel):
    """A buyer, as the people who work here know them: who they are, what they buy, and what is open on their desk."""

    id: str
    name: str
    initials: str  # how the legacy ERP signs their orders
    categories: list[str]  # the categories they buy, the ones with the most parts first
    parts: int  # parts they own
    open_lines: int  # open order lines on their desk (old lines that are probably not open are not counted)
    open_value: Money
    past_due_lines: int  # open lines promised before the data date
