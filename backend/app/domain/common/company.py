"""The company's name, for the few sentences that say it.

It is configuration, not code: `company:` in the recipe's answers.yaml, written to `build_meta` by the build. Without a database or a configured
name (a unit test, another customer's first build) the domain says "the company". The short name is the first word ("the company" -> "the company").
"""

from __future__ import annotations

import os

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.domain.cache import memo

GENERIC = "the company"


@memo
def _configured(session: Session) -> str:
    try:
        row = session.execute(text("select value from build_meta where key = 'company'")).first()
    except OperationalError:
        row = None
    return (row[0] if row and row[0] else os.environ.get("LOOKOUT_COMPANY", "")).strip()


def company_name(session: Session | None = None, *, full: bool = False) -> str:
    """The configured name ('the company' short, 'the company' full), else LOOKOUT_COMPANY, else 'the company'."""
    name = _configured(session) if session is not None else os.environ.get("LOOKOUT_COMPANY", "").strip()
    if not name:
        return GENERIC
    return name if full else name.split()[0]
