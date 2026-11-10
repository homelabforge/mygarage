"""Reading standard coverages off a declarations page.

The coverage read matches PHRASES, not layouts, so it lives on the insurance
parser base class and every provider gets it. These tests pin that, and pin
the one thing the first cut got wrong: the document-wide read must come from
the page, never from a summary string another parser synthesised.
"""

from decimal import Decimal

import pytest

from app.services.document_parsers.insurance import (
    AllstateInsuranceParser,
    GeicoInsuranceParser,
    GenericInsuranceParser,
    ProgressiveInsuranceParser,
    StateFarmInsuranceParser,
)

RAM = "1C6SRFFT8MN123456"
MIRAGE = "ML32A3HJ0HH123457"

PAGE = f"""Policy Number: 868776469
Policy Period: 01/27/2026 to 07/27/2026
Total Premium: $2,082.00

VIN {RAM} 2021 Ram 1500
Bodily Injury Liability $100,000 each person/$300,000 each accident
Property Damage Liability $50,000 each accident
Comprehensive Actual Cash Value $1,000 $146.00
Roadside Assistance

VIN {MIRAGE} 2017 Mitsubishi Mirage
Bodily Injury Liability $25,000 each person/$50,000 each accident
Collision Actual Cash Value $500 $299.00
"""

ALL_PARSERS = [
    ProgressiveInsuranceParser,
    StateFarmInsuranceParser,
    GeicoInsuranceParser,
    AllstateInsuranceParser,
    GenericInsuranceParser,
]


def _by_key(coverages):
    return {c["coverage_key"]: c for c in coverages}


@pytest.mark.parametrize("parser_class", ALL_PARSERS, ids=lambda c: c.PARSER_NAME)
def test_every_provider_reads_the_coverages(parser_class):
    """It used to be one provider's private method; the other four returned
    nothing and the user re-typed thirteen coverages by hand."""
    data = parser_class().parse_document(PAGE)
    assert data.coverages, f"{parser_class.PARSER_NAME} read no coverages"
    assert "bodily_injury" in _by_key(data.coverages)


@pytest.mark.parametrize("parser_class", ALL_PARSERS, ids=lambda c: c.PARSER_NAME)
def test_the_document_read_never_invents_a_premium(parser_class):
    """THE REGRESSION. The document-wide coverages were taken from a summary
    string one parser built ("Bodily Injury: 100000/300000, Property Damage:
    50000"); re-parsing that prose put property damage's LIMIT into bodily
    injury's PREMIUM and dropped property damage entirely."""
    coverages = _by_key(parser_class().parse_document(PAGE).coverages)
    assert coverages["bodily_injury"]["premium"] is None
    assert "property_damage" in coverages
    assert coverages["property_damage"]["limit_primary"] == "50000"


def test_a_vehicle_with_a_section_gets_its_own_coverages():
    data = ProgressiveInsuranceParser().parse_document(PAGE)
    ram = _by_key(data.vehicle_coverages[RAM])
    mirage = _by_key(data.vehicle_coverages[MIRAGE])
    assert ram["bodily_injury"]["limit_primary"] == "100000"
    assert mirage["bodily_injury"]["limit_primary"] == "25000"
    # Each section stops at the next VIN, so neither takes the other's.
    assert "collision" not in ram
    assert "property_damage" not in mirage


def test_a_section_keeps_its_deductible_and_premium_columns():
    data = ProgressiveInsuranceParser().parse_document(PAGE)
    comprehensive = _by_key(data.vehicle_coverages[RAM])["comprehensive"]
    deductible, premium = comprehensive["deductible"], comprehensive["premium"]
    assert deductible is not None and premium is not None
    assert Decimal(deductible) == Decimal("1000")
    assert Decimal(premium) == Decimal("146.00")


def test_a_page_with_no_vin_sections_still_reads_document_coverages():
    """The fallback every vehicle on such a page is offered."""
    flat = "Bodily Injury Liability $100,000 each person\nRoadside Assistance"
    data = GenericInsuranceParser().parse_document(flat)
    assert set(_by_key(data.coverages)) == {"bodily_injury", "roadside_assistance"}
    assert data.vehicle_coverages == {}


def test_a_vehicle_whose_section_lists_none_is_not_given_anothers():
    """THE REGRESSION. The document-wide read is dominated by whichever
    vehicle the page listed first, so falling back for a vehicle that HAS a
    section would post the first vehicle's coverage against the second."""
    page = f"""VIN {RAM} 2021 Ram 1500
Collision $500 deductible

VIN {MIRAGE} 2017 Mitsubishi Mirage
Liability only, see endorsement
"""
    data = ProgressiveInsuranceParser().parse_document(page)
    assert "collision" in _by_key(data.vehicle_coverages[RAM])
    # Keyed, and empty: its own section is the answer for it.
    assert data.vehicle_coverages[MIRAGE] == []
