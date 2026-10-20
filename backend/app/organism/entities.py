"""The things an answer mentions, found by the annotate module on the server, so the screen never posts text to be annotated on every render.

Spans keep the annotate module's shape ({start, end, type, ref, label, text}, UTF-16 offsets into the text they were found in)."""

from __future__ import annotations

from .schemas import Recommendation


def attach(rec: Recommendation, session) -> Recommendation:
    """Add `answer_entities` (the finding), `recommendation_entities` (each assumption, then each thing that would change the answer, one list per line) and each point's `entities`."""
    if session is None or rec is None:
        return rec
    from ..domain.annotate import service  # noqa: PLC0415

    spans = lambda text: [s.model_dump() for s in service.annotate(session, text)]  # noqa: E731
    rec.answer_entities = spans(rec.finding)
    rec.recommendation_entities = [spans(t) for t in [*rec.assumptions, *rec.would_change]]
    for p in rec.points:
        p.entities = spans(p.text)
    return rec
