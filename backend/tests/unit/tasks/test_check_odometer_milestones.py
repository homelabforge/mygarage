"""Wiring: which render context the milestone job actually resolves.

The dispatcher-level suite
(`tests/unit/services/test_notification_units.py`) constructs the
`RenderContext` itself, so every assertion in it passes just as happily if
the scheduled job hands the dispatcher a hardcoded default on every run.
The WIRING is the thing under test here, and Task 5 proved this distinction
is not academic: a route mutation there left the generator suite passing 8
of 8 while the wiring tests failed 3 of 6.

A scheduled job has no caller, so it uses the VEHICLE OWNER's units
(`render_context_for_vehicle`) -- deliberately the opposite of a request,
which uses the caller's. The instance default is pinned to METRIC for the
duration of each test while the owner is IMPERIAL, so an owned vehicle that
fell back to `render_context_default` fails rather than coincidentally
agreeing, and an ownerless vehicle that somehow resolved a user fails too.

Derivations, computed from `UnitConverter.MILES_TO_KM = 1.60934` rather
than transcribed:

    100,000 canonical km / 1.60934 = 62,137.2736... -> "62,137 mi"
    100,000 canonical km rendered as km              -> "100,000 km"

Tests share one database with no per-test rollback, so every row created
here is torn down in `finally`, and every VIN/username is scoped to this
module.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.units import IMPERIAL_PRESET, METRIC_PRESET, UnitSet, field_to_column
from app.models.odometer import OdometerRecord
from app.models.settings import Setting
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.settings_service import SettingsService
from app.tasks.scheduled import check_odometer_milestones
from app.utils.default_unit_prefs import DEFAULT_UNIT_PREFS_KEY

_VIN_PREFIX = "MILESTONEUNITS"
_OWNED_VIN = f"{_VIN_PREFIX}01"
_OWNERLESS_VIN = f"{_VIN_PREFIX}02"
_OWNER_USERNAME = "milestone_units_owner"
_OWNED_NICKNAME = "Milestone Units Owned"
_OWNERLESS_NICKNAME = "Milestone Units Ownerless"

# A milestone boundary (MILESTONE_INTERVAL_KM = 10_000) so the job's
# integer-floor arithmetic lands exactly on the number under test.
_ODOMETER_KM = Decimal("100000")
_READING_DATE = date(2026, 6, 15)

_EXPECTED_OWNER_MESSAGE = f"Congratulations! {_OWNED_NICKNAME} has reached 62,137 mi!"
_EXPECTED_DEFAULT_MESSAGE = f"Congratulations! {_OWNERLESS_NICKNAME} has reached 100,000 km!"


class _PassthroughSessionContext:
    """Hand `check_odometer_milestones` the fixture's open session as-is.

    Mirrors `tests/unit/tasks/test_check_def_levels.py`: the job does
    `async with AsyncSessionLocal() as db:` and this splices in the
    test-managed session without closing it on exit.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


@pytest.fixture
def patch_session(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> AsyncSession:
    """Route the job's internal `AsyncSessionLocal()` to the test's session."""
    monkeypatch.setattr(
        "app.tasks.scheduled.AsyncSessionLocal",
        lambda: _PassthroughSessionContext(db_session),
    )
    return db_session


@pytest_asyncio.fixture
async def enable_milestones(db_session: AsyncSession):
    """Turn on one notification service plus the milestone toggle, restoring
    whatever the shared settings table held before."""
    keys = ("ntfy_enabled", "notify_milestones")
    originals: dict[str, str | None] = {}
    for key in keys:
        row = await SettingsService.get(db_session, key)
        originals[key] = row.value if row is not None else None
        await SettingsService.set(db_session, key, "true")
    await db_session.commit()
    yield
    for key, value in originals.items():
        await SettingsService.set(db_session, key, value if value is not None else "false")
    await db_session.commit()


@pytest_asyncio.fixture
async def metric_instance_default(db_session: AsyncSession):
    """Pin `default_unit_prefs` to METRIC, restoring the prior row after.

    Deliberately the opposite of the owner's imperial set below, so the two
    resolution paths are distinguishable rather than equal by luck.
    """
    row = await db_session.get(Setting, DEFAULT_UNIT_PREFS_KEY)
    original: dict[str, str | None] | None = None
    if row is not None:
        original = {"value": row.value, "category": row.category}
        row.value = json.dumps(METRIC_PRESET.model_dump())
    else:
        db_session.add(
            Setting(
                key=DEFAULT_UNIT_PREFS_KEY,
                value=json.dumps(METRIC_PRESET.model_dump()),
                category="general",
            )
        )
    await db_session.commit()
    yield
    saved = await db_session.get(Setting, DEFAULT_UNIT_PREFS_KEY)
    if original is None:
        if saved is not None:
            await db_session.delete(saved)
    elif saved is not None:
        saved.value = original["value"]
        saved.category = original["category"]
    else:
        db_session.add(Setting(key=DEFAULT_UNIT_PREFS_KEY, **original))
    await db_session.commit()


def _user_unit_columns(units: UnitSet) -> dict[str, str]:
    """Explicit overrides for all eleven quantities, so the resolved set is
    exactly `units` and cannot drift with a preset change.

    `field_to_column` owns the one asymmetry (`secondary_gallon` is stored
    unprefixed while the ten quantities carry a `unit_` prefix).
    """
    return {field_to_column(field): value for field, value in units.model_dump().items()}


@pytest_asyncio.fixture
async def seeded_vehicles(db_session: AsyncSession):
    """One imperial-owner vehicle and one ownerless vehicle, both parked on a
    milestone boundary, torn down afterwards."""
    owner = User(
        username=_OWNER_USERNAME,
        email=f"{_OWNER_USERNAME}@example.test",
        unit_preference="custom",
        show_both_units=False,
        **_user_unit_columns(IMPERIAL_PRESET),
    )
    db_session.add(owner)
    await db_session.commit()
    await db_session.refresh(owner)

    db_session.add_all(
        [
            Vehicle(
                vin=_OWNED_VIN,
                user_id=owner.id,
                nickname=_OWNED_NICKNAME,
                vehicle_type="Car",
            ),
            Vehicle(
                vin=_OWNERLESS_VIN,
                user_id=None,
                nickname=_OWNERLESS_NICKNAME,
                vehicle_type="Car",
            ),
        ]
    )
    await db_session.commit()
    db_session.add_all(
        [
            OdometerRecord(
                vin=_OWNED_VIN,
                date=_READING_DATE,
                odometer_km=_ODOMETER_KM,
                source="manual",
            ),
            OdometerRecord(
                vin=_OWNERLESS_VIN,
                date=_READING_DATE,
                odometer_km=_ODOMETER_KM,
                source="manual",
            ),
        ]
    )
    await db_session.commit()

    try:
        yield owner
    finally:
        # A failed test can leave the session in a rolled-back-pending
        # state; the suite shares one database, so cleanup must still run.
        await db_session.rollback()
        await db_session.execute(
            delete(OdometerRecord).where(OdometerRecord.vin.like(f"{_VIN_PREFIX}%"))
        )
        await db_session.execute(delete(Vehicle).where(Vehicle.vin.like(f"{_VIN_PREFIX}%")))
        await db_session.execute(delete(User).where(User.username == _OWNER_USERNAME))
        await db_session.commit()


def _messages_for(mock: AsyncMock, nickname: str) -> list[str]:
    """Milestone messages this module's vehicle produced.

    `check_odometer_milestones` sweeps the WHOLE vehicles table and the test
    database is shared across the run, so other modules' committed vehicles
    can dispatch too. Scoping by nickname keeps the assertions deterministic
    regardless of what else is present.
    """
    return [
        call.kwargs["message"]
        for call in mock.await_args_list
        if nickname in call.kwargs.get("title", "")
    ]


@pytest.mark.unit
@pytest.mark.notifications
class TestCheckOdometerMilestonesUnits:
    async def test_owned_vehicle_renders_in_the_owners_units(
        self,
        patch_session,
        enable_milestones,
        metric_instance_default,
        seeded_vehicles,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The owner is imperial while the instance default is metric, so this
        can only pass if the job resolved the OWNER."""
        mock = AsyncMock(return_value={"ntfy": True})
        monkeypatch.setattr(
            "app.services.notifications.dispatcher.NotificationDispatcher.dispatch", mock
        )

        await check_odometer_milestones()

        assert _messages_for(mock, _OWNED_NICKNAME) == [_EXPECTED_OWNER_MESSAGE]

    async def test_ownerless_vehicle_falls_back_to_the_instance_default(
        self,
        patch_session,
        enable_milestones,
        metric_instance_default,
        seeded_vehicles,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`Vehicle.user_id IS NULL` is a real state. The job must fall back to
        the instance default (metric here), not raise and not silently use the
        other vehicle's owner."""
        mock = AsyncMock(return_value={"ntfy": True})
        monkeypatch.setattr(
            "app.services.notifications.dispatcher.NotificationDispatcher.dispatch", mock
        )

        await check_odometer_milestones()

        assert _messages_for(mock, _OWNERLESS_NICKNAME) == [_EXPECTED_DEFAULT_MESSAGE]

    async def test_the_two_vehicles_render_differently_in_one_sweep(
        self,
        patch_session,
        enable_milestones,
        metric_instance_default,
        seeded_vehicles,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """One run, one identical canonical reading, two different renderings.

        A per-run context resolved once and reused for every vehicle would
        pass both tests above only if it happened to match; this pins that
        the context is resolved PER VEHICLE.
        """
        mock = AsyncMock(return_value={"ntfy": True})
        monkeypatch.setattr(
            "app.services.notifications.dispatcher.NotificationDispatcher.dispatch", mock
        )

        await check_odometer_milestones()

        assert _messages_for(mock, _OWNED_NICKNAME) == [_EXPECTED_OWNER_MESSAGE]
        assert _messages_for(mock, _OWNERLESS_NICKNAME) == [_EXPECTED_DEFAULT_MESSAGE]

    async def test_the_job_stamps_the_canonical_kilometre_value(
        self,
        patch_session,
        enable_milestones,
        metric_instance_default,
        seeded_vehicles,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Storage stays metric-canonical: rendering in miles must not write
        miles back into `last_milestone_notified_km`."""
        mock = AsyncMock(return_value={"ntfy": True})
        monkeypatch.setattr(
            "app.services.notifications.dispatcher.NotificationDispatcher.dispatch", mock
        )

        await check_odometer_milestones()

        stamped = (
            await patch_session.execute(
                select(Vehicle.last_milestone_notified_km).where(Vehicle.vin == _OWNED_VIN)
            )
        ).scalar_one()
        assert stamped == _ODOMETER_KM
