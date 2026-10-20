"""Carry-through: the conditions the offer tools returned are guaranteed to reach the answer, by code.

The model writes the words; code checks the answer against what compare_offers returned and, for each condition the answer left out (an insolvency
process, a prepayment, the Incoterm, a lead time, a validity date, an origin option and the date it can start, a minimum order, a surcharge), adds it
to one `Conditions` row in the tool's own words and figures. Every figure in such a row came from a tool, so the verifier's checks bind it. The same
tool output gives the same rows on every trial: they are sorted by id."""

from __future__ import annotations

import re


def conditions_from_compare(data: dict) -> dict[str, dict]:
    """{id: {"text", "tokens"}}: the conditions of each offer beside the current supplier, from a compare_offers result."""
    out: dict[str, dict] = {}
    part = data.get("part") or "?"
    for col in data.get("columns") or []:
        if col.get("current"):
            continue
        who, k = col.get("supplier") or "The supplier", col.get("key") or "offer"
        t = col.get("terms") or {}

        def add(name: str, text: str, tokens: list) -> None:
            out[f"cond:{part}:{k}:{name}"] = {"text": f"{who}: {text}", "tokens": [str(x).lower() for x in tokens if x]}

        if t.get("incoterm"):
            add("incoterm", f"{t['incoterm']}" + (f" {t['incoterm_place']}" if t.get("incoterm_place") else ""), [t["incoterm"]])
        lt = t.get("lead_time")
        if lt:
            add("lead_time", f"lead time {lt['text']}" + (f" ({lt['basis']})" if lt.get("basis") else ""), [lt["text"]])
        if t.get("valid_until"):
            add("valid_until", f"valid until {t.get('valid_until_words') or t['valid_until']}", [t["valid_until"], t.get("valid_until_words")])
        if t.get("prepayment"):
            add("prepayment", f"prepayment: {t['prepayment']}", ["prepay"])
        if t.get("payment_terms"):
            add("payment_terms", f"payment terms {t['payment_terms']}", [t["payment_terms"].split(" (")[0]])
        if t.get("moq"):
            add("moq", f"minimum order {t['moq']}", [re.sub(r"\D", "", t["moq"]) and t["moq"].split()[0]])
        if t.get("surcharge"):
            add("surcharge", f"surcharge {t['surcharge']['pct']}, {t['surcharge']['included']}", [t["surcharge"]["pct"], "surcharge"])
        o = t.get("origin") or {}
        if o.get("available_from"):
            add("origin_start", f"{o.get('claim') or o.get('iso') or 'another origin'} can start from {o.get('available_from_words') or o['available_from']}", [o["available_from"], o.get("available_from_words")])
        for i, c in enumerate(c for c in re.split(r"(?<=[.])\s+", col.get("conditions") or "") if c and not c.lower().startswith("last paid")):
            add(f"note{i}", c.rstrip("."), [])  # free text: mentioned when the answer shares most of its distinctive words
    return out


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zäöüß]{6,}", text.lower())}


def mentioned(condition: dict, answer_text: str) -> bool:
    a = answer_text.lower()
    if condition["tokens"]:
        return any(t in a for t in condition["tokens"])
    w = _words(condition["text"])
    return len(w & _words(a)) >= max(2, len(w) // 2)


def missing(conditions: dict[str, dict], answer_text: str) -> list[str]:
    """The text of each condition the answer does not carry, in id order, each text once: one supplier's clause read for several parts is one condition
    (BUYER: 'Quote the other four parts' repeated the same duty clause three times in Conditions)."""
    return list(dict.fromkeys(c["text"] for _, c in sorted(conditions.items()) if not mentioned(c, answer_text)))


def grouped(texts: list[str]) -> list[str]:
    """One entry per supplier: 'Acme: lead time 30 days; Acme: Net 60' becomes 'Acme: lead time 30 days; Net 60' (F105: say the name once)."""
    out: dict[str, list[str]] = {}
    for t in texts:
        who, _, what = t.partition(": ")
        out.setdefault(who if what else t, []).append(what or "")
    return [f"{who}: {'; '.join(dict.fromkeys(w for w in whats if w))}" if any(whats) else who for who, whats in out.items()]
