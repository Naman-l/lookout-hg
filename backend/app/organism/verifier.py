"""The verifier: code only. It turns the model's draft into the Recommendation and checks it against what the
tools actually returned during the run (the evidence register) and what the ledger actually holds.

Hard checks (a failure marks the run `did_not_pass`, and the screen says so plainly):
  schema            the draft parses
  evidence          the item kind's required tools ran, and the shortage was examined for every part the notice affects
  numbers           every cited id was returned by a tool, and the value matches (quantities exactly, money to 0.01)
  dates             every day-and-month in the text or a draft is a date some tool returned
  prose             every numeral in the written text is one a tool returned (ids, dates and years are not numerals)
  open_questions    every question has an owner; unknowns a tool raised are carried in by code if the draft omitted them
  handoffs          every specialist in the plan ended with a valid handoff
  actions           every action cited exists for this run, is a supplier request awaiting approval, and is
                    addressed to the contact on file; nothing is drafted on a trust item
  budget            the run stayed inside its cost cap
"""

from __future__ import annotations

import re
from decimal import Decimal

from pydantic import ValidationError

from ..domain.actions import ledger
from ..domain.common import AS_OF
from . import id_shapes
from .context import RunContext
from .schemas import DoneLine, Point, Recommendation, RecommendationDraft, RecommendationFinding, RecommendationNumber, VerifierResult

_MONTHS = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
_SPEC = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?\s?(?:V(?:DC|AC)?|kV|mV|W|kW|mW|A|mA|Ah|mAh|Hz|kHz|MHz|GHz|mm|cm|µm|um|kg|g|°C|nm|dB|Ω|ohms?|kΩ|[Kk]?[Bb]it|GB|MB)(?![a-z])|(?<![\w.])\d+[Dd](?!\w)")  # '24 V', '3.3 kW', '2D': a rating in a part's name or spec is not a quantity


def mask_specs(text: str) -> str:
    """The text with each rating (48 V, 24 V, 5 mm, 2D) blanked out, same length: the number in a part's name is not a figure about anything."""
    return _SPEC.sub(lambda m: " " * len(m.group(0)), text)


_NOT_NUMERALS = [
    re.compile(r"\b[A-Z]{2,4}-[A-Z0-9][A-Z0-9\-/]*\b"),  # PN-12345, ORD-26-00450/10, XX-0001, A-1234abcd
    re.compile(r"\b\d{4}-\d{2}(?:-\d{2})?\b"),  # 2026-10, 2026-10-13
    re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTHS}\b", re.I),  # 10 October
    re.compile(rf"\b{_MONTHS}\.?\s+\d{{1,2}}\b", re.I),  # Oct 15
    re.compile(r"\b20\d{2}\b"),  # 2026
    re.compile(r"\bQ[1-4]\b"),
    re.compile(r"^\s*\d+[.)]\s", re.M),  # list markers: "1. ", "2) "
    re.compile(r"\blines?\s+\d+(?:\s*(?:,|and|&)\s*\d+)*", re.I),  # "line 10", "lines 10 and 20": references, not quantities
    _SPEC,
]
# Words that belong to how the app works, not to the company's world: a buyer should never read them in an answer or a draft.
_INTERNAL = re.compile(r"\b(hand[- ]?offs?|clerks?|planners?|hand(?:ed)? (?:off|back)|specialists?|sub-?agents?|analysts?|aliases|alias|normali[sz]er|qty_received|purchase_orders|verifier|evidence register|tool calls?|tools?|JSON|API|MCP|prompts?|LLM|language model|run-[0-9a-f]{8}|"
                       r"the agent|the model|system prompt|get_[a-z_]+|[a-z]+_[a-z]+_[a-z_]+)\b", re.I)


_BANNED = re.compile(r"\b(?:ways? through|staged|unknowns?|tranches?|conditional|gross|allocation from (?:its |the supplier's |\w+'s )?other capacity|reviewer|items?)\b", re.I)


_SLOP = re.compile(r"\b(?:it is important|worth noting|in order to ensure|leverag\w*|proactive(?:ly)?|streamlin\w*|robust|comprehensive|navigat\w*|landscape|moving forward|at this time|"
                   r"may potentially|could possibly|it seems|various|several factors|monitor the situation|consider your options|stay in close contact|keep an eye on)\b", re.I)


def slop_words(text: str) -> list[str]:
    """Filler a buyer would read as machine prose (F112): a warning on what the buyer reads and on the drafts, never a failure."""
    return sorted({m.group(0).lower() for m in _SLOP.finditer(text)})


def banned_words(text: str) -> list[str]:
    """Words a buyer does not use (plan-13 wording: item → case, unknown → not known yet, gross, conditional, tranche, …): a warning, never a failure."""
    return sorted({m.group(0).lower() for m in _BANNED.finditer(text)})


def internal_words(text: str) -> list[str]:
    """Plumbing words in buyer-facing text ('handoff', 'specialist', a tool name): worth a warning, and a refusal in a draft."""
    return sorted({m.group(0).lower() for m in _INTERNAL.finditer(text)})


_ROLE_TITLE = re.compile(r"\b(?:the )?(?:planning lead|procurement lead|purchasing manager|category manager|finance lead|department head)\b", re.I)  # say who, or the function ("planning")
_PLAIN_ROLE = {"planning lead": "planning"}


_DAY_COUNT = re.compile(r"\b(\d[\d,]*)[\s-]+(?:calendar[\s-]+|business[\s-]+|working[\s-]+)?days?\b|\bdays?_(?:left|past_due)\W{1,4}(\d[\d,]*)|\"days\"\W{1,4}(\d[\d,]*)|\bnet[\s-]*(\d+)\b", re.I)  # "Net 30" is thirty days of payment terms


def day_counts(text: str) -> set[int]:
    """Every day count a text states ('36 days', 'days_left: 36', '"days": 98'): what a tool said, or what the answer says."""
    out = set()
    for m in _DAY_COUNT.finditer(text or ""):
        raw = next(g for g in m.groups() if g)
        out.add(int(raw.replace(",", "")))
    return out


_LEFT_CLAIM = re.compile(r"\b(\d[\d,]*)[\s-]+(?:calendar[\s-]+|business[\s-]+|working[\s-]+)?days?\s+(?:left|remain\w*|to go|until|before|away|out|ahead|of (?:runway|slack|cover|time)|to (?:act|decide|respond|the deadline|deadline)|from (?:today|now))\b|\b(\d[\d,]*)-day\s+(?:runway|window|countdown)\b|\bin\s+(\d[\d,]*)[\s-]+days?\b|\bwith\s+(\d[\d,]*)\s+days?\s+(?:left|to)\b", re.I)
_LEFT_TOOL = re.compile(r"\b(?:days_left|days_to_effective)\W{1,4}(\d[\d,]*)", re.I)


def days_left_claims(text: str) -> set[int]:
    """The 'N days left' an answer states ('3 days left', 'in 18 days', '66 days until'): a count down to a date, which only a tool may supply."""
    return {int(next(g for g in m.groups() if g).replace(",", "")) for m in _LEFT_CLAIM.finditer(text or "")}


def days_left_in(text: str) -> set[int]:
    """The days-left figures a tool's text carries (days_left, days_to_effective)."""
    return {int(m.group(1).replace(",", "")) for m in _LEFT_TOOL.finditer(text or "")}


_PLAIN = {"numbers": "A figure in the answer does not match what the records returned", "prose": "The answer states a number that no lookup returned",
          "dates": "The answer states a date or a weekday that no lookup returned", "days": "The answer states a number of days that no lookup returned",
          "names": "The answer names a supplier by its number or a person by a job title", "evidence": "A lookup the answer needs was not made",
          "handoffs": "A step of the plan did not report back before the answer was written", "places": "The answer names a site that does not belong to that supplier", "counts": "The answer states a number of lines that does not match the records' count", "actions": "A draft or note the answer mentions was not prepared for this item",
          "budget": "The run cost more than its limit", "schema": "The answer could not be read",
          "claims": "The answer says it prepared an action, but nothing is waiting for signature"}


def plain_reasons(failures: list[str]) -> list[str]:
    """Each failed check in words a buyer reads: what kind of thing is wrong, never the id or the check's own text."""
    return list(dict.fromkeys(_PLAIN.get(f.split(":", 1)[0], "A check on the answer failed") for f in failures))


FINDING_WORDS, POINTS_MAX, ASK_POINTS_MAX, POINT_WORDS, LABEL_WORDS = 20, 4, 3, 40, 4


_CLAIM = re.compile(r"\b(staged|prepared|drafted|queued|ready for your (?:signature|approval)|(?:is|are) (?:now )?(?:with you |here )?for your (?:signature|approval)|awaiting your signature)\b", re.I)
_HEDGE_BEFORE = re.compile(r"\b(?:no|not|nothing|never|none|can|could|would|will|may|might|to be|if|unless|before|already)\b[^.;:]{0,30}$", re.I)
_HEDGE_AFTER = re.compile(r"^[^.;:]{0,30}\b(?:if you (?:ask|want|say)|on request|when you ask)\b", re.I)


def claim_failures(ctx, draft, action_ids) -> list[str]:
    """An Ask answer that says it staged, prepared or drafted something must have left a matching action waiting for signature in this run
    (staged, or an earlier draft it amended or linked): a claim alone is a false statement on screen (SIDEQ; LOOKOUT P1). Negations and offers do not count."""
    if not (ctx.item_key or "").startswith("ask:"):
        return []
    text = " ".join([*spoken_lines(draft), draft.next_step.what or ""])
    claims = [m for m in _CLAIM.finditer(text) if not _HEDGE_BEFORE.search(text[max(0, m.start() - 40):m.start()]) and not _HEDGE_AFTER.search(text[m.end():m.end() + 40])]
    if not claims:
        return []
    waiting = [aid for aid in action_ids if (a := ledger.get(ctx.db_path, aid)) is not None and a.state == "proposed" and ledger.in_run(ctx.db_path, aid, ctx.run_id)]
    return [] if waiting else [f"claims: the answer says it {claims[0].group(1).lower()} an action, but this run left none waiting for signature"]


def spoken_lines(draft) -> list[str]:
    """Every line of prose a buyer reads in the answer, except the questions: the finding, the points' rows, the assumptions and what would change it."""
    return [draft.finding, *[f"{p.label}. {p.text}" for p in getattr(draft, "points", [])], *draft.assumptions, *draft.would_change]


_ACTION_WORDS = re.compile(r"\b(?:approve|send|call|phone|ask|order|place|confirm|decide|chase|request|hold|expedite|sign|close|keep|reply|review|wait|accept|reject|extend|reroute|release|pay|cancel|escalate|draft|check|pick|choose|wait for)\b", re.I)
_AT_STAKE = re.compile(r"\$|€|\d|\brobots?\b|\bunits?\b|\bbuilds?\b", re.I)


def headline_gaps(finding: str, action: bool = True) -> list[str]:
    """What a headline must let a buyer read on its own: what is at stake (money, robots or a count) and what to do (an action). Checked in code at the write.
    A case's finding is its Situation (`action=False`): what happened and what it hits; the next step says what to do."""
    out = []
    if not _AT_STAKE.search(finding):
        out.append("say what is at stake: money, robots or a count")
    if action and not _ACTION_WORDS.search(finding):
        out.append("say what to do: an action (who does what)")
    return out


def shape_failures(draft, coded: bool = False, ask: bool = False) -> list[str]:
    """The answer is skimmed, not read: a decision sentence of at most 20 words, then at most 4 short rows."""
    out = []
    n = len(draft.finding.split())
    if n > FINDING_WORDS:
        out.append(f"shape: the finding has {n} words; it is one decision sentence of at most {FINDING_WORDS}; move the detail into points")
    points = getattr(draft, "points", [])
    limit = ASK_POINTS_MAX if ask else POINTS_MAX
    if len(points) > limit:
        out.append(f"shape: {len(points)} points; at most {limit}" + (" in an answer to a question" if ask else ""))
    for p in points:
        if not coded and (len(p.text.split()) > POINT_WORDS or len(p.label.split()) > LABEL_WORDS):
            out.append(f"shape: the point '{p.label}' is too long; a label of a few words and one short line")
    return out


def done_lines(ctx, services, action_ids: list[str]) -> list[DoneLine]:
    """What the run did, in words, from the ledger: each line carries its action id and stage."""
    out = []
    for aid in action_ids:
        a = ledger.get(ctx.db_path, aid)
        if a is None:
            continue
        waiting = {"proposed": "waiting for your approval", "approved": "approved", "executed": "sent", "rejected": "declined", "failed": "failed to send"}.get(a.state, a.state)
        if a.type == "note" and (a.change or {}).get("kind") == "record":
            out.append(DoneLine(text=f"Prepared a decision: {a.body}: {waiting}", action_id=aid, stage=a.state))
        elif a.type == "note" and (a.change or {}).get("kind") == "note" and a.state == "proposed":
            out.append(DoneLine(text=f"Prepared a note to {(a.change or {}).get('to') or 'the team'}: {waiting}", action_id=aid, stage=a.state))
        elif a.type == "note":
            who = (a.change or {}).get("owner") or "a buyer"
            out.append(DoneLine(text=f"Logged a question for {who}", action_id=aid, stage="logged"))
        elif a.type == "supplier_alias":
            out.append(DoneLine(text=f"Proposed linking two supplier ids: {waiting}", action_id=aid, stage=a.state))
        else:
            contact = services.suppliers.contact_for(a.target.id) if a.target else None
            out.append(DoneLine(text=f"Drafted a request to {contact.name if contact else 'the supplier'}: {waiting}", action_id=aid, stage=a.state))
    return out


def plain_role(text: str) -> str:
    """A role title the data uses as an owner, in the words a buyer says ('planning'): applied to the questions code carries in."""
    return re.sub(r"\b(?:the )?planning lead\b", "planning", text or "", flags=re.I)


CARRY_MAX = 4  # the Conditions row carries at most this many dropped conditions, each once (BUYER R1: ~40 conditions, one supplier's terms five times)


def _supplier_of(db_path):
    """part id -> the name of the supplier on its latest order line, for grouping questions to suppliers; None when there is no database."""
    import sqlite3  # noqa: PLC0415

    if not db_path:
        return None
    cache: dict = {}

    def of(part: str):
        if part not in cache:
            try:
                with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
                    row = con.execute("SELECT r.name FROM po_lines p JOIN supplier_records r ON r.record_id = p.identity_id WHERE p.part_number = ? AND p.status != 'CANCELLED' "
                                      "ORDER BY p.order_date DESC LIMIT 1", (part,)).fetchone()
                cache[part] = row[0] if row else None
            except sqlite3.Error:
                cache[part] = None
        return cache[part]
    return of


def collapse_similar(questions: list, supplier_of=None) -> list:
    """Questions that ask the same thing of the same person for different builds, parts or months are one question: more than two with the same owner
    and the same reason become the first, with a count of the rest. The fire raised 28 stock questions that were one question 28 times.
    A question for a supplier is merged only with the same supplier's (supplier_of: part id -> supplier name): one question per supplier, naming its parts."""
    def key_of(q):
        if q.owner != "supplier" or supplier_of is None:
            return (q.owner, q.why_it_blocks, None)
        parts = [r.id for r in q.refs if r.type == "part"]
        return (q.owner, q.why_it_blocks, supplier_of(parts[0]) if parts else None)
    groups: dict[tuple, list] = {}
    for q in questions:
        groups.setdefault(key_of(q), []).append(q)
    out, done = [], set()
    for q in questions:
        key = key_of(q)
        if key in done:
            continue
        done.add(key)
        g = groups[key]
        parts = sorted({r.id for x in g for r in x.refs if r.type == "part"})
        if len(g) > 2:      # per supplier: "(<supplier>: parts)" (fp-agent R1)
            what = f"{q.what} ({key[2]}: {', '.join(parts)})" if key[2] and parts else f"{q.what} (and {len(g) - 1} like it)"
            q = q.model_copy(update={"what": what, "refs": [r for x in g for r in x.refs][:12]})
        out.append(q)
        if len(g) == 2 and g[1].question.strip().lower() != g[0].question.strip().lower():  # two months asking the very same question is one question (run-38710a03, agent2)
            out.append(g[1])
    return out


_NUMERAL = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?![\w])")


_TODAY = re.compile(r"\b(?:today(?:\s+is|\s*\(|\s+being)|as of today[,\s(]|right now|this morning|at the time of writing|the current date)([^.;\n]{0,18})", re.I)  # the date must follow the claim directly ('today is 10 October', 'as of today, 15 October', 'right now it is 11 October': a bare 'today, … by 15 October' is not a claim of what today is
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_WEEKDAY_DATE = re.compile(rf"\b((?:Mon|Tues?|Wed(?:nes)?|Thu(?:rs)?|Fri|Sat(?:ur)?|Sun)(?:day)?)\b[,.]?\s+(?:the\s+)?(?:(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTHS})\b|({_MONTHS})\.?\s+(\d{{1,2}})\b)", re.I)


_PAST = re.compile(r"\b(?:was|were)\s+(?:due|expected|promised|supposed)|\b(?:has|have|had)\s+(?:not|never|yet to)\s+(?:come|arrived|arrive|replied|responded|sent|given)|\b(?:hasn't|haven't|hadn't)\s+(?:come|arrived|replied|responded|sent)|\b(?:missed|overdue|lapsed|expired|already passed)\b|\bnone\s+(?:has|have)\s+come", re.I)
_CONDITIONAL = re.compile(r"\b(?:if|unless|should|would|once|until|when|in case)\b", re.I)


def future_dates_in_past_tense(text: str) -> list[str]:
    """A date after the data date written as if it had already happened ('was due by 10 October and none has come' on 25 September): the sentence is returned."""
    out = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n", text or ""):
        if not _PAST.search(sentence) or _CONDITIONAL.search(sentence):
            continue
        if any((m, d) > (AS_OF.month, AS_OF.day) for m, d in dates_in(sentence)):
            out.append(sentence.strip()[:100])
    return out


_WORD_COUNT = re.compile(r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+(?:\w+\s+){0,2}(?:parts|lines|orders|suppliers|items|offers|units|sites|quotes|builds|robots)\b", re.I)
_WORD_NUMBERS = {w: i for i, w in enumerate(["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"])} | {"a dozen": 12, "a couple": 2}
_COUNT = r"(\d{1,3}|" + "|".join(sorted(map(re.escape, _WORD_NUMBERS), key=len, reverse=True)) + r")"
_NUMWORDS = "(?:" + "|".join(w for w in _WORD_NUMBERS if " " not in w) + ")"  # another count in the gap starts a new clause: its own count, not a qualifier of the first
# a count of lines said with a state: the tool's count with that meaning is the only right number
_COUNTED = [
    (re.compile(rf"\b{_COUNT}\s+(?:\w+\s+){{0,3}}(?:lines?|orders?)\b(?:(?!\blines?\b|\borders?\b|\d|\b{_NUMWORDS}\b)[^.;\n]){{0,60}}\b(?:already (?:past due|late)|past due|overdue|late before)", re.I), ":lines_already_late", "lines already past due"),
    (re.compile(rf"\b{_COUNT}\s+(?:\w+\s+){{0,3}}(?:lines?|orders?)\b(?:(?!\blines?\b|\borders?\b|\d|\b{_NUMWORDS}\b)[^.;\n]){{0,40}}\b(?:under the notice|in scope|affected by the notice)", re.I), ":lines_in_scope", "lines under the notice"),
]


_PLACE_CLAIM = re.compile(r"\b([A-Z][\w&.-]+(?:\s[A-Z][\w&.-]+)?)['’]s\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+(?:quote|offer|site|plant|factory|facility|pack|line|unit)\b")


def place_claim_failures(text: str, ctx) -> list[str]:
    """"Acme's Springfield quote": a city written beside a supplier must be a place that supplier has in the records or that an offer of it returned."""
    import sqlite3  # noqa: PLC0415

    try:
        con = sqlite3.connect(f"file:{ctx.db_path}?mode=ro", uri=True)
        try:
            rows = con.execute("SELECT i.name, r.city FROM supplier_identities i JOIN supplier_records r ON r.identity_id = i.id WHERE r.city IS NOT NULL").fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return []
    cities = {c.split(",")[0].strip().lower() for _, c in rows}
    out = []
    for m in _PLACE_CLAIM.finditer(text or ""):
        who, place = m.group(1).lower(), m.group(2).lower()
        if place not in cities:
            continue
        mine = {c.split(",")[0].strip().lower() for n, c in rows if who in n.lower()}
        offered = " ".join(t for k, t in ctx.site_text.items() if who in k)
        if mine and place not in mine and place not in offered:
            out.append(f"places: '{m.group(0)}' names {m.group(2)}, which is not a place the records or the offers return for {m.group(1)} (" + ", ".join(sorted(mine)) + ")")
    return out


_OF_TOTAL = re.compile(r"\bof\s+(?:the\s+|these\s+|those\s+)?$", re.I)
_CLAIM_BEFORE_OF = re.compile(rf"\b{_COUNT}\s+of\s+(?:the\s+|these\s+|those\s+)?$", re.I)


def count_claim_failures(text: str, ctx) -> list[str]:
    """A count of lines written as a number or a word ('Three Acme lines are already past due') must be the count a tool returned for that meaning."""
    out = []
    for rx, suffix, what in _COUNTED:
        tool_counts = {ev.value for i, ev in ctx.evidence.items() if i.endswith(suffix)}
        if not tool_counts:
            continue
        for m in rx.finditer(text or ""):
            said = m.group(1).lower()
            if _OF_TOTAL.search((text or "")[max(0, m.start() - 12):m.start()]):  # 'four of the ten lines are past due': ten is the total, the count before 'of' is the claim
                before = _CLAIM_BEFORE_OF.search((text or "")[max(0, m.start() - 40):m.start()])
                if before is None:
                    continue
                said = before.group(1).lower()
            n = int(said) if said.isdigit() else _WORD_NUMBERS.get(said)
            if n is not None and Decimal(n) not in tool_counts:
                out.append(f"counts: '{m.group(0)[:70]}' says {n} {what}, but the tool counted {', '.join(str(int(v)) for v in sorted(tool_counts))}")
    return out


def weekday_mismatches(text: str, year: int) -> list[str]:
    """A weekday written beside a date that is not that weekday ('Monday 3 October'): the model counts days of the week, and gets them wrong."""
    from datetime import date  # noqa: PLC0415

    out = []
    for m in _WEEKDAY_DATE.finditer(text or ""):
        wd, d1, m1, m2, d2 = m.groups()
        month = _MONTH_NUM[(m1 or m2)[:3].lower()]
        day = int(d1 or d2)
        try:
            actual = date(year, month, day).weekday()
        except ValueError:
            continue
        if not _WEEKDAYS[actual].startswith(wd.lower()[:3]):
            out.append(f"{wd.capitalize()} {day} {_MONTH_LABEL[month]}")
    return out


def todays_date_claims(text: str) -> set[tuple[int, int]]:
    """Dates the text puts next to the word 'today' ('today is 10 October', 'as of today (10 Oct)'): the only today is the data date."""
    out: set[tuple[int, int]] = set()
    for m in _TODAY.finditer(text):
        claim = re.sub(r"\b(?:by|before|until|on|from|since|through)\s+(?:\d{1,2}\s+)?[A-Za-z]+\.?\s*\d{0,2}|[A-Za-z]+\.?\s+\d{1,2}\s*\(?(?:in\s+)?\d+\s+days?\)?|\d{1,2}\s+[A-Za-z]+\s*\(?(?:in\s+)?\d+\s+days?\)?", " ", m.group(1))  # '… by 15 October (in 20 days)' is a deadline with its countdown, not today's date
        out |= dates_in(claim)
    return out


def _why(e: Exception) -> str:
    errs = e.errors() if isinstance(e, ValidationError) else []
    return f"{errs[0]['msg']} at {'.'.join(str(x) for x in errs[0]['loc'])}" if errs else type(e).__name__


_MONTH_NUM = {m[:3].lower(): i + 1 for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"])}
_DATE_WORDS = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTHS})\w*|\b({_MONTHS})\w*\.?\s+(\d{{1,2}})\b", re.I)
_DATE_ISO = re.compile(r"\b20\d{2}-(\d{2})-(\d{2})\b")

_MONTH_LABEL = {i + 1: m for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"])}


def dates_in(text: str) -> set[tuple[int, int]]:
    """Every day-and-month in a text, as (month, day): '13 November', 'Nov 13' and '2026-11-13' are the same date."""
    out = {(int(m), int(d)) for m, d in _DATE_ISO.findall(text)}
    for d1, m1, m2, d2 in _DATE_WORDS.findall(text):
        out.add((_MONTH_NUM[(m1 or m2)[:3].lower()], int(d1 or d2)))
    return out


def numerals(text: str) -> list[Decimal]:
    for pat in _NOT_NUMERALS:
        text = pat.sub(" ", text)
    out = []
    for m in _NUMERAL.findall(text):
        try:
            v = Decimal(m.replace(",", ""))
            if v != 0:  # zero is absence, not a figure
                out.append(v)
        except Exception:  # noqa: BLE001
            pass
    for m in _WORD_COUNT.finditer(text):  # 'All eleven parts': a count written as a word is a figure like any other
        word = m.group(1).lower()
        if word in _WORD_NUMBERS and _WORD_NUMBERS[word] > 1:
            out.append(Decimal(_WORD_NUMBERS[word]))
    return out


def _same(a: Decimal, b: Decimal, unit: str) -> bool:
    return abs(a - b) <= (Decimal("0.01") if unit == "USD" else Decimal(0))




def product_pattern(services) -> re.Pattern:
    """The robots' names as the prose says them (the product families in the products table), longest first; matches nothing when the table lists none."""
    try:
        families = sorted({f for f in services.bom.product_families() if f}, key=lambda f: (-len(f), f))
    except Exception:  # noqa: BLE001  no products table (a unit test): no claim about a robot can be checked
        families = []
    return re.compile(r"\b(" + "|".join(re.escape(f) for f in families) + r")\b") if families else re.compile(r"(?!x)x")


_MONTH_NAMES = {m.lower(): i for i, m in _MONTH_LABEL.items()}
_MONTH_WORD = re.compile(r"(?<!\d\s)\b(" + "|".join(_MONTH_NAMES) + r")\b(?!\s+\d{1,2}\b)", re.I)  # 'October', not '13 October' (a date has its own check)


def _subject(ev, services, cache: dict, product_re: re.Pattern, part_re: re.Pattern) -> dict:
    """What a tool number is about: the robots it concerns (from the parts in its id and the robots in its name) and the months."""
    parts = set(part_re.findall(ev.id + " " + ev.name))
    products = {m.group(1) for m in product_re.finditer(ev.name)}
    for part in parts:
        if part not in cache:
            try:
                cache[part] = {(r.product.label or "").split()[0] for r in services.bom.where_used(part) if r.product.label}
            except Exception:  # noqa: BLE001  no answer means no claim about the robot
                cache[part] = set()
        products |= cache[part]
    months = {int(m) for m in re.findall(r"\b20\d\d-(\d\d)\b", ev.id)} | {_MONTH_NAMES[w.lower()] for w in _MONTH_WORD.findall(ev.name)}
    return {"products": products, "months": months}


_CLAUSE_BREAK = re.compile(r";|,\s+(?:and|but|while)\s|\s(?:and|while)\s+the\s", re.I)


def binding_failures(ctx: RunContext, text: str, services) -> list[str]:
    """A figure must be said of what it measures. '364' is a Alpha number; 'the Beta needs 364' passes the value check and fails here.
    Only a clear disagreement fails: every tool number with that value is about other robots, or other months, than the words around it."""
    cache: dict = {}
    product_re = product_pattern(services)
    part_re = id_shapes.pattern(ctx.db_path, "part")
    out = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n", mask_specs(text)):
        for m in _NUMERAL.finditer(sentence):
            try:
                v = Decimal(m.group(0).replace(",", ""))
            except Exception:  # noqa: BLE001
                continue
            if v == v.to_integral_value() and v < 10:  # '1 open line', '2 lines': a one-digit count matches too many tool figures to say what it is said of
                continue
            cands = [ev for ev in ctx.evidence.values() if _same(v, ev.value, ev.unit) and ev.unit not in ("USD", "days")]
            if not cands:
                continue
            subjects = [_subject(ev, services, cache, product_re, part_re) for ev in cands]

            def nearest(rx):  # the word of this kind closest to the figure, within 70 characters: '364 in October and 376 in November' binds each figure to its own month
                near = [(abs((w.start() + w.end()) // 2 - (m.start() + m.end()) // 2), w) for w in rx.finditer(sentence)]
                near = [x for x in near if x[0] <= 70]
                if rx is _MONTH_WORD:  # a month in the figure's own clause ('...Gamma G1 is short 24 EA ... in November') decides before one in the clause beside it
                    lo = max([b.end() for b in _CLAUSE_BREAK.finditer(sentence) if b.end() <= m.start()], default=0)
                    hi = min([b.start() for b in _CLAUSE_BREAK.finditer(sentence) if b.start() >= m.end()], default=len(sentence))
                    own = [x for x in near if lo <= x[1].start() and x[1].end() <= hi]
                    near = own or near
                if len({x[1].group(1).lower() for x in near}) > 1 and rx is _MONTH_WORD and len(re.findall(r"\d[\d,]*", sentence)) > 1:  # 'October and November are 364 and 376': a list, in an order only the reader can pair
                    return []
                return [min(near, key=lambda x: x[0])[1]] if near else []

            def entity_of():  # the robot a figure is said of: the last one named before it ('the Alpha ... is short 364 EA ... and the Beta ... 80 EA' binds each figure to its own clause), else the first after it ('364 Alpha robots')
                ends_clause = m.group(0).endswith(",") or sentence[m.end():m.end() + 1] in (",", ";")  # '...drive motor 364, the Beta B1 brake 80': a figure that ends its clause is said of the product before it
                after = [] if ends_clause else [w for w in product_re.finditer(sentence) if w.start() >= m.end() and w.start() - m.end() <= 70]
                gap = sentence[m.end():after[0].start()].split() if after else []
                if after and len(gap) <= 1 and not (gap and gap[0].lower() in {"ea", "and", "or", "units", "pieces", "pcs", "of", "in", "for"}):  # '80 Beta robots', '80 new Beta robots': the figure leads its noun
                    return [after[0]]
                before = [w for w in product_re.finditer(sentence) if w.end() <= m.start() and m.start() - w.end() <= 70]
                if before:
                    chain = [before[-1]]  # 'Alpha A1 and Beta B1 short 222': the figure is said of both robots of the list
                    for prev in reversed(before[:-1]):
                        if re.fullmatch(r"(?:\s+\w+)?(?:\s*,\s*|\s+and\s+|\s*,\s+and\s+)(?:\w+\s+)?", sentence[prev.end():chain[0].start()]) or re.fullmatch(r"\s*(?:\w+\s+)?(?:,|and)\s+(?:\w+\s+)?", sentence[prev.end():chain[0].start()]):
                            chain.insert(0, prev)
                        else:
                            break
                    return chain
                return [after[0]] if after else []

            said_p = {w.group(1) for w in entity_of()}
            if said_p and all(s["products"] and not (said_p & s["products"]) for s in subjects):
                out.append(f"numbers: {m.group(0)} is said of the {' and '.join(sorted(said_p))}, but the tool number with that value is about the {' and '.join(sorted(set().union(*[s['products'] for s in subjects])))}")
            said_m = {_MONTH_NAMES[w.group(1).lower()] for w in nearest(_MONTH_WORD)}
            if said_m and all(s["months"] and not (said_m & s["months"]) for s in subjects):
                out.append(f"numbers: {m.group(0)} is said of {' and '.join(_MONTH_LABEL[i] for i in sorted(said_m))}, but the tool number with that value is for {' and '.join(_MONTH_LABEL[i] for i in sorted(set().union(*[s['months'] for s in subjects])))}")
    return sorted(set(out))


def stray_in_text(ctx: RunContext, text: str) -> tuple[list[str], list[str]]:
    """Numbers and dates in a text that no tool returned. The verifier applies it to the answer and to every draft; the drafting tool applies it
    before a draft exists, so the clerk can fix it instead of the run failing."""
    tool_values = {ev.value for ev in ctx.evidence.values()} | set(ctx.seen_numerals)
    for phrase in sorted(ctx.say_forms, key=len, reverse=True):
        text = text.replace(phrase, " ")
    nums = sorted({str(v) for v in numerals(text) if not any(_same(v, t, "EA") for t in tool_values)})
    days = [f"{d} {_MONTH_LABEL[m]}" for m, d in sorted(dates_in(text) - ctx.seen_dates)]
    return nums, days


REASON_WORDS = 8
_NARRATION = re.compile(r"\b(?:here is|here's|lookout|your options|you can|we recommend|nothing is sent)\b|(?:^|\s)I(?:\s|$)", re.I)


_SHORT_PO = re.compile(r"(?<![\w-])(\d{5})/(\d{1,3})\b")
_FULL_PO = re.compile(r"\b[A-Z]{2,4}-\d{2}-(\d{5})/(\d{1,3})\b")


def short_po_refs(ctx: RunContext, text: str) -> str:
    """'PO 00554/30' is a PO line written short, not the figure 554. It is read as an id only when exactly one full PO line this run saw ends that way;
    an ambiguous or unknown one stays a numeral, and so stays unchecked. The check never gets looser than that."""
    seen: dict[tuple, set] = {}
    known = [*ctx.evidence]
    for ev in ctx.evidence.values():  # a number's own row and inputs name the lines it was computed from
        pv = getattr(ev, "provenance", None)
        known += [str(getattr(pv, "row", "") or "")] + [str(getattr(r, "id", "")) for r in (getattr(pv, "inputs", None) or [])]
    for full in _FULL_PO.finditer(" ".join(known)):
        seen.setdefault((full.group(1), full.group(2)), set()).add(full.group(0))
    return _SHORT_PO.sub(lambda m: " " if len(seen.get((m.group(1), m.group(2)), ())) == 1 else m.group(0), text)


BEFORE_NOTICE = re.compile(r"\b(?:past|late|overdue)\b[^.]{0,80}\bbefore (?:the|your) (?:fire|notice|force majeure|incident|attack)\b", re.I)


def before_notice_claim(text: str) -> bool:
    """'Four were already past their promised dates before the fire': a count before the notice is not what lines_already_late counts (it is counted on the
    data date), and the verifier would match its 4 to that unrelated figure (LOOKOUT, AGENT-EXPERT: three lines were late before the notice, four on 25 September)."""
    return bool(BEFORE_NOTICE.search(text or ""))


def recommended_drop(ctx: RunContext, rec) -> str | None:
    """Why the recommended way through cannot be shown, or None when it can: its kind is one code laid out; at most 8 words; it cites a tool
    figure when that option has figures (a figure-free reason is fine for one that has none); every figure and date it states is one it cites;
    no plumbing word, supplier id, role title, day count no tool gave, or narration. A failure drops the mark only; the answer is delivered."""
    n = len(rec.reason.split())
    if n > REASON_WORDS:
        return f"its reason has {n} words; at most {REASON_WORDS}"
    has_figures = any(i.startswith(f"option:{ctx.item_key}:{rec.kind}:") for i in ctx.evidence)
    if before_notice_claim(rec.reason) and not any(i.endswith(":lines_late_before_notice") for i in rec.number_ids):
        return "it counts lines late before the notice, which no figure it cites counts"
    if rec.kind in ctx.option_kinds and has_figures and not rec.number_ids:
        return "its reason cites no figure, and this option has figures"
    why = cited_line_drop(ctx, rec.kind, rec.reason, rec.number_ids)
    if why:
        return why
    words = _off_words(ctx, rec.reason)
    return f"its reason says {', '.join(repr(w) for w in words)}" if words else None


def _off_words(ctx: RunContext, text: str) -> list[str]:
    """Words a short line Lookout writes beside code's facts may not carry: plumbing, narration, a role title, a supplier id, a day count no tool gave."""
    words = internal_words(text) + [m.group(0).strip() for m in _NARRATION.finditer(text)] + [m.group(0) for m in _ROLE_TITLE.finditer(text)]
    words += id_shapes.pattern(ctx.db_path, "supplier", "legacy_supplier").findall(text)
    told = ctx.seen_day_counts | {int(ev.value) for ev in ctx.evidence.values() if ev.unit == "days" and ev.value == int(ev.value)}
    return words + [f"{d} days" for d in sorted(day_counts(text) - told)]


def finding_drop(ctx: RunContext, f) -> str | None:
    """Why a finding Lookout picked cannot be shown, or None: its key is a fact code found, its meaning is at most 8 words, every figure in it is one its
    fact states, every date one a tool returned, and no off word. A failure drops that finding only; the page shows code's template instead."""
    fact = ctx.finding_facts.get(f.key)
    if fact is None:
        return f"'{f.key}' is not a fact code found on this case"
    if before_notice_claim(f.meaning) and not before_notice_claim(fact):
        return "it says lines were late before the notice, which its fact does not"
    n = len(f.meaning.split())
    if n > REASON_WORDS:
        return f"its meaning has {n} words; at most {REASON_WORDS}"
    stated = numerals(fact)
    loose = sorted({str(v) for v in numerals(f.meaning) if not any(_same(v, t, "EA") for t in stated)})
    if loose:
        return f"its meaning states {', '.join(loose)}, which its fact does not"
    unseen = sorted(dates_in(f.meaning) - ctx.seen_dates - dates_in(fact))
    if unseen:
        return "its meaning states a date no tool returned"
    words = _off_words(ctx, f.meaning)
    return f"its meaning says {', '.join(repr(w) for w in words)}" if words else None


def cited_line_drop(ctx: RunContext, kind: str, text: str, number_ids: list[str]) -> str | None:
    """Why a line Lookout wrote about one way through (its why, or the recommended reason) cannot be shown, or None: the kind is one code laid
    out, and every figure and date in the text is one it cites (an id a tool returned)."""
    if not ctx.option_kinds:
        return "no ways through are laid out for this item"
    if kind not in ctx.option_kinds:
        return f"'{kind}' is not one of the ways laid out ({', '.join(ctx.option_kinds)})"
    unknown_ids = [i for i in number_ids if i not in ctx.evidence]
    if unknown_ids:
        return "it cites an id no tool returned: " + ", ".join(unknown_ids)
    cited = [ctx.evidence[i] for i in number_ids]
    original = text
    for ev in cited:
        if ev.say:
            text = text.replace(ev.say, " ")
    loose = sorted({str(v) for v in numerals(text) if not any(_same(v, ev.value, ev.unit) for ev in cited)})
    if loose:
        return f"it states {', '.join(loose)}, which it does not cite"
    unseen = sorted(dates_in(original) - ctx.seen_dates)
    if unseen:
        return "it states a date no tool returned: " + ", ".join(f"{d} {_MONTH_LABEL[m]}" for m, d in unseen)
    return None


def claim_rule_failures(ctx: RunContext, draft, services) -> list[str]:
    """The claim rules (answer_rules): a planned count is never 'short'; the rise on the uncovered need is never 'at stake' on open lines; no robots
    are named hit when the records show none short."""
    from .answer_rules import planned_short, robots_hit, stake_scope  # noqa: PLC0415

    out = []
    cited = [(ev.value, getattr(ev, "name", "") or getattr(ev, "label", "") or "") for ev in ctx.evidence.values()]
    for m, _ in planned_short(draft.finding, cited):
        out.append(f"binding: '{m.group(0)}' is a planned count (the forecast), not a shortfall; say planned, or give a short figure a tool returned")
    stake = next((ev for ev in ctx.evidence.values() if ev.id.endswith(":at_stake")), None)
    if stake is not None and stake_scope(draft.finding, getattr(getattr(stake, "provenance", None), "rule", None)):
        out.append("words: the figure is the rise on the need open orders don't cover; say that, not 'at stake'")
    if ctx.is_case:
        try:
            item = services.attention.get_item(ctx.item_key)
        except Exception:  # noqa: BLE001
            item = None
        if item is not None:
            for clause in robots_hit(draft.finding, getattr(item, "robots_short", []) or [], [r.label for r in getattr(item, "robots", []) or [] if getattr(r, "label", None)]):
                out.append(f"claims: '{clause.strip(', ')}' names robots hit, but the records show no robot short on this case; leave the robots out")
    return out


def verify(ctx: RunContext, raw_draft, *, services, cost_usd: float | None = None, max_cost_usd: float = 1.0,
           headline: list[str] | None = None, required_tools: tuple = (), required_calls: list[tuple[str, str]] | None = None, lookup_only_if_claims: bool = False, extra_checks=None) -> tuple[Recommendation | None, VerifierResult]:
    failures: list[str] = []
    try:
        draft = raw_draft if isinstance(raw_draft, RecommendationDraft) else RecommendationDraft.model_validate(raw_draft)
    except (ValidationError, TypeError) as e:
        return None, VerifierResult(passed=False, numbers_checked=0, numbers_from_tools=0, open_questions_with_owner=0, failures=[f"schema: the Recommendation did not parse ({_why(e)})"], reasons=[_PLAIN["schema"]])

    # numbers: cited ids must exist in the evidence register with the same value
    numbers, matched = [], 0
    for n in sorted(draft.numbers, key=lambda n: n.id):
        ev = ctx.evidence.get(n.id)
        if ev is None:
            failures.append(f"numbers: {n.id} was not returned by any tool")
            continue
        try:
            said = Decimal(str(n.value))
        except Exception:  # noqa: BLE001
            failures.append(f"numbers: {n.id} is {ev.value} {ev.unit} in the tool output but the Recommendation gives '{n.value}', which is not a number")
            continue
        if not _same(said, ev.value, ev.unit):
            failures.append(f"numbers: {n.id} is {ev.value} {ev.unit} in the tool output but the Recommendation says {n.value}")
            continue
        matched += 1
        numbers.append(RecommendationNumber(id=ev.id, value=str(ev.value), unit=ev.unit, name=ev.name, provenance=ev.provenance, say=ev.say))

    # evidence: the specialists must have looked at what this kind of item turns on
    makes_claims = bool(draft.numbers) or bool(numerals(" ".join(spoken_lines(draft))))
    for t in (required_tools if (makes_claims or not lookup_only_if_claims) else ()):  # a name, or a tuple of alternatives of which any one will do
        options = (t,) if isinstance(t, str) else t
        if not any(o in ctx.tools_called for o in options):
            failures.append(f"evidence: nobody called {' or '.join(options)}, which this kind of item needs")
    for tool_name, arg in sorted(required_calls or []):
        if (tool_name, arg) not in ctx.calls_made:
            failures.append(f"evidence: {tool_name} was not run for {arg}, which the notice affects")
    # headline numbers are added by code, so the same data always shows the same headline figures
    have = {n.id for n in numbers}
    for hid in sorted(headline or []):
        ev = ctx.evidence.get(hid)
        if ev is not None and hid not in have:
            numbers.append(RecommendationNumber(id=ev.id, value=str(ev.value), unit=ev.unit, name=ev.name, provenance=ev.provenance, say=ev.say))
    flagged = set(headline or [])
    numbers = sorted((n.model_copy(update={"headline": n.id in flagged}) for n in numbers), key=lambda n: (not n.headline, n.id))

    # prose: every numeral in the written text must be a tool number
    tool_values = {ev.value for ev in ctx.evidence.values()} | set(ctx.seen_numerals)  # figures and numerals a tool returned
    prose = " ".join(spoken_lines(draft))
    prose_original = prose
    for phrase in sorted(ctx.say_forms, key=len, reverse=True):  # "$1.54M" is a tool's own rounding of a tool figure
        prose = prose.replace(phrase, " ")
    prose = short_po_refs(ctx, prose)
    failures += binding_failures(ctx, prose_original, services)
    asked_text = " ".join(f"{q.what} {q.why_it_blocks} {q.question}" for q in draft.open_questions)
    drafted_text = " ".join(f"{a.subject or ''} {a.body or ''}" for a in (ledger.get(ctx.db_path, i) for i in sorted(set(ctx.action_ids))) if a is not None and a.type == "supplier_request")
    everything = " ".join([prose_original, asked_text, drafted_text])  # what the buyer reads and what would be sent
    for wd in weekday_mismatches(everything, AS_OF.year):
        failures.append(f"dates: '{wd}' is not that weekday; give the date alone, or a weekday a tool returned (never work out a weekday)")
    failures += count_claim_failures(everything, ctx) + place_claim_failures(everything, ctx)
    for s in future_dates_in_past_tense(everything):
        failures.append(f"dates: '{s}' writes a date that is still ahead of the data date ({AS_OF.day} {_MONTH_LABEL[AS_OF.month]}) as if it had passed; say it is promised by that date and how many days remain, as a tool gave them")
    wrong_today = sorted(todays_date_claims(everything) - {(AS_OF.month, AS_OF.day)})
    if wrong_today:
        failures.append("dates: the text says today is " + ", ".join(f"{d} {_MONTH_LABEL[m]}" for m, d in wrong_today)
                        + f"; today is {AS_OF.day} {_MONTH_LABEL[AS_OF.month]} {AS_OF.year}, the data date, and days left come only from the tools")
    unseen = sorted(dates_in(prose_original) - ctx.seen_dates)
    if unseen:
        failures.append("dates: " + ", ".join(f"{d} {_MONTH_LABEL[m]}" for m, d in unseen) + " is not a date any tool returned (a supplier's estimate is quoted in their words, not turned into a date)")
    asked = " ".join(f"{q.what} {q.why_it_blocks} {q.question} {q.owner}" for q in draft.open_questions)
    said = " ".join([*spoken_lines(draft), asked])
    draft_text = " ".join(f"{a.subject or ''} {a.body or ''}" for a in (ledger.get(ctx.db_path, i) for i in sorted(set(ctx.action_ids))) if a is not None and a.type == "supplier_request")
    supplier_id = id_shapes.pattern(ctx.db_path, "supplier", "legacy_supplier")  # a supplier is named, never numbered, in a sentence a buyer reads
    for sid in sorted(set(supplier_id.findall(said + " " + draft_text))):
        failures.append(f"names: {sid} is a supplier id; say the supplier's name")
    for role in sorted({m.group(0).lower() for m in _ROLE_TITLE.finditer(said)}):
        failures.append(f"names: '{role}' is a role title; say who (a buyer's name) or the function ('planning')")
    told = ctx.seen_day_counts | {int(ev.value) for ev in ctx.evidence.values() if ev.unit == "days" and ev.value == int(ev.value)}
    given = ctx.seen_days_left | {int(ev.value) for ev in ctx.evidence.values() if ev.unit == "days" and ev.value == int(ev.value) and ev.id.rsplit(":", 1)[-1] in ("days_left", "days_to_effective")}
    for n in sorted(days_left_claims(said) - given):  # a countdown is the tool's: 'in 18 days' from a deadline's own days_left, never from two dates the model subtracted
        failures.append(f"days: '{n} days left' is not the days left any tool returned for this item; give the date, or the days_left a tool gave")
    for n in sorted(day_counts(said) - told):  # the model never works out a date difference: a days-left is a figure a tool returned
        failures.append(f"days: '{n} days' is not a day count any tool returned; give the date, or a days figure a tool gave (never work it out from two dates)")
    warnings = [f"prose: '{m}' is an id; say the name" for m in sorted(set(id_shapes.pattern(ctx.db_path, "supplier", "legacy_supplier").findall(" ".join(spoken_lines(draft)))))]
    warnings += [f"message: it {s}; treated as information only" for s in sorted(ctx.injection_signals)]
    dropped = recommended_drop(ctx, draft.recommended) if draft.recommended else None
    if dropped:
        warnings.append(f"recommended: not shown, {dropped}")
    kept_findings = []
    for f in draft.findings:
        why_not = finding_drop(ctx, f)
        if why_not:
            warnings.append(f"findings: {f.key} is shown with code's template, {why_not}")
        elif f.key not in {k.key for k in kept_findings}:
            kept_findings.append(f)

    spoken = " ".join([*spoken_lines(draft), *[q.what + " " + q.question for q in draft.open_questions]])
    warnings += [f"prose: '{w}' is about how the app works; say it in the buyer's terms" for w in internal_words(spoken)]
    shown = " ".join([*spoken_lines(draft), draft.next_step.what, draft.recommended.reason if draft.recommended else "", *[f.meaning for f in draft.findings]])
    warnings += [f"words: '{w}' is not a buyer's word; say it as the buyer would" for w in banned_words(shown)]
    warnings += [f"slop: '{w}' is filler; name the case fact instead" for w in slop_words(" ".join([shown, drafted_text]))]
    if ctx.is_case and len(draft.finding.split()) > 14:  # F105; the gate refuses it live, a replayed older recording shows it here
        warnings.append(f"shape: the Situation has {len(draft.finding.split())} words; at most 14 on a case")
    warnings += [f"words: '{m.group(0).strip()}' is narration; Lookout is a system and says what is, not what it did" for m in _NARRATION.finditer(" ".join(spoken_lines(draft)))]
    asked_prose = " ".join(f"{q.what} {q.why_it_blocks} {q.question}" for q in draft.open_questions)      # the model's own questions are read for figures too (AI-UI-SYNC a)
    for phrase in sorted(ctx.say_forms, key=len, reverse=True):
        asked_prose = asked_prose.replace(phrase, " ")
    asked_prose = short_po_refs(ctx, mask_specs(asked_prose))
    stray = sorted({str(v) for v in numerals(prose) + numerals(asked_prose) if not any(_same(v, t, "EA") for t in tool_values)})
    failures += claim_rule_failures(ctx, draft, services)
    if stray:  # the answer is still delivered, the figure marked; only text that leaves the building (a draft) is blocked on it
        warnings.append(f"prose: numbers in the text that no tool returned: {', '.join(stray)}")

    # open questions: owners present; every tool-raised unknown is carried through
    carried = {q.what for q in draft.open_questions}
    merged = list(draft.open_questions)
    for u in ctx.unknowns:  # a tool's unknown is authoritative: code carries it in, the wording is the tool's (a role title the data uses is put in a buyer's words)
        if u.what not in carried:
            merged.append(u.model_copy(update={"what": plain_role(u.what), "why_it_blocks": plain_role(u.why_it_blocks), "question": plain_role(u.question), "owner": _PLAIN_ROLE.get(u.owner.lower(), u.owner)}))
            carried.add(u.what)
    merged = list({(q.what.strip().lower(), q.question.strip().lower()): q for q in reversed(merged)}.values())[::-1]   # the same question twice is one question (UX R1-18); one per PO line or part stays
    merged = collapse_similar(merged, supplier_of=_supplier_of(ctx.db_path))
    with_owner = sum(1 for q in merged if q.owner)  # the strip says "N of M owned": every question the Recommendation carries, not only the model's
    # (de-duplicate failures for a repeated unknown)
    failures = list(dict.fromkeys(failures))

    # handoffs
    for name in (ctx.delegated if ctx.open_plan else [m for m in ctx.plan if m not in ctx.optional or m in ctx.delegated]):  # Ask: whoever Lookout chose must have handed off; an unused optional step is fine
        if name not in ctx.handoffs:
            failures.append(f"handoffs: the {name.replace('_', ' ')} did not hand off")

    # the answer must rest on the handoffs: Lookout read every expected one before it wrote
    expected = ctx.delegated if ctx.open_plan else [m for m in ctx.plan if m not in ctx.optional or m in ctx.delegated]
    unread = [m for m in expected if m in ctx.handoffs and m not in ctx.handoffs_seen]
    if unread and ctx.plan:
        failures.append(f"handoffs: the Recommendation was written before reading the handoff of {', '.join(unread)}")

    failures += shape_failures(draft, coded=ctx.coded, ask=ctx.open_plan)
    from .carry import grouped, missing  # noqa: PLC0415

    answer_text = " ".join([*spoken_lines(draft), draft.next_step.what, *[f"{q.what} {q.why_it_blocks} {q.question}" for q in draft.open_questions]])
    dropped_all = list(dict.fromkeys(missing(ctx.conditions, answer_text)))  # carry-through: what the tools returned and the answer dropped, each once
    left_out = dropped_all[:CARRY_MAX] + ([f"+{len(dropped_all) - CARRY_MAX} more"] if len(dropped_all) > CARRY_MAX else [])   # the row shows a few; the warning keeps them all
    if dropped_all:
        warnings.append("carry: conditions the tools returned were added to the answer: " + "; ".join(dropped_all))
    if not (draft.next_step.who.strip() and draft.next_step.what.strip()):
        failures.append("shape: the answer ends without a next step; say who does what next")
    if draft.next_step.by and not (dates_in(draft.next_step.by) <= ctx.seen_dates):
        failures.append("dates: the next step's date is not one a tool returned")
    # actions
    staged = set(ctx.action_ids)
    for aid in draft.action_ids:
        if aid not in staged:
            covering = ledger.get(ctx.db_path, aid)  # a request this run found already waiting or sent to the same contact is linked to the run by the tool: citing it is right
            if covering is None or covering.type != "supplier_request" or covering.state not in ("proposed", "approved", "executed") or not ledger.in_run(ctx.db_path, aid, ctx.run_id):
                failures.append(f"actions: {aid} was not staged in this run")
    if not ctx.stage_allowed and ctx.action_ids:
        failures.append("actions: something was drafted on an item that allows no drafting")
    failures += claim_failures(ctx, draft, staged | set(draft.action_ids))
    for aid in sorted(staged):
        a = ledger.get(ctx.db_path, aid)
        if a is None or not ledger.in_run(ctx.db_path, aid, ctx.run_id):  # linked to this run: staged by it, or found by it already covering the ask (another item's open request to the same contact)
            failures.append(f"actions: {aid} is not in the ledger for this run")
            continue
        if a.type == "note" and (a.change or {}).get("kind") in ("record", "note"):  # a decision or a note the buyer asked for (stage_decision): awaiting the owner's signature, goes to no one
            if a.state != "proposed" or a.recipient is not None:
                failures.append(f"actions: {aid} is a {'decision record' if (a.change or {}).get('kind') == 'record' else 'staged note'} that is not simply awaiting the owner's signature")
            continue
        if a.type == "note":  # a logged question for a the company buyer: executed at once, never leaves the company
            if a.state != "executed" or a.recipient is not None:
                failures.append(f"actions: {aid} is a note that is not a plain log entry")
            continue
        if a.type == "supplier_alias":  # a proposal to link two ids: awaiting approval, goes to no one
            if a.state != "proposed" or a.recipient is not None:
                failures.append(f"actions: {aid} is an alias proposal that is not simply awaiting approval")
            continue
        if a.type != "supplier_request" or a.state != "proposed":
            failures.append(f"actions: {aid} is a {a.type} in state {a.state}; only supplier requests and alias proposals awaiting approval may be staged")
        if a.run_id != ctx.run_id:  # staged or joined by an earlier run: its text was checked by the tool that wrote it, with that run's evidence
            contact = services.suppliers.contact_for(a.target.id) if a.target else None
            if contact is None or a.recipient != contact.email:
                failures.append(f"actions: {aid} is not addressed to the contact on file")
            continue
        unseen_in_draft = sorted(dates_in(f"{a.subject or ''} {a.body or ''}") - ctx.seen_dates)
        if unseen_in_draft:
            failures.append(f"actions: {aid} names dates no tool returned: " + ", ".join(f"{d} {_MONTH_LABEL[m]}" for m, d in unseen_in_draft))
        loose = sorted({str(v) for v in numerals(f"{a.subject or ''} {a.body or ''}") if not any(_same(v, t, "EA") for t in tool_values)})
        if loose:
            failures.append(f"actions: {aid} states numbers that no tool returned: {', '.join(loose)}")
        contact = services.suppliers.contact_for(a.target.id) if a.target else None
        if contact is None or a.recipient != contact.email:
            failures.append(f"actions: {aid} is not addressed to the contact on file")

    for f in (extra_checks(ctx) if extra_checks else []):  # checks that belong to one kind of work (an import's step must have passed the gate)
        failures.append(f)

    # budget
    if cost_usd is not None and cost_usd > max_cost_usd:
        failures.append(f"budget: the run cost {cost_usd:.2f} USD, over its {max_cost_usd:.2f} USD cap")

    result = VerifierResult(passed=not failures, warnings=warnings, numbers_checked=len(draft.numbers), numbers_from_tools=matched, open_questions_with_owner=with_owner, open_questions=len(merged), failures=failures, reasons=plain_reasons(failures) + ([f"Some figures in the answer could not be checked against the records: {', '.join(stray)}"] if stray else []), unchecked=stray)
    rec = Recommendation(
        finding=draft.finding, unchecked=stray, next_step=draft.next_step, done=done_lines(ctx, services, sorted(staged | set(draft.action_ids))), points=[] if ctx.is_case else [Point(label=p.label, text=p.text) for p in draft.points] + ([Point(label="Conditions", text="; ".join(grouped(left_out)), added_by_code=True)] if left_out else []), numbers=numbers, assumptions=draft.assumptions, would_change=draft.would_change,
        open_questions=merged, action_ids=sorted(staged),
        findings=[RecommendationFinding(**f) for f in ctx.steward.get("findings", [])],
        recommended=draft.recommended if draft.recommended and not dropped else None, case_findings=kept_findings,
    )
    return rec, result
