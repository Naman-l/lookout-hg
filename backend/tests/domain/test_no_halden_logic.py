"""Nothing Halden-specific is used as logic or shown as a fixed fact in the domain code.

Every string constant in `app/domain` (docstrings and comments excepted) is scanned for the customer's names, ids, dates and
amounts. A fact of this month belongs in the data and the recipe; code that needs it reads it from the database. The developer
scripts and the steward's drift fixture are the only exceptions: they print or build against this customer on purpose.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"
DOMAIN = APP / "domain"
ORGANISM = APP / "organism"
ORGANISM_EXEMPT_DIRS = {"dev", "recordings", "knowledge"}  # developer tools and test stand-ins, the saved runs, and the glossary text (prompt prose, scanned by its own test)
EXEMPT: set[str] = set()      # no file in the domain package is exempt: the developer probe lives outside it, in backend/dev/
EXEMPT_DIRS = {"fixtures"}
ALLOWED = {"2023-06-01"}      # the Anthropic API version header the extractor sends: a protocol constant, not a fact of the customer's month

MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
PEOPLE = "Dana|Marcus|Priya|Tom|Sofia"
COMPANIES = ("Yunzhan|Hallerbeck|Saltmarsh|Quenvara|BCX|Lanxin|Baycrest|Alderpoint|Vistaray|Jadepeak|Ruilian|Meiya|Great Plains|Vinh Phuc|"
             "Monterrey|Corvell")
PRODUCTS = "Tern|Porter|Heron"
THE_COMPANY = "Halden"      # the company is configuration (answers.yaml `company`, build_meta); no string the domain shows may carry its name
PATTERN = re.compile(
    rf"\b({PEOPLE}|{COMPANIES}|{PRODUCTS}|{THE_COMPANY})\b|Hong Kong|Plant [12]\b|\bSUP-\d|\bV1\d{{4}}\b|\bHR-\d{{5}}|\bHPO-|\bPO-1\d{{4}}"
    rf"|\b20\d\d-\d\d(-\d\d)?\b|\b({MONTHS}) \d{{1,2}}\b|187,?420|\b38\.50?\b")


def _docstring_nodes(tree: ast.AST) -> set[int]:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                out.add(id(first.value))
    return out


# In the agent layer an id shape is a regular expression, so it is written escaped (SUP-\\d{4}): the same shapes, spelled as a pattern, count too.
ESCAPED_SHAPES = re.compile(r"\b(SUP|HPO|HR|PO)-\\d|\bV\\d\{|\bV1\\d")


def _hits() -> list[str]:
    found = []
    for path in sorted(DOMAIN.rglob("*.py")):
        if path.name in EXEMPT or EXEMPT_DIRS & set(path.relative_to(DOMAIN).parts):
            continue
        tree = ast.parse(path.read_text())
        docs = _docstring_nodes(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
                m = PATTERN.search(node.value)
                if m and node.value not in ALLOWED:
                    found.append(f"{path.relative_to(DOMAIN)}:{node.lineno}: {m.group(0)!r} in {node.value[:70]!r}")
    return found


def test_no_customer_fact_is_written_into_domain_code():
    assert _hits() == [], "a fact of this customer's month is in code; read it from the data:\n" + "\n".join(_hits())


def test_no_customer_fact_or_id_shape_is_written_into_the_agent_layer():
    """The organism package reads id shapes, the company and the buyers from the build; its code names none of them (docstrings, comments and tests excepted)."""
    found = []
    for path in sorted(ORGANISM.rglob("*.py")):
        if ORGANISM_EXEMPT_DIRS & set(path.relative_to(ORGANISM).parts):
            continue
        tree = ast.parse(path.read_text())
        docs = _docstring_nodes(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
                m = PATTERN.search(node.value) or ESCAPED_SHAPES.search(node.value)
                if m and node.value not in ALLOWED:
                    found.append(f"{path.relative_to(ORGANISM)}:{node.lineno}: {m.group(0)!r} in {node.value[:70]!r}")
    assert found == [], "a fact or an id shape of this customer is in the agent layer; read it from the build:\n" + "\n".join(found)
