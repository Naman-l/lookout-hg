"""The supplier-risk category's rules (BUYER-F 12-right-solution §Supplier risk), proved on the seed and on changed data."""

from __future__ import annotations

from sqlalchemy import update

from app.domain.attention import findings
from app.domain.suppliers.model import SupplierRecord


def _keys(session, key):
    return {f.key: f for f in findings.candidates(session, key)}


# R4 · prepaid terms with a late supplier are a finding of their own: the open value is cash out before goods that are likely late

def test_r4_the_prepaid_late_supplier_carries_the_cash_at_risk_first(session):
    found = findings.candidates(session, "risk:SUP-0029")
    assert found[0].key == "cash_at_risk" and found[0].fact == "$2.91M open on 10 lines under 100% T/T before shipment, with a supplier on time on 26% of 43 lines"
    assert "cash_at_risk" not in _keys(session, "risk:SUP-0011") and "cash_at_risk" not in _keys(session, "risk:SUP-0002")   # late, but not paid ahead


def test_r4_on_changed_data_the_finding_follows_the_terms_on_record(db_path, tmp_path):
    import shutil

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    db = tmp_path / "changed.db"
    shutil.copy(db_path, db)
    eng = create_engine(f"sqlite:///{db}", future=True)
    with Session(eng) as s:
        s.execute(update(SupplierRecord).where(SupplierRecord.identity_id == "SUP-0029").values(prepay_pct=0, payment_terms_raw="Net 30"))
        s.execute(update(SupplierRecord).where(SupplierRecord.identity_id == "SUP-0011").values(prepay_pct=100, payment_terms_raw="100% T/T in advance"))
        s.commit()
    with Session(eng) as s:
        assert "cash_at_risk" not in _keys(s, "risk:SUP-0029")
        q = _keys(s, "risk:SUP-0011")["cash_at_risk"]
        assert "under 100% T/T in advance, with a supplier on time on 44% of 48 lines" in q.fact
    eng.dispose()


# R1 · any letter to a supplier in an insolvency procedure, or answering a supplier's notice, reserves the company's rights

LETTER = "Dear {name},\n\nPlease confirm the dates.\n\nPlease reply by 20 October.\n\nBest regards,\nPriya Nair"


def _style(db, key, name, recipient, subject="Open lines"):
    from app.domain.actions.letters import house_style

    return house_style(LETTER.format(name=name), db_path=db, item_key=key, subject=subject, company_short="Acme", recipient=recipient)


def test_r1_letters_to_an_insolvent_supplier_or_answering_a_notice_reserve_rights(db_path):
    assert "Nothing in this email waives any of Acme's rights under the agreement." in _style(db_path, "risk:SUP-0002", "Katrin Vogel", "katrin.vogel@hallerbeck-antriebe.example")
    for key, name, rec in (("disruption:SUP-0013", "Lin Yu-ting", "lin.yuting@jadepeak.example"), ("incident:SUP-0018", "Zhou Hui", "zhou.hui@ruilian-cable.example")):
        assert "accepts the notice or waives any of Acme's rights" in _style(db_path, key, name, rec, subject="Your notice: revised dates")
    assert "rights" not in _style(db_path, "risk:SUP-0029", "Xu Jia", "xu.jia@vistaray.example")              # late and prepaid, not insolvent, no notice answered
    once = _style(db_path, "risk:SUP-0002", "Katrin Vogel", "katrin.vogel@hallerbeck-antriebe.example")
    from app.domain.actions.letters import house_style
    assert house_style(once, db_path=db_path, item_key="risk:SUP-0002", subject="Open lines", company_short="Acme", recipient="katrin.vogel@hallerbeck-antriebe.example") == once


def test_r1_on_changed_data_the_reservation_follows_the_insolvency_record(db_path, tmp_path):
    import shutil
    import sqlite3

    db = tmp_path / "changed.db"
    shutil.copy(db_path, db)
    con = sqlite3.connect(db)
    con.execute("UPDATE events SET identity_id = 'SUP-0029' WHERE identity_id = 'SUP-0002' AND topic = 'insolvency'")   # the insolvency is reported about another supplier
    con.execute("UPDATE offers SET conditions = NULL WHERE identity_id = 'SUP-0002'")                                    # and the first one's quote no longer says so
    con.commit()
    con.close()
    assert "waives any of Acme's rights" in _style(db, "risk:SUP-0029", "Xu Jia", "xu.jia@vistaray.example")
    assert "rights" not in _style(db, "risk:SUP-0002", "Katrin Vogel", "katrin.vogel@hallerbeck-antriebe.example")
