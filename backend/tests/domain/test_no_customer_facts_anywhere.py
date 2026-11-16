"""No file of the app names this customer: not in code, not in a comment, not in a prompt, not in the screens.

The names and ids are not written here: they are read at test time from the recipe's configuration and the raw data (tests/customer_terms.py).
Scanned: backend/app/**/*.py, *.md and *.yaml (prompts, glossaries, grading sheets) and frontend/src/**/*.ts(x), comments and docstrings included.
Not scanned: tests, the saved recordings, the generated API types, and the files still listed in tests/pending.py (each with the phase that
rewrites it). Nothing else is allow-listed: a hit is fixed at the source (configuration or generic copy).
"""

from __future__ import annotations

from pathlib import Path

from tests import customer_terms
from tests.pending import pending

ROOT = Path(__file__).resolve().parents[3]
TREES = ((ROOT / "backend" / "app", {".py", ".md", ".yaml"}), (ROOT / "frontend" / "src", {".ts", ".tsx"}))
SKIP_DIRS = {"recordings", "__pycache__", "node_modules"}
SKIP_FILES = {"schema.d.ts"}      # generated from the contract


def _files():
    for base, suffixes in TREES:
        for path in sorted(base.rglob("*")):
            rel = path.relative_to(ROOT).as_posix()
            if path.is_file() and path.suffix in suffixes and path.name not in SKIP_FILES and not SKIP_DIRS & set(path.parts) and not pending(rel):
                yield path


def test_the_terms_come_from_the_config_and_the_data():
    words, phrases = customer_terms.names()
    assert len(words) > 50 and len(phrases) > 100      # read from the vendor master, the project directory and the recipe: the scan would be empty without them


def test_no_file_of_the_app_names_the_customer_its_vendors_people_projects_or_ids():
    pattern = customer_terms.pattern()
    hits = []
    for path in _files():
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            m = pattern.search(line)
            if m:
                hits.append(f"{path.relative_to(ROOT)}:{n}: {m.group(0)!r} in {line.strip()[:90]!r}")
    assert hits == [], f"{len(hits)} places name this customer; make them generic or read them from configuration:\n" + "\n".join(hits[:60])


def test_the_scan_goes_red_on_a_name_a_person_a_project_an_id_or_the_company():
    """A scan that cannot fail proves nothing: each kind of fact, built from the configuration and the data, is found; generic words are not."""
    pattern = customer_terms.pattern()
    words, phrases = customer_terms.names()
    team = sorted(p for p in phrases if p.count(" ") == 1)[0]
    for line in (f"# ask {team.title()} to sign", f"x = '{sorted(words)[0].upper()}'", "# the HG Infra buyers", "pr = '1000204095'", "po = '4500120780/10'"):
        assert pattern.search(line), line
    for line in ("# ask the vendor for dates", "# the company's buyers", "e = 'XX-0007'", "n = 12345678", "# a project and its work fronts"):
        assert not pattern.search(line), line
