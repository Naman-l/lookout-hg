"""Defence in depth for message text, which is written by someone outside the company.

Two layers beside the sender-trust checks the inbox already runs (they live in the data recipe and see one planted trap):
1. Spotlighting: message text only ever reaches a model between markers that carry a per-run nonce, and any copy of the marker in the text is
   removed, so the text cannot close the block and pass itself off as ours.
2. A cheap signal scan: phrases that talk to an AI reader or ask for what a supplier has no business asking. It flags and never blocks: the signals
   are returned beside the text, shown to the model as a reason for more care, and become a warning on the run.
Neither replaces the hard guarantees (the recipient lock, approval, the gate); they make the model's own judgement better informed."""

from __future__ import annotations

import re
import secrets

_SIGNALS = [
    ("addresses an AI reader", re.compile(r"\b(ai|a\.i\.|llm|language model|chat ?bot|assistant|automated (agent|system)|ai agent|ai system)s?\b[^.\n]{0,60}\b(must|should|please|need to|are to|will)\b|\b(attention|note to|message for)\b[^.\n]{0,20}\b(ai|assistant|agent|model)\b", re.I)),
    ("asks to ignore or override instructions", re.compile(r"\b(ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|your|these|the)\b[^.\n]{0,30}\b(instructions?|rules?|guidelines?|policy|policies|prompts?|checks?)\b", re.I)),
    ("claims to be the system or its owner", re.compile(r"\b(system (message|prompt|override|notice)|developer (message|mode)|admin(istrator)? (override|mode)|new instructions?)\b", re.I)),
    ("asks for secrecy", re.compile(r"\b(do not|don't|never)\b[^.\n]{0,20}\b(tell|inform|notify|alert)\b|\b(do not|don't|never)\b[^.\n]{0,30}\b(mention|flag|report)\b[^.\n]{0,30}\b(anyone|the (buyer|buyers|team|user|owner|purchasing|procurement)|finance|the (company|customer|client))\b", re.I)),
    ("asks to move money or change bank details", re.compile(r"\b(wire|transfer|remit|pay|send)\b[^.\n]{0,40}\b(immediately|today|now|urgent(ly)?|before)\b|\b(new|updated|changed)\b[^.\n]{0,20}\b(bank|banking|payment|remittance)\b", re.I)),
    ("asks to send to another address", re.compile(r"\b(reply|respond|send|forward|cc|copy)\b[^.\n]{0,30}\b(to|at)\b[^.\n]{0,20}[\w.+-]+@[\w-]+\.[\w.-]+", re.I)),
    ("asks to act without approval", re.compile(r"\b(without|no need for|skip|bypass)\b[^.\n]{0,20}\b(approval|confirmation|review|sign[- ]?off|asking|checking)\b|\b(approve|confirm|accept)\b[^.\n]{0,20}\b(automatically|on (their|your) behalf)\b", re.I)),
]


def signals(text: str, company: str | None = None) -> list[str]:
    """Why a message reads like an instruction to an AI or an attempt to get something it should not. Empty means none found, not 'safe'.
    `company` is the customer's name (from the recipe): "do not mention it to <company>" is a request for secrecy like the other recipients."""
    found = [name for name, rx in _SIGNALS if rx.search(text or "")]
    if company and "asks for secrecy" not in found and re.search(r"\b(do not|don't|never)\b[^.\n]{0,30}\b(mention|flag|report)\b[^.\n]{0,30}\b" + re.escape(company) + r"\b", text or "", re.I):
        found.append("asks for secrecy")
    return found


def wrap(text: str, nonce: str | None = None) -> tuple[str, str]:
    """The text between markers carrying `nonce`; any copy of the marker inside is removed. Returns (wrapped, nonce)."""
    nonce = nonce or secrets.token_hex(4)
    tag = f"UNTRUSTED-SUPPLIER-TEXT-{nonce}"
    clean = re.sub(r"</?\s*UNTRUSTED[-A-Z0-9 ]*>|<<\s*/?\s*UNTRUSTED[-A-Z0-9 ]*>>", "[marker removed]", text or "", flags=re.I)
    return f"<<{tag}>>\n{clean}\n<</{tag}>>", nonce
