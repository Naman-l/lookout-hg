"""Message trust, computed in code from the sender and the words before any person or model reads a message.

Nothing here knows a supplier, an amount or a part: a sender is compared with the vendor master it is given, a price with the
history it is given, and the words with vocabularies that name an intent (change where payments go, talk to a machine, press
for today), not one message. The recipe's step 20 calls these functions; `verdict` turns the flags into blocked / review / ok.

Flags that block (nothing may follow from the message): sender_domain_lookalike, reply_to_freemail, bank_detail_change,
instruction_in_message. Everything else asks a person to look (review). A price far above the part's own history is review on
its own and blocks nothing; a spot offer also trips supplier_on_hold or advance_payment_demand when those are true.
"""

from __future__ import annotations

import re

FREEMAIL = {"gmail", "yahoo", "outlook", "hotmail", "freemail", "proton", "protonmail", "icloud", "aol", "gmx", "yandex", "qq", "163"}  # the name part of a free-mail domain
BLOCK = {"sender_domain_lookalike", "reply_to_freemail", "bank_detail_change", "instruction_in_message"}

FLAG_WORDS = {
    "sender_domain_lookalike": "the sender's domain imitates a supplier's (a letter swapped for one that looks like it)",
    "sender_domain_near_match": "the sender's domain is one or two letters from a supplier's",
    "reply_to_freemail": "replies would go to a free-mail address, not the supplier",
    "reply_to_other_domain": "replies would go to a different domain from the sender's",
    "bank_detail_change": "asks to change where payments go",
    "instruction_in_message": "contains an instruction aimed at software or AI systems",
    "urgency": "pushes for action today",
    "sender_not_in_master": "the sender is not in the supplier master",
    "sender_not_contact_on_file": "the sender's address is not the contact on file",
    "supplier_on_hold": "the supplier is on hold or inactive in the ERP",
    "advance_payment_demand": "demands payment before shipment",
    "price_far_above_history": "the price is far above what the company has paid for the part",
}

# What looks like what, in a domain name: folded before comparing.
_CONFUSABLE = (("rn", "m"), ("vv", "w"), ("cl", "d"), ("0", "o"), ("1", "l"), ("i", "l"), ("5", "s"))

# Intent vocabularies. Each pattern names a way of saying it, not one message.
_BANK_CHANGE = [re.compile(p, re.I) for p in (
    r"\b(?:updated?|new|changed?|revised|replacement|different|alternate|alternative)\s+(?:remittance|banking|bank|payment|wire|beneficiary|account)\s+(?:details?|instructions?|information|coordinates|account)\b",
    r"\bremit(?:tance)?\s+(?:all\s+|any\s+|future\s+)?payments?\s+(?:to|into)\b",
    r"\b(?:pay|wire|transfer|remit|settle|send)\b[^.\n]{0,80}\b(?:to|into)\b[^.\n]{0,40}\b(?:new|different|following|alternate)\s+(?:bank\s+)?account\b",
    r"\b(?:update|change|amend)\b[^.\n]{0,30}\bvendor (?:master|record|file|bank)",
    r"\b(?:bank\s+)?account\b[^.\n]{0,30}\b(?:is|has been|was)\s+(?:frozen|closed|suspended|under audit|locked)\b",
    r"\b(?:iban|swift|bic|routing number|sort code)\b[^.\n]{0,40}\b(?:changed|new|updated|below|following)\b",
)]
_URGENCY = re.compile(r"\bURGENT\b|immediate effect|confirm by return|by end of day|today so that|before (?:close|the end) of (?:business|day)|this lot won't last|act now|within 24 hours|time[- ]sensitive", re.I)
_ADVANCE = re.compile(r"wire transfer in advance|payment in advance|full prepayment|pay(?:ment)? before (?:shipment|shipping|dispatch)|cash in advance|100% (?:up ?front|in advance)", re.I)

# The shapes of text that speak to a machine rather than to a buyer (the one scan, shared with the message tool's soft signals).
_MACHINE = re.compile(
    r"\b(?:automated (?:purchasing |ordering |procurement )?(?:system|agent|process)|ai (?:assistant|agent|system|model)|language model|llm|chat ?bot|the assistant reading)\w*\b"
    r"|\b(?:ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}\b(?:previous|prior|above|earlier|all|your|these)\b[^.\n]{0,30}\b(?:instructions?|rules?|guidelines?|policy|policies|prompts?|checks?)\b"
    r"|\b(?:pre-?approved|already approved|approved in advance)\b"
    r"|\b(?:no|without)\b[^.\n]{0,20}\b(?:further|additional|human)\s+(?:review|approval|confirmation|check)\b"
    r"|\b(?:new|updated)\s+instructions?\s+for\b|\bsystem (?:message|override|notice)\b",
    re.I,
)


def _fold(label: str) -> str:
    out = label.lower()
    for a, b in _CONFUSABLE:
        out = out.replace(a, b)
    return out


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance; domain labels are short."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _split(domain: str) -> tuple[str, str]:
    label, _, tld = domain.lower().rpartition(".")
    return label, tld


def imitated_domain(domain: str, known: set[str] | list[str]) -> tuple[str, str] | None:
    """(the supplier domain this one imitates, 'lookalike' | 'near') or None. A known domain imitates nothing.

    lookalike: the two are the same once look-alike characters are folded (rn/m, vv/w, 0/o, 1/l), or the same name under another top-level domain.
    near: one or two letters apart (a reworded fraud domain), long enough that a few letters are not a coincidence."""
    d = domain.lower()
    known = {k.lower() for k in known}
    if not d or d in known:
        return None
    label, tld = _split(d)
    for k in sorted(known):
        klabel, ktld = _split(k)
        if (_fold(label) == _fold(klabel) and label != klabel) or (label == klabel and tld != ktld):
            return k, "lookalike"
    best = None
    for k in sorted(known):
        klabel, _ = _split(k)
        dist = edit_distance(_fold(label), _fold(klabel))
        limit = 2 if min(len(label), len(klabel)) >= 8 else 1 if min(len(label), len(klabel)) >= 5 else 0
        if 0 < dist <= limit and (best is None or dist < best[0]):
            best = (dist, k)
    return (best[1], "near") if best else None


def sender_flags(from_email: str | None, reply_to: str | None, known_domains: set[str] | list[str], contact_emails: set[str] | list[str] = ()) -> tuple[str, list[str]]:
    """(how the sender matches the vendor master, the flags): match is 'record' (a contact on file), 'domain' (a supplier's domain, not its contact),
    'lookalike', 'near', 'not_in_master' or 'unknown_sender' (no address, as in a pasted note)."""
    flags: list[str] = []
    if not from_email or "@" not in from_email:
        match = "unknown_sender"
    else:
        dom = from_email.split("@")[1].lower()
        known = {k.lower() for k in known_domains}
        if dom in known:
            match = "record" if from_email.lower() in {c.lower() for c in contact_emails} else "domain"
            if match == "domain":
                flags.append("sender_not_contact_on_file")
        else:
            hit = imitated_domain(dom, known)
            if hit and hit[1] == "lookalike":
                match = "lookalike"
                flags.append("sender_domain_lookalike")
            elif hit:
                match = "near"
                flags += ["sender_domain_near_match", "sender_not_in_master"]
            else:
                match = "not_in_master"
                flags.append("sender_not_in_master")
    if reply_to and "@" in reply_to and from_email and "@" in from_email:
        rdom, fdom = reply_to.split("@")[1].lower(), from_email.split("@")[1].lower()
        if rdom != fdom:
            flags.append("reply_to_freemail" if _split(rdom)[0] in FREEMAIL else "reply_to_other_domain")
    return match, flags


def content_flags(subject: str, body: str) -> list[str]:
    """What the words ask for, whoever sent them."""
    text = f"{subject}\n{body}"
    flags = []
    if any(p.search(text) for p in _BANK_CHANGE):
        flags.append("bank_detail_change")
    if _MACHINE.search(text):
        flags.append("instruction_in_message")
    if _URGENCY.search(text):
        flags.append("urgency")
    if _ADVANCE.search(text):
        flags.append("advance_payment_demand")
    return flags


def price_far_above_history(offer_price: float | None, reference_price: float | None, factor: float = 3.0) -> bool:
    """An offer at `factor` times what the company last paid for the part. Both prices must be in the same currency and unit; unknown is never a flag."""
    return bool(offer_price and reference_price and reference_price > 0 and offer_price >= factor * reference_price)


def verdict(flags: list[str] | set[str]) -> str:
    return "blocked" if BLOCK & set(flags) else "review" if flags else "ok"
