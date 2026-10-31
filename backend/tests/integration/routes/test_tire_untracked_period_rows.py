"""The period editor moves a row its period published on an axis the vehicle stopped tracking (D5).

A period published while its axis was tracked owns a row there. Once the
vehicle switches to the other axis only, the editor used to loop over tracked
axes and leave that row on the old date. Now a moved date moves it: only the
date, the figure stays as stored, a cleared mount date deletes it, and an axis
with no owned row never grows one.

Every scenario runs both ways: a car switched to hours only, and an hours ATV
switched to distance only.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete

from app.models.vehicle import Vehicle
from tests.integration.routes.test_tire_event_markers import (
    D0,
    D1,
    D2,
    DISTANCE,
    HOURS,
    Axis,
    E,
    X,
    _create_mount,
    _edit_period,
    _hand_set,
    _mark,
    _on,
    _reading,
    _rows,
    _stored,
)


@pytest.fixture(params=[DISTANCE, HOURS], ids=["distance", "hours"])
def ax(request) -> Axis:
    """The axis the period publishes on, before the vehicle stops tracking it."""
    return request.param


def _other(ax: Axis) -> Axis:
    return HOURS if ax is DISTANCE else DISTANCE


@pytest_asyncio.fixture
async def vin(ax: Axis, db_session, test_user):
    made = f"UNT{uuid.uuid4().hex[:14].upper()}"
    db_session.add(
        Vehicle(
            vin=made,
            user_id=test_user["id"],
            nickname="Untracked rows",
            vehicle_type="ATV" if ax is HOURS else "Car",
            year=2022,
            make="Honda",
            model="Pioneer" if ax is HOURS else "Civic",
            usage_unit=ax.usage_unit,
            secondary_usage_enabled=False,
        )
    )
    await db_session.commit()
    yield made
    await db_session.execute(delete(Vehicle).where(Vehicle.vin == made))
    await db_session.commit()


async def _stop_tracking(client: AsyncClient, headers, ax: Axis, vin: str) -> None:
    """Switch the vehicle to the other axis only, so `ax` is no longer tracked."""
    put = await client.put(
        f"/api/vehicles/{vin}",
        headers=headers,
        json={"usage_unit": _other(ax).usage_unit, "secondary_usage_enabled": False},
    )
    assert put.status_code == 200, put.text


@pytest.mark.asyncio
class TestTheEditorMovesAnUntrackedRow:
    async def test_a_moved_mount_date_moves_the_row(
        self, client, auth_headers, db_session, ax, vin
    ):
        tire = await _create_mount(client, auth_headers, ax, vin, "FL", D1, X)
        mount = _mark("tire_mount", tire["mount_periods"][0]["id"])
        await _stop_tracking(client, auth_headers, ax, vin)

        await _edit_period(client, auth_headers, vin, tire, mounted_on=D0.isoformat())

        assert await _rows(db_session, ax, vin) == [(D0, X, mount, "tire_mount")]

    async def test_a_corrected_figure_stays_when_the_date_moves(
        self, client, auth_headers, db_session, ax, vin
    ):
        tire = await _create_mount(client, auth_headers, ax, vin, "FL", D1, X)
        mount = _mark("tire_mount", tire["mount_periods"][0]["id"])
        await _hand_set(db_session, ax, vin, mount, X + 50)
        await _stop_tracking(client, auth_headers, ax, vin)

        await _edit_period(client, auth_headers, vin, tire, mounted_on=D0.isoformat())

        assert await _rows(db_session, ax, vin) == [(D0, X + 50, mount, "tire_mount")]

    async def test_a_cleared_mount_date_deletes_the_row(
        self, client, auth_headers, db_session, ax, vin
    ):
        tire = await _create_mount(client, auth_headers, ax, vin, "FL", D1, X)
        await _stop_tracking(client, auth_headers, ax, vin)

        await _edit_period(client, auth_headers, vin, tire, mounted_on=None)

        assert await _rows(db_session, ax, vin) == []

    async def test_both_dates_move_their_own_rows(self, client, auth_headers, db_session, ax, vin):
        tire = await _create_mount(client, auth_headers, ax, vin, "FL", E, X)
        off = await client.post(
            f"/api/vehicles/{vin}/tires/{tire['id']}/dismount",
            headers=auth_headers,
            json={"dismounted_on": D1.isoformat(), ax.dismounted: str(X + 100)},
        )
        assert off.status_code == 200, off.text
        period_id = tire["mount_periods"][0]["id"]
        await _stop_tracking(client, auth_headers, ax, vin)

        await _edit_period(
            client, auth_headers, vin, tire, mounted_on=D0.isoformat(), dismounted_on=D2.isoformat()
        )

        assert await _rows(db_session, ax, vin) == [
            (D0, X, _mark("tire_mount", period_id), "tire_mount"),
            (D2, X + 100, _mark("tire_dismount", period_id), "tire_dismount"),
        ]

    async def test_the_reading_behind_the_moved_row_is_republished(
        self, client, auth_headers, db_session, ax, vin
    ):
        tire = await _create_mount(client, auth_headers, ax, vin, "FL", D1, X)
        other = await _stored(client, auth_headers, vin)
        # Same figure on the same day, so the mount row already covers it.
        await _reading(client, auth_headers, ax, vin, other, D1, X)
        await _stop_tracking(client, auth_headers, ax, vin)

        await _edit_period(client, auth_headers, vin, tire, mounted_on=D0.isoformat())

        rows = await _rows(db_session, ax, vin)
        assert _on(rows, D0) == [(X, _mark("tire_mount", tire["mount_periods"][0]["id"]))]
        assert _on(rows, D1) == [(X, _mark("tire", other))]

    async def test_an_axis_with_no_owned_row_grows_none(
        self, client, auth_headers, db_session, ax, vin
    ):
        # guard: a period figure with no row of its own stays rowless, tracked or not.
        manual = await client.post(
            f"/api/vehicles/{vin}/{ax.route}",
            headers=auth_headers,
            json={"vin": vin, "date": D1.isoformat(), ax.column: str(X + 10)},
        )
        assert manual.status_code == 201, manual.text
        # The manual row reads higher, so the mount publishes nothing.
        tire = await _create_mount(client, auth_headers, ax, vin, "FL", D1, X)
        before = await _rows(db_session, ax, vin)
        assert [(d, v) for d, v, _, _ in before] == [(D1, X + 10)]
        await _stop_tracking(client, auth_headers, ax, vin)

        await _edit_period(client, auth_headers, vin, tire, mounted_on=D0.isoformat())

        assert await _rows(db_session, ax, vin) == before

    async def test_a_tracked_axis_still_moves_the_figure_too(
        self, client, auth_headers, db_session, ax, vin
    ):
        # guard: a captured axis behaves as today, date and figure both follow the period.
        tire = await _create_mount(client, auth_headers, ax, vin, "FL", D1, X)
        mount = _mark("tire_mount", tire["mount_periods"][0]["id"])
        await _hand_set(db_session, ax, vin, mount, X + 50)

        await _edit_period(
            client, auth_headers, vin, tire, mounted_on=D0.isoformat(), **{ax.mounted: str(X + 5)}
        )

        assert await _rows(db_session, ax, vin) == [(D0, X + 5, mount, "tire_mount")]
        assert await _rows(db_session, _other(ax), vin) == []
