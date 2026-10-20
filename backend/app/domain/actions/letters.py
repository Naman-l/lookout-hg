"""The house style of a supplier letter, applied in code before a draft's payload hash: when the clerk stages or amends one, and when a
recording is replayed, so the text a buyer signs is the same either way (BUYER R2 final). Nothing here adds a figure or a date:

- a quantity of a thousand or more reads with its thousands separator ("1,320 EA");
- a paragraph another item's ask added reads as its own paragraph, never "Also: Please also …";
- a part number in the text carries the part's name ("Corner bracket (<part number>)"), unless the name is already beside it;
- a letter answering a supplier's notice (a force majeure, a slip, an incident) keeps the reservation of rights: nothing in it accepts the notice or waives
  a right; a letter to a supplier in an insolvency procedure (its risk flags) reserves the rights too (BUYER R1);
- a letter to a contact on file opens with the contact's name, never "Dear <supplier> team,";
- a reply asked for by a date on or after the day a quote it names lapses is asked for a week before the lapse, so the answer can still be acted on;
- a letter to a supplier with a quote on file that lapses before the reply-by or within 14 days after it asks, once, that the quote hold (BUYER D5: a free ask
  in the same letter): "Please confirm that quote <no> holds past <its lapse date>." The quote number and its date are the record's, never the model's.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date, timedelta

_QTY = re.compile(r"\b(\d{4,})(?=\s*(?:EA|pcs|pieces|units)\b)")
_ALSO = re.compile(r"(^|\n\n)Also:\s*(\w)", re.I)
_PLEASE_ALSO = re.compile(r"(^|\n\n)Please also\s+", re.I)
_WAIVE = re.compile(r"\bwaiv", re.I)
_TEAM = re.compile(r"^(\s*)Dear [^,\n]+ team,")
_MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
_DAY_MONTH = r"(\d{1,2}) (" + "|".join(_MONTH_NAMES) + r")"
_LAPSE = re.compile(r"\blapses? on " + _DAY_MONTH)
_REPLY_BY = re.compile(r"\b(Please reply by )" + _DAY_MONTH)


def _reply_before_lapse(text: str) -> str:
    """'Please reply by 31 October' in a letter whose quote lapses on 31 October asks for the answer on 24 October, a week before (BUYER 02)."""
    lapse, ask = _LAPSE.search(text), _REPLY_BY.search(text)
    if not lapse or not ask:
        return text
    day = lambda d, m: date(2001, _MONTH_NAMES.index(m) + 1, int(d))  # noqa: E731  a year with no 29 February: only the day and month are compared
    by, lapses = day(ask.group(2), ask.group(3)), day(lapse.group(1), lapse.group(2))
    if by < lapses:
        return text
    new = lapses - timedelta(days=7)
    return text[:ask.start()] + f"{ask.group(1)}{new.day} {_MONTH_NAMES[new.month - 1]}" + text[ask.end():]


LAPSE_WINDOW_DAYS = 14


def _lapsing_quotes(db_path, recipient: str, reply_by: date) -> list[tuple[str, date]]:
    """(quote number, lapse date) for each quote on file from the recipient's supplier that lapses from the data date up to 14 days after the reply-by."""
    if not db_path or not recipient:
        return []
    from app.domain.common import AS_OF  # noqa: PLC0415

    con = sqlite3.connect(str(db_path), timeout=30)
    try:
        rows = con.execute("SELECT DISTINCT o.quote_no, o.validity_date FROM offers o JOIN supplier_records r ON r.identity_id = o.identity_id "
                           "WHERE lower(r.contact_email) = lower(?) AND o.quote_no IS NOT NULL AND o.quote_no != '' AND o.validity_date IS NOT NULL", (recipient,)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    out = []
    for no, valid in rows:
        try:
            lapse = date.fromisoformat(valid[:10])
        except ValueError:
            continue
        if AS_OF <= lapse <= reply_by + timedelta(days=LAPSE_WINDOW_DAYS):
            out.append((no, lapse))
    return sorted(out, key=lambda x: (x[1], x[0]))


def _quote_hold_ask(text: str, db_path, recipient: str) -> str:
    """One ask per lapsing quote the letter does not already name, placed before the sign-off."""
    from app.domain.common import AS_OF  # noqa: PLC0415

    from .tools import insert_before_signoff  # noqa: PLC0415

    ask = _REPLY_BY.search(text)
    if not ask:
        return text
    by = date(AS_OF.year, _MONTH_NAMES.index(ask.group(3)) + 1, int(ask.group(2)))
    if by < AS_OF:      # "Please reply by 5 January" written in the autumn is next year's
        by = date(AS_OF.year + 1, by.month, by.day)
    for no, lapse in _lapsing_quotes(db_path, recipient, by):
        if no in text:
            continue
        line = f"Please confirm that quote {no} holds past {lapse.day} {_MONTH_NAMES[lapse.month - 1]}."
        paras = text.split("\n\n")
        at = next((i for i, p in enumerate(paras) if _REPLY_BY.search(p)), None)      # the asks come before the reply-by, so the letter ends on its date
        text = "\n\n".join([*paras[:at], line, *paras[at:]]) if at is not None else insert_before_signoff(text, line)
    return text


def _contact_name(db_path, recipient: str) -> str | None:
    if not db_path or not recipient:
        return None
    con = sqlite3.connect(str(db_path), timeout=30)
    try:
        r = con.execute("SELECT contact_name FROM supplier_records WHERE lower(contact_email) = lower(?) AND contact_name IS NOT NULL AND contact_name != '' LIMIT 1", (recipient,)).fetchone()
        return r[0].strip() if r else None
    except sqlite3.Error:
        return None
    finally:
        con.close()


def reservation(company_short: str, notice: bool = True) -> str:
    if not notice:
        return f"Nothing in this email waives any of {company_short}'s rights under the agreement."
    return f"Nothing in this email accepts the notice or waives any of {company_short}'s rights under the agreement."


def _insolvent(db_path, recipient: str) -> bool:
    """The recipient's supplier carries an insolvency flag (its own quote or the news says so), read through the one risk rule."""
    if not db_path or not recipient:
        return False
    from sqlalchemy import create_engine, select  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    from app.domain.suppliers.model import SupplierRecord  # noqa: PLC0415
    from app.domain.suppliers.risk import risk_flags  # noqa: PLC0415

    eng = create_engine(f"sqlite:///{db_path}", future=True)
    try:
        with Session(eng) as s:
            ident = s.scalar(select(SupplierRecord.identity_id).where(SupplierRecord.contact_email.ilike(recipient)).limit(1))
            return bool(ident) and any(f.kind == "insolvency" for f in risk_flags(s, ident))
    except Exception:  # noqa: BLE001  no build to read the flags from: the text stays as written
        return False
    finally:
        eng.dispose()


def _names(db_path, ids: set[str]) -> dict[str, str]:
    if not ids or not db_path:
        return {}
    from app.domain import naming  # noqa: PLC0415

    con = sqlite3.connect(str(db_path), timeout=30)
    try:
        marks = ",".join("?" * len(ids))
        return {r[0]: naming.part_name(r[1]) for r in con.execute(f"SELECT part_number, description FROM parts WHERE part_number IN ({marks})", sorted(ids)) if r[1]}
    except sqlite3.Error:
        return {}
    finally:
        con.close()


def _named_parts(db_path, body: str) -> str:
    from app.organism import id_shapes  # noqa: PLC0415

    try:
        shape = id_shapes.pattern(db_path, "part")
    except Exception:  # noqa: BLE001  no build to read the shapes from: the text stays as written
        return body
    names = _names(db_path, set(shape.findall(body)))

    def name_it(m: re.Match) -> str:
        pid, name = m.group(0), names.get(m.group(0))
        before = body[max(0, m.start() - 80):m.start()].lower()
        if not name or name.split(",")[0].lower() in before:  # the name already sits beside it
            return pid
        return f"{name} ({pid})" if body[m.start() - 1:m.start()] != "(" else pid
    return shape.sub(name_it, body)


def house_style(body: str, *, db_path=None, item_key: str = "", subject: str = "", company_short: str = "", recipient: str = "") -> str:
    from .tools import insert_before_signoff  # noqa: PLC0415

    text = _QTY.sub(lambda m: f"{int(m.group(1)):,}", body or "")
    text = _ALSO.sub(lambda m: f"{m.group(1)}{m.group(2).upper()}", text)
    text = _PLEASE_ALSO.sub(lambda m: f"{m.group(1)}Please ", text)
    text = _named_parts(db_path, text)
    name = _contact_name(db_path, recipient) if _TEAM.match(text) else None
    if name:
        text = _TEAM.sub(lambda m: f"{m.group(1)}Dear {name},", text, count=1)
    text = _reply_before_lapse(text)
    text = _quote_hold_ask(text, db_path, recipient)
    answers_notice = item_key.startswith(("disruption:", "incident:")) and re.search(r"\b(force majeure|notice)\b", f"{subject} {text}", re.I)
    if company_short and not _WAIVE.search(text) and (answers_notice or _insolvent(db_path, recipient)):
        text = insert_before_signoff(text, reservation(company_short, notice=bool(answers_notice)))
    return text
