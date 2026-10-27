"""The "Auto-imported on" note carries the household's date, not the container's.

Every parser stamped it from a bare `datetime.now()`, so a household ahead of
the container (or a UTC container behind the household) got yesterday's date.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.document_parsers import insurance
from app.utils import household_time
from app.utils.household_time import household_zone_var
from tests.unit.services.test_insurance_document_coverages import ALL_PARSERS, PAGE
from tests.unit.utils.test_pdf_header_time import frozen_at


@pytest.mark.parametrize("parser_class", ALL_PARSERS, ids=lambda c: c.PARSER_NAME)
def test_the_import_note_is_dated_in_the_household_zone(
    monkeypatch: pytest.MonkeyPatch, parser_class: type[insurance.InsuranceDocumentParser]
) -> None:
    # 23:30 UTC on the 15th is the 16th in Auckland.
    frozen = frozen_at(datetime(2026, 7, 15, 23, 30, tzinfo=UTC))
    monkeypatch.setattr(insurance, "datetime", frozen)
    monkeypatch.setattr(household_time, "datetime", frozen)
    token = household_zone_var.set(ZoneInfo("Pacific/Auckland"))
    try:
        notes = parser_class().parse_document(PAGE).notes
    finally:
        household_zone_var.reset(token)
    assert notes is not None
    assert "on 2026-07-16" in notes, notes
