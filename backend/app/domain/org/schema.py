from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class OrgNode(BaseModel):
    """One box on the organisation chart: a person or a post to be filled, as the organogram draws it, with any edits laid over it."""

    id: str
    name: str | None  # None for an open post
    designation: str
    designation_full: str | None  # the short form in full, from the recipe's glossary ("AM" -> "Assistant Manager")
    reports_to: str | None  # an OrgNode id; None for the head
    category: str | None  # the desk label the sheet writes beside them
    portfolio: str | None  # a lead's line of what their team buys; an open post's desk
    responsibilities: str | None
    position: int  # order under their lead
    vacancy: bool
    member_id: str | None  # the SCM team member this box is (buyers.id): their Team page, purchasing groups and DoA limit
    role: str | None  # the member's desk, as the team answers word it
    purchasing_groups: list[str]
    email: str | None
    source: Literal["sheet", "added"]
    edited: list[str]  # the fields changed on this page since the sheet was read
    src: str | None  # where on the sheet: "row 5, column C"


class OrgEdit(BaseModel):
    """A change a person made on the Organisation page, kept in order; the chart is the sheet with these laid over it."""

    id: str
    at: str
    by: str
    op: Literal["add", "update", "remove"]
    person_id: str
    person: str  # the name (or post) at the time
    fields: dict[str, str | int | bool | None]
    undone: bool
    applied: bool  # False when the sheet no longer has the box the edit was made to
    summary: str


class OrgChart(BaseModel):
    title: str
    source_file: str
    head: str | None
    people: list[OrgNode]
    named: int  # people under the head
    open_posts: int
    total_on_sheet: int | None  # the sheet's own "Total Employee"
    edits: list[OrgEdit]  # newest first, undone ones included
    note: str


class OrgFields(BaseModel):
    """The fields a person may set on a box. Absent fields are left as they are; for a new box, name or vacancy and a designation are needed."""

    by: str
    name: str | None = None
    designation: str | None = None
    reports_to: str | None = None
    category: str | None = None
    portfolio: str | None = None
    responsibilities: str | None = None
    vacancy: bool | None = None


class OrgBy(BaseModel):
    by: str
