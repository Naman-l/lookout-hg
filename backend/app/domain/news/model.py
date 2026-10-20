"""External news items, matched to a supplier with a confidence or marked as a place or unrelated."""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class NewsItem(Base):
    __tablename__ = "news_items"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    date: Mapped[str] = mapped_column(String)
    source: Mapped[str | None] = mapped_column(String)
    headline: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    entity_raw: Mapped[str | None] = mapped_column(String)
    identity_id: Mapped[str | None] = mapped_column(ForeignKey("supplier_identities.id"))
    match_kind: Mapped[str] = mapped_column(String)  # supplier | place | other_company | unrelated
    confidence: Mapped[float | None] = mapped_column(Float)
    match_evidence: Mapped[str | None] = mapped_column(Text)
