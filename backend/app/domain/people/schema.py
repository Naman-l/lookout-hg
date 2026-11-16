from __future__ import annotations

from pydantic import BaseModel

from app.domain.common import Money


class Person(BaseModel):
    """A member of the SCM team, as the people who work here know them: who they are, which desk is theirs, and what is open on it."""

    id: str
    name: str
    initials: str
    role: str
    purchasing_groups: list[str]
    verticals: list[str]
    categories: list[str]  # what the "Who are you?" card says under the name (the role)
    open_lines: int  # PO lines on their purchasing groups not yet fully received
    open_prs: int  # PR lines on their purchasing groups not yet converted, deleted or closed
    open_value: Money
    past_due_lines: int  # open PO lines whose delivery date is before the data date
