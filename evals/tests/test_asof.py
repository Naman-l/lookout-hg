from evals import asof


def test_the_live_failure_is_caught():
    said = "Today is 10 October, so the 18-day figure looks stale."
    v = asof.violations([said], {18})
    assert any("2026-10-10" in x for x in v) and any("stale" in x for x in v)


def test_dates_that_are_not_claims_about_today_are_fine():
    ok = ["Yunzhan promised revised dates by 10 October.", "The lock ends on 2026-10-15; orders after 1 November pay more.",
          "Today is 25 September 2026.", "As of 2026-09-25 the shortage is 364.", "The quote expires October 13.",
          "As of 1 November the 25% duty applies.", "It is 15 October when the lock ends."]
    assert asof.violations(ok, {20}) == []


def test_other_ways_of_saying_today_are_caught():
    for said in ["As of today (2026-10-10) the order is late.", "It is now October 12 and nothing has arrived.", "Today (11 October) matters.",
                 "Current date: 3 October 2026", "10 October is today, so act now.", "The date today is 9 October."]:
        assert asof.violations([said]), said


def test_days_left_must_be_the_tools_number():
    assert asof.violations(["There are 20 days left."], {20}) == []
    assert asof.violations(["There are 18 days left."], {20})
    assert asof.violations(["Only 5 days remaining."], set())          # no tool figure: it is the agent's arithmetic
    assert asof.violations(["Revised dates are due in 14 days."], set()) == []   # not a days-left claim


def test_each_breach_is_listed_once():
    assert len(asof.violations(["Today is 10 October.", "Today is 10 October."])) == 1


def test_parse_handles_the_forms_the_model_uses():
    from datetime import date
    assert asof.parse("10 October") == date(2026, 10, 10) and asof.parse("Oct 10, 2026") == date(2026, 10, 10)
    assert asof.parse("2026-09-25") == asof.AS_OF and asof.parse("25th of September") == asof.AS_OF


def test_stale_orders_are_not_a_stale_clock():
    assert not asof.violations(["Three stale orders look stale and are probably closed."])
    assert asof.violations(["The 18-day figure looks stale."])
