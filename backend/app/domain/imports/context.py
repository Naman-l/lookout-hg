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
    t: dict[str, pd.DataFrame] = field(default_factory=dict)  # tables built so far (raw_* are never modified)
    issues: list[dict] = field(default_factory=list)
    drops: list[dict] = field(default_factory=list)
    step: str = ""  # set by the runner: the script being run
    as_of: date = AS_OF  # the data horizon: nothing dated after it is read

    def decision(self, key: str) -> tuple[str, str | None]:
        """What the person answered to a question: ("accept" | "change" | "skip", value). An unanswered question takes the proposed answer, which is `accept`."""
        d = (self.answers.get("decisions") or {}).get(key) or {}
        return d.get("action", "accept"), d.get("value")

    def read_csv(self, rel: str) -> pd.DataFrame:
        """A source file as text, one `src_row` (1-based data row) per record. Nothing is converted."""
        df = pd.read_csv(self.data / rel, dtype=str, keep_default_na=False, encoding="utf-8")
        df.insert(0, "src_row", range(1, len(df) + 1))
        return df

    def issue(self, key: str, file: str, issue: str, count: int, handling: str, rule: str, consequence: str,
              example: str, owner: str) -> None:
        """Record a defect. Nothing is recorded when count is 0. `owner` is a name, "ERP admin", or a token the
        runner resolves from the final tables: "@part:PN-12345", "@parts:HR-1,HR-2", "@suppliers:SUP-1,SUP-2"."""
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
