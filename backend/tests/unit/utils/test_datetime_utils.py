"""Tests for the naive-UTC datetime helpers."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.utils.datetime_utils import to_naive_utc


def test_an_aware_value_becomes_its_utc_wall_clock() -> None:
    result = to_naive_utc(datetime(2026, 10, 10, 12, tzinfo=timezone(timedelta(hours=2))))

    assert result == datetime(2026, 10, 10, 10)
    assert result.tzinfo is None


@pytest.mark.usefixtures("local_clock_off_utc")
def test_a_naive_value_is_already_utc_and_passes_through() -> None:
    naive = datetime(2026, 10, 10, 10)

    result = to_naive_utc(naive)

    assert result == naive
    assert result.tzinfo is None


def test_a_utc_value_keeps_its_wall_clock() -> None:
    result = to_naive_utc(datetime(2026, 10, 10, 10, tzinfo=UTC))

    assert result == datetime(2026, 10, 10, 10)
    assert result.tzinfo is None
