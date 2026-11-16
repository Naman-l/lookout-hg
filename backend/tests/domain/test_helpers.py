from datetime import date

import pytest

from app.domain.imports import helpers as h


def test_sap_dates_and_a_stop_on_anything_else():
    assert h.parse_dmy("20.10.2026") == h.parse_dmy("20/10/2026") == h.parse_dmy("2026-10-20") == date(2026, 10, 20)
    assert h.parse_dmy("  ") is None
    with pytest.raises(ValueError):
        h.parse_dmy("Oct 20")


def test_sheet_numbers_accounting_zero_and_excel_errors():
    assert h.parse_number("  51,485 ") == 51485 and h.parse_number("1,00,00,000") == 1e7 and h.parse_number("(2,500)") == -2500
    assert h.parse_number("  -   ") is None and h.parse_number("") is None
    with pytest.raises(ValueError):
        h.parse_number("#DIV/0!")


@pytest.mark.parametrize("raw,unit,want", [
    ("2.64 Cr", "rupee", (26_400_000, "cr")), ("45 L", "cr", (4_500_000, "lakh")), ("1.5 Lakh", "rupee", (150_000, "lakh")),
    ("23,50,000", "cr", (2_350_000, "rupee")), ("12.5", "cr", (125_000_000, "cr")), ("8,500", "rupee", (8_500, "rupee")), ("", "cr", (None, "")),
])
def test_amounts_in_rupees_lakh_and_crore(raw, unit, want):
    got = h.parse_inr(raw, unit)
    assert (round(got[0]) if got[0] is not None else None, got[1]) == want


def test_an_unreadable_amount_stops_the_build():
    with pytest.raises(ValueError):
        h.parse_inr("about 3 crore")


def test_indian_digit_grouping():
    assert h.in_group(12345678) == "1,23,45,678" and h.in_group(999) == "999" and h.in_group(-150000) == "-1,50,000"


def test_the_export_stamp_and_the_date_in_a_sheet_name():
    s = h.parse_export_stamp("ME2N - Purchasing Documents per Document Number | Exported 20.10.2026 08:15:09 | User JDOE | Variant /SCM")
    assert s == {"title": "ME2N - Purchasing Documents per Document Number", "exported_at": "2026-10-20T08:15:09", "user": "JDOE"}
    assert h.parse_export_stamp("no stamp here")["exported_at"] is None
    assert h.stamp_in_name("SCM Fund Requirement November-26 (16.10.26).csv") == date(2026, 10, 16) and h.stamp_in_name("Project Directory.csv") is None


def test_names_compared_loosely_and_months_as_sheets_write_them():
    assert h.norm_name("M/s. Acme Rail Fittings Pvt. Ltd.") == h.norm_name("ACME RAIL FITTINGS PRIVATE LIMITED") == "acme rail fittings"
    assert h.month_label("Oct'26") == h.month_label("October-26") == "2026-10" and h.month_label("Nov''26") == "2026-11" and h.month_label("Total") is None
    assert h.slug("UPPTCL Mirzapur-Chunar") == "upptcl-mirzapur-chunar"
