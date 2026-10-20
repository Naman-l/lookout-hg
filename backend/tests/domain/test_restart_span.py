"""The supplier's restart estimate is a range counted from the notice, not a date that moved."""
from __future__ import annotations

from app.domain.inbox import service as inbox

FIRE_NOTICE = "2026-09-22_NOTICE_OF_FORCE_MAJEURE_-_Shenzhen_Yunzhan_Precision_Motor_Co_Ltd"


def test_the_range_is_counted_from_the_notice_date_in_the_suppliers_words():
    assert inbox._restart_span("fire on 2026-09-18; partial production resumes in 6 to 8 weeks (the supplier's words)", "2026-09-22") == "Nov 3 – Nov 17 (6 to 8 weeks)"
    assert inbox._restart_span("partial production resumes in 2 to 4 weeks", "2026-01-05T09:00") == "Jan 19 – Feb 2 (2 to 4 weeks)"


def test_no_range_without_the_words_or_the_date():
    assert inbox._restart_span("a fire stopped deliveries", "2026-09-22") is None
    assert inbox._restart_span("partial production resumes in 6 to 8 weeks", None) is None


def test_the_fire_notice_shows_a_partial_restart_range_not_a_before_and_after(session):
    changes = inbox.message_detail(session, FIRE_NOTICE).changes
    restart = [c for c in changes if c.label == "Partial restart"]
    assert len(restart) == 1 and restart[0].before is None and restart[0].after == "Nov 3 – Nov 17 (6 to 8 weeks)"
    assert not [c for c in changes if c.label == "Recovery estimate"]
