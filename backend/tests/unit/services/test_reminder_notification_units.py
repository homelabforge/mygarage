"""Reminder notifications in the vehicle owner's units, and the R2 boundary.

`_build_reminder_message` owns three kinds of content and treats each
differently on purpose:

1. `due_mileage_km` is canonical km and is RENDERED in the reader's distance
   unit.
2. `due_hours` is dimensionless (R6). It is not a `UnitSet` quantity,
   `adapter_for(..., "hours")` raises `KeyError` by design, and it keeps a
   fixed `"hr"` formatter outside the unit system.
3. `notes` is stored prose and is passed through BYTE-IDENTICALLY.

Point 3 is the one worth pinning. An auto-generated low-tread reminder
(`tire_service._sync_low_tread_reminder`) writes `due_mileage_km=None` and
puts its tread depth and projected distance ONLY into `notes`, so this task
converting a reminder's own fields converts nothing at all in that message.
Rewriting the stored notes instead would persist display text: it would go
stale the moment a user changed preferences and would never refresh, because
notes are written once at creation and the reminder completes only when tread
recovers. Correct low-tread units are blocked on the tire workstream's
migration A gaining structured tread and distance columns (recorded in
`2026-08-25-tire-mount-periods-design.md` under "Low-tread reminder units").

`test_low_tread_notes_pass_through_byte_identically` therefore pins the
boundary in both directions, so a later change cannot quietly start rewriting
stored text.

Derivations, from `UnitConverter.MILES_TO_KM = 1.60934`:

    50,000 canonical km / 1.60934 = 31,068.6368... -> "31,069 mi"

Tests share one database with no per-test rollback: every row here is torn
down in `finally`, and the VIN/username are scoped to this module.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.units import IMPERIAL_PRESET, METRIC_PRESET, UnitSet, field_to_column
from app.models.reminder import Reminder
from app.models.settings import Setting
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.reminder_service import _build_reminder_message, check_due_reminders
from app.utils.default_unit_prefs import DEFAULT_UNIT_PREFS_KEY
from app.utils.render_context import RenderContext

_VIN_PREFIX = "REMINDERUNITS"
_OWNED_VIN = f"{_VIN_PREFIX}01"
_OWNERLESS_VIN = f"{_VIN_PREFIX}02"
_OWNER_USERNAME = "reminder_units_owner"

_METRIC_CTX = RenderContext(units=METRIC_PRESET, show_both=False)
_IMPERIAL_CTX = RenderContext(units=IMPERIAL_PRESET, show_both=False)

# Fixed, never relative: a calendar-relative fixture is a time bomb in a
# suite that shares one database.
_DUE_DATE = date(2020, 1, 1)
_DUE_MILEAGE_KM = Decimal("50000")

# Exactly the shape `tire_service._sync_low_tread_reminder` writes: metric
# prose, both quantities inside `notes`, and no `due_mileage_km` at all.
_LOW_TREAD_NOTES = "Tread 3.0 mm ≤ threshold 4.0 mm. ~12000 km remaining."


@pytest.mark.unit
class TestBuildReminderMessageUnits:
    """Pure formatting: the caller supplies the context, the builder renders."""

    def _mileage_reminder(self) -> Reminder:
        return Reminder(
            vin=_OWNED_VIN,
            title="Tire rotation",
            reminder_type="both",
            due_date=_DUE_DATE,
            due_mileage_km=_DUE_MILEAGE_KM,
            status="pending",
        )

    def test_metric_context_renders_kilometres(self) -> None:
        message = _build_reminder_message(self._mileage_reminder(), _METRIC_CTX)

        assert message == (
            "Service reminder: Tire rotation\nDue date: 2020-01-01\nDue mileage: 50,000 km"
        )

    def test_imperial_context_converts_the_canonical_kilometre_value(self) -> None:
        """Converted, not relabelled: 50,000 canonical km is 31,069 mi."""
        message = _build_reminder_message(self._mileage_reminder(), _IMPERIAL_CTX)

        assert message == (
            "Service reminder: Tire rotation\nDue date: 2020-01-01\nDue mileage: 31,069 mi"
        )
        assert "50,000" not in message

    def test_show_both_appends_the_counterpart(self) -> None:
        ctx = RenderContext(units=IMPERIAL_PRESET, show_both=True)

        message = _build_reminder_message(self._mileage_reminder(), ctx)

        assert message.endswith("Due mileage: 31,069 mi (50,000 km)")

    @pytest.mark.parametrize("ctx", [_METRIC_CTX, _IMPERIAL_CTX], ids=["metric", "imperial"])
    def test_due_hours_stay_dimensionless(self, ctx: RenderContext) -> None:
        """R6: hours are not a `UnitSet` quantity. Both unit sets render the
        same `hr` string, and neither raises the `KeyError` `adapter_for`
        would produce for `"hours"`."""
        reminder = Reminder(
            vin=_OWNED_VIN,
            title="Hydraulic service",
            reminder_type="hours",
            due_hours=Decimal("500.0"),
            status="pending",
        )

        message = _build_reminder_message(reminder, ctx)

        assert message == "Service reminder: Hydraulic service\nDue hours: 500.0 hr"

    def test_low_tread_notes_pass_through_byte_identically(self) -> None:
        """The R2 boundary, pinned in both directions.

        A low-tread reminder carries its tread depth and projected distance
        only in stored prose, with `due_mileage_km=None`. Both readers must
        get that prose back unaltered -- the imperial reader included, whose
        message keeps `3.0 mm` and `~12000 km` verbatim. This test fails the
        moment anything starts rewriting stored notes, which is the outcome
        it exists to prevent.
        """
        reminder = Reminder(
            vin=_OWNED_VIN,
            title="Tire tread low (FL)",
            reminder_type="date",
            due_date=_DUE_DATE,
            due_mileage_km=None,
            notes=_LOW_TREAD_NOTES,
            status="pending",
        )

        metric_message = _build_reminder_message(reminder, _METRIC_CTX)
        imperial_message = _build_reminder_message(reminder, _IMPERIAL_CTX)

        expected = (
            "Service reminder: Tire tread low (FL)\n"
            "Due date: 2020-01-01\n"
            f"Notes: {_LOW_TREAD_NOTES}"
        )
        assert metric_message == expected
        assert imperial_message == expected
        # The notes segment, isolated: byte-identical to what was stored.
        assert imperial_message.split("Notes: ", 1)[1] == _LOW_TREAD_NOTES
        # And specifically not converted in place.
        assert "3.0 mm" in imperial_message
        assert "~12000 km" in imperial_message


def _user_unit_columns(units: UnitSet) -> dict[str, str]:
    """Explicit overrides for all eleven quantities (`field_to_column` owns
    the `secondary_gallon` prefix asymmetry)."""
    return {field_to_column(field): value for field, value in units.model_dump().items()}


@pytest_asyncio.fixture
async def metric_instance_default(db_session: AsyncSession):
    """Pin `default_unit_prefs` to METRIC, the opposite of the owner's set."""
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


@pytest_asyncio.fixture
async def seeded_reminders(db_session: AsyncSession):
    """An imperial-owner vehicle and an ownerless one, each with one pending,
    already-due reminder carrying the same canonical mileage."""
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
                nickname="Reminder Units Owned",
                vehicle_type="Car",
            ),
            Vehicle(
                vin=_OWNERLESS_VIN,
                user_id=None,
                nickname="Reminder Units Ownerless",
                vehicle_type="Car",
            ),
        ]
    )
    await db_session.commit()
    db_session.add_all(
        [
            Reminder(
                vin=_OWNED_VIN,
                title="Reminder Units Owned Service",
                reminder_type="both",
                due_date=_DUE_DATE,
                due_mileage_km=_DUE_MILEAGE_KM,
                status="pending",
            ),
            Reminder(
                vin=_OWNERLESS_VIN,
                title="Reminder Units Ownerless Service",
                reminder_type="both",
                due_date=_DUE_DATE,
                due_mileage_km=_DUE_MILEAGE_KM,
                status="pending",
            ),
        ]
    )
    await db_session.commit()

    try:
        yield
    finally:
        # A failed test can leave the session in a rolled-back-pending
        # state; the suite shares one database, so cleanup must still run.
        await db_session.rollback()
        await db_session.execute(delete(Reminder).where(Reminder.vin.like(f"{_VIN_PREFIX}%")))
        await db_session.execute(delete(Vehicle).where(Vehicle.vin.like(f"{_VIN_PREFIX}%")))
        await db_session.execute(delete(User).where(User.username == _OWNER_USERNAME))
        await db_session.commit()


@pytest.mark.unit
class TestCheckDueRemindersUnits:
    """Wiring, not formatting: which context the scheduler entry point resolves.

    `check_due_reminders` has no caller, so it resolves the VEHICLE OWNER's
    context per reminder. The instance default is pinned to metric while the
    owner is imperial, so a job that fell back to the default fails instead
    of coincidentally agreeing.
    """

    def _stub_dispatcher(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        sent: list[str] = []

        class _StubDispatcher:
            def __init__(self, db):
                pass

            async def dispatch(self, event_type, title, message):
                sent.append(message)

        monkeypatch.setattr(
            "app.services.notifications.dispatcher.NotificationDispatcher",
            _StubDispatcher,
        )
        return sent

    def _own(self, sent: list[str], title: str) -> list[str]:
        """Messages this module's reminder produced. The job sweeps every
        pending reminder in the shared database."""
        return [m for m in sent if m.startswith(f"Service reminder: {title}")]

    async def test_owned_reminder_renders_in_the_owners_units(
        self,
        db_session: AsyncSession,
        metric_instance_default,
        seeded_reminders,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sent = self._stub_dispatcher(monkeypatch)

        await check_due_reminders(db_session)

        assert self._own(sent, "Reminder Units Owned Service") == [
            "Service reminder: Reminder Units Owned Service\n"
            "Due date: 2020-01-01\n"
            "Due mileage: 31,069 mi"
        ]

    async def test_ownerless_reminder_falls_back_to_the_instance_default(
        self,
        db_session: AsyncSession,
        metric_instance_default,
        seeded_reminders,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sent = self._stub_dispatcher(monkeypatch)

        await check_due_reminders(db_session)

        assert self._own(sent, "Reminder Units Ownerless Service") == [
            "Service reminder: Reminder Units Ownerless Service\n"
            "Due date: 2020-01-01\n"
            "Due mileage: 50,000 km"
        ]

    async def test_both_reminders_render_differently_in_one_sweep(
        self,
        db_session: AsyncSession,
        metric_instance_default,
        seeded_reminders,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """One sweep, one canonical mileage, two renderings: the context is
        resolved per reminder, not once for the run."""
        sent = self._stub_dispatcher(monkeypatch)

        await check_due_reminders(db_session)

        assert self._own(sent, "Reminder Units Owned Service") == [
            "Service reminder: Reminder Units Owned Service\n"
            "Due date: 2020-01-01\n"
            "Due mileage: 31,069 mi"
        ]
        assert self._own(sent, "Reminder Units Ownerless Service") == [
            "Service reminder: Reminder Units Ownerless Service\n"
            "Due date: 2020-01-01\n"
            "Due mileage: 50,000 km"
        ]
