"""What a recipe step is handed: the raw files, the tables built so far, and the places to record what it found."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from app.domain.common import AS_OF


@dataclass
class Ctx:
    data: Path  # data/, read only
    answers: dict  # the recipe's answers.yaml: decisions a person made, with who and why
    gate: dict = field(default_factory=dict)  # the recipe's gate.yaml: what the load gate checks
    t: dict[str, pd.DataFrame] = field(default_factory=dict)  # tables built so far (raw_* are never modified)
    issues: list[dict] = field(default_factory=list)
    drops: list[dict] = field(default_factory=list)
    step: str = ""  # set by the runner: the script being run
    as_of: date = AS_OF  # the data horizon: nothing dated after it is read

    def decision(self, key: str) -> tuple[str, str | None]:
        """What the person answered to a question: ("accept" | "change" | "skip", value). An unanswered question takes the proposed answer, which is `accept`."""
        d = (self.answers.get("decisions") or {}).get(key) or {}
        return d.get("action", "accept"), d.get("value")

    def read_csv(self, rel: str, skip: int = 0) -> pd.DataFrame:
        """A source file as text, one `src_row` (1-based data row) per record, after `skip` lines before the header. Nothing is converted."""
        df = pd.read_csv(self.data / rel, dtype=str, keep_default_na=False, encoding="utf-8", skiprows=skip)
        df.insert(0, "src_row", range(1, len(df) + 1))
        return df

    def first_line(self, rel: str) -> str:
        with (self.data / rel).open(encoding="utf-8") as f:
            return f.readline().rstrip("\n")

    def read_grid(self, rel: str) -> pd.DataFrame:
        """A hand-built sheet with a layout of its own (title rows, multi-row headers), as a grid of text: columns c0..cN, `src_row` = the
        1-based line of the file. Nothing is converted or skipped."""
        df = pd.read_csv(self.data / rel, dtype=str, keep_default_na=False, encoding="utf-8", header=None)
        df.columns = [f"c{i}" for i in range(df.shape[1])]
        df.insert(0, "src_row", range(1, len(df) + 1))
        return df

    def find(self, pattern: str) -> list[str]:
        """The files under data/ that match a glob, as paths relative to data/, in name order."""
        return sorted(p.relative_to(self.data).as_posix() for p in self.data.glob(pattern) if p.is_file())

    def issue(self, key: str, file: str, issue: str, count: int, handling: str, rule: str, consequence: str,
              example: str, owner: str) -> None:
        """Record a defect. Nothing is recorded when count is 0. `owner` is a person's first name or full name, "SAP admin", a function's
        title, or "@groups:R01,L02" (the member who owns most of those purchasing groups), resolved from the final tables."""
        if count <= 0:
            return
        assert handling in {"fix", "infer", "flag", "link", "leave", "drop"}, handling
        assert key not in {i["key"] for i in self.issues}, f"duplicate issue key {key}"
        self.issues.append(dict(key=key, file=file, issue=issue, count=int(count), handling=handling, rule=rule,
                                consequence=consequence, example=example, owner=owner, step=self.step))

    def drop(self, raw_table: str, src_row: int, reason: str, kept_as: str | None = None) -> None:
        """A raw row that will have no clean row. The load gate requires every raw row to be kept or dropped here."""
        self.drops.append(dict(raw_table=raw_table, src_row=int(src_row), reason=reason, kept_as=kept_as, step=self.step))


def examples(values, n: int = 3, sep: str = "; ") -> str:
    """A short, deterministic example string from an iterable of values."""
    seen: list[str] = []
    for v in values:
        s = str(v)
        if s not in seen:
            seen.append(s)
        if len(seen) == n:
            break
    return sep.join(seen)
