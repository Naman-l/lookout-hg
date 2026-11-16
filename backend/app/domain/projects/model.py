"""Projects: the unit HG plans, buys and is measured by. A project has plants (SAP), names the sheets write in other ways (aliases, linked by a
person's answer, never guessed), and work fronts that consume groups of material."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.base import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # a slug made from the name the directory prints
    name: Mapped[str] = mapped_column(String)
    vertical: Mapped[str] = mapped_column(String)  # roads | railway | bess | solar | td
    vertical_raw: Mapped[str] = mapped_column(String)
    stage: Mapped[str] = mapped_column(String)  # new | running | nearing_completion
    stage_raw: Mapped[str] = mapped_column(String)
    state: Mapped[str | None] = mapped_column(String)
    district: Mapped[str | None] = mapped_column(String)
    tracking_no: Mapped[str | None] = mapped_column(String)  # what ME5A's Requirement Tracking Number carries for this project
    head_name: Mapped[str | None] = mapped_column(String)
    head_email: Mapped[str | None] = mapped_column(String)
    planner_name: Mapped[str | None] = mapped_column(String)
    planner_email: Mapped[str | None] = mapped_column(String)
    sap_plant_name: Mapped[str | None] = mapped_column(String)
    src_row: Mapped[int] = mapped_column(Integer)


class ProjectPlant(Base):
    """A SAP plant and the project it belongs to; the head-office plant belongs to none."""

    __tablename__ = "project_plants"

    plant: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str | None] = mapped_column(String)  # the plant's long name, as MB51's Name 1 prints it


class ProjectAlias(Base):
    """A name a source writes for a project. Linked by a person's answer (with who and why), by the plant, or by the name itself; a name nobody
    answered for stays unresolved, never matched by likeness."""

    __tablename__ = "project_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alias: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)  # the kind of file that writes it (fund sheet, look-ahead, ...)
    project_ids: Mapped[str | None] = mapped_column(String)  # comma list: a column can stand for two projects ("KD-1&2"); None = unresolved
    method: Mapped[str] = mapped_column(String)  # same_name | answer | plant | unresolved
    answered_by: Mapped[str | None] = mapped_column(String)
    evidence: Mapped[str | None] = mapped_column(Text)


class WorkFront(Base):
    """A front of work on a project and the material groups it consumes: how a late material becomes a stopped front."""

    __tablename__ = "work_fronts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String)
    material_groups: Mapped[str] = mapped_column(Text)  # comma list
