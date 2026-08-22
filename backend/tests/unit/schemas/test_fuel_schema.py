"""Unit tests for FuelRecordCreate's cross-field validators.

Phase 2.1 of v2.27.0-rc2 fixes:

  rc1 accepted fuel records with no odometer reading and no fuel-amount
  data. The "required" rule lived only in the frontend form, so any
  non-browser client (curl, mobile app, the importer) could write
  empty records. The new model_validator on FuelRecordCreate enforces
  the rule at the schema level.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas.fuel import FuelRecordCreate

VIN = "1HGBH41JXMN109186"
TODAY = date(2026, 5, 5)


def _base_kwargs() -> dict[str, object]:
    return {"vin": VIN, "date": TODAY}


def test_create_with_odometer_and_liters_succeeds():
    record = FuelRecordCreate(**_base_kwargs(), odometer_km=12345.6, liters=40.0)
    assert record.liters == 40.0


def test_create_with_odometer_and_kwh_succeeds():
    record = FuelRecordCreate(**_base_kwargs(), odometer_km=12345.6, kwh=55.5)
    assert record.kwh == 55.5


def test_create_with_odometer_and_propane_succeeds():
    record = FuelRecordCreate(**_base_kwargs(), odometer_km=12345.6, propane_liters=20.0)
    assert record.propane_liters == 20.0


def test_create_with_odometer_and_propane_tank_pair_succeeds():
    record = FuelRecordCreate(
        **_base_kwargs(),
        odometer_km=12345.6,
        tank_size_kg=18.0,
        tank_quantity=2,
    )
    assert record.tank_size_kg == 18.0


def test_propane_tank_refill_without_odometer_succeeds():
    """A bottled/tank propane refill has no odometer to record.

    The propane tab writes to fuel_records but tracks tank refills for
    RVs and trailers (PropaneRecordForm posts ``odometer_km: undefined``
    deliberately, because a travel trailer has no odometer at all and a
    motorhome's reading is meaningless for a grill bottle). Requiring one
    422'd every propane record the UI could produce.
    """
    record = FuelRecordCreate(**_base_kwargs(), propane_liters=8.5)
    assert record.propane_liters == 8.5
    assert record.odometer_km is None


def test_propane_tank_pair_without_odometer_succeeds():
    """The tank-size form of the same refill (service derives the liters)."""
    record = FuelRecordCreate(**_base_kwargs(), tank_size_kg=14.97, tank_quantity=1)
    assert record.tank_quantity == 1
    assert record.odometer_km is None


def test_propane_with_liters_still_requires_odometer():
    """Propane alongside liquid fuel is a vehicle fill-up, not a tank refill."""
    with pytest.raises(ValidationError) as excinfo:
        FuelRecordCreate(**_base_kwargs(), propane_liters=8.5, liters=40.0)
    assert "odometer_km is required" in str(excinfo.value)


def test_propane_with_missed_fillup_still_requires_odometer():
    """missed_fillup means "I have the odometer but not the amount"."""
    with pytest.raises(ValidationError) as excinfo:
        FuelRecordCreate(**_base_kwargs(), propane_liters=8.5, missed_fillup=True)
    assert "odometer_km is required" in str(excinfo.value)


def test_kwh_without_odometer_fails():
    """The propane exemption must not leak to charge sessions."""
    with pytest.raises(ValidationError) as excinfo:
        FuelRecordCreate(**_base_kwargs(), kwh=55.5)
    assert "odometer_km is required" in str(excinfo.value)


def test_create_without_odometer_fails():
    with pytest.raises(ValidationError) as excinfo:
        FuelRecordCreate(**_base_kwargs(), liters=40.0)
    assert "odometer_km is required" in str(excinfo.value)


def test_create_without_any_fuel_amount_fails():
    with pytest.raises(ValidationError) as excinfo:
        FuelRecordCreate(**_base_kwargs(), odometer_km=12345.6)
    assert "fuel record must include at least one of" in str(excinfo.value)


def test_create_with_only_tank_size_no_quantity_fails():
    """tank_size_kg without tank_quantity is also "no fuel amount"."""
    with pytest.raises(ValidationError):
        FuelRecordCreate(
            **_base_kwargs(),
            odometer_km=12345.6,
            tank_size_kg=18.0,
        )


def test_missed_fillup_only_needs_odometer():
    """The explicit escape hatch for partial historical entries."""
    record = FuelRecordCreate(
        **_base_kwargs(),
        odometer_km=12345.6,
        missed_fillup=True,
    )
    assert record.missed_fillup is True
    assert record.liters is None


def test_missed_fillup_still_requires_odometer():
    with pytest.raises(ValidationError) as excinfo:
        FuelRecordCreate(**_base_kwargs(), missed_fillup=True)
    assert "odometer_km is required" in str(excinfo.value)


# ---------------------------------------------------------------------------
# obc_trip_duration_s — accept seconds OR HH:MM[:SS] (Phase 2.2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        (120, 120),
        (0, 0),
        ("120", 120),
        ("02:15", 2 * 3600 + 15 * 60),  # 8100
        ("00:45", 45 * 60),  # 2700
        ("1:05", 1 * 3600 + 5 * 60),  # 3900
        ("02:15:30", 2 * 3600 + 15 * 60 + 30),  # 8130
        ("", None),
        (None, None),
    ],
)
def test_obc_trip_duration_accepts_int_and_hhmm(raw, expected):
    record = FuelRecordCreate(
        **_base_kwargs(),
        odometer_km=12345.6,
        liters=40.0,
        obc_trip_duration_s=raw,
    )
    assert record.obc_trip_duration_s == expected


@pytest.mark.parametrize(
    "raw",
    [
        "bad",
        "02:60",  # minute component >= 60
        "02:15:60",  # second component >= 60
        "02:15:30:01",  # too many parts
        "::",
    ],
)
def test_obc_trip_duration_rejects_malformed(raw):
    with pytest.raises(ValidationError):
        FuelRecordCreate(
            **_base_kwargs(),
            odometer_km=12345.6,
            liters=40.0,
            obc_trip_duration_s=raw,
        )
