"""Insights (PLAN 13): Team, Projects, Pricing, Estimates and the Daily brief. Read-only, computed by code; every figure names the records it rests on.

Team is visible to the Head of SCM for everyone, to each lead for their own team (who reports up to them, per the organogram) and to each member
for themselves (`viewer`: a member id or full name); a page the viewer may not see answers 403. Nothing is ranked or sorted by a performance figure."""

from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain import lookups
from app.domain.insights import service
from app.domain.insights.schema import Brief, EstimatesResponse, MemberPage, PricingDetail, PricingResponse, ProjectPage, ProjectsResponse, TeamResponse

router = APIRouter()


@router.get("/insights/team", response_model=TeamResponse, summary="The SCM team, one row per member the viewer may see: as the organogram draws it, never ranked")
def team(viewer: str | None = None, session: Session = Depends(get_session)):
    return service.team(session, viewer)


@router.get("/insights/team/{person}", response_model=MemberPage, summary="One member's page: open PRs and age, POs released, turnaround against their vertical, "
            "savings, effort on cancelled PRs, days waited on others, workload")
def team_member(person: str, viewer: str | None = None, session: Session = Depends(get_session)):
    b = lookups.member_of(session, person)
    if b is None:
        raise HTTPException(404, "no such member of the SCM team")
    if not service.can_see(session, viewer, b.id):
        raise HTTPException(403, f"This is {b.name}'s Team page. Only {service.who_sees(session, b.id)} see it.")
    page = service.member(session, b.id)
    note = None if viewer else f"No viewer named: on screen this page is shown only to {service.who_sees(session, b.id)}."
    return page.model_copy(update={"viewer_note": note}) if note else page


@router.get("/insights/projects", response_model=ProjectsResponse, summary="Every project by vertical: open PRs, turnaround, cancelled lines, budget vs actual, "
            "requirement vs fund vs received, long-lead status, ₹ at risk, days held by Projects")
def projects(session: Session = Depends(get_session)):
    return service.projects(session)


@router.get("/insights/projects/{pid}", response_model=ProjectPage, summary="One project: where its lines stand on the ladder, whose move, work-front readiness, "
            "top materials, its Today cases")
def project(pid: str, session: Session = Depends(get_session)):
    resolved = lookups.resolve_project(session, pid) or pid
    page = service.project_page(session, resolved)
    if page is None:
        raise HTTPException(404, "no such project")
    return page


@router.get("/insights/pricing", response_model=PricingResponse, summary="Per material: rate by site and vendor, spread, 12-month trend, last price vs budget vs latest quote")
def pricing(session: Session = Depends(get_session)):
    return service.pricing(session)


@router.get("/insights/pricing/{material}", response_model=PricingDetail, summary="One material's prices in detail, PV lines against their index, and what a spread leaves unknown")
def pricing_material(material: str, session: Session = Depends(get_session)):
    out = service.pricing_detail(session, material)
    if out is None:
        raise HTTPException(404, "no PO on file for this material")
    return out


@router.get("/insights/estimates", response_model=EstimatesResponse, summary="Per project and month: requirement vs fund vs received; bias, accuracy, repeat over-askers, "
            "sheet names that resolve to no project")
def estimates(session: Session = Depends(get_session)):
    return service.estimates(session)


@router.get("/brief/{person}", response_model=Brief, summary="A member's Daily brief: the morning email they would get (never sent)")
def brief(person: str, session: Session = Depends(get_session)):
    out = service.brief(session, person)
    if out is None:
        raise HTTPException(404, "no such member of the SCM team")
    return out


def _warm() -> None:
    """Every purchase's ladder is read once per build (about a second); reading it as the server starts keeps the first Insights page quick."""
    try:
        from app.db import SessionLocal  # noqa: PLC0415

        with SessionLocal() as s:
            service.ladders(s)
            service.project_rows(s)
    except Exception:  # noqa: BLE001  no database yet: the first request reads it instead
        pass


threading.Thread(target=_warm, name="insights-warm", daemon=True).start()
