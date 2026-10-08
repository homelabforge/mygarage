"""The EU registration certificate parser (#211): the text path, the model
path, and the vehicle patch both feed."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.document_parsers.base import DocumentType
from app.services.document_parsers.registration import (
    EURegistrationCertificateParser,
    RegistrationData,
    clean_vin,
    eu_category,
    from_llm_fields,
    iso_date,
    to_decimal,
    to_int,
)
from app.services.document_parsers.registry import DocumentParserRegistry
from app.services.registration_certificate_service import (
    guess_vehicle_type,
    suggested_tax_records,
    vehicle_patch,
)

FR_SIV = """RÉPUBLIQUE FRANÇAISE
CERTIFICAT D'IMMATRICULATION
A AB-123-CD   B 12/03/2023
C.1 DUPONT JEAN
C.4a PROPRIETAIRE DU VEHICULE
D.1 RENAULT
D.2 RFB1A2
D.3 CLIO
E VF1RFB00X56123456
F.1 1800   F.2 1800   F.3 2900
G 1210   G.1 1120
I 15/03/2023
J M1   J.1 VP   J.2 AB   J.3 CI
K e2*2007/46*0123*05
P.1 1498   P.2 74   P.3 ES   P.6 5
S.1 5   S.2 0
U.1 72   U.2 3250
V.7 118   V.9 Euro 6d-TEMP
X.1 10/02/2026
Y.1 162,50   Y.2 0   Y.3 0   Y.4 11   Y.5 2,76   Y.6 176,26
"""

LU_SNCA = """GRAND-DUCHÉ DE LUXEMBOURG
SOCIÉTÉ NATIONALE DE CIRCULATION AUTOMOBILE
Certificat d'immatriculation Partie I
A
AB 1234
B
15.01.2020
D.1
VOLKSWAGEN
D.3
GOLF
E
WVWZZZAUZLW123456
J
M1
P.1
1968
P.2
110
P.3
GO
V.7
119
"""

DE_TEIL_I = """BUNDESREPUBLIK DEUTSCHLAND
ZULASSUNGSBESCHEINIGUNG TEIL I
A: M-AB 1234
B: 03.06.2019
C.1.1: MÜLLER
D.1: BMW
D.2: 3L
D.3: 320D
E: WBA8E51070A123456
J: M1
P.1: 1995
P.2: 140
P.3: Diesel
P.3 GO
V.7: 112
V.9: EURO6
"""

INSURANCE = """ATTESTATION D'ASSURANCE AUTOMOBILE
Contrat n° 123456
Assuré : M. DUPONT JEAN
Valable du 01/01/2026 au 31/12/2026
Véhicule : RENAULT CLIO immatriculé AB-123-CD
"""


@pytest.fixture
def parser() -> EURegistrationCertificateParser:
    return EURegistrationCertificateParser()


class TestCanParse:
    def test_a_marker_is_enough(self, parser):
        assert parser.can_parse("CERTIFICAT D'IMMATRICULATION\nRÉPUBLIQUE FRANÇAISE")

    def test_four_codes_are_enough_without_a_marker(self, parser):
        assert parser.can_parse("A AB-123-CD\nB 12/03/2023\nD.1 RENAULT\nE VF1RFB00X56123456")

    def test_an_insurance_certificate_is_not_one(self, parser):
        assert not parser.can_parse(INSURANCE)
        assert not parser.can_parse("")

    def test_the_registry_serves_it(self):
        assert isinstance(
            DocumentParserRegistry.get_registration_parser(), EURegistrationCertificateParser
        )


class TestFrenchCertificate:
    def test_every_field_is_read_as_printed(self, parser):
        data = parser.parse(FR_SIV)
        assert isinstance(data, RegistrationData)
        assert data.document_type is DocumentType.REGISTRATION
        assert data.country == "FR"  # RÉPUBLIQUE FRANÇAISE beats Belgium's shared marker
        assert data.plate == "AB-123-CD"
        assert data.first_registration == "2023-03-12"
        assert data.holder == "DUPONT JEAN"
        assert data.make == "RENAULT"
        assert data.type_variant_version == "RFB1A2"
        assert data.commercial_name == "CLIO"
        assert data.vin == "VF1RFB00X56123456"
        assert data.extracted_vin == data.vin
        assert data.max_mass_kg == 1800
        assert data.mass_in_service_kg == 1210
        assert data.eu_category == "M1"
        assert data.national_category == "VP"
        assert data.type_approval == "e2*2007/46*0123*05"
        assert data.displacement_cc == 1498
        assert data.power_kw == 74
        assert data.energy_code == "ES"
        assert data.fiscal_power == 5
        assert data.seats == 5
        assert data.co2_g_km == 118
        assert data.euro_class == "Euro 6d-TEMP"
        assert data.last_inspection == "2026-02-10"
        assert data.taxes == {
            "Y.1": Decimal("162.50"),
            "Y.2": Decimal("0"),
            "Y.3": Decimal("0"),
            "Y.4": Decimal("11"),
            "Y.5": Decimal("2.76"),
            "Y.6": Decimal("176.26"),
        }
        assert data.confidence_score == 100.0
        assert data.field_confidence["vin"] == "high"
        assert data.field_confidence["plate"] == "high"
        assert data.field_confidence["make"] == "medium"
        assert data.get_validation_warnings() == []

    def test_noise_around_the_codes_does_not_matter(self, parser):
        noisy = (
            "Document édité par l'ANTS\n"
            + FR_SIV.replace("D.1 RENAULT", "D 1 : RENAULT").replace("P.3 ES", "P-3 ES")
            + "\nMentions: aucune\n"
        )
        data = parser.parse(noisy)
        assert data.make == "RENAULT"
        assert data.energy_code == "ES"
        assert data.vin == "VF1RFB00X56123456"

    def test_vin_without_its_label_is_the_only_17_character_token(self, parser):
        data = parser.parse(
            "CERTIFICAT D'IMMATRICULATION\nRÉPUBLIQUE FRANÇAISE\nVF1RFB00X56123456\nD.1 RENAULT"
        )
        assert data.vin == "VF1RFB00X56123456"
        assert data.field_confidence["vin"] == "medium"


class TestOtherCountries:
    def test_luxembourg_label_above_value(self, parser):
        data = parser.parse(LU_SNCA)
        assert data.country == "LU"
        assert data.plate == "AB 1234"
        assert data.first_registration == "2020-01-15"
        assert data.make == "VOLKSWAGEN"
        assert data.commercial_name == "GOLF"
        assert data.vin == "WVWZZZAUZLW123456"
        assert data.displacement_cc == 1968
        assert data.power_kw == 110
        assert data.energy_code == "GO"
        assert data.co2_g_km == 119

    def test_german_teil_i_with_colons(self, parser):
        data = parser.parse(DE_TEIL_I)
        assert data.country == "DE"
        assert data.plate == "M-AB 1234"
        assert data.first_registration == "2019-06-03"
        assert data.make == "BMW"
        assert data.commercial_name == "320D"
        assert data.vin == "WBA8E51070A123456"
        # The first P.3 ("Diesel") is not a code; the second is.
        assert data.energy_code == "GO"
        assert data.euro_class == "EURO6"

    def test_country_falls_back_to_the_plate_format(self, parser):
        data = parser.parse("A AB-123-CD\nB 12/03/2023\nD.1 RENAULT\nE VF1RFB00X56123456")
        assert data.country == "FR"
        assert data.field_confidence["country"] == "medium"

    def test_a_country_hint_is_used_when_the_document_says_nothing(self, parser):
        data = parser.parse(
            "A XX 999\nB 12/03/2023\nD.1 RENAULT\nE VF1RFB00X56123456", country="es"
        )
        assert data.country == "ES"
        # The plate does not match Spain's format: kept, with a doubt.
        assert data.plate == "XX 999"
        assert data.field_confidence["plate"] == "low"


class TestValidators:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("VF1RFB00X56123456", "VF1RFB00X56123456"),
            ("vf1 rfb00x 56123456", "VF1RFB00X56123456"),
            ("VF1RFB00X5612345O", None),
            ("VF1RFB00X5612345", None),
            (123, None),
        ],
    )
    def test_clean_vin(self, raw, expected):
        assert clean_vin(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("12/03/2023", "2023-03-12"),
            ("12.03.2023", "2023-03-12"),
            ("2023-03-12", "2023-03-12"),
            (date(2023, 3, 12), "2023-03-12"),
            ("31/02/2023", None),
            ("12/03/1850", None),
            ("tomorrow", None),
        ],
    )
    def test_iso_date(self, raw, expected):
        assert iso_date(raw) == expected

    def test_to_int_and_to_decimal(self):
        assert to_int("1 498 cm3") == 1498
        assert to_int(74.0) == 74
        assert to_int(74.5) is None
        assert to_int("-5") is None
        assert to_int(True) is None
        assert to_decimal("162,50") == Decimal("162.50")
        assert to_decimal("1 234,56 €") == Decimal("1234.56")
        assert to_decimal("1,234.56") == Decimal("1234.56")
        assert to_decimal(11) == Decimal("11")
        assert to_decimal("gratuit") is None

    def test_eu_category(self):
        assert eu_category("M1") == "M1"
        assert eu_category("l3e") == "L3e"
        assert eu_category("M.1") == "M1"
        assert eu_category("VP") is None


class TestModelPath:
    def test_valid_values_are_kept_and_invalid_ones_dropped_with_a_warning(self):
        data = from_llm_fields(
            {
                "country": "FR",
                "A": "ab-123-cd",
                "B": "2023-03-12",
                "D1": "Renault",
                "D3": "Clio",
                "E": "VF1RFB00X5612345O",
                "J": "M1",
                "J1": "vp",
                "P1": "1498 cm3",
                "P2": 74.0,
                "P3": "ES",
                "P6": "cinq",
                "V9": "Euro 6d-TEMP",
                "X1": "10/02/2026",
                "Y1": "162,50",
                "Y3": None,
                "unexpected": "ignored",
            },
            model="llava",
        )
        assert data.parser_name == "vision:llava"
        assert data.country == "FR"
        assert data.plate == "AB-123-CD"
        assert data.first_registration == "2023-03-12"
        assert data.make == "Renault"
        assert data.commercial_name == "Clio"
        assert data.vin is None
        assert data.eu_category == "M1"
        assert data.national_category == "VP"
        assert data.displacement_cc == 1498
        assert data.power_kw == 74
        assert data.energy_code == "ES"
        assert data.fiscal_power is None
        assert data.euro_class == "Euro 6d-TEMP"
        assert data.last_inspection == "2026-02-10"
        assert data.taxes == {"Y.1": Decimal("162.50")}
        assert [w.split(":")[0] for w in data.warnings] == ["E", "P.6"]
        assert "VIN (E) not found" in data.get_validation_warnings()
        assert data.confidence_score == 70.0

    def test_country_from_the_plate_when_the_model_gave_none(self):
        data = from_llm_fields({"A": "AB-123-CD", "E": "VF1RFB00X56123456"})
        assert data.country == "FR"
        assert data.field_confidence["country"] == "medium"


class TestVehiclePatch:
    def test_full_certificate_maps_onto_the_vehicle(self, parser):
        patch, dropped = vehicle_patch(parser.parse(FR_SIV))
        assert dropped == []
        assert patch == {
            "vin": "VF1RFB00X56123456",
            "license_plate": "AB-123-CD",
            "first_registration_date": "2023-03-12",
            "make": "RENAULT",
            "model": "CLIO",
            "displacement_l": "1.5",
            "power_kw": 74,
            "fuel_type": "gasoline",
            "fiscal_power": 5,
            "co2_g_km": 118,
            "euro_emission_class": "Euro 6d-TEMP",
            "eu_category": "M1",
            "national_category": "VP",
            "registration_country": "FR",
            "vehicle_type": "Car",
        }

    def test_plug_in_hybrid_code_sets_both_fuel_types(self):
        data = RegistrationData(energy_code="EE", country="FR")
        patch, _ = vehicle_patch(data)
        assert patch["fuel_type"] == "plugin_hybrid"
        assert patch["fuel_type_secondary"] == "electric"

    def test_a_value_the_vehicle_schema_refuses_is_dropped_with_a_reason(self):
        data = RegistrationData(fiscal_power=5, co2_g_km=118, euro_class="x" * 12)
        data.co2_g_km = 5000  # past the schema's bound, as a misread could be
        patch, dropped = vehicle_patch(data)
        assert "co2_g_km" not in patch
        assert patch["fiscal_power"] == 5
        assert dropped and dropped[0].startswith("co2_g_km:")

    @pytest.mark.parametrize(
        ("eu", "national", "expected"),
        [
            ("M1", "VP", "Car"),
            ("N1", "CTTE", "Truck"),
            ("L3e", "MTT2", "Motorcycle"),
            ("M1", "VASP", "RV"),
            ("O2", "REM", "Trailer"),
            ("L7e", None, "Car"),
            ("L1e", None, "Motorcycle"),
            ("N2", None, "Truck"),
            (None, None, None),
            ("T1", None, None),
        ],
    )
    def test_vehicle_type_guess(self, eu, national, expected):
        assert guess_vehicle_type(eu, national) == expected

    def test_suggested_taxes_prefer_the_components_over_the_total(self, parser):
        data = parser.parse(FR_SIV)
        suggestions = suggested_tax_records(data)
        assert suggestions == [
            {
                "code": "Y.1",
                "tax_type": "registration_tax",
                "amount": Decimal("162.50"),
                "date": "2023-03-12",
            }
        ]
        data.taxes = {"Y.6": Decimal("176.26")}
        assert suggested_tax_records(data)[0]["tax_type"] == "registration"
        data.first_registration = None
        assert suggested_tax_records(data) == []
