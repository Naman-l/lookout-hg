"""Quote extraction: the checks that make a record trustworthy, and the model-assisted extractor that proposes records.

A quote (an email, or a PDF attached to one) is turned into offers by an extractor. Whoever extracts, the work is a record file,
`recipes/<name>/extractions/<message>.yaml`: one offer per entry, each citing the exact line of the document it was read from. The
build replays the files with no model and no key and runs `verify` on every price; a record that fails stops the build.

The extractor (`python -m app.domain.imports.extract <message id>`) asks a model to read one message into that file. What the model
returns is data to check, not a result: each entry goes through `verify`, the ones that pass are written with `by: model` and
`reviewed: false` (the build does not load them until a person sets `reviewed: true`), the ones that fail are listed under `rejected`
with the reason.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import yaml
from pypdf import PdfReader

WINDOW = 40   # lines: how far before the price its part (or the supplier's model number) may stand

# What a record may carry. Everything else (ids, trust, the per-piece price) is derived by the build.
FIELDS = ("source", "line", "line_ref", "quote_no", "supplier_name", "part_number", "supplier_model", "qty_break", "price_raw", "price", "currency",
          "price_basis", "incoterm", "incoterm_place", "origin_claim", "origin_iso", "lead_time", "lead_time_condition", "lead_time_days",
          "validity_date", "moq", "tooling_usd", "surcharge_pct", "surcharge_included", "payment_terms", "prepayment", "available_from", "conditions")


def _lines(text: str) -> list[str]:
    return [" ".join(l.split()) for l in text.splitlines() if l.strip()]


def document_lines(data: Path, source: str, body: str) -> list[str]:
    """The lines of the document a record cites: the PDF's text, or the message body."""
    if source.startswith("pdf:"):
        return _lines("\n".join(p.extract_text() for p in PdfReader(data / "quotes" / "pdf" / source[4:]).pages))
    return _lines(body)


def verify(rec: dict, lines: list[str], subject: str = "") -> str | None:
    """None when the record's price is on its cited line next to its part (or the part is in the email's subject), else the reason it is not."""
    line = " ".join((rec.get("line") or "").split())
    at = [i for i, l in enumerate(lines) if l == line]
    if not line or not at:
        return f"the cited line is not in the document: {rec.get('line')!r}"
    if not rec.get("price_raw"):
        return "the record has no raw price"
    name = " ".join((rec.get("supplier_name") or "").split()).lower()
    if name and not any(name in l.lower() for l in lines) and name not in subject.lower():
        return f"the supplier name {rec['supplier_name']!r} is not in the document: leave it out to use the name in the supplier master"
    figure = str(rec["price_raw"]).split()[-1]
    if figure not in line:
        return f"the price {rec['price_raw']!r} is not on its cited line {line!r}"
    anchors = [a for a in (rec.get("part_number"), rec.get("supplier_model")) if a]
    if anchors and not any(a in subject for a in anchors) and not any(a in lines[j] for i in at for j in range(max(0, i - WINDOW), i + 1) for a in anchors):
        return f"neither {' nor '.join(anchors)} stands within {WINDOW} lines before the price on {line!r}"
    return None


def build_prompt(subject: str, body: str, source: str) -> str:
    return (
        "You read one supplier quote into price records for a procurement system. Reply with JSON only: a list of objects.\n"
        f"Allowed keys: {', '.join(FIELDS)}.\n"
        "Rules: `line` must be copied character for character from the document, the line that carries the price. `price_raw` is the price exactly "
        "as written there (with its unit words, e.g. 'per 1,000 240.58'). `price` is the number, with a decimal point. Leave a key out when the "
        "document does not say it; never infer a currency, a date or an origin. A lead time that depends on an event keeps the event in "
        "`lead_time_condition`. One object per price (one per quantity break). If the document corrects an earlier number, return the correction "
        "only.\n\n"
        f"Source: {source}\nSubject: {subject}\n\n--- document ---\n{body}\n--- end ---"
    )


def complete(prompt: str) -> str:
    """One model call, by the Messages API over httpx (needs ANTHROPIC_API_KEY). The extractor takes any function with this shape, so tests pass a fake."""
    import httpx

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit("set ANTHROPIC_API_KEY to run the extractor (the build itself never needs it)")
    r = httpx.post("https://api.anthropic.com/v1/messages", timeout=120, headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                   json={"model": os.environ.get("LOOKOUT_EXTRACT_MODEL", "claude-sonnet-5-5"), "max_tokens": 4000, "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status()
    return r.json()["content"][0]["text"]


def parse_reply(text: str) -> list[dict]:
    """The JSON list in a model's reply (it may wrap it in a code fence). Anything else is no records."""
    m = re.search(r"\[.*\]", text, re.S)
    try:
        out = json.loads(m.group(0)) if m else []
    except json.JSONDecodeError:
        return []
    return [r for r in out if isinstance(r, dict)]


def extract(message_id: str, subject: str, body: str, data: Path, out_dir: Path, *, source: str = "email", ask=complete, model: str = "") -> Path:
    """Propose the records for one message and write them to `out_dir/<message>.yaml` as `by: model, reviewed: false`. Never overwrites a file."""
    target = out_dir / f"{message_id}.yaml"
    if target.exists():
        raise FileExistsError(f"{target.name} already exists; remove it to extract again")
    lines = document_lines(data, source, body)
    kept, rejected = [], []
    for rec in parse_reply(ask(build_prompt(subject, body, source))):
        rec = {k: v for k, v in rec.items() if k in FIELDS}
        rec["source"] = source
        problem = verify(rec, lines, subject if source == "email" else "")
        (rejected.append({"record": rec, "reason": problem}) if problem else kept.append(rec))
    doc = {"message": message_id, "by": "model", "model": model or os.environ.get("LOOKOUT_EXTRACT_MODEL", "claude-sonnet-5-5"), "reviewed": False,
           "note": "proposed by the model; every entry below passed the price check. A person sets reviewed: true after reading it against the document.",
           "offers": kept}
    if rejected:
        doc["rejected"] = rejected
    out_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=140), encoding="utf-8")
    return target
