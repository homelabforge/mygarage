"""Unit tests for the `check_def_levels` scheduled job (Task 16).

DEF (Diesel Exhaust Fluid) depletes over weeks, not minutes, so this job uses
*crossing-based* dedup instead of a cooldown: `Vehicle.def_low_notified_at`
is stamped the moment a vehicle's latest DEF fill_level crosses at/under the
configured threshold, and cleared the moment it recovers above threshold.
That means a single dip only ever notifies once, but a refill-then-dip-again
cycle notifies again — unlike a time-based cooldown, which would either nag
daily or (if long enough) swallow a fresh depletion after a refill.

`check_def_levels()` opens its own `AsyncSessionLocal()` session internally
(matching every sibling job in `scheduled.py`), so these tests monkeypatch
`app.tasks.scheduled.AsyncSessionLocal` to hand back the fixture-managed
`db_session` wrapped in a no-op async context manager — this keeps seeded
vehicles/DEF records and the job's own queries/commit on the same
transaction while still exercising real DB fixtures end-to-end. Only
`NotificationDispatcher.notify_def_low` is mocked.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.units import IMPERIAL_PRESET, METRIC_PRESET, UnitSet, field_to_column
from app.models.def_record import DEFRecord
from app.models.settings import Setting
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.settings_service import SettingsService
from app.tasks.scheduled import _get_def_low_threshold_percent, check_def_levels
from app.utils.datetime_utils import utc_now
from app.utils.default_unit_prefs import DEFAULT_UNIT_PREFS_KEY
from app.utils.render_context import RenderContext

# Every vehicle this module creates uses this VIN prefix, so the autouse
# cleanup fixture below can wipe just this module's leftovers.
_VIN_PREFIX = "DEFLEVELTESTVIN"


@pytest_asyncio.fixture(autouse=True)
async def _clean_slate(db_session: AsyncSession) -> None:
    """Wipe this module's fixtures left over from a previous test.

    `check_def_levels()` commits for real — it holds its own transaction
    inside `AsyncSessionLocal()`, which is spliced onto the fixture-managed
    `db_session` here (see `patch_session` below) — so vehicles/DEF records
    created by an earlier test persist in the shared, session-scoped test
    database. Without cleanup, the next test's full-table `check_def_levels()`
    scan would pick up leftover diesel vehicles and skew dispatch counts.
    Scoped to this module's VIN prefix so unrelated fixtures are untouched.
    """
    await db_session.execute(delete(DEFRecord).where(DEFRecord.vin.like(f"{_VIN_PREFIX}%")))
    await db_session.execute(delete(Vehicle).where(Vehicle.vin.like(f"{_VIN_PREFIX}%")))
    await db_session.commit()


class _PassthroughSessionContext:
    """Async context manager that hands back an already-open session as-is.

    `check_def_levels()` does `async with AsyncSessionLocal() as db:` — this
    stand-in lets tests splice in the fixture's `db_session` instead of a
    freshly created (and separately-transacted) session, without closing it
    on exit (the `db_session` fixture owns that lifecycle).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


@pytest.fixture
def patch_session(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> AsyncSession:
    """Route the job's internal `AsyncSessionLocal()` to the test's `db_session`."""
    monkeypatch.setattr(
        "app.tasks.scheduled.AsyncSessionLocal",
        lambda: _PassthroughSessionContext(db_session),
    )
    return db_session


@pytest_asyncio.fixture
async def make_vehicle(
    db_session: AsyncSession,
) -> Callable[..., Awaitable[Vehicle]]:
    """Create a vehicle, diesel-capable with a DEF tank by default."""
    counter = {"n": 0}

    async def _factory(
        *,
        fuel_type: str | None = "diesel",
        fuel_type_secondary: str | None = None,
        capacity: Decimal | None = Decimal("75.00"),
        archived: bool = False,
        def_low_notified_at: Any = None,
    ) -> Vehicle:
        counter["n"] += 1
        vehicle = Vehicle(
            vin=f"{_VIN_PREFIX}{counter['n']:02d}",
            nickname=f"DEF Test Car {counter['n']}",
            vehicle_type="Car",
            year=2022,
            make="TestMake",
            model="TestModel",
            fuel_type=fuel_type,
            fuel_type_secondary=fuel_type_secondary,
            def_tank_capacity_liters=capacity,
            archived_at=utc_now() if archived else None,
            def_low_notified_at=def_low_notified_at,
        )
        db_session.add(vehicle)
        await db_session.flush()
        return vehicle

    return _factory


@pytest_asyncio.fixture
async def add_def_record(
    db_session: AsyncSession,
) -> Callable[..., Awaitable[DEFRecord]]:
    """Add a DEF record (fill_level is a 0-1 fraction) for a vehicle."""

    async def _factory(
        vin: str,
        *,
        fill_level: Decimal,
        record_date: date,
        entry_type: str = "purchase",
    ) -> DEFRecord:
        record = DEFRecord(
            vin=vin,
            date=record_date,
            fill_level=fill_level,
            entry_type=entry_type,
        )
        db_session.add(record)
        await db_session.flush()
        return record

    return _factory


@pytest_asyncio.fixture
async def enable_def_low(db_session: AsyncSession) -> Callable[..., Awaitable[None]]:
    """Enable DEF-low notifications: a service enabled + the feature toggle on."""

    async def _enable(
        *,
        notify: str = "true",
        threshold: str | None = "25",
    ) -> None:
        await SettingsService.set(db_session, "ntfy_enabled", "true")
        await SettingsService.set(db_session, "notify_def_low", notify)
        if threshold is not None:
            await SettingsService.set(db_session, "notify_def_low_threshold_percent", threshold)
        await db_session.flush()

    return _enable


_OWNER_USERNAME = "def_units_owner"


def _user_unit_columns(units: UnitSet) -> dict[str, str]:
    """Explicit overrides for all eleven quantities, so the owner's resolved
    set is exactly `units` (`field_to_column` owns the `secondary_gallon`
    prefix asymmetry)."""
    return {field_to_column(field): value for field, value in units.model_dump().items()}


@pytest_asyncio.fixture
async def def_owner(db_session: AsyncSession):
    """An imperial vehicle owner, removed afterwards.

    Its vehicles go first: `Vehicle.user_id` references this row, and the
    autouse `_clean_slate` only runs at the START of a test, so a user
    deleted while one of this module's vehicles still pointed at it would
    trip the foreign key.
    """
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
    try:
        yield owner
    finally:
        await db_session.rollback()
        await db_session.execute(delete(DEFRecord).where(DEFRecord.vin.like(f"{_VIN_PREFIX}%")))
        await db_session.execute(delete(Vehicle).where(Vehicle.vin.like(f"{_VIN_PREFIX}%")))
        await db_session.execute(delete(User).where(User.username == _OWNER_USERNAME))
        await db_session.commit()


@pytest_asyncio.fixture
async def metric_instance_default(db_session: AsyncSession):
    """Pin `default_unit_prefs` to METRIC, the opposite of `def_owner`'s set,
    restoring whatever the shared settings table held before."""
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


def _def_calls(mock: AsyncMock) -> list[Any]:
    """Filter notify_def_low awaits down to this module's vehicles.

    `check_def_levels()` scans the WHOLE vehicles table, and the test DB is
    session-scoped and shared across every test file in the run — other
    modules' committed diesel fixtures (e.g. test_def_fuel_type_gate.py's
    vehicles with 0.50-0.75 fill levels) are visible to the sweep. Raw
    `assert_awaited_once()` / `await_count` assertions would therefore be
    hostage to whatever inbound rows happen to sit below this module's
    thresholds. Scoping every count assertion to the `_VIN_PREFIX` keeps
    them deterministic regardless of what other files leave behind.
    """
    return [
        call
        for call in mock.await_args_list
        if str(call.kwargs.get("vin", "")).startswith(_VIN_PREFIX)
    ]


def _patch_notify_def_low(
    monkeypatch: pytest.MonkeyPatch,
    *,
    side_effect: Any = None,
) -> AsyncMock:
    """Patch `NotificationDispatcher.notify_def_low` at the class level."""
    mock = AsyncMock(
        return_value={"ntfy": True} if side_effect is None else None,
        side_effect=side_effect,
    )
    monkeypatch.setattr(
        "app.services.notifications.dispatcher.NotificationDispatcher.notify_def_low",
        mock,
    )
    return mock


@pytest.mark.unit
@pytest.mark.def_records
@pytest.mark.asyncio
class TestCheckDefLevels:
    async def test_below_threshold_unstamped_dispatches_and_stamps(
        self, patch_session, make_vehicle, add_def_record, enable_def_low, monkeypatch
    ):
        await enable_def_low(threshold="25")
        vehicle = await make_vehicle(capacity=Decimal("75.00"))
        await add_def_record(vehicle.vin, fill_level=Decimal("0.20"), record_date=date(2026, 7, 1))
        mock = _patch_notify_def_low(monkeypatch)

        await check_def_levels()

        calls = _def_calls(mock)
        assert len(calls) == 1
        kwargs = calls[0].kwargs
        assert kwargs["vin"] == vehicle.vin
        assert kwargs["percent"] == Decimal("20.00")
        assert kwargs["remaining_liters"] == Decimal("15.0000")
        assert kwargs["as_of_date"] == date(2026, 7, 1)
        assert vehicle.def_low_notified_at is not None

    async def test_below_threshold_already_stamped_no_dispatch(
        self, patch_session, make_vehicle, add_def_record, enable_def_low, monkeypatch
    ):
        await enable_def_low(threshold="25")
        stamp = utc_now()
        vehicle = await make_vehicle(def_low_notified_at=stamp)
        await add_def_record(vehicle.vin, fill_level=Decimal("0.10"), record_date=date(2026, 7, 1))
        mock = _patch_notify_def_low(monkeypatch)

        await check_def_levels()

        assert _def_calls(mock) == []
        assert vehicle.def_low_notified_at == stamp

    async def test_refill_above_threshold_clears_stamp_no_dispatch(
        self, patch_session, make_vehicle, add_def_record, enable_def_low, monkeypatch
    ):
        await enable_def_low(threshold="25")
        vehicle = await make_vehicle(def_low_notified_at=utc_now())
        await add_def_record(vehicle.vin, fill_level=Decimal("0.80"), record_date=date(2026, 7, 1))
        mock = _patch_notify_def_low(monkeypatch)

        await check_def_levels()

        assert _def_calls(mock) == []
        assert vehicle.def_low_notified_at is None

    async def test_dip_again_after_recovery_dispatches_again(
        self, patch_session, make_vehicle, add_def_record, enable_def_low, monkeypatch
    ):
        await enable_def_low(threshold="25")
        vehicle = await make_vehicle()
        mock = _patch_notify_def_low(monkeypatch)

        # First dip below threshold — dispatches and stamps.
        await add_def_record(vehicle.vin, fill_level=Decimal("0.10"), record_date=date(2026, 6, 1))
        await check_def_levels()
        assert len(_def_calls(mock)) == 1
        assert vehicle.def_low_notified_at is not None

        # Refill above threshold — clears the stamp, no dispatch.
        await add_def_record(vehicle.vin, fill_level=Decimal("0.90"), record_date=date(2026, 6, 15))
        await check_def_levels()
        assert len(_def_calls(mock)) == 1
        assert vehicle.def_low_notified_at is None

        # Dip again — re-dispatches (crossing-based dedup, not cooldown).
        await add_def_record(vehicle.vin, fill_level=Decimal("0.15"), record_date=date(2026, 7, 1))
        await check_def_levels()
        assert len(_def_calls(mock)) == 2
        assert vehicle.def_low_notified_at is not None

    async def test_skips_vehicle_with_no_def_capacity(
        self, patch_session, make_vehicle, add_def_record, enable_def_low, monkeypatch
    ):
        await enable_def_low(threshold="25")
        vehicle = await make_vehicle(capacity=None)
        await add_def_record(vehicle.vin, fill_level=Decimal("0.05"), record_date=date(2026, 7, 1))
        mock = _patch_notify_def_low(monkeypatch)

        await check_def_levels()

        assert _def_calls(mock) == []
        assert vehicle.def_low_notified_at is None

    async def test_skips_vehicle_with_no_def_records(
        self, patch_session, make_vehicle, enable_def_low, monkeypatch
    ):
        await enable_def_low(threshold="25")
        vehicle = await make_vehicle()
        mock = _patch_notify_def_low(monkeypatch)

        await check_def_levels()

        assert _def_calls(mock) == []
        assert vehicle.def_low_notified_at is None

    async def test_skips_non_diesel_vehicle(
        self, patch_session, make_vehicle, add_def_record, enable_def_low, monkeypatch
    ):
        await enable_def_low(threshold="25")
        vehicle = await make_vehicle(fuel_type="gasoline", fuel_type_secondary=None)
        await add_def_record(vehicle.vin, fill_level=Decimal("0.05"), record_date=date(2026, 7, 1))
        mock = _patch_notify_def_low(monkeypatch)

        await check_def_levels()

        assert _def_calls(mock) == []

    async def test_skips_archived_vehicle(
        self, patch_session, make_vehicle, add_def_record, enable_def_low, monkeypatch
    ):
        await enable_def_low(threshold="25")
        vehicle = await make_vehicle(archived=True)
        await add_def_record(vehicle.vin, fill_level=Decimal("0.05"), record_date=date(2026, 7, 1))
        mock = _patch_notify_def_low(monkeypatch)

        await check_def_levels()

        assert _def_calls(mock) == []

    async def test_toggle_off_skips_even_when_below_threshold(
        self, patch_session, make_vehicle, add_def_record, enable_def_low, monkeypatch
    ):
        await enable_def_low(notify="false", threshold="25")
        vehicle = await make_vehicle()
        await add_def_record(vehicle.vin, fill_level=Decimal("0.05"), record_date=date(2026, 7, 1))
        mock = _patch_notify_def_low(monkeypatch)

        await check_def_levels()

        assert _def_calls(mock) == []
        assert vehicle.def_low_notified_at is None

    async def test_garbage_threshold_falls_back_to_25(
        self, patch_session, make_vehicle, add_def_record, enable_def_low, monkeypatch
    ):
        await enable_def_low(threshold="banana")
        vehicle = await make_vehicle()
        # 24% is below the fallback of 25% but above any degenerate parse
        # (e.g. 0) — proves the fallback landed on 25, not fail-closed.
        await add_def_record(vehicle.vin, fill_level=Decimal("0.24"), record_date=date(2026, 7, 1))
        mock = _patch_notify_def_low(monkeypatch)

        await check_def_levels()

        assert len(_def_calls(mock)) == 1
        assert vehicle.def_low_notified_at is not None

    async def test_boundary_percent_equals_threshold_notifies(
        self, patch_session, make_vehicle, add_def_record, enable_def_low, monkeypatch
    ):
        await enable_def_low(threshold="25")
        vehicle = await make_vehicle()
        await add_def_record(vehicle.vin, fill_level=Decimal("0.25"), record_date=date(2026, 7, 1))
        mock = _patch_notify_def_low(monkeypatch)

        await check_def_levels()

        assert len(_def_calls(mock)) == 1
        assert vehicle.def_low_notified_at is not None

    async def test_all_backends_failed_no_stamp_retries_next_run(
        self, patch_session, make_vehicle, add_def_record, enable_def_low, monkeypatch
    ):
        """An all-failed dispatch (e.g. a transient Discord outage) must not
        stamp `def_low_notified_at` — mirrors TelemetryService.check_thresholds's
        `any(dispatch_results.values())` guard. Crossing-based dedup means a
        stamp here would otherwise silence the alert until the tank refills
        and dips again, which can be weeks away; leaving it unstamped means
        the next day's run retries the dispatch."""
        await enable_def_low(threshold="25")
        vehicle = await make_vehicle()
        await add_def_record(vehicle.vin, fill_level=Decimal("0.10"), record_date=date(2026, 7, 1))
        mock = _patch_notify_def_low(monkeypatch, side_effect=lambda **_kwargs: {"discord": False})

        await check_def_levels()

        assert len(_def_calls(mock)) == 1
        assert vehicle.def_low_notified_at is None

    async def test_at_least_one_backend_succeeded_stamps(
        self, patch_session, make_vehicle, add_def_record, enable_def_low, monkeypatch
    ):
        """A stamp lands as soon as at least one backend actually delivered,
        even if another configured backend reported failure."""
        await enable_def_low(threshold="25")
        vehicle = await make_vehicle()
        await add_def_record(vehicle.vin, fill_level=Decimal("0.10"), record_date=date(2026, 7, 1))
        mock = _patch_notify_def_low(
            monkeypatch, side_effect=lambda **_kwargs: {"discord": True, "ntfy": False}
        )

        await check_def_levels()

        assert len(_def_calls(mock)) == 1
        assert vehicle.def_low_notified_at is not None

    async def test_per_vehicle_isolation_first_raises_second_still_processed(
        self, patch_session, make_vehicle, add_def_record, enable_def_low, monkeypatch
    ):
        await enable_def_low(threshold="25")
        vehicle_a = await make_vehicle()
        vehicle_b = await make_vehicle()
        await add_def_record(
            vehicle_a.vin, fill_level=Decimal("0.10"), record_date=date(2026, 7, 1)
        )
        await add_def_record(
            vehicle_b.vin, fill_level=Decimal("0.10"), record_date=date(2026, 7, 1)
        )

        async def _side_effect(*args: Any, **kwargs: Any) -> dict[str, bool]:
            if kwargs.get("vin") == vehicle_a.vin:
                raise RuntimeError("boom")
            return {"ntfy": True}

        mock = _patch_notify_def_low(monkeypatch, side_effect=_side_effect)

        await check_def_levels()

        # Both vehicles were attempted despite vehicle_a's dispatcher blowing up.
        assert len(_def_calls(mock)) == 2
        assert vehicle_a.def_low_notified_at is None
        assert vehicle_b.def_low_notified_at is not None


@pytest.mark.unit
@pytest.mark.def_records
@pytest.mark.asyncio
class TestThresholdClamp:
    """`notify_def_low_threshold_percent` is clamped to 1-99."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("500", 99),  # over the ceiling → clamps down to 99
            ("0", 1),  # zero → clamps up to 1
            ("-10", 1),  # negative → clamps up to 1
        ],
    )
    async def test_out_of_range_values_are_clamped(
        self, db_session: AsyncSession, raw: str, expected: int
    ) -> None:
        await SettingsService.set(db_session, "notify_def_low_threshold_percent", raw)
        await db_session.flush()

        assert await _get_def_low_threshold_percent(db_session) == expected


@pytest.mark.unit
@pytest.mark.def_records
@pytest.mark.asyncio
class TestDefLowRenderContextWiring:
    """Which render context the job hands `notify_def_low`.

    The DEF message is a forced litres/gallons pair whose gallon flavour comes
    from that context (D4b), so a job that resolved the wrong one would ship a
    correct-looking message in the wrong gallon. The dispatcher-level suite
    (`tests/unit/services/test_notification_units.py`) constructs the context
    itself and cannot see this; the wiring is what these two tests pin.

    A scheduled job has no caller, so it uses the VEHICLE OWNER's units and
    falls back to the instance default when the vehicle is ownerless. The
    instance default is pinned to metric here while the owner is imperial, so
    the two paths are distinguishable rather than equal by luck.
    """

    async def _run(
        self,
        db_session: AsyncSession,
        make_vehicle,
        add_def_record,
        enable_def_low,
        monkeypatch: pytest.MonkeyPatch,
        *,
        owner: User | None,
    ) -> RenderContext:
        await enable_def_low(threshold="25")
        vehicle = await make_vehicle(capacity=Decimal("75.00"))
        if owner is not None:
            vehicle.user_id = owner.id
            await db_session.flush()
        await add_def_record(vehicle.vin, fill_level=Decimal("0.20"), record_date=date(2026, 7, 1))
        mock = _patch_notify_def_low(monkeypatch)

        await check_def_levels()

        calls = [call for call in _def_calls(mock) if call.kwargs["vin"] == vehicle.vin]
        assert len(calls) == 1
        return calls[0].kwargs["ctx"]

    async def test_owned_vehicle_uses_the_owners_units(
        self,
        patch_session,
        db_session: AsyncSession,
        make_vehicle,
        add_def_record,
        enable_def_low,
        metric_instance_default,
        def_owner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctx = await self._run(
            db_session, make_vehicle, add_def_record, enable_def_low, monkeypatch, owner=def_owner
        )

        assert ctx.units.volume == "gal_us"
        assert ctx.units.distance == "mi"
        assert ctx.show_both is False

    async def test_ownerless_vehicle_falls_back_to_the_instance_default(
        self,
        patch_session,
        db_session: AsyncSession,
        make_vehicle,
        add_def_record,
        enable_def_low,
        metric_instance_default,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`make_vehicle` leaves `user_id` NULL, which is a real production
        state, not a test-only shortcut."""
        ctx = await self._run(
            db_session, make_vehicle, add_def_record, enable_def_low, monkeypatch, owner=None
        )

        assert ctx.units.volume == "L"
        assert ctx.units.distance == "km"
        assert ctx.show_both is False
