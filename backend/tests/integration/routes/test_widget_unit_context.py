"""D7: the widget API's conversion context, driven over BOTH HTTP endpoints.

Widgets use the CONVERSION layer only (R4). `WidgetVehicle.odometer` is
`int | None` and `recent_mpg` is `float | None`, and D7 freezes those fields,
so nothing here may go through `unit_formatting`/`unit_derived`: a string with
a parenthetical counterpart cannot populate a frozen numeric schema.

Three separate contracts are pinned, because each is invisible to the others:

1. **Shape.** Literal key sets, written out by hand, compared with `==`.
   Deriving the expectation from `WidgetVehicle.model_fields` or from the
   returned payload would move with an accidental rename and prove nothing.
2. **Meaning.** D7 freezes field MEANINGS, not only names. `odometer` is
   miles by contract and `odometer_km` is kilometres, for every owner. A
   naive `adapter_for(units, "distance")` would render `odometer` in
   kilometres for a metric owner: same key set, silently different meaning,
   and the key-set test above would still pass. So the odometer figures are
   asserted to be IDENTICAL under a metric and an imperial owner.
3. **Flavour, per D4b.** Only the gallon-flavoured MPG fields take their
   context from the owner. A `mpg_us`/`mpg_uk` primary states its own flavour
   and wins outright, even against a disagreeing `secondary_gallon`; only a
   metric primary (`l_100km`, `km_l`) defers to `secondary_gallon`. Both
   conflict directions are tested, because two users whose settings agree
   prove nothing.

These are HTTP tests on purpose. A service-level test alone passes when a
route forgets to pass the context, and the two route modules
(`routes/widget.py`, `routes/widget_v2.py`) call different service methods,
so each has to be driven separately.

All fixture data is canonical metric and absolute-dated; nothing here changes
a stored value.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.models.fuel import FuelRecord
from app.models.odometer import OdometerRecord
from app.models.settings import Setting
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.widget_api_key import WidgetApiKey
from app.services.widget_auth import display_prefix, generate_widget_key, hash_widget_key

TEST_PASSWORD_HASH = (
    "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw"
    "$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"
)

# --- canonical (metric) fixture data -------------------------------------
# Chosen so every derived figure below is exact, with no rounding tie in
# sight: a value sitting on a .5 boundary would make a rounding-mode change
# look like a conversion change.
SEED_ODOMETER_KM = Decimal("16093.40")  # 16093.40 / 1.60934 == 10000 exactly
SEED_ODOMETER_DATE = date(2026, 1, 20)
SEED_PREV_FILL_KM = Decimal("15000.00")
SEED_PREV_FILL_DATE = date(2026, 1, 1)
SEED_LAST_FILL_KM = Decimal("15500.00")  # 500 km since the previous full tank
SEED_LAST_FILL_DATE = date(2026, 1, 15)
SEED_LITERS = Decimal("40.000")  # 40 L over 500 km == 8.00 L/100km exactly

SEED_YEAR = 2022
SEED_MAKE = "Honda"
SEED_MODEL = "Civic"
SEED_LABEL = "2022 Honda Civic"

# --- expected display figures, derived by hand from the seed above -------
# odometer:            16093.40 km / 1.60934 km-per-mi = 10000 mi
# odometer_km:         round(16093.40)                 = 16093 km
# consumption:         40.000 L / 500.00 km * 100      = 8.00 L/100km
# recent/average_km_per_l:  100 / 8.00                 = 12.5 km/L
# recent/average_mpg (US):  235.214 / 8.00 = 29.40175  -> 29.4 (precision 1)
# recent/average_mpg (UK):  282.481 / 8.00 = 35.310125 -> 35.3 (precision 1)
EXPECTED_ODOMETER_MI = 10000
EXPECTED_ODOMETER_KM = 16093
EXPECTED_L_PER_100KM = 8.0
EXPECTED_KM_PER_L = 12.5
EXPECTED_MPG_US = 29.4
EXPECTED_MPG_UK = 35.3

# --- odometer values that do NOT divide exactly ---------------------------
# `SEED_ODOMETER_KM` above is exact on purpose, which means it cannot see the
# rounding path at all: 16093.40 / 1.60934 is 10000 with nothing to round.
# These two do, in both directions, and they are the values at which this
# phase's single-rounding path DISAGREES with the pre-phase double-rounding
# one (`int(round(UnitConverter.km_to_miles(km)))`, where `km_to_miles`
# already rounded to 2 dp before the outer `round` saw it). Derived by hand
# and confirmed against the adapter's own factor, `UnitConverter.MILES_TO_KM`
# = 1.60934:
#
#   120001.24 / 1.60934 = 74565.49890...  -> 74565 (rounds DOWN)
#     old path: round(74565.49890, 2) = 74565.50 -> round() -> 74566
#   120006.07 / 1.60934 = 74568.50013...  -> 74569 (rounds UP)
#     old path: round(74568.50013, 2) = 74568.50 -> round() -> 74568 (even)
#
# `odometer_km` is unaffected either way (`Decimal / Decimal("1")` is the
# identity, then rounded to the nearest whole km).
ROUNDS_DOWN_ODOMETER_KM = Decimal("120001.24")
EXPECTED_ROUNDS_DOWN_MI = 74565
EXPECTED_ROUNDS_DOWN_KM = 120001
ROUNDS_UP_ODOMETER_KM = Decimal("120006.07")
EXPECTED_ROUNDS_UP_MI = 74569
EXPECTED_ROUNDS_UP_KM = 120006

# --- frozen response shapes (D7), written out by hand --------------------
V1_VEHICLE_KEYS = {
    "label",
    "year",
    "make",
    "model",
    "odometer",
    "odometer_date",
    "recent_mpg",
    "average_mpg",
    "upcoming_maintenance",
    "overdue_maintenance",
    "service_records",
    "fuel_records",
    "last_service_date",
    "last_fuel_date",
    "documents",
    "notes",
    "photos",
}

V2_VEHICLE_KEYS = {
    "label",
    "year",
    "make",
    "model",
    "odometer",
    "odometer_km",
    "odometer_date",
    "recent_l_per_100km",
    "average_l_per_100km",
    "recent_km_per_l",
    "average_km_per_l",
    "recent_mpg",
    "average_mpg",
    "latest_hours",
    "average_l_per_hr",
    "average_cost_per_hr",
    "upcoming_maintenance",
    "overdue_maintenance",
    "service_records",
    "fuel_records",
    "last_service_date",
    "last_fuel_date",
    "documents",
    "notes",
    "photos",
}


def _expected_v1_payload(mpg: float) -> dict[str, object]:
    """The whole v1 body for the seeded vehicle, with `mpg` the only variable.

    Every other field is a literal: pinning only MPG would leave a unit swap
    on `odometer` invisible.
    """
    return {
        "label": SEED_LABEL,
        "year": SEED_YEAR,
        "make": SEED_MAKE,
        "model": SEED_MODEL,
        "odometer": EXPECTED_ODOMETER_MI,
        "odometer_date": "2026-01-20",
        "recent_mpg": mpg,
        "average_mpg": mpg,
        "upcoming_maintenance": 0,
        "overdue_maintenance": 0,
        "service_records": 0,
        "fuel_records": 2,
        "last_service_date": None,
        "last_fuel_date": "2026-01-15",
        "documents": 0,
        "notes": 0,
        "photos": 0,
    }


def _expected_v2_payload(mpg: float) -> dict[str, object]:
    """The whole v2 body for the seeded vehicle, with `mpg` the only variable.

    The hours trio is null: the seeded vehicle is pure-distance. They are
    pinned anyway, because they are frozen numeric fields too.
    """
    return {
        "label": SEED_LABEL,
        "year": SEED_YEAR,
        "make": SEED_MAKE,
        "model": SEED_MODEL,
        "odometer": EXPECTED_ODOMETER_MI,
        "odometer_km": EXPECTED_ODOMETER_KM,
        "odometer_date": "2026-01-20",
        "recent_l_per_100km": EXPECTED_L_PER_100KM,
        "average_l_per_100km": EXPECTED_L_PER_100KM,
        "recent_km_per_l": EXPECTED_KM_PER_L,
        "average_km_per_l": EXPECTED_KM_PER_L,
        "recent_mpg": mpg,
        "average_mpg": mpg,
        "latest_hours": None,
        "average_l_per_hr": None,
        "average_cost_per_hr": None,
        "upcoming_maintenance": 0,
        "overdue_maintenance": 0,
        "service_records": 0,
        "fuel_records": 2,
        "last_service_date": None,
        "last_fuel_date": "2026-01-15",
        "documents": 0,
        "notes": 0,
        "photos": 0,
    }


def _unique_vin() -> str:
    return ("WVU" + uuid.uuid4().hex)[:17].upper()


@pytest_asyncio.fixture
async def local_auth_mode(db_session):
    """Pin `auth_mode` to 'local' and restore whatever was there before.

    `require_widget_key` 401s outright under `auth_mode=none`, and the suite
    shares one database with no per-test rollback, so a neighbouring test that
    left the row set would otherwise decide this file's outcome.
    """
    row = (
        await db_session.execute(select(Setting).where(Setting.key == "auth_mode"))
    ).scalar_one_or_none()
    original = row.value if row is not None else None
    if row is None:
        db_session.add(Setting(key="auth_mode", value="local"))
    else:
        row.value = "local"
    await db_session.commit()
    try:
        yield
    finally:
        current = (
            await db_session.execute(select(Setting).where(Setting.key == "auth_mode"))
        ).scalar_one_or_none()
        if current is None:
            if original is not None:
                db_session.add(Setting(key="auth_mode", value=original))
        elif original is None:
            await db_session.delete(current)
        else:
            current.value = original
        await db_session.commit()


@pytest_asyncio.fixture
async def widget_owner_factory(db_session, local_auth_mode):
    """Build an owner with the given unit columns, one seeded vehicle, and a key.

    `odometer_km` overrides the (deliberately exact) `SEED_ODOMETER_KM` for
    the tests that need a reading the mile conversion actually has to round.

    Returns `(plaintext_key, vin)`. Every row created is deleted in the
    `finally`: the suite shares one database with no per-test rollback, so a
    leaked `users` row carrying unit overrides is not merely clutter, it is a
    different conversion context for whatever runs next.
    """
    user_ids: list[int] = []
    vins: list[str] = []

    async def _make(
        *, odometer_km: Decimal = SEED_ODOMETER_KM, **unit_columns: str
    ) -> tuple[str, str]:
        suffix = uuid.uuid4().hex[:12]
        user = User(
            username=f"widget_units_{suffix}",
            email=f"widget_units_{suffix}@example.com",
            hashed_password=TEST_PASSWORD_HASH,
            is_active=True,
            is_admin=False,
            **unit_columns,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        user_ids.append(user.id)

        vin = _unique_vin()
        db_session.add(
            Vehicle(
                vin=vin,
                nickname="Units",
                vehicle_type="Car",
                user_id=user.id,
                year=SEED_YEAR,
                make=SEED_MAKE,
                model=SEED_MODEL,
            )
        )
        await db_session.commit()
        vins.append(vin)

        db_session.add(OdometerRecord(vin=vin, odometer_km=odometer_km, date=SEED_ODOMETER_DATE))
        db_session.add_all(
            [
                FuelRecord(
                    vin=vin,
                    date=SEED_PREV_FILL_DATE,
                    odometer_km=SEED_PREV_FILL_KM,
                    liters=SEED_LITERS,
                    price_per_unit=Decimal("1.50"),
                    cost=Decimal("60.00"),
                    is_full_tank=True,
                ),
                FuelRecord(
                    vin=vin,
                    date=SEED_LAST_FILL_DATE,
                    odometer_km=SEED_LAST_FILL_KM,
                    liters=SEED_LITERS,
                    price_per_unit=Decimal("1.50"),
                    cost=Decimal("60.00"),
                    is_full_tank=True,
                ),
            ]
        )
        await db_session.commit()

        plaintext = generate_widget_key()
        db_session.add(
            WidgetApiKey(
                user_id=user.id,
                name="units",
                key_hash=hash_widget_key(plaintext),
                key_prefix=display_prefix(plaintext),
                scope="all_vehicles",
                allowed_vins=None,
            )
        )
        await db_session.commit()
        return plaintext, vin

    try:
        yield _make
    finally:
        for vin in vins:
            await db_session.execute(delete(FuelRecord).where(FuelRecord.vin == vin))
            await db_session.execute(delete(OdometerRecord).where(OdometerRecord.vin == vin))
            await db_session.execute(delete(Vehicle).where(Vehicle.vin == vin))
        for user_id in user_ids:
            await db_session.execute(delete(WidgetApiKey).where(WidgetApiKey.user_id == user_id))
            await db_session.execute(delete(User).where(User.id == user_id))
        await db_session.commit()


async def _get_v1(client: AsyncClient, key: str, vin: str) -> dict[str, object]:
    resp = await client.get(f"/api/widget/vehicle/{vin}", headers={"X-API-Key": key})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _get_v2(client: AsyncClient, key: str, vin: str) -> dict[str, object]:
    resp = await client.get(f"/api/v2/widget/vehicle/{vin}", headers={"X-API-Key": key})
    assert resp.status_code == 200, resp.text
    return resp.json()


# Owner unit-column recipes. `unit_preference` is the base preset; a non-null
# override column beats it (D3). NULL columns mean "no override".
US_IMPERIAL_OWNER = {"unit_preference": "imperial"}
UK_CONSUMPTION_OWNER = {"unit_preference": "imperial", "unit_consumption": "mpg_uk"}
METRIC_OWNER = {"unit_preference": "metric"}
UK_PRIMARY_VS_US_SECONDARY = {
    "unit_preference": "imperial",
    "unit_consumption": "mpg_uk",
    "secondary_gallon": "us",
}
US_PRIMARY_VS_UK_SECONDARY = {
    "unit_preference": "imperial",
    "unit_consumption": "mpg_us",
    "secondary_gallon": "uk",
}
METRIC_PRIMARY_UK_SECONDARY = {
    "unit_preference": "metric",
    "unit_consumption": "l_100km",
    "secondary_gallon": "uk",
}
METRIC_PRIMARY_US_SECONDARY = {
    "unit_preference": "metric",
    "unit_consumption": "l_100km",
    "secondary_gallon": "us",
}
KM_PER_L_PRIMARY_UK_SECONDARY = {
    "unit_preference": "metric",
    "unit_consumption": "km_l",
    "secondary_gallon": "uk",
}


@pytest.mark.integration
@pytest.mark.asyncio
class TestWidgetResponseShapeIsFrozen:
    """D7 freezes the key set. These compare against hand-written literals."""

    async def test_v1_vehicle_keys_are_exactly_the_frozen_v1_set(
        self, client: AsyncClient, widget_owner_factory
    ):
        key, vin = await widget_owner_factory(**US_IMPERIAL_OWNER)
        assert set((await _get_v1(client, key, vin)).keys()) == V1_VEHICLE_KEYS

    async def test_v2_vehicle_keys_are_exactly_the_frozen_v2_set(
        self, client: AsyncClient, widget_owner_factory
    ):
        key, vin = await widget_owner_factory(**US_IMPERIAL_OWNER)
        assert set((await _get_v2(client, key, vin)).keys()) == V2_VEHICLE_KEYS

    async def test_the_key_sets_do_not_move_with_the_owners_units(
        self, client: AsyncClient, widget_owner_factory
    ):
        """A metric owner gets the same KEYS as an imperial one.

        This is the test that cannot see a unit swap, which is why
        `TestWidgetFieldMeaningsAreFrozen` below exists. It is here to pin
        that a per-owner conversion context never adds, drops, or renames a
        field.
        """
        metric_key, metric_vin = await widget_owner_factory(**METRIC_OWNER)
        imperial_key, imperial_vin = await widget_owner_factory(**US_IMPERIAL_OWNER)
        assert set((await _get_v1(client, metric_key, metric_vin)).keys()) == V1_VEHICLE_KEYS
        assert set((await _get_v1(client, imperial_key, imperial_vin)).keys()) == V1_VEHICLE_KEYS
        assert set((await _get_v2(client, metric_key, metric_vin)).keys()) == V2_VEHICLE_KEYS
        assert set((await _get_v2(client, imperial_key, imperial_vin)).keys()) == V2_VEHICLE_KEYS


@pytest.mark.integration
@pytest.mark.asyncio
class TestWidgetFieldMeaningsAreFrozen:
    """D7 freezes MEANINGS too. Every frozen numeric field is pinned literally."""

    async def test_v1_body_is_pinned_for_a_us_owner(
        self, client: AsyncClient, widget_owner_factory
    ):
        key, vin = await widget_owner_factory(**US_IMPERIAL_OWNER)
        assert await _get_v1(client, key, vin) == _expected_v1_payload(EXPECTED_MPG_US)

    async def test_v2_body_is_pinned_for_a_us_owner(
        self, client: AsyncClient, widget_owner_factory
    ):
        key, vin = await widget_owner_factory(**US_IMPERIAL_OWNER)
        assert await _get_v2(client, key, vin) == _expected_v2_payload(EXPECTED_MPG_US)

    async def test_v1_odometer_stays_miles_for_a_metric_owner(
        self, client: AsyncClient, widget_owner_factory
    ):
        """`odometer` is miles by contract, for everyone.

        16093.40 canonical km is 10,000 mi and 16,093 km. Rendering the
        owner's resolved distance unit here would hand a metric owner 16093
        under the key `odometer`, which is the exact silent-meaning-change D7
        forbids.
        """
        key, vin = await widget_owner_factory(**METRIC_OWNER)
        body = await _get_v1(client, key, vin)
        assert body["odometer"] == EXPECTED_ODOMETER_MI
        assert body["odometer"] != EXPECTED_ODOMETER_KM

    async def test_v2_odometer_pair_stays_miles_and_km_for_a_metric_owner(
        self, client: AsyncClient, widget_owner_factory
    ):
        key, vin = await widget_owner_factory(**METRIC_OWNER)
        body = await _get_v2(client, key, vin)
        assert body["odometer"] == EXPECTED_ODOMETER_MI
        assert body["odometer_km"] == EXPECTED_ODOMETER_KM

    async def test_odometer_is_the_same_miles_figure_for_a_metric_and_an_imperial_owner(
        self, client: AsyncClient, widget_owner_factory
    ):
        """Two owners, opposite `distance` primaries, identical odometer output.

        Asserted against the literal as well as against each other: two
        payloads agreeing with one another would still agree if both had
        silently become kilometres.
        """
        metric_key, metric_vin = await widget_owner_factory(**METRIC_OWNER)
        imperial_key, imperial_vin = await widget_owner_factory(**US_IMPERIAL_OWNER)

        metric_v1 = await _get_v1(client, metric_key, metric_vin)
        imperial_v1 = await _get_v1(client, imperial_key, imperial_vin)
        assert metric_v1["odometer"] == imperial_v1["odometer"] == EXPECTED_ODOMETER_MI

        metric_v2 = await _get_v2(client, metric_key, metric_vin)
        imperial_v2 = await _get_v2(client, imperial_key, imperial_vin)
        assert metric_v2["odometer"] == imperial_v2["odometer"] == EXPECTED_ODOMETER_MI
        assert metric_v2["odometer_km"] == imperial_v2["odometer_km"] == EXPECTED_ODOMETER_KM

    async def test_v2_metric_consumption_fields_ignore_the_owners_units(
        self, client: AsyncClient, widget_owner_factory
    ):
        """`*_l_per_100km` and `*_km_per_l` are name-pinned, not preference-driven.

        An owner on `mpg_uk` still gets 8.00 L/100km and 12.5 km/L; only the
        MPG pair moves.
        """
        uk_key, uk_vin = await widget_owner_factory(**UK_CONSUMPTION_OWNER)
        metric_key, metric_vin = await widget_owner_factory(**METRIC_OWNER)
        for key, vin in ((uk_key, uk_vin), (metric_key, metric_vin)):
            body = await _get_v2(client, key, vin)
            assert body["recent_l_per_100km"] == EXPECTED_L_PER_100KM
            assert body["average_l_per_100km"] == EXPECTED_L_PER_100KM
            assert body["recent_km_per_l"] == EXPECTED_KM_PER_L
            assert body["average_km_per_l"] == EXPECTED_KM_PER_L


@pytest.mark.integration
@pytest.mark.asyncio
class TestWidgetGallonFlavourPrecedence:
    """D4b: a gallon-flavoured primary wins; only a metric primary defers."""

    async def test_v1_us_primary_yields_us_mpg(self, client: AsyncClient, widget_owner_factory):
        key, vin = await widget_owner_factory(**US_IMPERIAL_OWNER)
        body = await _get_v1(client, key, vin)
        assert body["recent_mpg"] == EXPECTED_MPG_US
        assert body["average_mpg"] == EXPECTED_MPG_US

    async def test_v1_uk_primary_yields_uk_mpg(self, client: AsyncClient, widget_owner_factory):
        key, vin = await widget_owner_factory(**UK_CONSUMPTION_OWNER)
        body = await _get_v1(client, key, vin)
        assert body["recent_mpg"] == EXPECTED_MPG_UK
        assert body["average_mpg"] == EXPECTED_MPG_UK

    async def test_v2_us_primary_yields_us_mpg(self, client: AsyncClient, widget_owner_factory):
        key, vin = await widget_owner_factory(**US_IMPERIAL_OWNER)
        body = await _get_v2(client, key, vin)
        assert body["recent_mpg"] == EXPECTED_MPG_US
        assert body["average_mpg"] == EXPECTED_MPG_US

    async def test_v2_uk_primary_yields_uk_mpg(self, client: AsyncClient, widget_owner_factory):
        key, vin = await widget_owner_factory(**UK_CONSUMPTION_OWNER)
        body = await _get_v2(client, key, vin)
        assert body["recent_mpg"] == EXPECTED_MPG_UK
        assert body["average_mpg"] == EXPECTED_MPG_UK

    async def test_v1_uk_primary_beats_a_disagreeing_us_secondary_gallon(
        self, client: AsyncClient, widget_owner_factory
    ):
        """`consumption=mpg_uk` + `secondary_gallon=us` must be UK MPG.

        The primary states its own flavour, so `secondary_gallon` is not
        consulted at all. Two agreeing settings would prove nothing.
        """
        key, vin = await widget_owner_factory(**UK_PRIMARY_VS_US_SECONDARY)
        body = await _get_v1(client, key, vin)
        assert body["recent_mpg"] == EXPECTED_MPG_UK
        assert body["average_mpg"] == EXPECTED_MPG_UK

    async def test_v2_uk_primary_beats_a_disagreeing_us_secondary_gallon(
        self, client: AsyncClient, widget_owner_factory
    ):
        key, vin = await widget_owner_factory(**UK_PRIMARY_VS_US_SECONDARY)
        body = await _get_v2(client, key, vin)
        assert body["recent_mpg"] == EXPECTED_MPG_UK
        assert body["average_mpg"] == EXPECTED_MPG_UK

    async def test_v1_us_primary_beats_a_disagreeing_uk_secondary_gallon(
        self, client: AsyncClient, widget_owner_factory
    ):
        """The other conflict direction, so an always-UK bug cannot hide here."""
        key, vin = await widget_owner_factory(**US_PRIMARY_VS_UK_SECONDARY)
        body = await _get_v1(client, key, vin)
        assert body["recent_mpg"] == EXPECTED_MPG_US
        assert body["average_mpg"] == EXPECTED_MPG_US

    async def test_v2_us_primary_beats_a_disagreeing_uk_secondary_gallon(
        self, client: AsyncClient, widget_owner_factory
    ):
        key, vin = await widget_owner_factory(**US_PRIMARY_VS_UK_SECONDARY)
        body = await _get_v2(client, key, vin)
        assert body["recent_mpg"] == EXPECTED_MPG_US
        assert body["average_mpg"] == EXPECTED_MPG_US

    async def test_v1_l_100km_primary_takes_uk_from_secondary_gallon(
        self, client: AsyncClient, widget_owner_factory
    ):
        """`l_100km` states no flavour, so `secondary_gallon` supplies it."""
        key, vin = await widget_owner_factory(**METRIC_PRIMARY_UK_SECONDARY)
        body = await _get_v1(client, key, vin)
        assert body["recent_mpg"] == EXPECTED_MPG_UK
        assert body["average_mpg"] == EXPECTED_MPG_UK

    async def test_v2_l_100km_primary_takes_uk_from_secondary_gallon(
        self, client: AsyncClient, widget_owner_factory
    ):
        key, vin = await widget_owner_factory(**METRIC_PRIMARY_UK_SECONDARY)
        body = await _get_v2(client, key, vin)
        assert body["recent_mpg"] == EXPECTED_MPG_UK
        assert body["average_mpg"] == EXPECTED_MPG_UK

    async def test_v1_l_100km_primary_takes_us_from_secondary_gallon(
        self, client: AsyncClient, widget_owner_factory
    ):
        key, vin = await widget_owner_factory(**METRIC_PRIMARY_US_SECONDARY)
        body = await _get_v1(client, key, vin)
        assert body["recent_mpg"] == EXPECTED_MPG_US
        assert body["average_mpg"] == EXPECTED_MPG_US

    async def test_v2_l_100km_primary_takes_us_from_secondary_gallon(
        self, client: AsyncClient, widget_owner_factory
    ):
        key, vin = await widget_owner_factory(**METRIC_PRIMARY_US_SECONDARY)
        body = await _get_v2(client, key, vin)
        assert body["recent_mpg"] == EXPECTED_MPG_US
        assert body["average_mpg"] == EXPECTED_MPG_US

    async def test_v2_km_l_primary_also_takes_its_flavour_from_secondary_gallon(
        self, client: AsyncClient, widget_owner_factory
    ):
        """`km_l` is the second flavourless consumption token, not just `l_100km`."""
        key, vin = await widget_owner_factory(**KM_PER_L_PRIMARY_UK_SECONDARY)
        body = await _get_v2(client, key, vin)
        assert body["recent_mpg"] == EXPECTED_MPG_UK
        assert body["average_mpg"] == EXPECTED_MPG_UK

    async def test_the_two_endpoints_agree_on_mpg_for_one_owner(
        self, client: AsyncClient, widget_owner_factory
    ):
        """v2 is a strict superset of v1: both flavour sites resolve identically.

        Also pinned against the literal, so this cannot pass by both sites
        being wrong in the same direction.
        """
        key, vin = await widget_owner_factory(**UK_PRIMARY_VS_US_SECONDARY)
        v1 = await _get_v1(client, key, vin)
        v2 = await _get_v2(client, key, vin)
        assert v1["recent_mpg"] == v2["recent_mpg"] == EXPECTED_MPG_UK
        assert v1["average_mpg"] == v2["average_mpg"] == EXPECTED_MPG_UK


@pytest.mark.integration
@pytest.mark.asyncio
class TestWidgetIgnoresTheInstanceGallonSetting:
    """The instance-wide `imperial_gallon_standard` no longer reaches widgets."""

    async def test_a_us_owner_keeps_us_mpg_on_a_uk_instance(
        self, client: AsyncClient, db_session, widget_owner_factory
    ):
        """Seeding the phase-0 global to 'uk' must not move a US owner's MPG.

        Before Task 7 both widget endpoints read `imperial_gallon_standard`
        through `resolve_gallon_flavour(self.db)`, which carries no caller
        identity. This pins the migration: the owner's `UnitSet` decides, the
        instance setting does not.
        """
        row = (
            await db_session.execute(
                select(Setting).where(Setting.key == "imperial_gallon_standard")
            )
        ).scalar_one_or_none()
        original = row.value if row is not None else None
        if row is None:
            db_session.add(Setting(key="imperial_gallon_standard", value="uk"))
        else:
            row.value = "uk"
        await db_session.commit()
        try:
            key, vin = await widget_owner_factory(**US_IMPERIAL_OWNER)
            assert (await _get_v1(client, key, vin))["recent_mpg"] == EXPECTED_MPG_US
            assert (await _get_v2(client, key, vin))["recent_mpg"] == EXPECTED_MPG_US
        finally:
            current = (
                await db_session.execute(
                    select(Setting).where(Setting.key == "imperial_gallon_standard")
                )
            ).scalar_one_or_none()
            if current is None:
                if original is not None:
                    db_session.add(Setting(key="imperial_gallon_standard", value=original))
            elif original is None:
                await db_session.delete(current)
            else:
                current.value = original
            await db_session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
class TestOdometerRoundsOnceNotTwice:
    """The eighth visible change of this phase, which nothing else can see.

    D7 freezes `odometer` as a whole number of miles, and the pre-phase path
    reached that number through TWO roundings:
    `int(round(UnitConverter.km_to_miles(km)))`, where `km_to_miles` had
    already rounded the quotient to 2 dp. The conversion layer rounds once,
    `int(round(km / MILES_TO_KM))`, which is strictly more correct and shifts
    roughly 0.6% of readings by exactly 1 mile.

    Every other test in this file seeds `SEED_ODOMETER_KM = 16093.40`, which
    divides exactly into 10,000 mi and therefore exercises no rounding at
    all. These two seed values do, one in each direction, and both are values
    at which the old and new paths disagree -- so this is a regression pin on
    a frozen numeric field, not just a smoke test of the arithmetic.
    """

    async def test_v1_rounds_a_fractional_mile_down(
        self, client: AsyncClient, widget_owner_factory
    ):
        key, vin = await widget_owner_factory(
            odometer_km=ROUNDS_DOWN_ODOMETER_KM, **US_IMPERIAL_OWNER
        )
        body = await _get_v1(client, key, vin)
        assert body["odometer"] == EXPECTED_ROUNDS_DOWN_MI
        # The figure the double-rounded path produced, pinned as absent so a
        # reintroduction fails here rather than passing by one mile.
        assert body["odometer"] != EXPECTED_ROUNDS_DOWN_MI + 1

    async def test_v1_rounds_a_fractional_mile_up(self, client: AsyncClient, widget_owner_factory):
        """The other direction. A single-direction test cannot tell "rounds
        once" from "always truncates"."""
        key, vin = await widget_owner_factory(
            odometer_km=ROUNDS_UP_ODOMETER_KM, **US_IMPERIAL_OWNER
        )
        body = await _get_v1(client, key, vin)
        assert body["odometer"] == EXPECTED_ROUNDS_UP_MI
        assert body["odometer"] != EXPECTED_ROUNDS_UP_MI - 1

    async def test_v2_rounds_the_pair_the_same_way(self, client: AsyncClient, widget_owner_factory):
        """v2 carries both figures, so it pins the km side too: `odometer_km`
        rounds to the nearest whole km and is NOT affected by the mile-side
        change."""
        key, vin = await widget_owner_factory(
            odometer_km=ROUNDS_DOWN_ODOMETER_KM, **US_IMPERIAL_OWNER
        )
        body = await _get_v2(client, key, vin)
        assert body["odometer"] == EXPECTED_ROUNDS_DOWN_MI
        assert body["odometer_km"] == EXPECTED_ROUNDS_DOWN_KM

        up_key, up_vin = await widget_owner_factory(
            odometer_km=ROUNDS_UP_ODOMETER_KM, **US_IMPERIAL_OWNER
        )
        up_body = await _get_v2(client, up_key, up_vin)
        assert up_body["odometer"] == EXPECTED_ROUNDS_UP_MI
        assert up_body["odometer_km"] == EXPECTED_ROUNDS_UP_KM

    async def test_a_metric_owner_gets_the_same_rounded_miles(
        self, client: AsyncClient, widget_owner_factory
    ):
        """D7 again: the rounding change is not a units change. A metric owner
        sees the identical mile figure, not the km one."""
        key, vin = await widget_owner_factory(odometer_km=ROUNDS_DOWN_ODOMETER_KM, **METRIC_OWNER)
        body = await _get_v2(client, key, vin)
        assert body["odometer"] == EXPECTED_ROUNDS_DOWN_MI
        assert body["odometer_km"] == EXPECTED_ROUNDS_DOWN_KM
