"""The all-time on-time share hides a supplier getting worse (LOOKOUT pain-patterns): the record also carries the latest 10 receipts and, when the
latest receipts are late in a row, the streak and this year's late share against last year's, the figures LOOKOUT's scripts read from the same lines."""

from app.domain.suppliers.service import delivery_performance


def test_the_streak_is_on_the_suppliers_getting_worse_and_matches_the_receipts(session):
    dp = delivery_performance(session)
    y = dp["SUP-0001"]
    assert round(y.on_time_pct * 100) == 70 and (y.last10_on_time, y.last10_n) == (1, 10)       # 70% all-time, 1 of its last 10 on time
    s = y.streak
    assert (s.late_in_row, s.first, s.last, s.min_days_late, s.max_days_late) == (9, "2026-05-06", "2026-08-19", 8, 26)
    assert (s.late_this_year, s.n_this_year, s.late_last_year, s.n_last_year) == (11, 17, 4, 33)
    assert s.line == "Last 9 receipts late · 65% late in 2026 (12% in 2025)"
    assert dp["SUP-0013"].streak.late_in_row == 5 and dp["SUP-0029"].streak.late_in_row == 7 and dp["SUP-0002"].streak.late_in_row == 10
    assert sorted(k for k, v in dp.items() if v.streak) == ["SUP-0001", "SUP-0002", "SUP-0013", "SUP-0029"]       # Quenvara (44% all-time) has no run: plain on-time stays
