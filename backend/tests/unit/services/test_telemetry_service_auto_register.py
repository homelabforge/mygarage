"""Unit tests for TelemetryService.auto_register_parameter param-class inference.

Task 11: MQTT-discovered params arrive with an empty config block (`config={}`),
so `param_class` has historically been left `None` for anything the WiCAN
config didn't label — which silently bypassed all `TelemetryValidator`
range/rate checks. `infer_param_class()` (Task 10) gives us a conservative,
catalog-based fallback; this file pins how `auto_register_parameter` wires it
in for both the new-row and existing-row (backfill) paths.
"""

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
