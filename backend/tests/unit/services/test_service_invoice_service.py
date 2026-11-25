"""`service_invoice_service`: a workshop invoice's as-printed answer → a draft visit.

The model answers are shaped on what qwen2.5:7b returned for a real
23-line South African tax invoice: the totals right, the line ``amount``
copied from the Total column (with VAT) despite the prompt, and one line's
unit price taken from the line below it.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pymupdf

from app.services import service_invoice_service as svc

TODAY = date(2026, 11, 4)
VENDORS = [(1, "Unlimited Auto (ANGRi)"), (4, "Foximoto (Pty) Ltd"), (7, "Shell Ultra City")]


def dec(value: str) -> Decimal:
    return Decimal(value)


def _line(desc, qty, price, amount, kind="part"):
    return {
        "description": desc,
        "quantity": qty,
        "unit_price": price,
        "amount": amount,
        "kind": kind,
    }


# Line amounts WITH 15 % VAT, as the model returned them; the third line's
# unit price is the next line's (the model's real mistake).
TAX_INCLUSIVE = {
    "invoice_number": "INV18499",
    "date": "19/11/2025",
    "vendor_name": "Unlimited Auto ANGRi",
    "odometer": "112,625km",
    "odometer_unit": "km",
    "currency": "zar",
    "subtotal": 103804.3,  # wrong on purpose: the model's own subtotal is not used
    "tax_amount": 2310.13,
    "total": 17710.97,
    "line_items": [
        _line("Attend to Engine not Starting", 1, 10000, 11500, "labour"),
        _line("Engine Oil to Spec", 6, 160, 1104),
        _line("Chain kit & sprockets", 1, 730.48, 3887.45),
        _line("Conversion Gasket Set", 1, 730.48, 840.05),
        _line("Spark plug", 6, 52.13, 359.70),
        {
            "description": "Recondition Cylinder Heads",
            "quantity": None,
            "unit_price": None,
            "amount": 19.77,
            "kind": "sublet",
        },
    ],
}


class TestNumbersAndDates:
    def test_numbers_as_printed(self):
        assert svc._number("R1 913.00") == dec("1913.00")
        assert svc._number("112,625km") == dec("112625")
        assert svc._number("1.234,56") == dec("1234.56")
        assert svc._number(0.33) == dec("0.33")
        assert svc._number(True) is None
        assert svc._number("n/a") is None

    def test_iso_and_month_names(self):
        assert svc.parse_date("2025-11-19", today=TODAY) == date(2025, 11, 19)
        assert svc.parse_date("Oct 13, 2025", today=TODAY) == date(2025, 10, 13)
        assert svc.parse_date("19 November 2025", today=TODAY) == date(2025, 11, 19)

    def test_numeric_dates_settled_by_the_digits(self):
        assert svc.parse_date("19/11/2025", month_first=True, today=TODAY) == date(2025, 11, 19)
        assert svc.parse_date("11/19/2025", today=TODAY) == date(2025, 11, 19)

    def test_ambiguous_numeric_dates_follow_the_order_asked(self):
        assert svc.parse_date("05-10-2026", today=TODAY) == date(2026, 10, 5)
        assert svc.parse_date("05-10-2026", month_first=True, today=TODAY) == date(2026, 5, 10)

    def test_a_date_in_the_future_is_a_misread(self):
        assert svc.parse_date("05-12-2026", today=TODAY) is None
        assert svc.parse_date("rubbish", today=TODAY) is None


class TestVendor:
    def test_company_suffixes_and_brackets_do_not_matter(self):
        assert svc.match_vendor("FOXIMOTO (PTY) LTD", VENDORS) == 4
        assert svc.match_vendor("Unlimited Auto ANGRi", VENDORS) == 1

    def test_no_match_or_a_tie_is_none(self):
        assert svc.match_vendor("Midas Tokai", VENDORS) is None
        assert svc.match_vendor(None, VENDORS) is None
        assert svc.match_vendor("Auto", [(1, "Auto One"), (2, "Auto Two")]) is None


class TestLines:
    def test_a_wrapped_description_joins_its_line(self):
        lines = svc._lines(
            [
                _line(
                    "air filter fitment, brake fluid replacement and bleeding of brakes,",
                    1.5,
                    598,
                    897,
                ),
                {
                    "description": "fitment of chain adjuster bolt",
                    "quantity": None,
                    "unit_price": None,
                    "amount": None,
                },
            ]
        )
        assert len(lines) == 1
        assert lines[0].description.endswith("brakes, fitment of chain adjuster bolt")

    def test_zero_lines_of_a_job_card_are_dropped(self):
        lines = svc._lines([_line("Road Test Vehicle", 0, 0, 0), _line("Oil", 1, 100, 100)])
        assert [line.description for line in lines] == ["Oil"]


class TestReconcile:
    def test_lines_before_tax_are_kept(self):
        lines = svc._lines([_line("A", 1, 100, 100), _line("B", 2, 50, 100)])
        rec = svc.reconcile(lines, subtotal=None, tax=dec("30"), total=dec("230"))
        assert rec.costs == [dec("100.00"), dec("100.00")]
        assert rec.tax_amount == dec("30.00")
        assert rec.warnings == []

    def test_no_tax_invoice(self):
        lines = svc._lines(
            [_line("air filter incl. oil", 1, 440, 440), _line("brake fluid", 0.33, 550, 181.5)]
        )
        rec = svc.reconcile(lines, subtotal=dec("621.5"), tax=None, total=dec("621.5"))
        assert rec.costs == [dec("440.00"), dec("181.50")]
        assert rec.tax_amount is None

    def test_quantity_times_price_when_amount_is_the_wrong_column(self):
        lines = svc._lines([_line("A", 2, 50, 999), _line("B", 1, 100, 999)])
        rec = svc.reconcile(lines, subtotal=None, tax=dec("30"), total=dec("230"))
        assert rec.costs == [dec("100.00"), dec("100.00")]

    def test_tax_inclusive_lines_lose_the_tax_to_the_cent(self):
        draft, warnings = svc.build_draft(TAX_INCLUSIVE, vendors=VENDORS, today=TODAY)
        costs = [line["cost"] for line in draft["line_items"]]
        assert warnings == []
        assert draft["tax_amount"] == dec("2310.13")
        assert sum(costs) + draft["tax_amount"] == dec("17710.97")
        # Lines whose quantity × price agrees take it exactly...
        assert costs[0] == dec("10000.00")
        assert costs[1] == dec("960.00")
        assert costs[3] == dec("730.48")
        # ...and the rounding lands on the line whose unit price was misread.
        assert costs[2] == dec("3380.39")

    def test_a_misread_line_is_a_warning_with_the_difference(self):
        lines = svc._lines([_line("A", 1, 100, 100), _line("B", None, None, 72.5)])  # B is 100
        rec = svc.reconcile(lines, subtotal=None, tax=dec("30"), total=dec("230"))
        assert rec.costs == [dec("100.00"), dec("72.50")]
        assert len(rec.warnings) == 1
        assert "(-27.50)" in rec.warnings[0]
        assert rec.tax_amount == dec("30.00")


class TestReconcileFallback:
    def test_a_missed_line_on_a_tax_inclusive_invoice_moves_no_money(self):
        # 3 × 100 before 15 % VAT; the model copied the Total column and missed C.
        lines = svc._lines([_line("A", 1, 100, 115), _line("B", 2, 50, 115)])
        rec = svc.reconcile(lines, subtotal=None, tax=dec("45"), total=dec("345"))
        assert rec.costs == [dec("100.00"), dec("100.00")]
        assert rec.tax_amount == dec("45.00")
        assert "(-100.00)" in rec.warnings[0]

    def test_a_misread_unit_price_falls_back_to_the_amount_less_tax(self):
        lines = svc._lines(
            [_line("A", 1, 100, 115), _line("B", 1, 100, 115), _line("C", 1, 7, 230)]
        )  # C really 200 before tax; one line (D, 100) missed
        rec = svc.reconcile(lines, subtotal=None, tax=dec("75"), total=dec("575"))
        assert rec.costs == [dec("100.00"), dec("100.00"), dec("200.00")]
        assert "(-100.00)" in rec.warnings[0]


class TestDraft:
    def test_visit_fields(self):
        draft, _ = svc.build_draft(TAX_INCLUSIVE, vendors=VENDORS, today=TODAY)
        assert draft["date"] == date(2025, 11, 19)
        assert draft["odometer_km"] == dec("112625")
        assert draft["vendor_id"] == 1
        assert draft["currency"] == "ZAR"
        assert draft["total"] == dec("17710.97")
        assert draft["invoice_number"] == "INV18499"
        assert draft["notes"] is None

    def test_line_notes_carry_kind_and_a_quantity_that_agrees(self):
        draft, _ = svc.build_draft(TAX_INCLUSIVE, vendors=VENDORS, today=TODAY)
        notes = [line["notes"] for line in draft["line_items"]]
        assert notes[0] == "Labour"
        assert notes[1] == "Part, 6 × 160.00"

    def test_miles_are_converted(self):
        draft, _ = svc.build_draft(
            {"odometer": 10000, "odometer_unit": "mi", "line_items": []}, vendors=[], today=TODAY
        )
        assert draft["odometer_km"] == dec("16093")

    def test_nothing_read_is_a_warning_not_an_error(self):
        draft, warnings = svc.build_draft({}, vendors=[], today=TODAY)
        assert draft["line_items"] == []
        assert "No lines were read from the invoice." in warnings

    def test_long_descriptions_fit_the_column(self):
        draft, _ = svc.build_draft(
            {"line_items": [_line("x" * 500, 1, 1, 1)], "total": 1}, vendors=[], today=TODAY
        )
        assert len(draft["line_items"][0]["description"]) == svc.DESCRIPTION_MAX


class TestLayoutText:
    def test_a_table_row_stays_on_one_line(self):
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((40, 100), "1", fontsize=10)
        page.insert_text((80, 100), "Water Pump", fontsize=10)
        page.insert_text((300, 100), "R2 795.50", fontsize=10)
        page.insert_text((450, 100), "R3 214.82", fontsize=10)
        page.insert_text((40, 120), "6", fontsize=10)
        page.insert_text((80, 120), "Spark plug", fontsize=10)
        page.insert_text((300, 120), "R273.70", fontsize=10)
        data = doc.tobytes()
        doc.close()
        text = svc.layout_text(data)
        assert text.splitlines() == [
            "1  |  Water Pump  |  R2 795.50  |  R3 214.82",
            "6  |  Spark plug  |  R273.70",
        ]
