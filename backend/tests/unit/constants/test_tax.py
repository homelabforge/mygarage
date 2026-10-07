"""Tax type codes (#211): the vocabulary, the legacy spellings, the normaliser."""

from __future__ import annotations

import typing

import pytest

from app.constants.tax import (
    LEGACY_TAX_TYPES,
    TAX_TYPE_VALUES,
    is_tax_type,
    normalize_tax_type,
)
from app.schemas.tax import TaxType
from app.services.country_profile_service import available_profile_ids, load_profile


@pytest.mark.unit
class TestVocabulary:
    def test_codes_are_snake_case_and_unique(self):
        assert len(set(TAX_TYPE_VALUES)) == len(TAX_TYPE_VALUES)
        for code in TAX_TYPE_VALUES:
            assert code == code.lower() and " " not in code

    def test_schema_literal_matches_the_constants(self):
        assert set(typing.get_args(TaxType)) == set(TAX_TYPE_VALUES)

    def test_every_legacy_string_maps_to_a_code(self):
        assert set(LEGACY_TAX_TYPES) == {"Registration", "Inspection", "Property Tax", "Tolls"}
        assert all(is_tax_type(code) for code in LEGACY_TAX_TYPES.values())

    def test_every_shipped_profile_lists_known_codes(self):
        for profile_id in available_profile_ids():
            profile = load_profile(profile_id)
            assert profile is not None
            assert all(is_tax_type(code) for code in profile.taxes.types), profile_id
            assert set(profile.taxes.names) <= set(profile.taxes.types), profile_id


@pytest.mark.unit
class TestNormalize:
    @pytest.mark.parametrize(
        "given,expected",
        [
            (None, None),
            ("", None),
            ("   ", None),
            ("registration", "registration"),
            ("co2_malus", "co2_malus"),
            ("Registration", "registration"),
            ("Property Tax", "property_tax"),
            ("PROPERTY TAX", "property_tax"),
            ("property tax", "property_tax"),
            ("  Tolls  ", "tolls"),
            ("Circulation Tax", "circulation_tax"),
            ("LEZ sticker", "lez_sticker"),
            ("Income Tax", "Income Tax"),
            ("bogus", "bogus"),
        ],
    )
    def test_spellings(self, given, expected):
        assert normalize_tax_type(given) == expected

    def test_is_tax_type_is_exact(self):
        assert is_tax_type("tolls")
        assert not is_tax_type("Tolls")
        assert not is_tax_type(None)
