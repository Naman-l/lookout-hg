"""What the build records about itself: defects found, steps run, gate checks, stamp."""

from __future__ import annotations

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class DataIssue(Base):
    """One defect: named, counted, handled, with its consequence and an owner (the Data issues screen)."""

    __tablename__ = "data_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String, unique=True)  # file.slug, stable
    file: Mapped[str] = mapped_column(String)
    issue: Mapped[str] = mapped_column(Text)  # what is wrong, in a buyer's words
    count: Mapped[int] = mapped_column(Integer)
    handling: Mapped[str] = mapped_column(String)  # fix | infer | flag | link | leave | drop
    rule: Mapped[str] = mapped_column(Text)  # what the step does about it
    consequence: Mapped[str] = mapped_column(Text)  # what goes wrong if nobody handles it
    example: Mapped[str] = mapped_column(Text)
    owner: Mapped[str] = mapped_column(String)
    step: Mapped[str] = mapped_column(String)  # the recipe script that handles it


class BuildStep(Base):
    __tablename__ = "build_steps"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    step: Mapped[str] = mapped_column(String)  # file name
    title: Mapped[str] = mapped_column(String)  # first line of the docstring
    rows_in: Mapped[int] = mapped_column(Integer)  # rows across the tables the step read
    rows_out: Mapped[int] = mapped_column(Integer)
    issues: Mapped[int] = mapped_column(Integer)
    seconds: Mapped[float] = mapped_column(Float)


class RowDrop(Base):
    """A raw row that has no clean row, with the reason. The gate requires every raw row to be here or in a clean table."""

    __tablename__ = "row_drops"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_table: Mapped[str] = mapped_column(String)
    src_row: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    kept_as: Mapped[str | None] = mapped_column(Text)  # the surviving row it duplicates
    step: Mapped[str] = mapped_column(String)


class LoadGateCheck(Base):
    __tablename__ = "load_gate"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    check: Mapped[str] = mapped_column(String)
    passed: Mapped[int] = mapped_column(Integer)
    detail: Mapped[str] = mapped_column(Text)


class BuildMeta(Base):
    __tablename__ = "build_meta"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text)
