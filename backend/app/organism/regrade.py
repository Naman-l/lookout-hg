"""`python -m app.organism.regrade`: grade the shipped recordings again with the current Reviewer, without re-running any workflow.

A recording is evidence and is never rewritten. The new grade goes to a sidecar beside it (recordings/grades/) and replay lays it over the recorded one, so the
no-key experience shows grades made on the same scale as a live run while the recording stays as it was made. About 0.001 USD a recording."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone

from . import recordings
from .review import REVIEW_MODEL, review


def kind_of(item_key: str) -> str:
    head = item_key.split(":", 1)[0]
    return head if head in ("disruption", "tariff", "unknown", "deadline", "compare", "import") else "common"


async def regrade_file(path) -> tuple[str, int | None]:
    """Grade one recording again and write the grade to a sidecar (recordings/grades/<same name>). The recording is evidence and is never rewritten."""
    doc = json.loads(path.read_text())
    rec = doc.get("recommendation")
    if not rec or not any(e["type"] == "review.result" for e in doc["events"]):  # a run code answered (a trust item) was never graded and is not now
        return path.name, None
    title = next((e["summary"] for e in doc["events"] if e["type"] == "run.started"), doc["item_key"])
    drafts = [{"to": a["recipient"], "subject": a["subject"], "body": a["body"]} for a in doc.get("actions", []) if a["type"] == "supplier_request"]  # the Reviewer reads what would be sent
    graded, cost = await review(kind_of(doc["item_key"]), title, rec, doc.get("verifier") or {}, drafts=drafts)
    if graded is None:
        return path.name, None
    side = {
        "graded_at": datetime.now(timezone.utc).isoformat(), "reviewer_model": REVIEW_MODEL, "recorded_at": doc["recorded_at"],
        "grade": {"reviewer_score": graded.score, "checks_passed": sum(c.passed for c in graded.checks), "checks_total": len(graded.checks), "summary": graded.summary,
                  "revised": bool((rec.get("grade") or {}).get("revised")),
                  "failed_checks": [{"name": c.name, "reason": c.critique or "failed this check"} for c in graded.failed]},
        "review_summary": f"Reviewer {graded.score}/100: {graded.summary}",
        "review_payload": {"score": graded.score, "checks": [c.model_dump() for c in graded.checks], "failed": [f"{c.name}: {c.critique}" for c in graded.failed], "cost_usd": round(cost, 4)},
    }
    out = recordings.sidecar_path(path)
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(side, indent=1, ensure_ascii=False) + "\n")
    return path.name, graded.score


async def main() -> int:
    out = []
    for p in sorted(recordings.DIR.glob("*.json")):
        out.append(await regrade_file(p))
        print(f"{out[-1][1] if out[-1][1] is not None else '--':>4}  {out[-1][0][:80]}", flush=True)
    sc = [s for _, s in out if s is not None]
    print(f"\n{len(sc)} graded of {len(out)}; average {sum(sc) / max(1, len(sc)):.1f}; min {min(sc, default=0)}; max {max(sc, default=0)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
