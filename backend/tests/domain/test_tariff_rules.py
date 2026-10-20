"""The duty category's rules (BUYER-F 12-right-solution §Tariff), proved on the seed and on changed data: the route reads the offers on file, never a part."""

from __future__ import annotations

from sqlalchemy import select, update

from app.domain.attention import option_kinds
from app.domain.quotes.model import Offer


def _duty(session, owner=None):
    return option_kinds.option_kinds(session, "tariff:all", owner)


# T2 · an offer on file from another origin that lands cheaper than China with the duty is the alternate-origin route, linked and ranked above the exclusion

def test_t2_the_alternate_origin_names_and_links_the_cheaper_quote(session):
    kinds = [o.kind for o in _duty(session)]
    sw = next(o for o in _duty(session) if o.kind == "switch_origin")
    assert kinds.index("switch_origin") < kinds.index("broker_exclusion")
    assert sw.label == "Alternate origin · Quenvara (HR-50110)" and "$1,224.52 landed vs $1,421.40 with the duty" in sw.changes        # the largest duty first
    assert any(r.type == "message" and "Malaysia_option" in r.id for r in sw.refs)
    dana = next(o for o in _duty(session, "Dana Reyes") if o.kind == "switch_origin")
    assert dana.label == "Alternate origin · Vinh Phuc (HR-40110)" and dana.changes.startswith("HR-40110: Vinh Phuc $160.87 landed vs $188.99 with the duty")
    assert any("VPM-Q-260924" in r.id for r in dana.refs)


def test_t2_on_changed_data_a_dearer_alternate_drops_out_and_none_left_puts_the_exclusion_first(session):
    try:
        session.execute(update(Offer).where(Offer.quote_no == "VPM-Q-260924").values(unit_price_each=400.0, price=400.0))   # Vinh Phuc now dearer than China with the duty
        session.flush()
        dana = next(o for o in _duty(session, "Dana Reyes") if o.kind == "switch_origin")
        assert "HR-40110" not in dana.changes and "Vinh Phuc" not in dana.label
        others = [o.id for o in session.scalars(select(Offer)) if (o.origin_iso or "") != "CN"]
        session.execute(update(Offer).where(Offer.id.in_(others)).values(origin_iso="CN", origin_claim="China"))           # every quote on file is China-origin
        session.flush()
        kinds = [o.kind for o in _duty(session)]
        sw = next(o for o in _duty(session) if o.kind == "switch_origin")
        assert sw.label == "Alternate origin" and not sw.refs and kinds.index("switch_origin") == kinds.index("broker_exclusion") + 1
    finally:
        session.rollback()


# T3 · duty on lines that cannot ship before the duty starts is fixed: budgeting it is started beside the chosen route, with the records' reason

def test_t3_the_fixed_duty_makes_budgeting_an_also_start_for_its_owner(session):
    dana = {o.kind: o for o in _duty(session, "Dana Reyes")}
    assert dana["accept"].also_start and dana["accept"].also_why == "$85K is owed on lines that cannot ship before Nov 1"
    assert not any(o.also_start for o in _duty(session, "Priya Nair") if o.kind == "accept")          # no fixed share of hers
    assert {o.kind: o for o in _duty(session)}["accept"].also_start                                    # the team view: the duty owed on lines that cannot ship


def test_t3_on_changed_figures_the_also_start_follows_the_fixed_share(session, monkeypatch):
    from decimal import Decimal

    from app.domain.attention import service

    real = service.item_detail

    def changed(s, key):
        d = real(s, key)
        if key != "tariff:all" or d is None:
            return d
        nums = []
        for n in d.numbers:
            if n.id == "duty_share_fixed:Dana":
                n = n.model_copy(update={"value": n.value.model_copy(update={"usd": Decimal("12345.00"), "amount": Decimal("12345.00")}), "label": n.label.replace("Nov 1", "Dec 1")})
            nums.append(n)
        return d.model_copy(update={"numbers": nums})

    monkeypatch.setattr(service, "item_detail", changed)
    assert {o.kind: o for o in _duty(session, "Dana Reyes")}["accept"].also_why == "$12K is owed on lines that cannot ship before Dec 1"
