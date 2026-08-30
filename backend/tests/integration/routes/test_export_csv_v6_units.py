"""What the four unit-bearing CSV exports actually put on the wire (v6).

Issue #152 phase 2b task 3. Task 2 taught the importer to READ schema v6;
this is the half that WRITES it. Everything here goes through the HTTP
surface, because the thing under test is the wiring: which unit set a route
resolves, and what it then stamps into the header row and the marker column.

Discriminating, not sampling
----------------------------
An implementation that wrote `marker = current_user.unit_preference` and
picked headers off `unit_preference` alone passes "metric account gets metric,
imperial account gets imperial" all day. The cases that kill it are here:

- a `custom` account whose eleven columns spell out the metric preset must
  emit marker `metric`, not `custom`;
- a `metric` account with ONE override must emit `custom`, not `metric`;
- an `auth_mode=none` request has no account at all and uses the instance
  default;
- an explicit `?units=metric` beats an imperial account outright;
- an explicit `?units=imperial` from a UK-gallon account emits US gallons
  under marker `imperial`, even with `imperial_gallon_standard` set to `uk`.

The callers are admins exporting a vehicle they do not own, which also pins
that the export renders the CALLER's units and never the OWNER's.

Every expected header row and every expected cell is a HAND-WRITTEN literal.
Tests share one database with no per-test rollback, so every row created here
is torn down in `finally`, and every username, email and VIN is scoped to this
module.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.units import IMPERIAL_PRESET, METRIC_PRESET, UnitSet
from app.models.def_record import DEFRecord
from app.models.fuel import FuelRecord
from app.models.hours import HoursRecord
from app.models.odometer import OdometerRecord
from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit
from app.models.settings import Setting
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.auth import create_access_token
from app.utils.default_unit_prefs import DEFAULT_UNIT_PREFS_KEY
from app.utils.gallon_flavour import GALLON_STANDARD_KEY

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# Pre-computed argon2id hash for "testpassword123", copied from
# tests/conftest.py: hashing here would need threads these containers do not
# always have.
_PASSWORD_HASH = "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"

_OWNER = "v6emit_owner"
_METRIC_CALLER = "v6emit_metric"
_ONE_OVERRIDE_CALLER = "v6emit_oneoff"
_UK_CALLER = "v6emit_uk"
_USERNAMES = (_OWNER, _METRIC_CALLER, _ONE_OVERRIDE_CALLER, _UK_CALLER)

_VIN = "V6EMITSRC00000001"
_DST_VIN = "V6EMITDST00000001"
_VINS = (_VIN, _DST_VIN)

# Imperial with UK gallons: the shape a UK instance seeds (migration 093).
UK_IMPERIAL = UnitSet.model_validate(
    IMPERIAL_PRESET.model_dump()
    | {"volume": "gal_uk", "consumption": "mpg_uk", "secondary_gallon": "uk"}
)

# --- seeded canonical values, and every unit's rendering of them ------------
#
# 500.00 km / 1.60934        = 310.68562...  -> "310.686" at 3 dp
# 40.000 L  / 3.78541        = 10.566876...  -> "10.5669" at 4 dp
# 40.000 L  / 4.54609        = 8.798787...   -> "8.7988"  at 4 dp
# 1.500/L   * 3.78541        = 5.678115      -> "5.678"   at 3 dp
# 1.500/L   * 4.54609        = 6.819135      -> "6.819"   at 3 dp
# 20.0 C    * 9/5 + 32       = 68.0          -> "68.0"    at 1 dp
# 235.214   / 8.00           = 29.40175      -> "29.402"  at 3 dp
# 282.481   / 8.00           = 35.310125     -> "35.310"  at 3 dp
# 100.0 kmh / 1.60934        = 62.13723...   -> "62.14"   at 2 dp
_FUEL_ODOMETER_KM = Decimal("500.00")
_FUEL_LITERS = Decimal("40.000")
_FUEL_PRICE_PER_L = Decimal("1.500")
_FUEL_TEMP_C = Decimal("20.0")
_FUEL_L_100KM = Decimal("8.00")
_FUEL_SPEED_KMH = Decimal("100.0")

# 600.00 km / 1.60934 = 372.82372... -> "372.824"
_SERVICE_ODOMETER_KM = Decimal("600.00")
# 1000.00 km / 1.60934 = 621.37265... -> "621.373"
_ODOMETER_KM = Decimal("1000.00")
# 10.000 L / 4.54609 = 2.19969... -> "2.1997"; 0.850 * 4.54609 = 3.8641765
_DEF_LITERS = Decimal("10.000")
_DEF_PRICE_PER_L = Decimal("0.850")

_FUEL_HEADERS_METRIC = [
    "units_version",
    "unit_system",
    "Date",
    "Filled At",
    "Odometer (km)",
    "Engine Hours",
    "Volume (L)",
    "Price Per Unit (L)",
    "Rebate",
    "Total Cost",
    "Full Tank",
    "Missed Fill-up",
    "Is Hauling",
    "Fuel Type Used",
    "Station ID",
    "Station",
    "Driver ID",
    "Driver",
    "Payment Method",
    "Trip Type",
    "Outside Temp (c)",
    "OBC Economy (l_100km)",
    "OBC Avg Speed (kmh)",
    "OBC Trip Duration (s)",
    "SOC Start (%)",
    "SOC End (%)",
    "Charge Level",
    "Charge Location",
    "Battery SOH (%)",
    "Notes",
]

_FUEL_HEADERS_UK_IMPERIAL = [
    "units_version",
    "unit_system",
    "Date",
    "Filled At",
    "Odometer (mi)",
    "Engine Hours",
    "Volume (gal_uk)",
    "Price Per Unit (gal_uk)",
    "Rebate",
    "Total Cost",
    "Full Tank",
    "Missed Fill-up",
    "Is Hauling",
    "Fuel Type Used",
    "Station ID",
    "Station",
    "Driver ID",
    "Driver",
    "Payment Method",
    "Trip Type",
    "Outside Temp (f)",
    "OBC Economy (mpg_uk)",
    "OBC Avg Speed (mph)",
    "OBC Trip Duration (s)",
    "SOC Start (%)",
    "SOC End (%)",
    "Charge Level",
    "Charge Location",
    "Battery SOH (%)",
    "Notes",
]


def _headers_for(user: User) -> dict[str, str]:
    """Bearer headers for `user`, matching conftest's `auth_headers`."""
    token = create_access_token(data={"sub": str(user.id), "username": user.username})
    return {"Authorization": f"Bearer {token}"}


async def _make_materialised_user(
    db: AsyncSession, username: str, units: UnitSet, *, is_admin: bool = True
) -> User:
    """A `custom` account with all eleven quantities written out explicitly."""
    user = User(
        username=username,
        email=f"{username}@example.com",
        hashed_password=_PASSWORD_HASH,
        is_active=True,
        is_admin=is_admin,
        unit_preference="custom",
        show_both_units=False,
        unit_distance=units.distance,
        unit_speed=units.speed,
        unit_length=units.length,
        unit_volume=units.volume,
        unit_consumption=units.consumption,
        unit_pressure=units.pressure,
        unit_temperature=units.temperature,
        unit_mass=units.mass,
        unit_torque=units.torque,
        unit_tread=units.tread,
        secondary_gallon=units.secondary_gallon,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _make_preset_user(
    db: AsyncSession, username: str, preference: str, **overrides: str
) -> User:
    """A preset account with only the named override columns written.

    Everything else stays NULL, which is what makes this a genuine "preset
    plus one override" row rather than a materialised custom one.
    """
    user = User(
        username=username,
        email=f"{username}@example.com",
        hashed_password=_PASSWORD_HASH,
        is_active=True,
        is_admin=True,
        unit_preference=preference,
        show_both_units=False,
        **overrides,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _set_setting(db: AsyncSession, key: str, value: str | None) -> None:
    """Upsert (or delete, for `value=None`) one settings row."""
    existing = (await db.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
    if value is None:
        if existing is not None:
            await db.delete(existing)
    elif existing is None:
        db.add(Setting(key=key, value=value))
    else:
        existing.value = value
    await db.commit()


async def _seed(db: AsyncSession, owner: User) -> None:
    """One vehicle owned by `owner`, plus one record in each unit-bearing pair."""
    for vin, nickname in ((_VIN, "V6 Emission Src"), (_DST_VIN, "V6 Emission Dst")):
        db.add(
            Vehicle(
                vin=vin,
                user_id=owner.id,
                nickname=nickname,
                vehicle_type="Car",
                year=2024,
                make="Test",
                model="V6Emit",
            )
        )
    await db.commit()

    db.add(
        FuelRecord(
            vin=_VIN,
            date=date(2026, 5, 18),
            odometer_km=_FUEL_ODOMETER_KM,
            engine_hours=Decimal("42.3"),
            liters=_FUEL_LITERS,
            price_per_unit=_FUEL_PRICE_PER_L,
            price_basis="per_volume",
            cost=Decimal("60.00"),
            is_full_tank=True,
            outside_temp_c=_FUEL_TEMP_C,
            obc_l_per_100km=_FUEL_L_100KM,
            obc_avg_speed_kmh=_FUEL_SPEED_KMH,
        )
    )
    db.add(
        DEFRecord(
            vin=_VIN,
            date=date(2026, 5, 19),
            odometer_km=_FUEL_ODOMETER_KM,
            liters=_DEF_LITERS,
            price_per_unit=_DEF_PRICE_PER_L,
            cost=Decimal("8.50"),
        )
    )
    db.add(
        OdometerRecord(
            vin=_VIN,
            date=date(2026, 5, 20),
            odometer_km=_ODOMETER_KM,
            notes="Odometer pin",
        )
    )
    db.add(
        HoursRecord(
            vin=_VIN,
            date=date(2026, 5, 22),
            engine_hours=Decimal("77.7"),
            notes="Hours pin",
            source="manual",
        )
    )
    visit = ServiceVisit(
        vin=_VIN,
        date=date(2026, 5, 21),
        odometer_km=_SERVICE_ODOMETER_KM,
        service_category="Maintenance",
    )
    db.add(visit)
    await db.flush()
    db.add(ServiceLineItem(visit_id=visit.id, description="Oil change", cost=Decimal("20.00")))
    await db.commit()


async def _cleanup(db: AsyncSession) -> None:
    """Remove every row this module creates, plus the settings it overwrites.

    Ordered child-first rather than relying on cascade, so the teardown does
    not depend on the FK pragma being on for whichever dialect is running.
    """
    visit_ids = (
        (await db.execute(select(ServiceVisit.id).where(ServiceVisit.vin.in_(_VINS))))
        .scalars()
        .all()
    )
    if visit_ids:
        await db.execute(delete(ServiceLineItem).where(ServiceLineItem.visit_id.in_(visit_ids)))
    await db.execute(delete(ServiceVisit).where(ServiceVisit.vin.in_(_VINS)))
    await db.execute(delete(FuelRecord).where(FuelRecord.vin.in_(_VINS)))
    await db.execute(delete(DEFRecord).where(DEFRecord.vin.in_(_VINS)))
    await db.execute(delete(OdometerRecord).where(OdometerRecord.vin.in_(_VINS)))
    await db.execute(delete(HoursRecord).where(HoursRecord.vin.in_(_VINS)))
    await db.execute(delete(Vehicle).where(Vehicle.vin.in_(_VINS)))
    await db.execute(delete(User).where(User.username.in_(_USERNAMES)))
    await db.commit()
    await _set_setting(db, DEFAULT_UNIT_PREFS_KEY, None)
    await _set_setting(db, GALLON_STANDARD_KEY, None)
    await _set_setting(db, "auth_mode", "local")


@pytest.fixture(autouse=True)
def _reset_export_rate_limit() -> None:
    """CSV exports are capped at 5/minute and this module makes far more.

    Same approach as `test_widget.py`: wipe the route module's own limiter
    storage before each test, so a 429 earned by a sibling test cannot
    masquerade as a units failure.
    """
    from app.routes.export import limiter as export_limiter

    export_limiter.reset()


def _read(body: str) -> tuple[list[str], dict[str, str]]:
    """The header row and the single data row of a one-record export."""
    reader = csv.DictReader(io.StringIO(body))
    rows = list(reader)
    assert reader.fieldnames is not None
    assert len(rows) == 1, f"expected exactly one data row, got {len(rows)}"
    return list(reader.fieldnames), rows[0]


class TestMarkerDiscriminatesOnTheResolvedSet:
    """`metric | imperial | custom`, from the resolved set and nothing else."""

    async def test_a_custom_account_resolving_to_metric_emits_metric(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The killer case for `marker = user.unit_preference`, which would
        say `custom` here. The account IS stored as `custom`; its eleven
        columns just happen to spell out the metric preset."""
        try:
            owner = await _make_materialised_user(db_session, _OWNER, IMPERIAL_PRESET)
            caller = await _make_materialised_user(db_session, _METRIC_CALLER, METRIC_PRESET)
            await _seed(db_session, owner)

            response = await client.get(
                f"/api/export/vehicles/{_VIN}/fuel/csv", headers=_headers_for(caller)
            )

            assert response.status_code == 200, response.text
            headers, row = _read(response.text)
            assert headers == _FUEL_HEADERS_METRIC
            assert row["unit_system"] == "metric"
            assert row["units_version"] == "6"
            assert row["Odometer (km)"] == "500.00"
            assert row["Volume (L)"] == "40.000"
            assert row["Price Per Unit (L)"] == "1.500"
        finally:
            await _cleanup(db_session)

    async def test_a_preset_account_with_one_override_emits_custom(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The other killer case: `unit_preference` says `metric`, but one
        non-null override column means the resolved set is not a preset. The
        distance column stays metric and only volume moves, which no binary
        metric/imperial marker can describe."""
        try:
            owner = await _make_materialised_user(db_session, _OWNER, IMPERIAL_PRESET)
            caller = await _make_preset_user(
                db_session, _ONE_OVERRIDE_CALLER, "metric", unit_volume="gal_uk"
            )
            await _seed(db_session, owner)

            response = await client.get(
                f"/api/export/vehicles/{_VIN}/fuel/csv", headers=_headers_for(caller)
            )

            assert response.status_code == 200, response.text
            headers, row = _read(response.text)
            assert row["unit_system"] == "custom"
            assert "Odometer (km)" in headers
            assert "Volume (gal_uk)" in headers
            assert "Price Per Unit (gal_uk)" in headers
            assert row["Odometer (km)"] == "500.00"
            assert row["Volume (gal_uk)"] == "8.7988"
            assert row["Price Per Unit (gal_uk)"] == "6.819"
            # Consumption and temperature stayed metric: only volume moved.
            assert row["OBC Economy (l_100km)"] == "8.00"
            assert row["Outside Temp (c)"] == "20.0"
        finally:
            await _cleanup(db_session)

    async def test_auth_mode_none_uses_the_instance_default_not_the_owners_units(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """No caller means no preference to resolve, so the instance default
        applies. Three-way discriminating: the instance default is UK
        imperial, the vehicle owner is US imperial, and the pre-v6 behaviour
        was a hardcoded metric default. Only one of the three emits
        `Volume (gal_uk)`."""
        try:
            owner = await _make_materialised_user(db_session, _OWNER, IMPERIAL_PRESET)
            await _seed(db_session, owner)
            await _set_setting(
                db_session, DEFAULT_UNIT_PREFS_KEY, json.dumps(UK_IMPERIAL.model_dump())
            )
            await _set_setting(db_session, "auth_mode", "none")

            # No Authorization header at all: `require_auth` returns None.
            response = await client.get(f"/api/export/vehicles/{_VIN}/fuel/csv")

            assert response.status_code == 200, response.text
            headers, row = _read(response.text)
            assert row["unit_system"] == "custom"
            assert "Volume (gal_uk)" in headers
            assert "Volume (gal_us)" not in headers
            assert "Volume (L)" not in headers
            assert row["Odometer (mi)"] == "310.686"
            assert row["Volume (gal_uk)"] == "8.7988"
        finally:
            await _cleanup(db_session)

    async def test_the_marker_is_never_imperial_uk_any_more(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """v6 stops EMITTING `imperial_uk`; the gallon flavour travels in the
        header token instead. The importer still ACCEPTS it forever."""
        try:
            owner = await _make_materialised_user(db_session, _OWNER, IMPERIAL_PRESET)
            caller = await _make_materialised_user(db_session, _UK_CALLER, UK_IMPERIAL)
            await _seed(db_session, owner)
            await _set_setting(db_session, GALLON_STANDARD_KEY, "uk")

            response = await client.get(
                f"/api/export/vehicles/{_VIN}/fuel/csv", headers=_headers_for(caller)
            )

            assert response.status_code == 200, response.text
            _headers, row = _read(response.text)
            assert row["unit_system"] == "custom"
            assert row["unit_system"] != "imperial_uk"
        finally:
            await _cleanup(db_session)


class TestExplicitUnitsParameterWinsOutright:
    """`?units=metric|imperial` produces a clean preset export, whoever asks."""

    async def test_explicit_metric_beats_an_imperial_account(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        try:
            owner = await _make_materialised_user(db_session, _OWNER, IMPERIAL_PRESET)
            await _seed(db_session, owner)

            response = await client.get(
                f"/api/export/vehicles/{_VIN}/fuel/csv?units=metric",
                headers=_headers_for(owner),
            )

            assert response.status_code == 200, response.text
            headers, row = _read(response.text)
            assert headers == _FUEL_HEADERS_METRIC
            assert row["unit_system"] == "metric"
            assert row["Odometer (km)"] == "500.00"
            assert row["Volume (L)"] == "40.000"
        finally:
            await _cleanup(db_session)

    async def test_explicit_imperial_from_a_uk_account_emits_us_gallons(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Exit criterion 11, and a deliberate contract change: before v6 an
        explicit `?units=imperial` on a UK instance emitted UK gallons under
        marker `imperial_uk`. `imperial` now means the imperial PRESET, whose
        volume is `gal_us`. The `imperial_gallon_standard` row is seeded to
        `uk` here precisely to prove it no longer reaches this path."""
        try:
            owner = await _make_materialised_user(db_session, _OWNER, IMPERIAL_PRESET)
            caller = await _make_materialised_user(db_session, _UK_CALLER, UK_IMPERIAL)
            await _seed(db_session, owner)
            await _set_setting(db_session, GALLON_STANDARD_KEY, "uk")

            response = await client.get(
                f"/api/export/vehicles/{_VIN}/fuel/csv?units=imperial",
                headers=_headers_for(caller),
            )

            assert response.status_code == 200, response.text
            headers, row = _read(response.text)
            assert row["unit_system"] == "imperial"
            assert "Volume (gal_us)" in headers
            assert "Volume (gal_uk)" not in headers
            # 40 L is 10.5669 US gallons, not 8.7988 UK ones.
            assert row["Volume (gal_us)"] == "10.5669"
            assert row["Price Per Unit (gal_us)"] == "5.678"
            assert row["OBC Economy (mpg_us)"] == "29.402"
        finally:
            await _cleanup(db_session)


class TestEveryUnitBearingPairEmitsTokenisedHeaders:
    """All four pairs, one unit set, full ordered header rows."""

    async def test_fuel_headers_and_values_under_uk_imperial(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        try:
            owner = await _make_materialised_user(db_session, _OWNER, IMPERIAL_PRESET)
            caller = await _make_materialised_user(db_session, _UK_CALLER, UK_IMPERIAL)
            await _seed(db_session, owner)

            response = await client.get(
                f"/api/export/vehicles/{_VIN}/fuel/csv", headers=_headers_for(caller)
            )

            assert response.status_code == 200, response.text
            headers, row = _read(response.text)
            assert headers == _FUEL_HEADERS_UK_IMPERIAL
            assert row["unit_system"] == "custom"
            assert row["Odometer (mi)"] == "310.686"
            assert row["Volume (gal_uk)"] == "8.7988"
            assert row["Price Per Unit (gal_uk)"] == "6.819"
            assert row["Outside Temp (f)"] == "68.0"
            assert row["OBC Economy (mpg_uk)"] == "35.310"
            assert row["OBC Avg Speed (mph)"] == "62.14"
            # Dimensionless columns are untouched by the unit set.
            assert row["Engine Hours"] == "42.3"
            assert row["Total Cost"] == "60.00"
        finally:
            await _cleanup(db_session)

    async def test_service_headers_and_values_under_uk_imperial(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        try:
            owner = await _make_materialised_user(db_session, _OWNER, IMPERIAL_PRESET)
            caller = await _make_materialised_user(db_session, _UK_CALLER, UK_IMPERIAL)
            await _seed(db_session, owner)

            response = await client.get(
                f"/api/export/vehicles/{_VIN}/service/csv", headers=_headers_for(caller)
            )

            assert response.status_code == 200, response.text
            headers, row = _read(response.text)
            assert headers == [
                "units_version",
                "unit_system",
                "Date",
                "Category",
                "Description",
                "Odometer (mi)",
                "Engine Hours",
                "Cost",
                "Vendor",
                "Notes",
            ]
            assert row["unit_system"] == "custom"
            # 600 km / 1.60934 = 372.82372...
            assert row["Odometer (mi)"] == "372.824"
            assert row["Cost"] == "20.00"
        finally:
            await _cleanup(db_session)

    async def test_def_headers_and_values_under_uk_imperial(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        try:
            owner = await _make_materialised_user(db_session, _OWNER, IMPERIAL_PRESET)
            caller = await _make_materialised_user(db_session, _UK_CALLER, UK_IMPERIAL)
            await _seed(db_session, owner)

            response = await client.get(
                f"/api/export/vehicles/{_VIN}/def/csv", headers=_headers_for(caller)
            )

            assert response.status_code == 200, response.text
            headers, row = _read(response.text)
            assert headers == [
                "units_version",
                "unit_system",
                "Date",
                "Odometer (mi)",
                "Volume (gal_uk)",
                "Price Per Unit (gal_uk)",
                "Total Cost",
                "Fill Level",
                "Source",
                "Brand",
                "Notes",
            ]
            assert row["unit_system"] == "custom"
            assert row["Odometer (mi)"] == "310.686"
            # 10 L / 4.54609 = 2.19969...; 0.850 * 4.54609 = 3.8641765
            assert row["Volume (gal_uk)"] == "2.1997"
            assert row["Price Per Unit (gal_uk)"] == "3.864"
        finally:
            await _cleanup(db_session)

    async def test_odometer_headers_and_values_under_uk_imperial(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        try:
            owner = await _make_materialised_user(db_session, _OWNER, IMPERIAL_PRESET)
            caller = await _make_materialised_user(db_session, _UK_CALLER, UK_IMPERIAL)
            await _seed(db_session, owner)

            response = await client.get(
                f"/api/export/vehicles/{_VIN}/odometer/csv", headers=_headers_for(caller)
            )

            assert response.status_code == 200, response.text
            headers, row = _read(response.text)
            assert headers == ["units_version", "unit_system", "Date", "Reading (mi)", "Notes"]
            assert row["unit_system"] == "custom"
            # 1000 km / 1.60934 = 621.37265...
            assert row["Reading (mi)"] == "621.373"
        finally:
            await _cleanup(db_session)

    async def test_a_dimensionless_pair_is_untouched_by_the_callers_units(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The hours export takes no `?units`, carries no unit-bearing column,
        and must keep saying `metric` however the caller reads numbers."""
        try:
            owner = await _make_materialised_user(db_session, _OWNER, IMPERIAL_PRESET)
            caller = await _make_materialised_user(db_session, _UK_CALLER, UK_IMPERIAL)
            await _seed(db_session, owner)

            response = await client.get(
                f"/api/export/vehicles/{_VIN}/hours/csv", headers=_headers_for(caller)
            )

            assert response.status_code == 200, response.text
            headers, row = _read(response.text)
            assert headers == [
                "units_version",
                "unit_system",
                "Date",
                "Engine Hours",
                "Notes",
                "Source",
            ]
            assert row["units_version"] == "6"
            assert row["unit_system"] == "metric"
            assert row["Engine Hours"] == "77.7"
        finally:
            await _cleanup(db_session)


class TestV6RoundTrip:
    """Export then import must land on the identical canonical values.

    Only meaningful now that emission and parsing have both moved: before this
    task the exporter wrote `Volume (gal_uk)` nowhere, so no test could prove
    the halves met. Values are read back after `expire_all()` so the assertion
    sees what the DATABASE holds at its declared NUMERIC scale, not the
    unrounded Python `Decimal` still sitting in the identity map.
    """

    async def test_a_uk_custom_fuel_export_imports_back_unchanged(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        try:
            owner = await _make_materialised_user(db_session, _OWNER, IMPERIAL_PRESET)
            caller = await _make_materialised_user(db_session, _UK_CALLER, UK_IMPERIAL)
            await _seed(db_session, owner)

            export_resp = await client.get(
                f"/api/export/vehicles/{_VIN}/fuel/csv", headers=_headers_for(caller)
            )
            assert export_resp.status_code == 200, export_resp.text
            # Pin the intermediate file, or this test passes for ANY
            # self-consistent pair of emitter and parser, including the pre-v6
            # metric one it is meant to replace.
            exported_headers, exported_row = _read(export_resp.text)
            assert exported_headers == _FUEL_HEADERS_UK_IMPERIAL
            assert exported_row["unit_system"] == "custom"
            assert exported_row["Volume (gal_uk)"] == "8.7988"

            import_resp = await client.post(
                f"/api/import/vehicles/{_DST_VIN}/fuel/csv",
                headers=_headers_for(caller),
                files={"file": ("fuel.csv", io.BytesIO(export_resp.content), "text/csv")},
            )
            assert import_resp.status_code == 200, import_resp.text
            assert import_resp.json()["success_count"] == 1

            db_session.expire_all()
            row = (
                await db_session.execute(select(FuelRecord).where(FuelRecord.vin == _DST_VIN))
            ).scalar_one()
            assert row.odometer_km == Decimal("500.00")
            assert row.liters == Decimal("40.000")
            assert row.price_per_unit == Decimal("1.500")
            assert row.outside_temp_c == Decimal("20.0")
            assert row.obc_l_per_100km == Decimal("8.00")
            assert row.obc_avg_speed_kmh == Decimal("100.0")
        finally:
            await _cleanup(db_session)

    async def test_an_imperial_odometer_export_imports_back_unchanged(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """`Reading (mi)` is the shape v6 introduces for the standalone
        odometer pair; v2 wrote a bare `Reading` in miles with no marker at
        all, and v3 through v5 could only write `Reading (km)`."""
        try:
            owner = await _make_materialised_user(db_session, _OWNER, IMPERIAL_PRESET)
            caller = await _make_materialised_user(db_session, _UK_CALLER, UK_IMPERIAL)
            await _seed(db_session, owner)

            export_resp = await client.get(
                f"/api/export/vehicles/{_VIN}/odometer/csv", headers=_headers_for(caller)
            )
            assert export_resp.status_code == 200, export_resp.text
            assert "Reading (mi)" in export_resp.text.splitlines()[0]

            import_resp = await client.post(
                f"/api/import/vehicles/{_DST_VIN}/odometer/csv",
                headers=_headers_for(caller),
                files={"file": ("odo.csv", io.BytesIO(export_resp.content), "text/csv")},
            )
            assert import_resp.status_code == 200, import_resp.text
            assert import_resp.json()["success_count"] == 1

            db_session.expire_all()
            row = (
                await db_session.execute(
                    select(OdometerRecord).where(OdometerRecord.vin == _DST_VIN)
                )
            ).scalar_one()
            assert row.odometer_km == Decimal("1000.00")
        finally:
            await _cleanup(db_session)
