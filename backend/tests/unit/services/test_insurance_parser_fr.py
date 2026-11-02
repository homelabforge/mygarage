"""The French motor insurance parser, the formula classifier and the vision
model's field mapping (#211).

The avis d'échéance below is synthetic, in the shape a French insurer's
renewal notice flattens to: the insurer in the header, the contract number,
the period « du … au … », the formula, the bonus-malus coefficient, a table
of garanties with their franchises and plafonds, the annual cotisation and
the monthly instalment, and the plate (never the VIN).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.document_parsers.insurance import (
    classify_formula,
    clean_plate,
    from_llm_fields,
    plates_in,
)
from app.services.document_parsers.insurance_fr import FrenchInsuranceParser, fr_date
from app.services.document_parsers.registry import DocumentParserRegistry

AVIS_ECHEANCE = """MAIF
Avis d'échéance
Contrat n° 1234567 A
Sociétaire : M. Jean DUPONT
Véhicule assuré : RENAULT ZOE
Immatriculation : AB-123-CD
Date de première mise en circulation : 12/03/2023
Période de garantie : du 01/01/2026 au 31/12/2026
Formule : Tiers étendu
Coefficient de réduction-majoration (bonus-malus) : 0,50
Garanties souscrites
Responsabilité civile : illimitée
Défense pénale et recours : plafond 20 000 €
Garantie du conducteur : plafond 1 000 000 €
Bris de glace : franchise 80 €
Vol et tentative de vol : franchise 300 €
Incendie : franchise 300 €
Catastrophes naturelles : franchise 380 €
Dommages tous accidents : non souscrite
Assistance 0 km : incluse
Véhicule de remplacement : 15 jours
Franchise : 300 €
Cotisation annuelle TTC : 612,40 €
Payable mensuellement : 51,03 € / mois
Assistance assurée par Mondial Assistance
"""

PROGRESSIVE = """Progressive Insurance
Mayfield Village, OH 44143
Policy: Auto 9876543210
Policy period August 26, 2025 - February 26, 2026
Total policy premium $612.00
Bodily Injury Liability $100,000 each person/$300,000 each accident
Comprehensive $500 deductible
Collision $500 deductible
"""


@pytest.fixture
def parser() -> FrenchInsuranceParser:
    return FrenchInsuranceParser()


@pytest.mark.unit
class TestCanParse:
    def test_a_french_notice_is_recognised(self, parser):
        assert parser.can_parse(AVIS_ECHEANCE)

    def test_a_progressive_page_is_not(self, parser):
        assert not parser.can_parse(PROGRESSIVE)

    def test_a_carte_grise_is_not(self, parser):
        text = "CERTIFICAT D'IMMATRICULATION\nA AB-123-CD\nB 12/03/2023\nD.1 RENAULT\nE VF1RFB00X56123456"
        assert not parser.can_parse(text)

    def test_the_registry_detects_it_after_the_named_insurers(self):
        assert isinstance(
            DocumentParserRegistry.detect_insurance_parser(AVIS_ECHEANCE), FrenchInsuranceParser
        )
        assert DocumentParserRegistry.detect_insurance_parser(PROGRESSIVE).PARSER_NAME == (
            "Progressive"
        )
        assert DocumentParserRegistry.get_insurance_parser("french").PARSER_NAME == (
            "FrenchInsurance"
        )


@pytest.mark.unit
class TestAvisEcheance:
    def test_every_field_is_read(self, parser):
        data = parser.parse_document(AVIS_ECHEANCE)
        assert data.provider == "MAIF"
        assert data.policy_number == "1234567"
        assert (data.start_date, data.end_date) == ("2026-01-01", "2026-12-31")
        assert data.premium_amount == Decimal("612.40")
        # The cotisation line says « annuelle »; the instalment line is not
        # the premium's own line, so it does not make the frequency monthly.
        assert data.premium_frequency == "Annual"
        assert data.deductible == Decimal("300")
        assert data.policy_type == "Third Party Extended"
        assert data.no_claims_class == "0.50"
        assert data.plates_found == ["AB-123-CD"]
        assert data.vehicles_found == []
        assert data.field_confidence["dates"] == "high"
        assert data.field_confidence["policy_number"] == "high"
        assert data.field_confidence["no_claims_class"] == "high"
        assert "No VINs" not in " ".join(data.get_validation_warnings())
        assert data.confidence_score >= 60

    def test_the_garanties_land_on_the_catalogue(self, parser):
        data = parser.parse_document(AVIS_ECHEANCE)
        by_key = {item["coverage_key"]: item for item in data.coverages}
        assert list(by_key) == [
            "glass",
            "third_party_liability",
            "driver_protection",
            "theft",
            "fire",
            "natural_disasters",
            "legal_protection",
            "assistance",
            "replacement_vehicle",
        ]
        assert by_key["glass"]["deductible"] == "80"
        assert by_key["theft"]["deductible"] == "300"
        assert by_key["natural_disasters"]["deductible"] == "380"
        assert by_key["driver_protection"]["limit_primary"] == "1000000"
        assert by_key["legal_protection"]["limit_primary"] == "20000"
        assert by_key["replacement_vehicle"]["limit_primary"] == "15"
        assert by_key["third_party_liability"]["limit_primary"] is None
        # « non souscrite » is not carried.
        assert "all_accidents_damage" not in by_key

    def test_the_insurer_is_the_first_printed_not_the_first_known(self, parser):
        text = AVIS_ECHEANCE.replace("MAIF\n", "MAAF\n").replace(
            "Sociétaire", "Groupe Covéa\nSociétaire"
        )
        assert parser.parse(text).provider == "MAAF"

    def test_a_labelled_insurer_wins(self, parser):
        text = "Assureur : Leocare\nContrat n° X-1\n" + AVIS_ECHEANCE
        assert parser.parse(text).provider == "Leocare"

    def test_an_echeance_alone_gives_a_yearly_term(self, parser):
        text = AVIS_ECHEANCE.replace(
            "Période de garantie : du 01/01/2026 au 31/12/2026", "Date d'échéance : 1er mars 2026"
        )
        data = parser.parse(text)
        assert (data.start_date, data.end_date) == ("2025-03-01", "2026-03-01")
        assert data.field_confidence["dates"] == "medium"

    def test_a_date_of_effect_alone_gives_a_yearly_term(self, parser):
        text = AVIS_ECHEANCE.replace(
            "Période de garantie : du 01/01/2026 au 31/12/2026", "Date d'effet : 15.06.2026"
        )
        data = parser.parse(text)
        assert (data.start_date, data.end_date) == ("2026-06-15", "2027-06-15")

    def test_a_monthly_premium_line_is_monthly(self, parser):
        text = AVIS_ECHEANCE.replace(
            "Cotisation annuelle TTC : 612,40 €", "Cotisation mensuelle : 51,03 €"
        )
        data = parser.parse(text)
        assert data.premium_amount == Decimal("51.03")
        assert data.premium_frequency == "Monthly"

    def test_tous_risques_and_au_tiers(self, parser):
        assert parser.parse(AVIS_ECHEANCE.replace("Tiers étendu", "Tous risques")).policy_type == (
            "Full Coverage"
        )
        assert parser.parse(AVIS_ECHEANCE.replace("Tiers étendu", "Au tiers")).policy_type == (
            "Third Party"
        )

    def test_a_target_vin_is_echoed(self, parser):
        data = parser.parse(AVIS_ECHEANCE, target_vin="vf1rfb00x56123456")
        assert data.extracted_vin == "VF1RFB00X56123456"


@pytest.mark.unit
class TestHelpers:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("15/03/2026", "2026-03-15"),
            ("15.03.2026", "2026-03-15"),
            ("1er mars 2026", "2026-03-01"),
            ("31 décembre 2025", "2025-12-31"),
            ("3 févr. 2026", "2026-02-03"),
            ("30 février 2026", None),
            ("", None),
            (None, None),
        ],
    )
    def test_fr_date(self, raw, expected):
        assert fr_date(raw) == expected

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Formule : Tous risques", "Full Coverage"),
            ("formule tiers plus", "Third Party Extended"),
            ("Formule : Tiers simple", "Third Party"),
            ("Au tiers avec vol et incendie", "Third Party"),
            ("Vollkasko mit 300 € SB", "Full Coverage"),
            ("Teilkasko", "Third Party Extended"),
            ("Kfz-Haftpflicht nur", "Third Party"),
            ("Polizza RC auto base", "Third Party"),
            ("Kasko completa", "Full Coverage"),
            ("Modalidad: todo riesgo con franquicia", "Full Coverage"),
            ("Terceros ampliado", "Third Party Extended"),
            ("Third party, fire and theft", "Third Party Extended"),
            # A North American page says « third party » of the other driver.
            ("Bodily injury to a third party", None),
            ("Nothing printed", None),
            (None, None),
        ],
    )
    def test_classify_formula(self, text, expected):
        assert classify_formula(text) == expected

    def test_a_labelled_formula_beats_marketing_text(self):
        text = "Formule : au tiers\nPassez en tous risques pour 10 € de plus par mois"
        assert classify_formula(text) == "Third Party"

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("AB-123-CD", "AB-123-CD"),
            ("ab 123 cd", "AB-123-CD"),
            ("AB123CD", "AB-123-CD"),
            ("1234 AB 56", "1234 AB 56"),
            ("M-AB 1234", "M-AB 1234"),
            ("ABCDEFG", None),
            ("", None),
            (3, None),
        ],
    )
    def test_clean_plate(self, raw, expected):
        assert clean_plate(raw) == expected

    def test_plates_in(self):
        assert plates_in("Immatriculation AB-123-CD puis ab 123 cd et EF-456-GH") == [
            "AB-123-CD",
            "EF-456-GH",
        ]


@pytest.mark.unit
class TestModelPath:
    def test_valid_values_are_kept_and_invalid_ones_rejected(self):
        data = from_llm_fields(
            {
                "insurer": " MAIF ",
                "policy_number": "1234567 A",
                "start_date": "2026-01-01",
                "end_date": "31/12/2026",
                "premium": "612,40",
                "payment_frequency": "annual",
                "deductible": 300,
                "policy_type": "tiers étendu",
                "coverages": [
                    {"name": "Bris de glace", "limit": None},
                    {"name": "Garantie du conducteur", "limit": "1 000 000"},
                    {"name": "Protection des bagages", "limit": 500},
                ],
                "plates": ["ab 123 cd"],
                "vins": ["VF1RFB00X56123456", "not a vin"],
                "no_claims_class": "0,50",
                "currency": "EUR",
            },
            model="gpt-4o",
        )
        assert data.parser_name == "vision:gpt-4o"
        assert data.provider == "MAIF"
        assert data.policy_number == "1234567 A"
        assert (data.start_date, data.end_date) == ("2026-01-01", "2026-12-31")
        assert data.premium_amount == Decimal("612.40")
        assert data.premium_frequency == "Annual"
        assert data.deductible == Decimal("300")
        assert data.policy_type == "Third Party Extended"
        assert data.no_claims_class == "0.50"
        assert data.plates_found == ["AB-123-CD"]
        assert data.vehicles_found == ["VF1RFB00X56123456"]
        keys = [item["coverage_key"] for item in data.coverages]
        assert keys == ["glass", "driver_protection"]
        assert data.coverages[1]["limit_primary"] == "1000000"
        assert data.unmatched_coverages == ["Protection des bagages"]
        assert data.field_confidence["provider"] == "high"
        assert data.field_confidence["dates"] == "high"
        assert "No VINs" not in " ".join(data.get_validation_warnings())

    def test_a_bad_date_and_an_unknown_formula_are_rejected(self):
        data = from_llm_fields(
            {"start_date": "soon", "end_date": "2026-12-31", "policy_type": "Formule Zen"}
        )
        assert (data.start_date, data.end_date) == (None, "2026-12-31")
        assert data.field_confidence["dates"] == "rejected"
        assert data.policy_type == "Other"
        assert data.field_confidence["policy_type"] == "rejected"
        assert data.provider == "Unknown"
        assert data.premium_frequency is None

    def test_the_frequency_falls_back_to_the_term(self):
        data = from_llm_fields({"start_date": "2026-01-01", "end_date": "2026-07-01"})
        assert data.premium_frequency == "Semi-Annual"

    def test_a_limit_on_a_coverage_without_a_limit_slot_is_dropped(self):
        # The model called a franchise a limit: the coverage is kept, the
        # amount is not filed by position as a deductible.
        data = from_llm_fields({"coverages": [{"name": "Vol", "limit": 300}]})
        assert data.coverages == [
            {
                "coverage_key": "theft",
                "limit_primary": None,
                "limit_secondary": None,
                "deductible": None,
                "premium": None,
            }
        ]
