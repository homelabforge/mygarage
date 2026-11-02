"""The insurance vocabularies: one list, three readers (#211)."""

from __future__ import annotations

import typing

import pytest

from app.constants.insurance import (
    EU_POLICY_TYPES,
    POLICY_TYPE_VALUES,
    clean_no_claims_class,
)
from app.models.insurance import POLICY_TYPES
from app.schemas.insurance import CoverageKey, PolicyType
from app.utils.insurance_coverages import COVERAGE_KEYS


class TestPolicyTypes:
    def test_schema_literal_matches_the_constants(self):
        assert tuple(typing.get_args(PolicyType)) == POLICY_TYPE_VALUES

    def test_the_model_reads_the_same_list(self):
        assert POLICY_TYPES == POLICY_TYPE_VALUES

    def test_the_european_formulas_are_in_the_list(self):
        assert set(EU_POLICY_TYPES) <= set(POLICY_TYPE_VALUES)
        assert "Third Party" in POLICY_TYPE_VALUES
        assert "Third Party Extended" in POLICY_TYPE_VALUES


def test_the_coverage_literal_matches_the_catalogue():
    assert tuple(typing.get_args(CoverageKey)) == COVERAGE_KEYS


class TestNoClaimsClass:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("0.50", "0.50"),
            ("0,50", "0.50"),
            (" SF 12 ", "SF 12"),
            ("50 %", "50 %"),
            ("1", "1"),
            ("-3", "-3"),
            ("", None),
            (None, None),
            (12, None),
            ("way too long for a class", None),
            ("0.50€", None),
        ],
    )
    def test_cleaning(self, raw, expected):
        assert clean_no_claims_class(raw) == expected
