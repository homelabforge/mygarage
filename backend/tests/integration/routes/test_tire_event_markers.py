"""Per-event markers for a no-period retire and dismount, and the day backer (S2-01, S2-02).

A retire or dismount with no period to close used to publish under the tire's
own marker, the one its readings use, so withdrawing a same-day reading at the
same figure took the event's row with it. They now publish under their own
markers. And when a tire row goes (a deleted tire, a withdrawn reading, a
follower moving its row off a day, a set fit lowering its row in place), the
highest tire figure left on that day, a reading's or a period bound's, is
published again so the day never reads below something still on file.

Every scenario runs on both axes: a distance car and an hours ATV.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.models.hours import HoursRecord
from app.models.odometer import OdometerRecord
from app.models.tire import Tire
from app.models.vehicle import Vehicle
from app.utils.odometer_sync import auto_sync_marker

E = date(2026, 6, 1)
D0 = date(2026, 6, 15)
D1 = date(2026, 6, 21)
D2 = date(2026, 6, 25)
X = Decimal("5000")

Row = tuple[date, Decimal, str | None, str | None]


@dataclass(frozen=True)
class Axis:
    """One axis's field names and table, so a scenario reads the same on both."""

    usage_unit: str
    reading: str
    mounted: str
    dismounted: str
    fit: str
    model: type[OdometerRecord] | type[HoursRecord]

    @property
    def column(self) -> str:
        return "engine_hours" if self.model is HoursRecord else "odometer_km"


DISTANCE = Axis(
    "distance", "odometer_km", "mounted_odometer_km", "dismounted_odometer_km", "odometer_km",
    OdometerRecord,
)  # fmt: skip
HOURS = Axis(
    "hours", "engine_hours", "mounted_hours", "dismounted_hours", "engine_hours", HoursRecord
)


@pytest.fixture(params=[DISTANCE, HOURS], ids=["distance", "hours"])
def ax(request) -> Axis:
    return request.param


@pytest_asyncio.fixture
async def vin(ax: Axis, db_session, test_user):
    made = f"EVM{uuid.uuid4().hex[:14].upper()}"
    db_session.add(
        Vehicle(
            vin=made,
            user_id=test_user["id"],
            nickname="Event markers",
            vehicle_type="ATV" if ax is HOURS else "Car",
            year=2022,
            make="Honda",
            model="Pioneer" if ax is HOURS else "Civic",
            usage_unit=ax.usage_unit,
        )
    )
    await db_session.commit()
    yield made
    await db_session.execute(delete(Vehicle).where(Vehicle.vin == made))
    await db_session.commit()


async def _rows(db_session, ax: Axis, vin: str) -> list[Row]:
    db_session.expire_all()
    model = ax.model
    found = (
        (
            await db_session.execute(
                select(model).where(model.vin == vin).order_by(model.date, model.id)
            )
        )
        .scalars()
        .all()
    )
    return [(r.date, Decimal(getattr(r, ax.column)), r.notes, r.source) for r in found]


def _on(rows: list[Row], day: date) -> list[tuple[Decimal, str | None]]:
    return [(value, notes) for d, value, notes, _ in rows if d == day]


def _reads(rows: list[Row], day: date) -> Decimal | None:
    return max((value for value, _ in _on(rows, day)), default=None)


def _mark(source: str, source_id: int) -> str:
    return auto_sync_marker(source, source_id)


async def _create_mount(
    client: AsyncClient, headers, ax: Axis, vin: str, position: str, on: date, figure=None
) -> dict:
    body = {"vin": vin, "position": position, "mounted_on": on.isoformat()}
    if figure is not None:
        body[ax.mounted] = str(figure)
    made = await client.post(
        f"/api/vehicles/{vin}/tires/create-and-mount", headers=headers, json=body
    )
    assert made.status_code == 201, made.text
    return made.json()


async def _stored(client: AsyncClient, headers, vin: str) -> int:
    made = await client.post(f"/api/vehicles/{vin}/tires", headers=headers, json={"vin": vin})
    assert made.status_code == 201, made.text
    return made.json()["id"]


async def _legacy_mounted(db_session, vin: str, position: str = "FL") -> int:
    """A tire on a corner with no period, the way pre-period tires were left."""
    tire = Tire(vin=vin, position=position, brand="Legacy")
    db_session.add(tire)
    await db_session.commit()
    return tire.id


async def _reading(client: AsyncClient, headers, ax: Axis, vin: str, tire_id: int, day, figure):
    url = f"/api/vehicles/{vin}/tires/{tire_id}/readings"
    before = {r["id"] for r in (await _tire(client, headers, vin, tire_id))["readings"]}
    logged = await client.post(
        url,
        headers=headers,
        json={"recorded_at": day.isoformat(), "tread_depth_mm": "7.0", ax.reading: str(figure)},
    )
    assert logged.status_code == 201, logged.text
    (new_id,) = {r["id"] for r in logged.json()["readings"]} - before
    return new_id


async def _tire(client: AsyncClient, headers, vin: str, tire_id: int) -> dict:
    listed = await client.get(
        f"/api/vehicles/{vin}/tires", headers=headers, params={"include_retired": "true"}
    )
    assert listed.status_code == 200, listed.text
    return next(t for t in listed.json()["tires"] if t["id"] == tire_id)


async def _off(client: AsyncClient, headers, ax: Axis, vin: str, tire_id: int, how: str, day, fig):
    body = {"dismounted_on": day.isoformat()}
    if fig is not None:
        body[ax.dismounted] = str(fig)
    done = await client.post(
        f"/api/vehicles/{vin}/tires/{tire_id}/{how}", headers=headers, json=body
    )
    assert done.status_code == 200, done.text


async def _restore(client: AsyncClient, headers, vin: str, tire_id: int) -> None:
    done = await client.post(f"/api/vehicles/{vin}/tires/{tire_id}/restore", headers=headers)
    assert done.status_code == 200, done.text


async def _delete_tire(client: AsyncClient, headers, vin: str, tire_id: int) -> None:
    gone = await client.delete(f"/api/vehicles/{vin}/tires/{tire_id}", headers=headers)
    assert gone.status_code == 204, gone.text


async def _delete_reading(client: AsyncClient, headers, vin: str, tire_id: int, rid: int) -> None:
    gone = await client.delete(
        f"/api/vehicles/{vin}/tires/{tire_id}/readings/{rid}", headers=headers
    )
    assert gone.status_code == 204, gone.text


async def _edit_period(client: AsyncClient, headers, vin: str, tire: dict, **fields) -> None:
    period_id = tire["mount_periods"][0]["id"]
    edited = await client.put(
        f"/api/vehicles/{vin}/tires/{tire['id']}/mount-periods/{period_id}",
        headers=headers,
        json=fields,
    )
    assert edited.status_code == 200, edited.text


async def _hand_set(db_session, ax: Axis, vin: str, notes: str, value: Decimal) -> None:
    """What a user does through the odometer or hours page: correct a tire-owned row."""
    model = ax.model
    row = (
        await db_session.execute(select(model).where(model.vin == vin, model.notes == notes))
    ).scalar_one()
    setattr(row, ax.column, value)
    await db_session.commit()


async def _event_tire(db_session, client, headers, vin: str, event: str) -> int:
    """A tire whose `event` (retire or dismount) has no period to close."""
    if event == "retire":
        return await _stored(client, headers, vin)
    return await _legacy_mounted(db_session, vin)


EVENTS = [("retire", "tire_retire"), ("dismount", "tire_lone_dismount")]
EVENT_IDS = ["retire", "lone_dismount"]


@pytest.mark.asyncio
class TestEventRowsHaveTheirOwnMarker:
    @pytest.mark.parametrize(("event", "source"), EVENTS, ids=EVENT_IDS)
    async def test_a_same_day_reading_withdrawn_leaves_the_event_row(
        self, client, auth_headers, db_session, ax, vin, event, source
    ):
        tire_id = await _event_tire(db_session, client, auth_headers, vin, event)
        await _off(client, auth_headers, ax, vin, tire_id, event, D1, X)
        reading_id = await _reading(client, auth_headers, ax, vin, tire_id, D1, X)

        await _delete_reading(client, auth_headers, vin, tire_id, reading_id)

        assert await _rows(db_session, ax, vin) == [(D1, X, _mark(source, tire_id), source)]

    @pytest.mark.parametrize("offset", [Decimal("0"), Decimal("10")], ids=["at_x", "above_x"])
    @pytest.mark.parametrize("whose", ["own_reading", "other_tire"])
    @pytest.mark.parametrize(("event", "source"), EVENTS, ids=EVENT_IDS)
    async def test_a_reading_first_never_suppresses_the_event_row(
        self, client, auth_headers, db_session, ax, vin, event, source, whose, offset
    ):
        tire_id = await _event_tire(db_session, client, auth_headers, vin, event)
        reader = tire_id if whose == "own_reading" else await _stored(client, auth_headers, vin)
        reading_id = await _reading(client, auth_headers, ax, vin, reader, D1, X + offset)

        await _off(client, auth_headers, ax, vin, tire_id, event, D1, X)

        assert (X, _mark(source, tire_id)) in _on(await _rows(db_session, ax, vin), D1)
        if whose == "own_reading":
            await _delete_reading(client, auth_headers, vin, tire_id, reading_id)
        else:
            await _delete_tire(client, auth_headers, vin, reader)
        assert await _rows(db_session, ax, vin) == [(D1, X, _mark(source, tire_id), source)]

    async def test_a_retire_after_a_restore_moves_the_one_retire_row(
        self, client, auth_headers, db_session, ax, vin
    ):
        tire_id = await _stored(client, auth_headers, vin)
        await _off(client, auth_headers, ax, vin, tire_id, "retire", D1, X)
        await _restore(client, auth_headers, vin, tire_id)

        await _off(client, auth_headers, ax, vin, tire_id, "retire", D2, X + 100)

        assert await _rows(db_session, ax, vin) == [
            (D2, X + 100, _mark("tire_retire", tire_id), "tire_retire")
        ]

    async def test_a_retire_with_no_figure_leaves_the_earlier_retire_row(
        self, client, auth_headers, db_session, ax, vin
    ):
        # guard: a figureless retire is a no-op on that axis today and stays one.
        tire_id = await _stored(client, auth_headers, vin)
        await _off(client, auth_headers, ax, vin, tire_id, "retire", D1, X)
        await _restore(client, auth_headers, vin, tire_id)

        await _off(client, auth_headers, ax, vin, tire_id, "retire", D2, None)

        assert [(d, v) for d, v, _, _ in await _rows(db_session, ax, vin)] == [(D1, X)]

    @pytest.mark.parametrize(("event", "source"), EVENTS, ids=EVENT_IDS)
    async def test_a_deleted_tire_takes_its_event_row(
        self, client, auth_headers, db_session, ax, vin, event, source
    ):
        # guard: the old tire-marked row went with the tire too; this pins the new markers.
        tire_id = await _event_tire(db_session, client, auth_headers, vin, event)
        await _off(client, auth_headers, ax, vin, tire_id, event, D1, X)

        await _delete_tire(client, auth_headers, vin, tire_id)

        assert await _rows(db_session, ax, vin) == []


@pytest.mark.asyncio
class TestTheDayBacker:
    async def test_a_deleted_tire_republishes_another_tires_reading(
        self, client, auth_headers, db_session, ax, vin
    ):
        a = await _stored(client, auth_headers, vin)
        b = await _stored(client, auth_headers, vin)
        await _reading(client, auth_headers, ax, vin, a, D1, X)
        await _reading(client, auth_headers, ax, vin, b, D1, X)
        assert _on(await _rows(db_session, ax, vin), D1) == [(X, _mark("tire", a))]

        await _delete_tire(client, auth_headers, vin, a)

        assert _on(await _rows(db_session, ax, vin), D1) == [(X, _mark("tire", b))]

    async def test_a_deleted_tire_republishes_a_mount_bound(
        self, client, auth_headers, db_session, ax, vin
    ):
        a = (await _create_mount(client, auth_headers, ax, vin, "FL", E))["id"]
        await _reading(client, auth_headers, ax, vin, a, D1, X)
        b = await _create_mount(client, auth_headers, ax, vin, "FR", D1, X)
        assert _on(await _rows(db_session, ax, vin), D1) == [(X, _mark("tire", a))]

        await _delete_tire(client, auth_headers, vin, a)

        mount = _mark("tire_mount", b["mount_periods"][0]["id"])
        assert _on(await _rows(db_session, ax, vin), D1) == [(X, mount)]

    async def test_a_withdrawn_reading_falls_back_to_a_mount_bound(
        self, client, auth_headers, db_session, ax, vin
    ):
        a = (await _create_mount(client, auth_headers, ax, vin, "FL", E))["id"]
        reading_id = await _reading(client, auth_headers, ax, vin, a, D1, X)
        b = await _create_mount(client, auth_headers, ax, vin, "FR", D1, X)

        await _delete_reading(client, auth_headers, vin, a, reading_id)

        mount = _mark("tire_mount", b["mount_periods"][0]["id"])
        assert _on(await _rows(db_session, ax, vin), D1) == [(X, mount)]

    async def test_a_lower_set_refit_republishes_the_reading_behind_it(
        self, client, auth_headers, db_session, ax, vin
    ):
        member = (await _create_mount(client, auth_headers, ax, vin, "FL", E))["id"]
        # Off again, so the first fit moves it and its new period's mount says X too.
        await _off(client, auth_headers, ax, vin, member, "dismount", E, None)
        u = (await _create_mount(client, auth_headers, ax, vin, "RL", E))["id"]
        made = await client.post(
            f"/api/vehicles/{vin}/tire-sets", headers=auth_headers, json={"name": "Summer"}
        )
        assert made.status_code == 201, made.text
        set_id = made.json()["id"]
        joined = await client.put(
            f"/api/vehicles/{vin}/tires/{member}", headers=auth_headers, json={"set_id": set_id}
        )
        assert joined.status_code == 200, joined.text
        fit_url = f"/api/vehicles/{vin}/tire-sets/{set_id}/mount"
        fitted = await client.post(
            fit_url, headers=auth_headers, json={"mounted_on": D1.isoformat(), ax.fit: str(X)}
        )
        assert fitted.status_code == 200, fitted.text
        await _reading(client, auth_headers, ax, vin, u, D1, X)
        assert _on(await _rows(db_session, ax, vin), D1) == [(X, _mark("tire_set", set_id))]

        # Every member is already on its corner, so only the set's own row moves.
        refit = await client.post(
            fit_url, headers=auth_headers, json={"mounted_on": D1.isoformat(), ax.fit: str(X - 10)}
        )
        assert refit.status_code == 200, refit.text

        # The member's mount bound ties with U's reading at X; the reading wins the tie.
        assert sorted(_on(await _rows(db_session, ax, vin), D1)) == [
            (X - 10, _mark("tire_set", set_id)),
            (X, _mark("tire", u)),
        ]

    async def test_a_lower_same_day_rerotation_is_refused(
        self, client, auth_headers, db_session, ax, vin
    ):
        # guard: the rotation's own lowering never gets that far, it's a reversed period.
        left = (await _create_mount(client, auth_headers, ax, vin, "FL", E))["id"]
        right = (await _create_mount(client, auth_headers, ax, vin, "FR", E))["id"]
        url = f"/api/vehicles/{vin}/tires/rotate"

        def body(figure: Decimal, first: str, second: str) -> dict:
            return {
                "rotated_on": D1.isoformat(),
                ax.fit: str(figure),
                "moves": [
                    {"tire_id": left, "position": first},
                    {"tire_id": right, "position": second},
                ],
            }

        rotated = await client.post(url, headers=auth_headers, json=body(X, "FR", "FL"))
        assert rotated.status_code == 200, rotated.text
        again = await client.post(url, headers=auth_headers, json=body(X - 10, "FL", "FR"))
        assert again.status_code == 409, again.text
        assert _reads(await _rows(db_session, ax, vin), D1) == X

    async def test_a_corrected_mount_row_keeps_its_correction(
        self, client, auth_headers, db_session, ax, vin
    ):
        # guard: a backer that already has a row is never republished over it (F3-1).
        tire = await _create_mount(client, auth_headers, ax, vin, "FL", D1, X + 100)
        mount = _mark("tire_mount", tire["mount_periods"][0]["id"])
        await _hand_set(db_session, ax, vin, mount, X + 50)
        await _off(client, auth_headers, ax, vin, tire["id"], "dismount", D1, X + 200)

        await _edit_period(client, auth_headers, vin, tire, dismounted_on=D2.isoformat())

        assert _on(await _rows(db_session, ax, vin), D1) == [(X + 50, mount)]

    async def test_a_corrected_reading_row_keeps_its_correction(
        self, client, auth_headers, db_session, ax, vin
    ):
        # guard: same as above, for a reading's row.
        t = await _stored(client, auth_headers, vin)
        await _reading(client, auth_headers, ax, vin, t, D1, X + 100)
        await _hand_set(db_session, ax, vin, _mark("tire", t), X + 50)
        s = await _create_mount(client, auth_headers, ax, vin, "RL", E)
        await _off(client, auth_headers, ax, vin, s["id"], "dismount", D1, X + 200)

        await _edit_period(client, auth_headers, vin, s, dismounted_on=D2.isoformat())

        assert _on(await _rows(db_session, ax, vin), D1) == [(X + 50, _mark("tire", t))]

    async def test_a_same_day_lowering_republishes_the_reading_behind(
        self, client, auth_headers, db_session, ax, vin
    ):
        t = await _create_mount(client, auth_headers, ax, vin, "FL", D1, X)
        u = await _stored(client, auth_headers, vin)
        await _reading(client, auth_headers, ax, vin, u, D1, X)

        await _edit_period(client, auth_headers, vin, t, **{ax.mounted: str(X - 5)})

        rows = await _rows(db_session, ax, vin)
        assert _reads(rows, D1) == X
        assert (X, _mark("tire", u)) in _on(rows, D1)

    async def test_a_re_retire_republishes_the_reading_behind_the_old_row(
        self, client, auth_headers, db_session, ax, vin
    ):
        t = await _stored(client, auth_headers, vin)
        await _off(client, auth_headers, ax, vin, t, "retire", D1, X)
        u = await _stored(client, auth_headers, vin)
        await _reading(client, auth_headers, ax, vin, u, D1, X)
        await _restore(client, auth_headers, vin, t)

        await _off(client, auth_headers, ax, vin, t, "retire", D2, X + 100)

        rows = await _rows(db_session, ax, vin)
        assert _on(rows, D1) == [(X, _mark("tire", u))]
        assert _on(rows, D2) == [(X + 100, _mark("tire_retire", t))]

    async def test_a_moved_mount_date_republishes_the_reading_behind(
        self, client, auth_headers, db_session, ax, vin
    ):
        t = await _create_mount(client, auth_headers, ax, vin, "FL", D1, X)
        u = await _stored(client, auth_headers, vin)
        await _reading(client, auth_headers, ax, vin, u, D1, X)

        await _edit_period(client, auth_headers, vin, t, mounted_on=D0.isoformat())

        rows = await _rows(db_session, ax, vin)
        assert _on(rows, D1) == [(X, _mark("tire", u))]
        assert _on(rows, D0) == [(X, _mark("tire_mount", t["mount_periods"][0]["id"]))]
