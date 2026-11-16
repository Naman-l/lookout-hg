"""Nothing of the previous customer (Halden) is left in the app: its recipe, domain packages and recordings were removed (docs/hg/NOTES.md).

The old names are written here on purpose: Halden is not this build's customer, and a test may name what must be gone. Scanned like the
customer-facts scan, code and comments; the files listed in tests/pending.py are skipped until their phase rewrites them.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.domain.test_no_customer_facts_anywhere import ROOT, _files
from tests.pending import PENDING, pending

OLD = re.compile(r"\b(Halden|Dana Reyes|Marcus Chen|Priya Nair|Tern|Porter P5|Heron H1|Yunzhan|Hallerbeck|Saltmarsh|Quenvara|Lanxin|Baycrest|Alderpoint|Vistaray|"
                 r"Jadepeak|Ruilian|Meiya|Great Plains|Vinh Phuc|Corvell)\b|\bSUP-\d+\b|\bV1\d{4}\b|\bHR-\d{5}\b|\bHPO-\d"
                 r"|\b(?:HPO|HR|SUP|PO)-\\d")      # the Halden id shapes, also as code writes them in a regular expression (HPO-\d{2}-\d{5})


def test_no_file_of_the_app_names_the_previous_customer():
    hits = [f"{p.relative_to(ROOT)}:{n}: {m.group(0)!r}" for p in _files() for n, line in enumerate(p.read_text(errors="ignore").splitlines(), 1) if (m := OLD.search(line))]
    assert hits == [], "\n".join(hits[:40])


def test_the_halden_recipe_and_packages_are_gone():
    gone = ["recipes/halden", "backend/app/domain/parts", "backend/app/domain/bom", "backend/app/domain/demand", "backend/app/domain/tariffs",
            "backend/app/domain/consignments", "backend/app/domain/stock", "backend/app/domain/news", "backend/app/organism/dev", "dummy_data/generate.py"]
    assert [g for g in gone if (ROOT / g).exists()] == []


def test_every_pending_path_exists():
    """A pending entry for a file that no longer exists hides nothing and must leave the list."""
    assert [p for p in PENDING if not (ROOT / p).exists()] == [] and not pending("backend/app/domain/prs/model.py")


def test_nothing_is_pending_any_more():
    """Phases 2-4 re-pointed every platform file at the HG recipe: no file is skipped by the scans."""
    assert PENDING == {}
