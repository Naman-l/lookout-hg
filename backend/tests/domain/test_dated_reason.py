"""AI-UI-SYNC M5: a recommended reason that says no date was given, on a case whose every line has the supplier's new date, drops that clause."""
from types import SimpleNamespace

from app.domain.attention.api import dated_reason


def _d(*dates):
    return SimpleNamespace(po_lines=[SimpleNamespace(revised_date=x) for x in dates])


def _a(reason):
    return {"finding": "x", "recommended": {"kind": "allocation", "reason": reason, "number_ids": ["n"]}}


def test_the_no_date_clause_goes_when_every_line_has_a_new_date():
    assert dated_reason(_d("2026-11-09", "2026-11-04"), _a("2 lines already past due; no date given"))["recommended"]["reason"] == "2 lines already past due"


def test_it_stays_when_a_line_has_no_new_date_or_the_reason_says_nothing_of_dates():
    for d, a in [(_d("2026-11-09", None), _a("2 lines already past due; no date given")), (_d(), _a("x; no date given")),
                 (_d("2026-11-09"), _a("only route that names a date")), (_d("2026-11-09"), None)]:
        assert dated_reason(d, a) == a
