"""Rules on what an answer's sentence may claim of a figure, keyed by the figure's own meaning (its label, its provenance) and by the case's fields,
never by a case. Each rule has two uses: the verifier refuses a live answer that breaks it (the model rewrites), and the item endpoint corrects a
recorded answer that broke it before the rule existed (a replay cannot rewrite itself), the way `two_step_duty` does.

planned_short   a count said to be "short" may not be a count that is only "planned" (the forecast for the month), AI-UI-SYNC M2
stake_scope     a figure whose provenance is the rise on the need open orders do not cover is said that way, never "at stake" on open lines
robots_hit      an answer may not name robots hit when the case's records show no robot short (robots_short is empty)
"""

from __future__ import annotations

import re
from decimal import Decimal

_NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\w])")
_SHORT_AFTER = re.compile(r"^(?P<mid>[^.;$]{0,48}?)\bshort\b", re.I)
_HIT = re.compile(r",?\s*\b(?:hits?|stops?|short(?:s)?)\b[^.;]*", re.I)
NOT_COVERED = ("open orders do not cover", "open orders don't cover", "that open o")


def _value(s: str) -> Decimal | None:
    try:
        return Decimal(s.replace(",", ""))
    except Exception:  # noqa: BLE001
        return None


def planned_short(text: str, cited: list[tuple[Decimal, str]]) -> list[tuple[re.Match, re.Match]]:
    """(figure, the 'short' after it) for each figure said to be short whose only cited meaning is a planned count."""
    out = []
    for m in _NUM.finditer(text or ""):
        v = _value(m.group(1))
        if v is None:
            continue
        labels = [lab.lower() for val, lab in cited if val == v]
        if labels and all("planned" in lab for lab in labels):
            after = _SHORT_AFTER.match(text[m.end():])
            if after:
                out.append((m, after))
    return out


def fix_planned_short(text: str, cited: list[tuple[Decimal, str]]) -> str:
    """'up to <n> <robot> robots short in <month>' -> '<n> <robot> robots planned in <month>': the figure keeps what it measures."""
    for m, after in reversed(planned_short(text, cited)):
        start = m.start()
        lead = text[max(0, start - 6):start]
        if lead.lower() == "up to ":
            start -= 6
        text = text[:start] + m.group(0) + after.group("mid") + "planned" + text[m.end() + after.end():]
    return text


def stake_scope(text: str, at_stake_rule: str | None) -> bool:
    """The finding says 'at stake' of a figure that is the rise on the need open orders do not cover."""
    return bool(at_stake_rule and any(k in at_stake_rule for k in NOT_COVERED) and re.search(r"\bat stake\b", text or "", re.I))


def fix_stake_scope(text: str, at_stake_rule: str | None) -> str:
    if not stake_scope(text, at_stake_rule):
        return text
    return re.sub(r"\bat stake\b", "on the need open orders don't cover", text, flags=re.I)


def robots_hit(text: str, robots_short: list, products: list[str]) -> list[str]:
    """The clauses that name a robot hit when no robot is short in the records."""
    if robots_short or not products:
        return []
    return [m.group(0) for m in _HIT.finditer(text or "") if any(p and p in m.group(0) for p in products)]


def fix_robots_hit(text: str, robots_short: list, products: list[str]) -> str:
    for clause in robots_hit(text, robots_short, products):
        text = text.replace(clause, "")
    return re.sub(r"\s+([.;])", r"\1", text).strip()


def correct_answer(answer: dict | None, detail) -> dict | None:
    """A served answer with each rule applied to its finding (a recorded one may predate the rule). Figures come from the answer's own numbers, read
    with the item's labels; nothing is added."""
    if not answer or not answer.get("finding") or detail is None:
        return answer
    labels = {n.id: n.label for n in getattr(detail, "numbers", []) or []}
    cited = []
    for n in answer.get("numbers") or []:
        nid = str(n.get("id", ""))
        own = nid.split(f"item:{detail.key}:", 1)[1] if nid.startswith(f"item:{detail.key}:") else nid
        v = n.get("value")
        v = v.get("value") if isinstance(v, dict) else v
        val = _value(str(v)) if v is not None else None
        if val is not None:
            cited.append((val, labels.get(own) or n.get("label") or n.get("name") or ""))
    finding, reasons = answer["finding"], []
    for fix, why in ((lambda t: fix_planned_short(t, cited), "a planned count is not a shortfall"),
                     (lambda t: fix_stake_scope(t, getattr(getattr(getattr(detail, "at_stake", None), "provenance", None), "rule", None)), "the figure is the rise on the need open orders don't cover"),
                     (lambda t: fix_robots_hit(t, getattr(detail, "robots_short", []) or [], [r.label for r in getattr(detail, "robots", []) or [] if r.label]), "the records show no robot short")):
        new = fix(finding)
        if new != finding:
            finding, reasons = new, [*reasons, f"corrected by a rule: {why}"]
    if not reasons:
        return answer
    return {**answer, "finding": finding, "corrections": [*(answer.get("corrections") or []), *reasons]}     # marked: the agent did not write the corrected words


def correct_recommendation(rec, detail):
    """The same correction on a Recommendation model (a run page), so the item page and the run page say one thing."""
    if rec is None or detail is None:
        return rec
    fixed = correct_answer(rec.model_dump(mode="json"), detail)
    if fixed.get("finding") == rec.finding:
        return rec
    return rec.model_copy(update={"finding": fixed["finding"], "corrections": fixed["corrections"], "answer_entities": []})
