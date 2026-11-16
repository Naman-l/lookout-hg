"""No real person's name, real vendor name, the company's real mail domain or a personal file link from the review repo appears anywhere in this tree.

The names are read from the review repo at test time (tests/review_terms.py); the test is skipped where that repo is not on disk. Scanned: every
text file of the repository (code, data, recipe, docs, generator), the built UI and the caches excepted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests import review_terms

ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".git", "node_modules", ".venv", "dist", "__pycache__", ".pytest_cache"}
BINARY = {".db", ".png", ".jpg", ".jpeg", ".ico", ".woff", ".woff2", ".pyc", ".webp", ".gif"}

pytestmark = pytest.mark.skipif(not review_terms.REVIEW.exists(), reason="the review repo is not on this machine")


def test_the_names_come_from_the_review_repo():
    t = review_terms.terms()
    assert len(t["people_read"]) >= 2 and len(t["vendors"]) >= 20 and t["domains"]      # read there, not written here
    assert t["people"] and t["people"] == t["people_read"] - review_terms.organogram_people()      # only the organogram's people are let through


def test_no_real_name_or_link_from_the_review_repo_is_in_this_tree():
    pattern = review_terms.pattern()
    hits = []
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file() or SKIP_DIRS & set(p.relative_to(ROOT).parts) or p.suffix in BINARY:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        hits += [f"{p.relative_to(ROOT)}:{n}: {m.group(0)!r}" for n, line in enumerate(text.splitlines(), 1) if (m := pattern.search(line))]
    assert hits == [], f"{len(hits)} real names or links from the review repo:\n" + "\n".join(hits[:40])
