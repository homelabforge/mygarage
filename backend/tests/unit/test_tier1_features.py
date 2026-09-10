"""Unit tests for third-party fuel CSV adapters, tire wear, and webhook fuel commands."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.routes.webhooks import _parse_fuel_command
from app.schemas.fuel import FuelRecordCreate
from app.services.import_adapters.fuel_csv import (
    detect_format,
    parse_drivvo,
    parse_fuelio,
    parse_tesla,
)
from app.services.tire_results import WearStatus
from app.services.tire_service import project_wear


class _Reading:
    def __init__(self, recorded_at, odometer_km, tread_depth_mm):
        self.recorded_at = recorded_at
        self.odometer_km = odometer_km
        self.tread_depth_mm = tread_depth_mm


def _tire_with(readings, min_tread, *, bounded=True):
    """A tire whose mount history supports (or does not support) a projection.

    v3.3.0 made the projection period-aware: the distance is the tire's own,
    not the vehicle's odometer span between two readings. So these tests need
    a tire with a bounded mount period, and `bounded=False` exercises the case
    the release exists to stop publishing.
    """
    from app.models.tire import Tire, TireMountPeriod

    # `readings` are plain stand-ins, not ORM instances, so they go through
    # project_wear's explicit parameter rather than the relationship.
    tire = Tire(vin="V" * 17, position="FL", min_tread_mm=min_tread)
    tire.mount_periods = [
        TireMountPeriod(
            position="FL",
            mounted_on=date(2025, 1, 1),
            mounted_odometer_km=Decimal("9000") if bounded else None,
        )
    ]
    return tire


def test_parse_fuelio_metric():
    csv_data = (
        "Date,Odometer,Fuel Type,Volume(l),Price,Total cost,Full tank,Notes\n"
        "2026-01-15,12345.0,Gasoline,40.5,1.499,60.71,1,Shell\n"
    )
    rows = parse_fuelio(csv_data)
    assert len(rows) == 1
    assert rows[0]["date"] == date(2026, 1, 15)
    assert rows[0]["liters"] == Decimal("40.5")
    assert rows[0]["odometer_km"] == Decimal("12345.0")
    assert rows[0]["is_full_tank"] is True


def test_parse_drivvo():
    csv_data = (
        "Date,Odometer (km),Quantity (liters),Price/liter,Total cost,Full tank,Notes\n"
        "15/01/2026,20000,35.2,1.55,54.56,yes,BP\n"
    )
    rows = parse_drivvo(csv_data)
    assert len(rows) == 1
    assert rows[0]["liters"] == Decimal("35.2")
    assert rows[0]["odometer_km"] == Decimal("20000")


def test_parse_tesla_charge():
    csv_data = (
        "Charge End Date,Energy Added (kWh),Odometer,Cost,Starting SOC,Ending SOC,"
        "Charge Type,Location\n"
        "2026-03-01,42.5,15000,8.50,20,80,L2,Home\n"
    )
    rows = parse_tesla(csv_data)
    assert len(rows) == 1
    assert rows[0]["kwh"] == Decimal("42.5")
    assert rows[0]["soc_start_pct"] == Decimal("20")
    assert rows[0]["soc_end_pct"] == Decimal("80")
    assert rows[0]["charge_level"] == "L2"
    assert rows[0]["charge_location"] == "home"
    assert rows[0]["price_basis"] == "per_kwh"


def test_detect_format_tesla():
    csv_data = "Charge Start Date,Charge End Date,Energy Added\n2026-01-01,2026-01-01,10\n"
    assert detect_format(csv_data) == "tesla"


def test_detect_format_fuelio():
    csv_data = "Date,Odometer,Fuel Type,Volume(l),Price,Total cost\n2026-01-01,1,Gas,10,1,10\n"
    assert detect_format(csv_data) == "fuelio"


def test_detect_format_drivvo():
    csv_data = (
        "Date,Odometer (km),Quantity (liters),Price/liter,Total cost\n01/01/2026,1000,40,1.5,60\n"
    )
    assert detect_format(csv_data) == "drivvo"


def test_project_wear():
    readings = [
        _Reading(date(2026, 6, 1), Decimal("12000"), Decimal("4.0")),
        _Reading(date(2026, 1, 1), Decimal("10000"), Decimal("6.0")),
    ]
    result = project_wear(_tire_with(readings, Decimal("2.0")), Decimal("12000"), readings)
    assert result.status is WearStatus.PROJECTED
    assert result.km_remaining == Decimal("2000.0")
    assert result.wear_date is not None


def test_project_wear_needs_two_readings():
    readings = [_Reading(date(2026, 1, 1), Decimal("10000"), Decimal("6.0"))]
    result = project_wear(_tire_with(readings, Decimal("2.0")), Decimal("12000"), readings)
    assert result.status is WearStatus.INSUFFICIENT_READINGS
    assert result.km_remaining is None


def test_project_wear_already_below_threshold():
    readings = [
        _Reading(date(2026, 6, 1), Decimal("12000"), Decimal("1.5")),
        _Reading(date(2026, 1, 1), Decimal("10000"), Decimal("6.0")),
    ]
    result = project_wear(_tire_with(readings, Decimal("2.0")), Decimal("12000"), readings)
    assert result.status is WearStatus.AT_OR_BELOW_MINIMUM
    assert result.km_remaining == Decimal("0")
    assert result.wear_date == date(2026, 6, 1)


def test_project_wear_is_suppressed_without_a_bounded_mount_history():
    """The whole reason this release exists.

    With no odometer on the mount period, the only distance available is the
    vehicle's raw odometer span -- which for a two-set owner counts the
    kilometres driven on the OTHER set, and errs high. The number is withheld
    rather than published with an "estimate" badge.
    """
    readings = [
        _Reading(date(2026, 6, 1), Decimal("12000"), Decimal("4.0")),
        _Reading(date(2026, 1, 1), Decimal("10000"), Decimal("6.0")),
    ]
    result = project_wear(
        _tire_with(readings, Decimal("2.0"), bounded=False),
        Decimal("12000"),
        readings,
    )
    assert result.status is WearStatus.UNVERIFIED_MOUNT_HISTORY
    assert result.km_remaining is None


def test_a_worn_tire_says_replace_now_even_with_no_mount_history():
    """C7. The safety statement needs no distance to be true.

    Before this fix this returned UNVERIFIED_MOUNT_HISTORY, so the card asked
    for an odometer while the low-tread reminder was already raised against
    the same tire.
    """
    readings = [
        _Reading(date(2026, 6, 1), Decimal("12000"), Decimal("1.5")),
        _Reading(date(2026, 1, 1), Decimal("10000"), Decimal("6.0")),
    ]
    tire = _tire_with(readings, Decimal("2.0"), bounded=False)
    tire.tread_depth_mm = Decimal("1.5")
    result = project_wear(tire, Decimal("12000"), readings)
    assert result.status is WearStatus.AT_OR_BELOW_MINIMUM
    assert result.km_remaining == Decimal("0")
    assert result.wear_date == date(2026, 6, 1)


@pytest.mark.parametrize(
    "readings",
    [
        pytest.param(
            [_Reading(date(2026, 6, 1), Decimal("12000"), Decimal("1.5"))], id="one_reading"
        ),
        pytest.param(
            [
                _Reading(date(2026, 6, 1), None, Decimal("1.5")),
                _Reading(date(2026, 1, 1), None, Decimal("6.0")),
            ],
            id="no_reading_odometers",
        ),
        pytest.param(
            [
                _Reading(date(2026, 6, 1), Decimal("12000"), Decimal("1.5")),
                _Reading(date(2026, 1, 1), Decimal("10000"), Decimal("1.5")),
            ],
            id="flat_tread",
        ),
        pytest.param(
            [
                _Reading(date(2026, 6, 1), Decimal("12000"), Decimal("1.5")),
                _Reading(date(2026, 1, 1), Decimal("10000"), Decimal("1.4")),
            ],
            id="rising_tread",
        ),
    ],
)
def test_the_threshold_beats_every_rate_prerequisite(readings):
    """C7. None of these prerequisites make a worn tire un-worn."""
    tire = _tire_with(readings, Decimal("2.0"))
    tire.tread_depth_mm = Decimal("1.5")
    result = project_wear(tire, Decimal("12000"), readings)
    assert result.status is WearStatus.AT_OR_BELOW_MINIMUM
    assert result.km_remaining == Decimal("0")


def test_a_worn_tire_with_no_readings_invents_no_date():
    """C8. The threshold reads the tire's own tread, the same scalar the
    card shows and the reminder tests, so all three agree by construction.
    With no reading there is no date, and `utc_now()` is not a substitute."""
    tire = _tire_with([], Decimal("2.0"))
    tire.tread_depth_mm = Decimal("1.5")
    result = project_wear(tire, Decimal("12000"), [])
    assert result.status is WearStatus.AT_OR_BELOW_MINIMUM
    assert result.km_remaining == Decimal("0")
    assert result.wear_date is None


def test_a_cleared_tread_scalar_still_replaces_now_from_the_reading():
    """C8's fallback. The task-5 brief said to delete this as unreachable
    once the hoisted C7 check landed. It is not: the hoisted check reads
    `tire.tread_depth_mm`, the tire's own scalar, and that field is nullable.
    `TireUpdate` accepts an explicit null for it and `update_tire` uses
    `exclude_unset`, so a user who clears the tire's scalar tread in the
    editor leaves the scalar None while readings below the minimum still
    exist. The hoisted check cannot see that case; it must fall through to
    the reading-derived `remaining_tread <= 0` branch further down. Deleting
    that branch turns this into a PROJECTED result with a negative
    `km_remaining` instead of AT_OR_BELOW_MINIMUM.
    """
    readings = [
        _Reading(date(2026, 7, 1), Decimal("15000"), Decimal("1.0")),
        _Reading(date(2026, 2, 1), Decimal("11000"), Decimal("5.0")),
    ]
    tire = _tire_with(readings, Decimal("2.0"))
    tire.tread_depth_mm = None
    result = project_wear(tire, Decimal("15000"), readings)
    assert result.status is WearStatus.AT_OR_BELOW_MINIMUM
    assert result.km_remaining == Decimal("0")


def _seasonal_tire(min_tread):
    """Two mount periods with a storage gap between them.

    The existing `_tire_with` builds ONE continuous period, where the
    interval intersection and the raw odometer delta are equal BY
    CONSTRUCTION. No assertion on that fixture can distinguish the correct
    implementation from the broken one, which is why the defect shipped.
    """
    from app.models.tire import Tire, TireMountPeriod

    tire = Tire(vin="V" * 17, position="FL", min_tread_mm=min_tread)
    tire.mount_periods = [
        TireMountPeriod(
            id=1,
            position="FL",
            mounted_on=date(2026, 1, 1),
            dismounted_on=date(2026, 3, 31),
            mounted_odometer_km=Decimal("0"),
            dismounted_odometer_km=Decimal("12000"),
        ),
        TireMountPeriod(
            id=2,
            position="FL",
            mounted_on=date(2026, 7, 1),
            dismounted_on=date(2026, 10, 31),
            mounted_odometer_km=Decimal("20000"),
            dismounted_odometer_km=Decimal("26000"),
        ),
    ]
    return tire


def test_project_wear_excludes_distance_driven_on_the_other_set():
    """The seasonal regression. Spec A promised this test and never wrote it.

    Readings at 10,000 and 22,000, tread 6.0 to 4.0 mm, minimum 2.0. Driven
    on THIS tire between them: 2,000 + 2,000 = 4,000 km, so 2.0 mm of usable
    tread remains at 2.0 mm per 4,000 km, which is 4,000 km of life. The raw
    odometer span is 12,000 km and yields 12,000.
    """
    readings = [
        _Reading(date(2026, 8, 1), Decimal("22000"), Decimal("4.0")),
        _Reading(date(2026, 3, 1), Decimal("10000"), Decimal("6.0")),
    ]
    result = project_wear(_seasonal_tire(Decimal("2.0")), Decimal("26000"), readings)
    assert result.status is WearStatus.PROJECTED
    assert result.km_remaining == Decimal("4000.0")


def _migrated_then_remounted_tire():
    """A migrated assumed period, later bounded by a real dismount, followed
    by a fresh open period whose bounds cover both readings.

    Shared by the recovery test and the blocking-list test below: both need
    this exact migrated-then-remounted shape, and the blocking-list test
    additionally needs the readings attached to `tire.readings` (not just
    passed to `project_wear`), because `_to_response` reads that relationship
    directly rather than taking an override. `TireReading` instances (not the
    lightweight `_Reading` stand-in) are required here: `_to_response`
    serialises `tire.readings` through `TireReadingResponse.model_validate`,
    which needs `id`/`tire_id`/`vin`/`created_at` that `_Reading` does not
    carry.
    """
    from app.models.tire import Tire, TireMountPeriod, TireReading

    tire = Tire(
        id=1,
        vin="V" * 17,
        position="FL",
        min_tread_mm=Decimal("2.0"),
        created_at=datetime(2026, 1, 1),
    )
    tire.mount_periods = [
        TireMountPeriod(
            id=1,
            position="FL",
            mounted_on=None,
            dismounted_on=date(2026, 3, 31),
            mounted_odometer_km=None,
            dismounted_odometer_km=Decimal("10000"),
            is_assumed=True,
        ),
        TireMountPeriod(
            id=2,
            position="FL",
            mounted_on=date(2026, 4, 1),
            dismounted_on=None,
            mounted_odometer_km=Decimal("10000"),
            is_assumed=False,
        ),
    ]
    tire.readings = [
        TireReading(
            id=1,
            tire_id=1,
            vin=tire.vin,
            recorded_at=date(2026, 5, 1),
            odometer_km=Decimal("12000"),
            tread_depth_mm=Decimal("4.0"),
            created_at=datetime(2026, 5, 1),
        ),
        TireReading(
            id=2,
            tire_id=1,
            vin=tire.vin,
            recorded_at=date(2026, 4, 2),
            odometer_km=Decimal("10000"),
            tread_depth_mm=Decimal("6.0"),
            created_at=datetime(2026, 4, 2),
        ),
    ]
    return tire


def test_a_migrated_tire_recovers_once_a_dismount_bounds_its_assumed_period():
    """Spec A promised this one too. Today the projection is suppressed
    because LIFETIME distance is incomplete, even though both readings sit
    inside a fully known later mount."""
    tire = _migrated_then_remounted_tire()
    result = project_wear(tire, Decimal("12000"), tire.readings)
    assert result.status is WearStatus.PROJECTED
    assert result.km_remaining == Decimal("2000.0")
    assert result.blocking_period_ids == []


def test_a_clean_projection_still_reports_its_lifetime_blocker():
    """A clean projection does not erase the lifetime figure's own blocker.

    NOTE: this does NOT, by itself, prove `_to_response` unions the two
    blocking lists rather than `or`-ing them. On this fixture
    `wear.blocking_period_ids` is empty, so `[1] or []` and
    `sorted({1} | set())` both evaluate to `[1]` -- there is nothing on the
    wear side for `or` to mask. See
    `test_wear_blockers_are_not_masked_by_lifetime_blockers` below for the
    fixture that actually distinguishes the two.
    """
    from app.services.tire_service import TireService

    tire = _migrated_then_remounted_tire()
    # `_to_response` is a pure formatting method: it reads the tire and the
    # two calculations and touches no session. Constructed without __init__
    # so the test needs no database.
    service = TireService.__new__(TireService)
    payload = service._to_response(tire, current_odometer=Decimal("12000"))

    assert payload.wear_status == "projected"
    assert payload.distance_status == "incomplete"
    # The assumed period still blocks the LIFETIME figure, and must still be
    # named, but it must not be the only thing the field can ever say.
    assert payload.blocking_period_ids == [1]


def _overlapping_periods_tire():
    """Three periods shaped so the lifetime and interval blocker lists
    genuinely diverge, which `_migrated_then_remounted_tire()` cannot do.

    `distance_between` only ever blocks on a MISSING bound when the period
    cannot be proven disjoint from the reading interval -- and any period
    missing a bound blocks the LIFETIME figure unconditionally, so that kind
    of block is always a subset of the lifetime blockers. `or` and union
    agree whenever the wear side can only ever be a subset of the distance
    side.

    The two lists can only diverge when the interval helper blocks for a
    reason `distance_on_tire` does not check at all: overlapping,
    FULLY-BOUNDED periods. `distance_on_tire` sums every bounded period
    unconditionally and never checks for overlap between them, so periods
    2 and 3 below never appear in its blocking list, only in the interval
    helper's.

    - Period 1: missing its start odometer, and dismounted at 8,000 km --
      at or below the older reading's 10,000 km, so `distance_between`'s
      near-bound proof (C2) correctly excludes it from the interval. It
      still blocks the LIFETIME figure, since `distance_on_tire` has no
      such exclusion.
    - Periods 2 and 3: both fully bounded, both inside the [10000, 12000]
      reading interval, and overlapping each other by 500 km
      (11000-11500), so the interval helper reports `OVERLAPPING_HISTORY`
      naming them. Neither is missing a bound, so neither ever reaches
      `distance_on_tire`'s blocking list.
    """
    from app.models.tire import Tire, TireMountPeriod, TireReading

    tire = Tire(
        id=1,
        vin="V" * 17,
        position="FL",
        min_tread_mm=Decimal("2.0"),
        created_at=datetime(2026, 1, 1),
    )
    tire.mount_periods = [
        TireMountPeriod(
            id=1,
            position="FL",
            mounted_on=None,
            dismounted_on=date(2026, 3, 31),
            mounted_odometer_km=None,
            dismounted_odometer_km=Decimal("8000"),
            is_assumed=True,
        ),
        TireMountPeriod(
            id=2,
            position="FL",
            mounted_on=date(2026, 4, 1),
            dismounted_on=date(2026, 4, 20),
            mounted_odometer_km=Decimal("10000"),
            dismounted_odometer_km=Decimal("11500"),
            is_assumed=False,
        ),
        TireMountPeriod(
            id=3,
            position="FL",
            mounted_on=date(2026, 4, 10),
            dismounted_on=date(2026, 4, 30),
            mounted_odometer_km=Decimal("11000"),
            dismounted_odometer_km=Decimal("12000"),
            is_assumed=False,
        ),
    ]
    tire.readings = [
        TireReading(
            id=1,
            tire_id=1,
            vin=tire.vin,
            recorded_at=date(2026, 5, 1),
            odometer_km=Decimal("12000"),
            tread_depth_mm=Decimal("4.0"),
            created_at=datetime(2026, 5, 1),
        ),
        TireReading(
            id=2,
            tire_id=1,
            vin=tire.vin,
            recorded_at=date(2026, 4, 2),
            odometer_km=Decimal("10000"),
            tread_depth_mm=Decimal("6.0"),
            created_at=datetime(2026, 4, 2),
        ),
    ]
    return tire


def test_wear_blockers_are_not_masked_by_lifetime_blockers():
    """The response boundary used to `or` these two lists together, so any
    lifetime blocker hid the wear blockers completely.

    The overlapping-periods tire is the fixture that actually forces the two
    lists apart: the lifetime figure is blocked by period 1 alone (a missing
    bound, correctly excluded from the interval by C2), while the projection
    is separately blocked by periods 2 and 3 (a fully-bounded overlap
    `distance_on_tire` never checks for). `or` would report only `[1]`,
    silently dropping the periods the projection actually needs repaired.
    """
    from app.services.tire_service import TireService

    tire = _overlapping_periods_tire()
    service = TireService.__new__(TireService)
    payload = service._to_response(tire, current_odometer=Decimal("12000"))

    assert payload.wear_status == "no_distance_on_tire"
    assert payload.distance_status == "incomplete"
    # Union of {1} (lifetime) and {2, 3} (interval). `or` would have produced
    # [1] alone, since {1} is non-empty and therefore short-circuits it.
    assert payload.blocking_period_ids == [1, 2, 3]


def test_parse_fuel_command_metric():
    vehicle_key, payload = _parse_fuel_command("fuel 1HGCM82633A004352 45000 40.5 1.55 62.78")
    assert vehicle_key == "1HGCM82633A004352"
    assert payload.odometer_km == Decimal("45000")
    assert payload.liters == Decimal("40.5")
    assert payload.kwh is None
    assert payload.price_per_unit == Decimal("1.55")
    assert payload.cost == Decimal("62.78")
    assert payload.price_basis == "per_volume"


def test_parse_fuel_command_imperial_and_kwh():
    vehicle_key, payload = _parse_fuel_command("fuel Model3 15000mi 42.5kWh 0.20 8.50")
    assert vehicle_key == "Model3"
    assert payload.odometer_km == Decimal("15000") * Decimal("1.609344")
    assert payload.kwh == Decimal("42.5")
    assert payload.liters is None
    assert payload.price_basis == "per_kwh"
    assert payload.price_per_unit == Decimal("0.20")
    assert payload.cost == Decimal("8.50")


def test_parse_fuel_command_gal_converts_price_to_per_liter():
    _key, payload = _parse_fuel_command("fuel Civic 10000mi 12gal 3.50")
    assert payload.liters == Decimal("12") * Decimal("3.785411784")
    assert payload.price_per_unit == Decimal("3.50") / Decimal("3.785411784")
    assert payload.price_basis == "per_volume"


def test_parse_fuel_command_rejects_garbage():
    with pytest.raises(HTTPException) as exc:
        _parse_fuel_command("charge now please")
    assert exc.value.status_code == 400


def test_fuel_record_create_accepts_ev_charge_session_fields():
    record = FuelRecordCreate(
        vin="5YJSA1E26MF123456",
        date=date(2026, 3, 1),
        odometer_km=Decimal("25000"),
        kwh=Decimal("42.5"),
        price_basis="per_kwh",
        price_per_unit=Decimal("0.20"),
        cost=Decimal("8.50"),
        soc_start_pct=Decimal("18"),
        soc_end_pct=Decimal("80"),
        charge_level="L2",
        charge_location="home",
        battery_soh_pct=Decimal("94"),
        fuel_type_used="electric",
    )
    assert record.soc_start_pct == Decimal("18")
    assert record.charge_level == "L2"
    assert record.charge_location == "home"


def test_fuel_record_create_rejects_bad_charge_level():
    with pytest.raises(Exception):
        FuelRecordCreate(
            vin="5YJSA1E26MF123456",
            date=date(2026, 3, 1),
            odometer_km=Decimal("25000"),
            kwh=Decimal("10"),
            charge_level="L3",
        )


class TestChargeFieldValidation:
    """Create was validated; update and the webhook payload were not."""

    def test_update_rejects_bad_charge_level(self):
        from app.schemas.fuel import FuelRecordUpdate

        with pytest.raises(ValidationError):
            FuelRecordUpdate(charge_level="L3")

    def test_update_rejects_bad_charge_location(self):
        from app.schemas.fuel import FuelRecordUpdate

        with pytest.raises(ValidationError):
            FuelRecordUpdate(charge_location="work")

    def test_update_accepts_valid_values(self):
        from app.schemas.fuel import FuelRecordUpdate

        assert FuelRecordUpdate(charge_level="DCFC").charge_level == "DCFC"
        assert FuelRecordUpdate(charge_location="home").charge_location == "home"

    def test_webhook_payload_rejects_bad_charge_level(self):
        from app.routes.webhooks import WebhookFuelPayload

        with pytest.raises(ValidationError):
            WebhookFuelPayload(vin="1HGCM82633A004352", charge_level="L4")

    @pytest.mark.parametrize(
        "field,value",
        [
            ("soc_start_pct", 101),
            ("soc_end_pct", -1),
            ("battery_soh_pct", 150),
            ("liters", -5),
            ("odometer_km", -1),
        ],
    )
    def test_webhook_payload_rejects_out_of_range(self, field, value):
        from app.routes.webhooks import WebhookFuelPayload

        with pytest.raises(ValidationError):
            WebhookFuelPayload(vin="1HGCM82633A004352", **{field: value})

    def test_webhook_payload_allows_charge_session_without_odometer_or_amount(self):
        """The webhook contract is deliberately looser than FuelRecordCreate."""
        from app.routes.webhooks import WebhookFuelPayload

        payload = WebhookFuelPayload(vin="1HGCM82633A004352", kwh=45)
        assert payload.odometer_km is None


def test_parse_fuel_command_accepts_long_nickname():
    """Vehicle.nickname is String(100); the payload's vin is capped at 17.

    Building the payload straight from the raw key raised a bare pydantic
    ValidationError inside the handler, surfacing as a 500 rather than a 400,
    and Telegram then retried the same update forever.
    """
    vehicle_key, payload = _parse_fuel_command("fuel MyOtherDailyDriver 45000 40")
    assert vehicle_key == "MyOtherDailyDriver"
    assert payload.odometer_km == Decimal("45000")


class TestParseOptions:
    """Odometer unit and decimal separator are declared, never guessed."""

    def test_comma_decimal_is_not_multiplied(self):
        from app.services.import_adapters.fuel_csv import ParseOptions

        csv_data = (
            "Data,Odômetro,Quantidade (litros),Preço/litro,Total\n"
            '2026-01-15,45000,"35,2","1,55","54,56"\n'
        )
        rows = parse_drivvo(csv_data, ParseOptions(decimal_separator="comma"))
        assert rows[0]["liters"] == Decimal("35.2")
        assert rows[0]["price_per_unit"] == Decimal("1.55")

    def test_dot_separator_strips_thousands_commas(self):
        from app.services.import_adapters.fuel_csv import _dec

        assert _dec("1,234.5") == Decimal("1234.5")

    def test_comma_separator_converts_to_dot(self):
        from app.services.import_adapters.fuel_csv import _dec

        assert _dec("35,2", sep="comma") == Decimal("35.2")
        assert _dec("1.234,5", sep="comma") == Decimal("1234.5")

    def test_miles_odometer_is_converted(self):
        from app.services.import_adapters.fuel_csv import ParseOptions

        csv_data = "Date,Odometer,Gallons,Price,Total cost\n2026-01-15,12345,10,3.50,35.00\n"
        rows = parse_fuelio(csv_data, ParseOptions(odometer_unit="mi"))
        assert rows[0]["odometer_km"] == Decimal("12345") * Decimal("1.609344")

    def test_unambiguous_header_overrides_the_option(self):
        from app.services.import_adapters.fuel_csv import ParseOptions

        csv_data = "Date,Odometer (mi),Liters\n2026-01-15,12345,40\n"
        rows = parse_drivvo(csv_data, ParseOptions(odometer_unit="km"))
        assert rows[0]["odometer_km"] == Decimal("12345") * Decimal("1.609344")

    def test_km_header_ignores_a_miles_declaration(self):
        from app.services.import_adapters.fuel_csv import ParseOptions

        csv_data = "Date,Odometer (km),Liters\n2026-01-15,12345,40\n"
        rows = parse_drivvo(csv_data, ParseOptions(odometer_unit="mi"))
        assert rows[0]["odometer_km"] == Decimal("12345")

    def test_defaults_are_metric_and_dot(self):
        from app.services.import_adapters.fuel_csv import ParseOptions

        assert ParseOptions().odometer_unit == "km"
        assert ParseOptions().decimal_separator == "dot"

    def test_parsers_still_work_without_options(self):
        csv_data = "Date,Odometer,Liters,Price,Total cost\n2026-01-15,45000,40,1.50,60.00\n"
        rows = parse_fuelio(csv_data)
        assert rows[0]["odometer_km"] == Decimal("45000")


def test_odometro_alone_is_not_classified_drivvo():
    """`a and b or c` binds as `(a and b) or c`.

    Any header set containing 'odometro' was classified Drivvo regardless of the
    intended 'data' guard, so the file went to a parser that finds none of its
    columns and silently imported zero rows. After the fix it is unrecognized,
    which the endpoint reports as an explicit 400 instead.
    """
    assert detect_format("Fecha,odometro,Gallons,Price\n2026-01-15,45000,10,3.50\n") is None


def test_drivvo_pt_still_detected():
    assert detect_format("Data,Odômetro,Quantidade (litros)\n2026-01-15,45000,35.2\n") == "drivvo"
