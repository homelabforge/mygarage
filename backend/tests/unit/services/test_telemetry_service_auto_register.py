"""Unit tests for TelemetryService.auto_register_parameter param-class inference.

Task 11: MQTT-discovered params arrive with an empty config block (`config={}`),
so `param_class` has historically been left `None` for anything the WiCAN
config didn't label — which silently bypassed all `TelemetryValidator`
range/rate checks. `infer_param_class()` (Task 10) gives us a conservative,
catalog-based fallback; this file pins how `auto_register_parameter` wires it
in for both the new-row and existing-row (backfill) paths.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice
from app.models.livelink_parameter import LiveLinkParameter
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.telemetry_service import TelemetryService


@pytest_asyncio.fixture
async def make_vehicle_and_device(db_session: AsyncSession):
    """Async factory: creates a minimal user, vehicle, and device.

    Returns an async callable: (db_session) -> (vin, device_id).
    Mirrors the fixture in test_telemetry_canonicalization.py.
    """

    async def _factory(session: AsyncSession) -> tuple[str, str]:
        user = User(
            username="autoreg_test_user",
            email="autoreg_test@example.com",
            hashed_password="x",
            is_active=True,
            is_admin=False,
        )
        session.add(user)
        await session.flush()

        vin = "AUTOREGTEST00001"
        vehicle = Vehicle(
            vin=vin,
            user_id=user.id,
            nickname="Auto Register Test Car",
            vehicle_type="Car",
        )
        session.add(vehicle)
        await session.flush()

        device_id = "aabbccddeeff02"
        device = LiveLinkDevice(
            device_id=device_id,
            vin=vin,
            enabled=True,
        )
        session.add(device)
        await session.flush()

        return vin, device_id

    return _factory


@pytest.mark.asyncio
class TestAutoRegisterNewParamInference:
    """New-row registration should infer param_class when config omits it."""

    async def test_mqtt_style_registration_infers_percentage_class(self, db_session):
        """config={} registration of a fuel-level PID gets classified percentage."""
        svc = TelemetryService(db_session)

        param = await svc.auto_register_parameter("2F-FUELTANKLEVEL", unit=None, param_class=None)

        assert param.param_class == "percentage"
        # Literal, not computed via _classify_param — that call would make the
        # assertion tautological. ("percentage" currently classifies to
        # "other"; the category-distinct case is pinned by
        # test_new_row_category_recomputed_from_inferred_class below.)
        assert param.category == "other"

    async def test_new_row_category_recomputed_from_inferred_class(self, db_session):
        """config={} registration of an RPM PID resolves class "frequency"
        AND category "engine" — a category DISTINCT from the "other" a None
        class would yield, so a regression that classifies from the raw
        config class instead of the resolved class fails here.

        Hand-typed literals on purpose: routing the expectation through
        _classify_param would rebuild the tautology.
        """
        svc = TelemetryService(db_session)

        param = await svc.auto_register_parameter("0C-ENGINERPM", unit=None, param_class=None)

        assert param.param_class == "frequency"
        assert param.category == "engine"

    async def test_inferred_class_activates_validator_rejection(
        self, db_session, make_vehicle_and_device
    ):
        """A 255 fuel-level reading is rejected once inference classifies it
        as percentage; the validator drops out-of-range values, it does not
        clamp them."""
        vin, device_id = await make_vehicle_and_device(db_session)
        svc = TelemetryService(db_session)

        # MQTT-style: config block empty for this key.
        result_bad = await svc.store_telemetry(vin, device_id, {"2F-FUELTANKLEVEL": 255}, {}, None)
        assert "2F-FUELTANKLEVEL" not in result_bad.validated_data

        result_ok = await svc.store_telemetry(vin, device_id, {"2F-FUELTANKLEVEL": 50}, {}, None)
        assert result_ok.validated_data.get("2F-FUELTANKLEVEL") == 50

    async def test_explicit_config_class_beats_inference(self, db_session):
        """Explicit config class always wins over what the catalog would infer.

        "2F-FUELTANKLEVEL" would infer to "percentage", but an explicit
        config class of "voltage" must be honored instead.
        """
        svc = TelemetryService(db_session)

        param = await svc.auto_register_parameter(
            "2F-FUELTANKLEVEL", unit=None, param_class="voltage"
        )

        assert param.param_class == "voltage"

    async def test_unknown_key_stays_unclassified(self, db_session, make_vehicle_and_device):
        """A key that matches nothing in the catalog keeps param_class=None,
        and validation is bypassed exactly as it is today."""
        vin, device_id = await make_vehicle_and_device(db_session)
        svc = TelemetryService(db_session)

        param = await svc.auto_register_parameter("9B-CUSTOMSENSOR", unit=None, param_class=None)
        assert param.param_class is None

        # A wildly out-of-any-real-range value still passes through because
        # there's no class to validate against.
        result = await svc.store_telemetry(vin, device_id, {"9B-CUSTOMSENSOR": 999999}, {}, None)
        assert result.validated_data.get("9B-CUSTOMSENSOR") == 999999


@pytest.mark.asyncio
class TestAutoRegisterBackfillInference:
    """Existing rows with a None class get backfilled by inference, without
    ever touching user-owned dashboard display state."""

    async def test_existing_none_class_backfilled_by_inference(self, db_session):
        """A pre-existing row with no class, re-seen with an empty config,
        gets its param_class backfilled from the catalog."""
        svc = TelemetryService(db_session)

        existing = LiveLinkParameter(
            param_key="2F-FUELTANKLEVEL",
            display_name="Fuel Tank Level",
            unit=None,
            param_class=None,
            category="other",
            show_on_dashboard=True,
            archive_only=False,
            storage_interval_seconds=0,
        )
        db_session.add(existing)
        await db_session.flush()

        param = await svc.auto_register_parameter("2F-FUELTANKLEVEL", unit=None, param_class=None)

        assert param.param_class == "percentage"
        # Display flags are user-owned dashboard state — backfill must never
        # flip them, even though the resolved class's "new row" defaults
        # would differ (percentage is not in the dashboard-default list).
        assert param.show_on_dashboard is True
        assert param.archive_only is False

    async def test_backfill_preserves_hand_tuned_category(self, db_session):
        """Category is user-editable in the admin UI: when an unclassified
        row already carries a hand-tuned category (anything but the "other"
        default), the class backfill fills param_class but must NOT recompute
        category over the user's value."""
        svc = TelemetryService(db_session)

        existing = LiveLinkParameter(
            param_key="2F-FUELTANKLEVEL",
            display_name="Fuel Tank Level",
            unit=None,
            param_class=None,
            category="engine",  # hand-set by a user, not the "other" default
            show_on_dashboard=True,
            archive_only=False,
            storage_interval_seconds=0,
        )
        db_session.add(existing)
        await db_session.flush()

        param = await svc.auto_register_parameter("2F-FUELTANKLEVEL", unit=None, param_class=None)

        assert param.param_class == "percentage"
        assert param.category == "engine"

    async def test_explicit_config_class_beats_inference_on_backfill(self, db_session):
        """Backfill also prefers an explicit config class over inference."""
        svc = TelemetryService(db_session)

        existing = LiveLinkParameter(
            param_key="2F-FUELTANKLEVEL",
            display_name="Fuel Tank Level",
            unit=None,
            param_class=None,
            category="other",
            show_on_dashboard=True,
            archive_only=False,
            storage_interval_seconds=0,
        )
        db_session.add(existing)
        await db_session.flush()

        param = await svc.auto_register_parameter(
            "2F-FUELTANKLEVEL", unit=None, param_class="voltage"
        )

        assert param.param_class == "voltage"

    async def test_existing_already_classed_row_not_reclassified(self, db_session):
        """A row that already has a param_class is never overwritten by
        inference (one-directional backfill: only fills when unset)."""
        svc = TelemetryService(db_session)

        existing = LiveLinkParameter(
            param_key="2F-FUELTANKLEVEL",
            display_name="Fuel Tank Level",
            unit=None,
            param_class="power_factor",
            category="engine",
            show_on_dashboard=True,
            archive_only=False,
            storage_interval_seconds=0,
        )
        db_session.add(existing)
        await db_session.flush()

        param = await svc.auto_register_parameter("2F-FUELTANKLEVEL", unit=None, param_class=None)

        assert param.param_class == "power_factor"


@pytest.mark.asyncio
class TestAutoRegisterDashboardDefaults:
    """Which classes are chartable out of the box, and that all are shown.

    `archive_only` keeps a parameter out of the chart picker, so a headline
    reading whose class is unlisted is registered unchartable. That is what
    happened to the Mopeka preset's tank level. It never kept anything off a
    gauge: the Live tab drew every reading until `show_on_dashboard` became a
    per-reading switch, and every new parameter now starts with it on.
    """

    async def test_propane_level_is_chartable_on_registration(self, db_session):
        """Ingest tests register this key without a class and leave the row.

        A key registered earlier returns its existing row, so clear it first or
        this test reads their archive-only row whenever it runs after them.
        """
        from sqlalchemy import delete

        key = "PROPANE_T1_LEVEL_PCT"
        await db_session.execute(
            delete(LiveLinkParameter).where(LiveLinkParameter.param_key == key)
        )
        await db_session.commit()

        param = await TelemetryService(db_session).auto_register_parameter(
            key, unit="%", param_class="propane"
        )

        assert param.show_on_dashboard is True
        assert param.archive_only is False

    async def test_diagnostics_stay_archive_only(self, db_session):
        """The negative control: widening the list must not surface every row.

        Reading quality, rejected counts and gateway uptime are real
        parameters worth storing and worth nobody's chart.
        """
        svc = TelemetryService(db_session)

        for key, klass in (
            ("PROPANE_T1_QUALITY", "diagnostic"),
            ("RV_GATEWAY_RSSI", "signal"),
        ):
            param = await svc.auto_register_parameter(key, unit=None, param_class=klass)
            assert param.archive_only is True, key

    async def test_every_class_registers_on_the_dashboard(self, db_session):
        """Hiding a gauge is a per-reading switch now, not a class default.

        Before migration 114 the class list decided this too, and on a
        production copy it had hidden 36 of 53 parameters' gauges, none of them
        by anyone's choice. Keys are unique per run: the suite shares one
        database, and a key registered earlier returns its existing row.
        """
        import uuid

        svc = TelemetryService(db_session)
        tag = uuid.uuid4().hex[:8].upper()
        cases = [
            (f"ZZDASH_PRESSURE_{tag}", "pressure"),
            (f"ZZDASH_DISTANCE_{tag}", "distance"),
            (f"ZZDASH_DIAGNOSTIC_{tag}", "diagnostic"),
            # No class, and a key with no catalog substring: `None` is inferred
            # from the key first, and a lucky inference would prove nothing.
            (f"ZZ_UNCLASSIFIABLE_{tag}", None),
        ]
        for key, klass in cases:
            param = await svc.auto_register_parameter(key, unit=None, param_class=klass)
            assert param.show_on_dashboard is True, key

        from sqlalchemy import delete

        await db_session.execute(
            delete(LiveLinkParameter).where(LiveLinkParameter.param_key.in_([k for k, _ in cases]))
        )
        await db_session.commit()


def _named_key() -> str:
    """The registry is shared by the whole suite, so every key is new."""
    return f"ZZNAMED_{uuid.uuid4().hex[:8].upper()}"


@pytest.mark.asyncio
class TestASourceNamesItsReading:
    """A source's name lands on a new row and on one still on its auto name."""

    async def test_a_new_row_takes_the_name(self, db_session):
        param = await TelemetryService(db_session).auto_register_parameter(
            _named_key(), display_name="Readable name"
        )
        assert param.display_name == "Readable name"

    async def test_a_row_on_its_auto_name_takes_it(self, db_session):
        svc = TelemetryService(db_session)
        key = _named_key()
        await svc.auto_register_parameter(key)
        param = await svc.auto_register_parameter(key, display_name="Readable name")
        assert param.display_name == "Readable name"

    async def test_a_row_with_no_name_takes_it(self, db_session):
        svc = TelemetryService(db_session)
        key = _named_key()
        (await svc.auto_register_parameter(key)).display_name = None
        param = await svc.auto_register_parameter(key, display_name="Readable name")
        assert param.display_name == "Readable name"

    async def test_a_name_someone_set_stays(self, db_session):
        svc = TelemetryService(db_session)
        key = _named_key()
        (await svc.auto_register_parameter(key)).display_name = "Mine"
        param = await svc.auto_register_parameter(key, display_name="Readable name")
        assert param.display_name == "Mine"


@pytest.mark.asyncio
async def test_declared_units_fill_rows_on_file_and_create_none(db_session):
    svc = TelemetryService(db_session)
    with_unit, without, absent = _named_key(), _named_key(), _named_key()
    await svc.auto_register_parameter(with_unit, unit="psi")
    await svc.auto_register_parameter(without)
    await svc.fill_declared_units({with_unit: "kPa", without: "kPa", absent: "kPa"})
    assert (await svc.get_parameter(with_unit)).unit == "psi"
    assert (await svc.get_parameter(without)).unit == "kPa"
    assert await svc.get_parameter(absent) is None


@pytest.mark.asyncio
class TestASourceNameFitsTheColumn:
    """`livelink_parameters.display_name` is VARCHAR(100). A source's name went in
    unclamped, so a longer one failed the ingest flush on PostgreSQL (TQ-L2).
    SQLite stores the whole string, which is what these tests catch on main."""

    async def test_a_new_reading_gets_the_first_100_characters(self, db_session):
        svc = TelemetryService(db_session)
        key = _named_key()
        long_name = "Volumetric efficiency " + "x" * 150
        await svc.auto_register_parameter(key, display_name=long_name)
        await db_session.flush()
        db_session.expire_all()
        param = await svc.get_parameter(key)
        assert param is not None
        assert param.display_name == long_name[:100]

    async def test_a_rename_on_the_auto_name_gets_the_first_100_characters(self, db_session):
        svc = TelemetryService(db_session)
        key = _named_key()
        await svc.auto_register_parameter(key)
        long_name = "Trip economy " + "y" * 150
        await svc.auto_register_parameter(key, display_name=long_name)
        await db_session.flush()
        db_session.expire_all()
        param = await svc.get_parameter(key)
        assert param is not None
        assert param.display_name == long_name[:100]
