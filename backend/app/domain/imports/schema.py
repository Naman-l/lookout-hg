from __future__ import annotations

from pydantic import BaseModel, Field


class DataIssue(BaseModel):
    """A defect found in the company's files, named, counted, handled, with its consequence and an owner (the Data issues table)."""

    key: str
    issue: str
    file: str
    count: int
    handling: str  # fix | infer | flag | link | leave | drop
    rule: str
    consequence: str
    example: str
    owner: str
    step: str


class BuildStep(BaseModel):
    seq: int
    step: str
    title: str
    rows_in: int
    rows_out: int
    issues: int
    seconds: float


class BuildStamp(BaseModel):
    as_of: str
    recipe: str
    recipe_hash: str
    built_at: str
    counts: dict[str, int]
    gate_checks: int
    gate_failed: int


class ImportExample(BaseModel):
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    note: str | None = None

    model_config = {"populate_by_name": True}


class ImportProposed(BaseModel):
    answer: str
    effect: str


class ImportQuestion(BaseModel):
    """One flashcard: a question that has the same answer for every entry it covers, with a proposed answer."""

    id: str
    kind: str  # alias | currency | origin | duplicate_row | possible_duplicate | stock_count | other
    question: str
    covers: int
    file: str | None = None
    examples: list[ImportExample] = []
    entries: list[str] = []
    proposed: ImportProposed
    state: str = "open"  # open | accepted | changed | skipped
    answer: str | None = None
    answered_by: str | None = None
    answered_at: str | None = None


class ImportDeck(BaseModel):
    import_id: str
    questions: list[ImportQuestion]


class ImportAnswer(BaseModel):
    question_id: str
    action: str  # accept | change | skip
    value: str | None = None


class ImportAnswers(BaseModel):
    answered_by: str
    answers: list[ImportAnswer]


class ImportFileChange(BaseModel):
    file: str
    rows_in: int
    rows_out: int
    changes: list[str]


class ImportCheck(BaseModel):
    name: str
    passed: bool


class ImportAnswerCounts(BaseModel):
    total: int
    changed: int
    skipped: int


class ImportDryRun(BaseModel):
    hash: str
    files: list[ImportFileChange]
    checks: list[ImportCheck]
    answers: ImportAnswerCounts
    recipe_steps: int


class ImportApproval(BaseModel):
    hash: str
    approved_by: str


class ImportLoaded(BaseModel):
    loaded: bool
    built_at: str
