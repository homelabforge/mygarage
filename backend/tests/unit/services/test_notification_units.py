"""Notification rendering in the reader's units: L3 and the DEF forced pair.

Two surfaces, two deliberately different rules.

**L3 was a live shipped bug.** ``notify_odometer_milestone`` announced
``"<n> miles"`` for a value derived from ``Vehicle.last_milestone_notified_km``
-- canonical KILOMETRES. ``app/tasks/scheduled.py`` logs the very same number
as km three lines after dispatching it, so a metric user was told their
kilometres were miles. Captured before the fix::

    Congratulations! Metric Truck has reached 100,000 miles!

for a canonical input of 100,000 km. Every test here pins the WHOLE message,
so a "fix" that merely swapped the word ``miles`` for ``km`` -- still wrong
for an imperial reader, who wants the value CONVERTED -- fails just as loudly
as the original did.

**DEF is the opposite rule (R7):** a forced dual representation. It emits
litres and gallons always, independent of ``show_both``, in a fixed
litres-then-gallons order. The gallon flavour follows D4b precedence: a
``gal_us``/``gal_uk`` primary states its own flavour and wins outright, and
``secondary_gallon`` applies only when ``volume`` is ``L``. Both conflict
directions are exercised below, not two settings that happen to agree.

Expected strings are derived, not transcribed from the plan's illustrative
grammar table (which has carried arithmetic errors through six rounds):

    100,000 km / 1.60934 (``UnitConverter.MILES_TO_KM``) = 62,137.2736...
        -> ``mi`` adapter precision 0 -> "62,137 mi"
    2.50 L / 3.78541 (``US_GALLONS_TO_LITERS``) = 0.66043...
        -> ``gal_us`` adapter precision 2 -> "0.66 gal"
    2.50 L / 4.54609 (``UK_GALLONS_TO_LITERS``) = 0.54992...
        -> ``gal_uk`` adapter precision 2 -> "0.55 gal"

No database: the dispatcher is handed a ``RenderContext`` by its caller and
resolves nothing itself (the scheduled job owns that, and
``tests/unit/tasks/test_check_odometer_milestones.py`` owns proving it).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.constants.units import IMPERIAL_PRESET, METRIC_PRESET, UnitSet
from app.services.notifications.dispatcher import NotificationDispatcher
from app.utils.render_context import RenderContext

_VIN = "1FTFW1ET5DFC10312"
_AS_OF = date(2026, 6, 15)

# A litre primary that defers to secondary_gallon, and the two conflict cases.
_METRIC_SECONDARY_UK = UnitSet.model_validate(
    METRIC_PRESET.model_dump() | {"secondary_gallon": "uk"}
)
_UK_PRIMARY_US_SECONDARY = UnitSet.model_validate(
    IMPERIAL_PRESET.model_dump() | {"volume": "gal_uk", "secondary_gallon": "us"}
)
_US_PRIMARY_UK_SECONDARY = UnitSet.model_validate(
    IMPERIAL_PRESET.model_dump() | {"volume": "gal_us", "secondary_gallon": "uk"}
)


@pytest.fixture
def dispatcher() -> NotificationDispatcher:
    """A dispatcher whose `dispatch` is mocked, so tests read the message."""
    d = NotificationDispatcher(AsyncMock())
    d.dispatch = AsyncMock(return_value={"ntfy": True})
    return d


def _message(dispatcher: NotificationDispatcher) -> str:
    """The `message` kwarg of the single dispatch this test triggered."""
    return dispatcher.dispatch.call_args.kwargs["message"]


@pytest.mark.unit
@pytest.mark.notifications
class TestOdometerMilestoneUnits:
    """L3: the milestone value is canonical km and must be rendered, not relabelled."""

    async def test_metric_reader_is_told_kilometres_not_miles(
        self, dispatcher: NotificationDispatcher
    ) -> None:
        """The shipped bug, from the metric reader's side: 100,000 canonical km
        was announced as "100,000 miles". The label must say km AND the number
        must be unchanged, because no conversion is due for this reader."""
        ctx = RenderContext(units=METRIC_PRESET, show_both=False)

        await dispatcher.notify_odometer_milestone(
            vehicle_name="Metric Truck", canonical_km=Decimal("100000"), ctx=ctx
        )

        assert _message(dispatcher) == "Congratulations! Metric Truck has reached 100,000 km!"
        assert "miles" not in _message(dispatcher)

    async def test_imperial_reader_gets_the_value_converted_not_relabelled(
        self, dispatcher: NotificationDispatcher
    ) -> None:
        """The other half of L3, and the half a label-only fix would miss:
        100,000 canonical km is 62,137 mi, not 100,000 of anything."""
        ctx = RenderContext(units=IMPERIAL_PRESET, show_both=False)

        await dispatcher.notify_odometer_milestone(
            vehicle_name="Imperial Truck", canonical_km=Decimal("100000"), ctx=ctx
        )

        assert _message(dispatcher) == "Congratulations! Imperial Truck has reached 62,137 mi!"
        assert "100,000" not in _message(dispatcher)

    async def test_show_both_appends_the_counterpart(
        self, dispatcher: NotificationDispatcher
    ) -> None:
        """`ctx.show_both` reaches the formatter rather than being dropped on
        the way: the same canonical value gains a parenthetical counterpart."""
        ctx = RenderContext(units=METRIC_PRESET, show_both=True)

        await dispatcher.notify_odometer_milestone(
            vehicle_name="Both Truck", canonical_km=Decimal("100000"), ctx=ctx
        )

        assert (
            _message(dispatcher)
            == "Congratulations! Both Truck has reached 100,000 km (62,137 mi)!"
        )

    async def test_title_still_names_the_vehicle(self, dispatcher: NotificationDispatcher) -> None:
        """The unit work must not disturb the event type or the title."""
        ctx = RenderContext(units=METRIC_PRESET, show_both=False)

        await dispatcher.notify_odometer_milestone(
            vehicle_name="Metric Truck", canonical_km=Decimal("100000"), ctx=ctx
        )

        kwargs = dispatcher.dispatch.call_args.kwargs
        assert kwargs["event_type"] == "odometer_milestone"
        assert kwargs["title"] == "Milestone Reached: Metric Truck"


@pytest.mark.unit
@pytest.mark.notifications
@pytest.mark.def_records
class TestDefForcedVolumePair:
    """R7: DEF stays dual regardless of `show_both`, with D4b flavour precedence."""

    async def _dispatch_def(self, dispatcher: NotificationDispatcher, ctx: RenderContext) -> str:
        await dispatcher.notify_def_low(
            vehicle_name="My Truck",
            vin=_VIN,
            percent=Decimal("25"),
            remaining_liters=Decimal("2.50"),
            as_of_date=_AS_OF,
            ctx=ctx,
        )
        return _message(dispatcher)

    async def test_stays_dual_for_a_metric_reader_with_show_both_off(
        self, dispatcher: NotificationDispatcher
    ) -> None:
        """The forced pair is not `format_quantity` with a flag: a metric
        reader who has NOT opted into show-both still gets both units."""
        ctx = RenderContext(units=METRIC_PRESET, show_both=False)

        message = await self._dispatch_def(dispatcher, ctx)

        assert message == (
            f"DEF level for My Truck ({_VIN}) is at 25.0% "
            "(2.50 L / 0.66 gal remaining), as of 2026-06-15."
        )

    async def test_show_both_does_not_change_the_forced_pair(
        self, dispatcher: NotificationDispatcher
    ) -> None:
        """Same unit set, `show_both=True`: byte-identical, and specifically
        NOT the parenthesised counterpart grammar `format_quantity` would add."""
        ctx = RenderContext(units=METRIC_PRESET, show_both=True)

        message = await self._dispatch_def(dispatcher, ctx)

        assert message == (
            f"DEF level for My Truck ({_VIN}) is at 25.0% "
            "(2.50 L / 0.66 gal remaining), as of 2026-06-15."
        )

    async def test_litre_primary_defers_to_a_uk_secondary_gallon(
        self, dispatcher: NotificationDispatcher
    ) -> None:
        """`volume="L"` states no gallon flavour, so `secondary_gallon` supplies
        it: 2.50 L is 0.55 UK gal, not 0.66 US gal."""
        ctx = RenderContext(units=_METRIC_SECONDARY_UK, show_both=False)

        message = await self._dispatch_def(dispatcher, ctx)

        assert message == (
            f"DEF level for My Truck ({_VIN}) is at 25.0% "
            "(2.50 L / 0.55 gal remaining), as of 2026-06-15."
        )

    async def test_gal_uk_primary_beats_a_us_secondary_gallon(
        self, dispatcher: NotificationDispatcher
    ) -> None:
        """D4b conflict direction one: a UK-gallon primary wins outright over
        `secondary_gallon="us"`."""
        ctx = RenderContext(units=_UK_PRIMARY_US_SECONDARY, show_both=False)

        message = await self._dispatch_def(dispatcher, ctx)

        assert message == (
            f"DEF level for My Truck ({_VIN}) is at 25.0% "
            "(2.50 L / 0.55 gal remaining), as of 2026-06-15."
        )

    async def test_gal_us_primary_beats_a_uk_secondary_gallon(
        self, dispatcher: NotificationDispatcher
    ) -> None:
        """D4b conflict direction two, the mirror image. Testing only one
        direction would pass for an implementation that always preferred one
        flavour."""
        ctx = RenderContext(units=_US_PRIMARY_UK_SECONDARY, show_both=False)

        message = await self._dispatch_def(dispatcher, ctx)

        assert message == (
            f"DEF level for My Truck ({_VIN}) is at 25.0% "
            "(2.50 L / 0.66 gal remaining), as of 2026-06-15."
        )

    async def test_dispatcher_does_not_read_the_instance_gallon_setting(
        self, dispatcher: NotificationDispatcher
    ) -> None:
        """The flavour comes from the passed context, never from ambient state.

        `dispatcher.db` here is a bare `AsyncMock`: a surviving
        `resolve_gallon_flavour(self.db)` would fabricate a coroutine rather
        than a Setting row, so this asserts the context alone decides. The UK
        context must win even though the mock DB can answer nothing at all.
        """
        ctx = RenderContext(units=_UK_PRIMARY_US_SECONDARY, show_both=False)

        message = await self._dispatch_def(dispatcher, ctx)

        assert "0.55 gal" in message
        assert "0.66" not in message
