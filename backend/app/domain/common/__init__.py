"""Value objects shared by every layer: the records, the API, the screens and the agents.

Every number Lookout shows or reasons with is a Money or a Quantity that carries its Provenance: where it
came from, how it was obtained, and which records it was computed from. A value nobody knows is an Unknown
with an owner, never a zero or a blank.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

def recipe_as_of() -> date:
    """The date the recipe declares in answers.yaml (the data README's "today"): the day the data was written for, whatever `LOOKOUT_AS_OF` builds."""
    import yaml

    from app.domain.common.recipe import recipe_dir

    return date.fromisoformat(str(yaml.safe_load((recipe_dir() / "answers.yaml").read_text())["as_of"]))


def _resolve_as_of() -> date:
    """The data date: `LOOKOUT_AS_OF` (an ISO date) when set, else the date the recipe declares in answers.yaml (the data README's "today").
    It is the clock for "past due" and "days left" and the horizon of the data: nothing dated after it is read. Never the wall clock."""
    import os

    env = os.environ.get("LOOKOUT_AS_OF")
    return date.fromisoformat(env) if env else recipe_as_of()


AS_OF: date = _resolve_as_of()
"""The data snapshot date and horizon (see `_resolve_as_of`). Every "past due", "days left" and detector window is computed against
this, never against the wall clock, so the numbers are the same on any day the app is run. Build and serve with the same value."""

EntityType = Literal[
    "supplier", "supplier_record", "vendor_library", "project", "plant", "workfront", "material", "pr", "pr_line", "po", "po_line", "receipt",
    "cs", "quote", "milestone", "lc", "abg", "fund_line", "fund_check", "requirement", "budget_rate", "lookahead", "index", "invoice",
    "person", "contact", "message", "item", "action", "data_issue", "doa_rule",
]

Method = Literal["stated", "computed", "inferred", "flagged", "unknown", "extracted"]


class EntityRef(BaseModel):
    """A typed pointer to a record. The UI renders it as that entity's chip; agents cite it."""

    type: EntityType
    id: str
    label: str | None = None


class Provenance(BaseModel):
    """Where a value came from.

    stated: copied from a source field. computed: derived by code from `inputs` with `rule`. inferred: filled
    by a rule from other evidence (labelled on screen). flagged: kept as found but marked suspect. unknown:
    not knowable from the data. extracted: read from free text (an email or a PDF) at `row`.
    """

    method: Method
    source: str  # a table name ("po_lines"), "message:<file>", "notice", or "recipe"
    row: str | None = None  # source row id or line reference
    raw: str | None = None  # the value exactly as it appeared in the source
    inputs: list[EntityRef] = Field(default_factory=list)
    rule: str | None = None  # the function and version that computed it
    by: str = "recipe"  # "recipe", a service name, or a person


class Money(BaseModel):
    amount: Decimal
    currency: str  # ISO 4217
    base: Decimal | None = None  # the amount in the base currency the recipe names (`base_currency`); the screens and every sum read this
    provenance: Provenance


class Quantity(BaseModel):
    value: Decimal
    uom: str  # the unit as the records hold it, after the recipe's conversions (MT, KM, NO, SET, RM, ...)
    provenance: Provenance


class Conditional(BaseModel):
    """A value that only holds under a condition, kept together: "6 weeks after sample approval"."""

    value: Money | Quantity | str
    condition: str
    provenance: Provenance


Owner = str  # a team member id from the data (the buyers table), a contact id (project_head:<project>, finance_treasury, ...), "vendor", or "unassigned"; never a name written in code


class Unknown(BaseModel):
    """A fact the data does not hold. Shown as "unknown · ask <owner>", never as a number."""

    what: str
    why_it_blocks: str
    owner: Owner
    question: str
    refs: list[EntityRef] = Field(default_factory=list)
