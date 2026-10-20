from decimal import Decimal

import pytest

from app.domain.imports import helpers as h


@pytest.mark.parametrize("raw,want", [("HR51110", "HR-51110"), (" hr-51110 ", "HR-51110"), ("HR-5O110", "HR-50110"), ("HR 51110", "HR-51110"), ("XYZ", "XYZ")])
def test_part_number(raw, want, monkeypatch):
    monkeypatch.setitem(h.PART_FORMAT, "prefix", "HR-")      # the format is the recipe's, not the code's
    monkeypatch.setitem(h.PART_FORMAT, "digits", 5)
    assert h.norm_part_number(raw) == want


def test_country_spellings_and_stop_on_unknown():
    assert {h.iso_country(x) for x in ["CN", "China", "PRC", "P.R. China", "China (PRC)"]} == {"CN"}
    assert h.iso_country("") is None
    with pytest.raises(ValueError):
        h.iso_country("Atlantis")


def test_hts_formats_and_letter_o():
    assert h.hts_digits("8504.40.9580") == ("8504409580", False)
    assert h.hts_digits("85O4.40.9580") == ("8504409580", True)
    assert h.hts_digits("731815") == ("731815", False)
    assert h.hts_digits("") == (None, False)


def test_payment_terms():
    assert h.parse_payment_terms("NET60")["label"] == "Net 60"
    assert h.parse_payment_terms("Net 45 days")["net_days"] == 45
    assert h.parse_payment_terms("Cash in advance")["prepay_pct"] == 100
    assert h.parse_payment_terms("30% deposit, balance before shipment")["prepay_pct"] == 30


def test_incoterm_split():
    assert h.split_incoterm("FOB SZ") == ("FOB", "Shenzhen")
    assert h.split_incoterm("EXW") == ("EXW", None)
    assert h.split_incoterm("") == (None, None)


def test_units():
    assert h.norm_uom("Each") == "EA" and h.norm_uom("pcs") == "EA"
    assert h.to_part_unit(9, "KPCS") == (9000.0, "EA")
    assert h.to_part_unit(1000, "FT")[1] == "M"
    assert h.to_part_unit(10, "BOX") is None


def test_dates_and_numbers():
    assert h.parse_date_any("12/04/2024").isoformat() == "2024-12-04"
    assert h.parse_date_any("2026-09-25").isoformat() == "2026-09-25"
    assert h.parse_date_any("") is None
    assert h.parse_number("389,50", ",") == Decimal("389.50")
    assert h.parse_number("1.234,50", ",") == Decimal("1234.50")
