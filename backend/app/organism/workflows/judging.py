"""Judging an answer: the verifier's hard checks, the Reviewer's soft grade, and at most one revision.

The judge is called by the runner each time Lookout answers. It verifies, reviews, records both as run events, and
returns a prompt telling Lookout what to fix (once) or None. Whatever it saw last is the run's final state."""

from __future__ import annotations

import json
import os

from .. import company
from ..review import ENABLED, Review, needs_revision, review, revision_prompt
from ..runs import store
from ..schemas import FailedCheck, Grade
from ..toolkit import plural
from ..verifier import verify


# "after" (default): the Recommendation is delivered as soon as code has verified it and the Reviewer's grade follows a few
# seconds later. The one thing that does not wait is a draft: when the run staged a request to a supplier, the Reviewer first
# reads that request for the critical check "nothing in it commits the company", and a fail sends Lookout back once.
# "inline": the Reviewer grades every check first and Lookout revises once on a critical fail; a turn plus a review on every
# run, so it does not fit the 30 s fire.
MODE = os.environ.get("LOOKOUT_REVIEW_MODE", "after")


def _failed(graded) -> list[FailedCheck]:
    return [FailedCheck(name=c.name, reason=c.critique or "failed this check") for c in graded.failed] if graded else []


class Judging:
    def __init__(self, *, kind: str, title: str, services, max_cost: float, headline_fn=None, required_tools=(), required_calls_fn=None, lookup_only_if_claims=False, extra_checks=None):
        self.kind, self.title, self.services, self.max_cost = kind, title, services, max_cost
        self.headline_fn, self.required_tools, self.required_calls_fn, self.lookup_only_if_claims = headline_fn, required_tools, required_calls_fn, lookup_only_if_claims
        self.extra_checks = extra_checks
        self.revised = False
        self.revision_rejected = False
        self.rec = self.verdict = self.graded = None
        self.first = None  # the first answer's (rec, verdict, structured output), kept in case the revision does worse
        self.review_cost = 0.0
        self.draft_check = None  # the critical-only review of a staged request, before delivery

    def _staged_requests(self, ctx) -> list[dict]:
        """The supplier requests this run staged, as the Reviewer reads them."""
        from ...domain.actions import ledger  # noqa: PLC0415

        out = []
        for aid in ctx.action_ids:
            a = ledger.get(ctx.db_path, aid)
            if a is not None and a.type == "supplier_request":
                out.append({"to": a.recipient, "subject": a.subject, "body": a.body})
        return out

    async def __call__(self, result) -> str | None:
        ctx = result.ctx
        self.rec, self.verdict = verify(
            ctx, result.structured_output, services=self.services, cost_usd=(result.cost_usd or 0) + self.review_cost, max_cost_usd=self.max_cost,
            headline=self.headline_fn(ctx) if self.headline_fn else None, required_tools=self.required_tools,
            required_calls=self.required_calls_fn(ctx) if self.required_calls_fn else None, lookup_only_if_claims=self.lookup_only_if_claims, extra_checks=self.extra_checks,
        )
        v = self.verdict
        if self.revised and self.first is not None and not v.passed and self.first[1].passed:
            # the revision broke a check the first answer passed: keep the first answer
            self.rec, self.verdict, result.structured_output = self.first
            v = self.verdict
            self.revision_rejected = True
            ctx.recorder.emit("verifier.result", "The revision did worse on a code check, so the first answer stands", agent="verifier", **v.model_dump())
            return None
        ctx.recorder.emit(
            "verifier.result",
            f"{v.numbers_from_tools} of {v.numbers_checked} numbers from tools · {plural(v.open_questions_with_owner, 'open question')} with an owner"
            + ("" if v.passed else f" · {plural(len(v.failures), 'check')} failed"), agent="verifier", **v.model_dump(),
        )
        if self.revised:  # no second review: the revision is verified by code, and the first review's grade stays
            return None
        self.graded = None
        if ENABLED and MODE == "inline" and self.rec is not None:
            self.graded, cost = await review(self.kind, self.title, self.rec.model_dump(mode="json"), v.model_dump())
            self.review_cost += cost
            self._announce(ctx, self.graded, cost)
        drafts = self._staged_requests(ctx) if (ENABLED and MODE != "inline" and self.rec is not None and v.passed) else []
        if drafts:  # a request waits for approval: check what it commits before the answer is delivered
            self.draft_check, cost = await review(self.kind, self.title, self.rec.model_dump(mode="json"), v.model_dump(), drafts=drafts, only_critical=True)
            self.review_cost += cost
            failed = [c.critique or c.name for c in self.draft_check.failed] if self.draft_check else []
            ctx.recorder.emit("step.text", "The Reviewer read the drafted request: " + (f"it commits {company.names(ctx.db_path)[1]} to something" if failed else f"it commits {company.names(ctx.db_path)[1]} to nothing" if self.draft_check else "could not check it"), agent="reviewer", system=True)
        if needs_revision(v.passed, self.graded or self.draft_check, self.revised):
            self.revised = True
            self.first = (self.rec, self.verdict, result.structured_output)
            ctx.recorder.emit("revision.started", "Lookout revises once after the review" if v.passed else "Lookout revises once: a check failed", agent="lookout")
            return revision_prompt(v.model_dump(), self.graded or self.draft_check)
        return None

    def _announce(self, ctx, graded, cost) -> None:
        ctx.recorder.emit(
            "review.result", f"Reviewer {graded.score}/100: {graded.summary}" if graded else "The Reviewer could not run: ungraded", agent="reviewer",
            score=graded.score if graded else None, checks=[c.model_dump() for c in graded.checks] if graded else [],
            failed=[f"{c.name}: {c.critique}" for c in graded.failed] if graded else [], cost_usd=round(cost, 4),
        )

    async def grade_after(self, result) -> None:
        """After the run has finished: the Reviewer grades the delivered Recommendation and the grade is added to it.
        Never changes the run's status; an unavailable Reviewer leaves the Recommendation ungraded."""
        if not (ENABLED and MODE == "after" and self.rec is not None and self.verdict is not None):
            return
        ctx = result.ctx
        graded, cost = await review(self.kind, self.title, self.rec.model_dump(mode="json"), self.verdict.model_dump(), drafts=self._staged_requests(ctx))
        self.graded = graded
        self.review_cost += cost
        self.rec.grade = Grade(reviewer_score=graded.score if graded else None, checks_passed=sum(c.passed for c in graded.checks) if graded else None, checks_total=len(graded.checks) if graded else None, summary=graded.summary if graded else "Not graded", failed_checks=_failed(graded))
        row = store.read_run(ctx.db_path, ctx.run_id)
        if row and row["recommendation_json"]:
            doc = json.loads(row["recommendation_json"])
            doc["grade"] = self.rec.grade.model_dump()
            store.update_run(ctx.db_path, ctx.run_id, recommendation_json=json.dumps(doc), cost_usd=(row["cost_usd"] or 0) + cost)
        self._announce(ctx, graded, cost)

    def finish(self, result) -> tuple[str, str | None, str | None]:
        """(status, recommendation_json, verifier_json) once the loop is over; the grade is attached here."""
        if self.verdict is None:
            return result.status, None, None
        if self.rec is not None:
            self.rec.grade = Grade(reviewer_score=self.graded.score if self.graded else None, checks_passed=sum(c.passed for c in self.graded.checks) if self.graded else None, checks_total=len(self.graded.checks) if self.graded else None, summary=(self.graded.summary if self.graded else "Not graded") + (" (revised once, first answer kept)" if self.revision_rejected else " (revised once)" if self.revised else ""), revised=self.revised and not self.revision_rejected, failed_checks=_failed(self.graded))
        result.cost_usd = (result.cost_usd or 0) + self.review_cost
        return ("ok" if self.verdict.passed else "did_not_pass"), (self.rec.model_dump_json() if self.rec else None), self.verdict.model_dump_json()
