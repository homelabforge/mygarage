"""Mount periods: the odometer records they publish, the contradictions the
writers refuse, and the period editor.

Every tire operation that takes an odometer publishes it as a vehicle
odometer record so the distance calculation can see it. Before v3.4.0
mount, dismount, retire AND every tread reading published with one marker,
`[AUTO-SYNC from tire #<tire_id>]`, so nothing could later say which event a
record came from. Now each period event has its own marker, which is what
lets the editor move the right record and only that one.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from datetime import date as date_type
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.constants.units import IMPERIAL_PRESET
from app.models.odometer import OdometerRecord
from app.models.settings import Setting
from app.models.tire import Tire, TireMountPeriod
from app.models.vehicle import Vehicle
from app.schemas.tire import MountPeriodUpdate, TireCreateAndMountRequest, TireDismountRequest
from app.services.tire_service import (
    ODOMETER_SOURCE_TIRE,
    ODOMETER_SOURCE_TIRE_DISMOUNT,
    ODOMETER_SOURCE_TIRE_MOUNT,
    TireService,
)
from app.utils.default_unit_prefs import DEFAULT_UNIT_PREFS_KEY
from app.utils.odometer_sync import auto_sync_marker


@pytest.fixture
async def vehicle(db_session, test_user):
    vin = f"TIREPER{uuid.uuid4().hex[:10].upper()}"[:17]
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=test_user["id"],
            nickname="Periods",
            vehicle_type="Car",
            year=2020,
            make="Honda",
            model="Fit",
        )
    )
    await db_session.commit()
    yield vin
    await db_session.execute(delete(OdometerRecord).where(OdometerRecord.vin == vin))
    await db_session.execute(delete(Vehicle).where(Vehicle.vin == vin))
    await db_session.commit()


@pytest.fixture
async def other_vehicle(db_session, test_user):
    """A second vehicle, for the cross-VIN refusal. Same pattern as
    `test_tire_sets.py`'s fixture of the same name."""
    vin = f"TIREPERB{uuid.uuid4().hex[:9].upper()}"[:17]
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=test_user["id"],
            nickname="Periods B",
            vehicle_type="Car",
            year=2021,
            make="Toyota",
            model="Yaris",
        )
    )
    await db_session.commit()
    yield vin
    await db_session.execute(delete(OdometerRecord).where(OdometerRecord.vin == vin))
    await db_session.execute(delete(Vehicle).where(Vehicle.vin == vin))
    await db_session.commit()


async def _records(db_session, vin: str) -> list[OdometerRecord]:
    db_session.expire_all()
    return list(
        (
            await db_session.execute(
                select(OdometerRecord)
                .where(OdometerRecord.vin == vin)
                .order_by(OdometerRecord.date, OdometerRecord.id)
            )
        )
        .scalars()
        .all()
    )


async def _periods(db_session, tire_id: int) -> list[TireMountPeriod]:
    db_session.expire_all()
    return list(
        (
            await db_session.execute(
                select(TireMountPeriod)
                .where(TireMountPeriod.tire_id == tire_id)
                .order_by(TireMountPeriod.id)
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
class TestOdometerMarkers:
    async def test_mount_and_dismount_publish_period_owned_records(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        base = f"/api/vehicles/{vehicle}/tires"
        made = await client.post(
            f"{base}/create-and-mount",
            headers=auth_headers,
            json={
                "vin": vehicle,
                "position": "FL",
                "brand": "M",
                "mounted_on": "2026-01-10",
                "mounted_odometer_km": "10000",
            },
        )
        assert made.status_code == 201, made.text
        tire_id = made.json()["id"]
        (period,) = await _periods(db_session, tire_id)
        # Captured immediately: `_records` below calls `expire_all()`, and
        # reading an expired attribute off an async-session object outside an
        # `await` raises MissingGreenlet. The id itself is what every
        # assertion below needs, not the live ORM handle.
        period_id = period.id
        (rec,) = await _records(db_session, vehicle)
        assert rec.date == date(2026, 1, 10) and rec.odometer_km == Decimal("10000")
        assert rec.notes == auto_sync_marker(ODOMETER_SOURCE_TIRE_MOUNT, period_id)
        assert rec.source == ODOMETER_SOURCE_TIRE_MOUNT

        off = await client.post(
            f"{base}/{tire_id}/dismount",
            headers=auth_headers,
            json={"dismounted_on": "2026-03-10", "dismounted_odometer_km": "12000"},
        )
        assert off.status_code == 200, off.text
        recs = await _records(db_session, vehicle)
        assert [r.notes for r in recs] == [
            auto_sync_marker(ODOMETER_SOURCE_TIRE_MOUNT, period_id),
            auto_sync_marker(ODOMETER_SOURCE_TIRE_DISMOUNT, period_id),
        ]

    async def test_a_reading_keeps_the_tire_level_marker(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        base = f"/api/vehicles/{vehicle}/tires"
        made = await client.post(
            f"{base}/create-and-mount",
            headers=auth_headers,
            json={"vin": vehicle, "position": "FR", "brand": "R"},
        )
        assert made.status_code == 201, made.text
        tire_id = made.json()["id"]
        read = await client.post(
            f"{base}/{tire_id}/readings",
            headers=auth_headers,
            json={"recorded_at": "2026-02-01", "tread_depth_mm": "7.0", "odometer_km": "11000"},
        )
        assert read.status_code == 201, read.text
        (rec,) = [r for r in await _records(db_session, vehicle) if r.date == date(2026, 2, 1)]
        assert rec.notes == auto_sync_marker(ODOMETER_SOURCE_TIRE, tire_id)

    async def test_delete_removes_the_periods_records_too(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        base = f"/api/vehicles/{vehicle}/tires"
        made = await client.post(
            f"{base}/create-and-mount",
            headers=auth_headers,
            json={
                "vin": vehicle,
                "position": "RL",
                "brand": "D",
                "mounted_on": "2026-01-10",
                "mounted_odometer_km": "10000",
            },
        )
        tire_id = made.json()["id"]
        await client.post(
            f"{base}/{tire_id}/dismount",
            headers=auth_headers,
            json={"dismounted_on": "2026-03-10", "dismounted_odometer_km": "12000"},
        )
        assert len(await _records(db_session, vehicle)) == 2
        gone = await client.delete(f"{base}/{tire_id}", headers=auth_headers)
        assert gone.status_code == 204, gone.text
        assert await _records(db_session, vehicle) == []


async def _tire_positions(db_session, vin: str) -> dict[int, str | None]:
    db_session.expire_all()
    rows = (await db_session.execute(select(Tire.id, Tire.position).where(Tire.vin == vin))).all()
    return {tire_id: position for tire_id, position in rows}


async def _seed_mutual_ac_history(db_session, vin: str) -> tuple[int, int, int]:
    """Two mutually contradicting legacy typos. Truth: A 0 to 4,000 km,
    B 4,000 to 8,000, C 8,000 to 12,000, dated in that order at FL. Stored:
    A's dismount typed 9,000 and C's mount typed 3,000, below A's TRUE
    dismount as well, so A and C contradict each other and neither can be
    fixed alone without the other still flagging it.

    Returns `(tire_id, a_id, c_id)`.
    """
    tire = Tire(vin=vin, position=None, brand="Mutual", mount_periods=[], readings=[])
    db_session.add(tire)
    await db_session.flush()
    tire_id = tire.id
    for start, end, lo, hi in (
        (date_type(2024, 1, 1), date_type(2024, 3, 1), "0", "9000"),
        (date_type(2024, 3, 1), date_type(2024, 6, 1), "4000", "8000"),
        (date_type(2024, 6, 1), date_type(2024, 9, 1), "3000", "12000"),
    ):
        db_session.add(
            TireMountPeriod(
                tire_id=tire_id,
                position="FL",
                mounted_on=start,
                dismounted_on=end,
                mounted_odometer_km=Decimal(lo),
                dismounted_odometer_km=Decimal(hi),
                is_assumed=False,
            )
        )
    await db_session.commit()
    a, _b, c = await _periods(db_session, tire_id)
    return tire_id, a.id, c.id


@pytest.mark.asyncio
class TestWritersRefuseContradictions:
    async def test_a_mount_backdated_before_the_last_dismount_is_refused(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        base = f"/api/vehicles/{vehicle}/tires"
        made = await client.post(
            f"{base}/create-and-mount",
            headers=auth_headers,
            json={
                "vin": vehicle,
                "position": "FL",
                "mounted_on": "2026-01-01",
                "mounted_odometer_km": "1000",
            },
        )
        tire_id = made.json()["id"]
        await client.post(
            f"{base}/{tire_id}/dismount",
            headers=auth_headers,
            json={"dismounted_on": "2026-03-01", "dismounted_odometer_km": "2000"},
        )
        again = await client.post(
            f"{base}/{tire_id}/mount",
            headers=auth_headers,
            json={"position": "FR", "mounted_on": "2026-02-15", "mounted_odometer_km": "2000"},
        )
        assert again.status_code == 409, again.text
        assert "dismounted" in again.json()["detail"]

    async def test_a_dismount_dated_before_its_mount_is_refused(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        base = f"/api/vehicles/{vehicle}/tires"
        made = await client.post(
            f"{base}/create-and-mount",
            headers=auth_headers,
            json={
                "vin": vehicle,
                "position": "FL",
                "mounted_on": "2026-04-10",
                "mounted_odometer_km": "5000",
            },
        )
        tire_id = made.json()["id"]
        off = await client.post(
            f"{base}/{tire_id}/dismount", headers=auth_headers, json={"dismounted_on": "2026-03-01"}
        )
        assert off.status_code == 409, off.text
        still = await client.get(base, headers=auth_headers)
        assert [t["position"] for t in still.json()["tires"] if t["id"] == tire_id] == ["FL"]
        # The 409 rolled the request back: a later, valid write on the SAME
        # session succeeds. Without production's rollback in the test
        # dependency, the flushed dismount would still be pending here and
        # the SQLite lock guard would raise on the open transaction.
        ok = await client.post(
            f"{base}/{tire_id}/dismount", headers=auth_headers, json={"dismounted_on": "2026-05-01"}
        )
        assert ok.status_code == 200, ok.text

    async def test_a_tire_with_an_old_fault_elsewhere_can_still_be_dismounted(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """Incremental policy: a legacy fault on another
        period neither blocks this write nor is silently healed by it."""
        base = f"/api/vehicles/{vehicle}/tires"
        made = await client.post(
            f"{base}/create-and-mount",
            headers=auth_headers,
            json={
                "vin": vehicle,
                "position": "FL",
                "mounted_on": "2026-04-01",
                "mounted_odometer_km": "5000",
            },
        )
        tire_id = made.json()["id"]
        # Seeded the way a pre-3.4.0 writer could leave one: reversed odometers.
        db_session.add(
            TireMountPeriod(
                tire_id=tire_id,
                position="FR",
                mounted_on=date_type(2025, 1, 1),
                dismounted_on=date_type(2025, 3, 1),
                mounted_odometer_km=Decimal("4000"),
                dismounted_odometer_km=Decimal("3000"),
                is_assumed=False,
            )
        )
        await db_session.commit()
        off = await client.post(
            f"{base}/{tire_id}/dismount",
            headers=auth_headers,
            json={"dismounted_on": "2026-06-01", "dismounted_odometer_km": "6000"},
        )
        assert off.status_code == 200, off.text
        legacy = next(p for p in await _periods(db_session, tire_id) if p.position == "FR")
        assert legacy.id in off.json()["blocking_period_ids"], "the old fault stays flagged"

    async def test_a_rotation_dated_before_a_mount_moves_nothing(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        base = f"/api/vehicles/{vehicle}/tires"
        ids = {}
        for position, day in (("FL", "2026-01-01"), ("FR", "2026-04-10")):
            made = await client.post(
                f"{base}/create-and-mount",
                headers=auth_headers,
                json={
                    "vin": vehicle,
                    "position": position,
                    "mounted_on": day,
                    "mounted_odometer_km": "1000",
                },
            )
            ids[position] = made.json()["id"]
        rotated = await client.post(
            f"{base}/rotate",
            headers=auth_headers,
            json={
                "rotated_on": "2026-03-01",
                "odometer_km": "1500",
                "moves": [
                    {"tire_id": ids["FL"], "position": "FR"},
                    {"tire_id": ids["FR"], "position": "FL"},
                ],
            },
        )
        assert rotated.status_code == 409, rotated.text
        assert await _tire_positions(db_session, vehicle) == {ids["FL"]: "FL", ids["FR"]: "FR"}

    async def test_a_set_fit_dated_before_a_displaced_tires_mount_changes_nothing(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """The tires coming OFF are validated too."""
        base = f"/api/vehicles/{vehicle}/tires"
        y = (
            await client.post(
                f"{base}/create-and-mount",
                headers=auth_headers,
                json={
                    "vin": vehicle,
                    "position": "FL",
                    "brand": "Y",
                    "mounted_on": "2026-01-01",
                    "mounted_odometer_km": "1000",
                },
            )
        ).json()["id"]
        await client.post(
            f"{base}/{y}/dismount",
            headers=auth_headers,
            json={"dismounted_on": "2026-02-01", "dismounted_odometer_km": "2000"},
        )
        x = (
            await client.post(
                f"{base}/create-and-mount",
                headers=auth_headers,
                json={
                    "vin": vehicle,
                    "position": "FL",
                    "brand": "X",
                    "mounted_on": "2026-03-01",
                    "mounted_odometer_km": "3000",
                },
            )
        ).json()["id"]
        set_id = (
            await client.post(
                f"/api/vehicles/{vehicle}/tire-sets", headers=auth_headers, json={"name": "Winter"}
            )
        ).json()["id"]
        assert (
            await client.put(f"{base}/{y}", headers=auth_headers, json={"set_id": set_id})
        ).status_code == 200
        before_positions = await _tire_positions(db_session, vehicle)
        before_records = len(await _records(db_session, vehicle))
        before_periods = len(await _periods(db_session, x)) + len(await _periods(db_session, y))

        fit = await client.post(
            f"/api/vehicles/{vehicle}/tire-sets/{set_id}/mount",
            headers=auth_headers,
            json={"mounted_on": "2026-02-15", "odometer_km": "2500"},
        )
        assert fit.status_code == 409, fit.text
        assert await _tire_positions(db_session, vehicle) == before_positions
        assert len(await _records(db_session, vehicle)) == before_records
        assert (
            len(await _periods(db_session, x)) + len(await _periods(db_session, y))
            == before_periods
        )

    async def test_a_retired_tire_cannot_be_mounted_or_rotated(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        base = f"/api/vehicles/{vehicle}/tires"
        made = await client.post(
            f"{base}/create-and-mount",
            headers=auth_headers,
            json={"vin": vehicle, "position": "FL"},
        )
        tire_id = made.json()["id"]
        assert (
            await client.post(f"{base}/{tire_id}/retire", headers=auth_headers, json={})
        ).status_code == 200
        mount = await client.post(
            f"{base}/{tire_id}/mount", headers=auth_headers, json={"position": "FL"}
        )
        assert mount.status_code == 409 and "retired" in mount.json()["detail"]
        other = (
            await client.post(
                f"{base}/create-and-mount",
                headers=auth_headers,
                json={"vin": vehicle, "position": "FR"},
            )
        ).json()["id"]
        rotate = await client.post(
            f"{base}/rotate",
            headers=auth_headers,
            json={
                "moves": [
                    {"tire_id": tire_id, "position": "FR"},
                    {"tire_id": other, "position": "FL"},
                ]
            },
        )
        assert rotate.status_code == 409 and "retired" in rotate.json()["detail"]

    async def test_mutually_contradicting_legacy_periods_repair_a_then_c(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """Fixing A first resolves A's fault against B and adds no fault key,
        so it is accepted even though C is still contradicted against A
        afterward; fixing C then clears the rest."""
        tire_id, a_id, c_id = await _seed_mutual_ac_history(db_session, vehicle)
        base = f"/api/vehicles/{vehicle}/tires"

        fix_a = await client.put(
            f"{base}/{tire_id}/mount-periods/{a_id}",
            headers=auth_headers,
            json={"dismounted_odometer_km": "4000"},
        )
        assert fix_a.status_code == 200, fix_a.text
        # The first repair is accepted but not clean: C's contradiction
        # persists, so it is not vacuous for the second repair to clear it.
        assert fix_a.json()["history_faults"] != []
        fix_c = await client.put(
            f"{base}/{tire_id}/mount-periods/{c_id}",
            headers=auth_headers,
            json={"mounted_odometer_km": "8000"},
        )
        assert fix_c.status_code == 200, fix_c.text
        final = await client.get(base, headers=auth_headers)
        tire_json = next(t for t in final.json()["tires"] if t["id"] == tire_id)
        assert tire_json["blocking_period_ids"] == []
        assert tire_json["history_faults"] == []

    async def test_mutually_contradicting_legacy_periods_repair_c_then_a(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """Same history, opposite order: fixing C first resolves C's fault
        against B and adds no fault key, so it is accepted even though C is
        still contradicted against A afterward; fixing A then clears the
        rest."""
        tire_id, a_id, c_id = await _seed_mutual_ac_history(db_session, vehicle)
        base = f"/api/vehicles/{vehicle}/tires"

        fix_c = await client.put(
            f"{base}/{tire_id}/mount-periods/{c_id}",
            headers=auth_headers,
            json={"mounted_odometer_km": "8000"},
        )
        assert fix_c.status_code == 200, fix_c.text
        # The first repair is accepted but not clean: A's contradiction
        # persists, so it is not vacuous for the second repair to clear it.
        assert fix_c.json()["history_faults"] != []
        fix_a = await client.put(
            f"{base}/{tire_id}/mount-periods/{a_id}",
            headers=auth_headers,
            json={"dismounted_odometer_km": "4000"},
        )
        assert fix_a.status_code == 200, fix_a.text
        final = await client.get(base, headers=auth_headers)
        tire_json = next(t for t in final.json()["tires"] if t["id"] == tire_id)
        assert tire_json["blocking_period_ids"] == []
        assert tire_json["history_faults"] == []


async def _seed_migrated_tire(db_session, vin: str) -> tuple[int, int]:
    """The migration-097 shape: mounted, assumed period with NO bounds.

    Seeded directly. `create-and-mount` defaults an omitted date to today, so
    it cannot produce an undated period.
    """
    tire = Tire(vin=vin, position="FL", brand="Migrated", min_tread_mm=Decimal("2.0"))
    db_session.add(tire)
    await db_session.flush()
    period = TireMountPeriod(
        tire_id=tire.id,
        position="FL",
        mounted_on=None,
        mounted_odometer_km=None,
        is_assumed=True,
        observed_active_on=date_type(2026, 9, 4),
    )
    db_session.add(period)
    await db_session.commit()
    return tire.id, period.id


@pytest.mark.asyncio
class TestMountPeriodEditor:
    async def test_recovery_with_the_odometer_alone(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """The headline. A migrated tire's projection is withheld; one edit
        supplying the mount odometer, date still unknown, brings it back and
        publishes NO vehicle odometer record, because a record needs a date."""
        tire_id, period_id = await _seed_migrated_tire(db_session, vehicle)
        base = f"/api/vehicles/{vehicle}/tires"
        for day, tread, odo in (("2026-05-01", "7.0", "12000"), ("2026-07-01", "6.0", "14000")):
            r = await client.post(
                f"{base}/{tire_id}/readings",
                headers=auth_headers,
                json={"recorded_at": day, "tread_depth_mm": tread, "odometer_km": odo},
            )
            assert r.status_code == 201, r.text
        before = next(
            t
            for t in (await client.get(base, headers=auth_headers)).json()["tires"]
            if t["id"] == tire_id
        )
        assert before["wear_status"] != "projected"
        assert before["distance_status"] == "nothing_bounded"
        records_before = len(await _records(db_session, vehicle))

        fixed = await client.put(
            f"{base}/{tire_id}/mount-periods/{period_id}",
            headers=auth_headers,
            json={"mounted_odometer_km": "10000"},
        )
        assert fixed.status_code == 200, fixed.text
        body = fixed.json()
        assert body["wear_status"] == "projected"
        assert body["distance_status"] == "complete"
        assert body["blocking_period_ids"] == []
        assert len(await _records(db_session, vehicle)) == records_before
        (period,) = await _periods(db_session, tire_id)
        assert period.mounted_on is None and period.is_assumed is True

    async def test_recovery_with_date_and_odometer_publishes_and_unassumes(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        tire_id, period_id = await _seed_migrated_tire(db_session, vehicle)
        base = f"/api/vehicles/{vehicle}/tires"
        fixed = await client.put(
            f"{base}/{tire_id}/mount-periods/{period_id}",
            headers=auth_headers,
            json={"mounted_on": "2026-04-01", "mounted_odometer_km": "10000"},
        )
        assert fixed.status_code == 200, fixed.text
        (period,) = await _periods(db_session, tire_id)
        assert period.is_assumed is False
        assert period.observed_active_on == date_type(2026, 9, 4)
        owned = [
            r
            for r in await _records(db_session, vehicle)
            if r.notes == auto_sync_marker(ODOMETER_SOURCE_TIRE_MOUNT, period_id)
        ]
        assert len(owned) == 1
        assert owned[0].date == date_type(2026, 4, 1) and owned[0].odometer_km == Decimal("10000")

    async def test_refusals(self, client: AsyncClient, auth_headers, vehicle, db_session):
        base = f"/api/vehicles/{vehicle}/tires"
        made = await client.post(
            f"{base}/create-and-mount",
            headers=auth_headers,
            json={
                "vin": vehicle,
                "position": "FL",
                "mounted_on": "2026-01-10",
                "mounted_odometer_km": "10000",
            },
        )
        tire_id = made.json()["id"]
        (open_period,) = await _periods(db_session, tire_id)
        url = f"{base}/{tire_id}/mount-periods/{open_period.id}"
        # Open period: any dismount key, even null, is a 409.
        assert (
            await client.put(url, headers=auth_headers, json={"dismounted_odometer_km": "11000"})
        ).status_code == 409
        assert (
            await client.put(url, headers=auth_headers, json={"dismounted_on": None})
        ).status_code == 409
        # Position is not a field: forbid-extra makes it a 422.
        assert (
            await client.put(url, headers=auth_headers, json={"position": "FR"})
        ).status_code == 422
        # Unknown period: 404.
        assert (
            await client.put(
                f"{base}/{tire_id}/mount-periods/999999", headers=auth_headers, json={"notes": "x"}
            )
        ).status_code == 404
        # Closed period: reopening is a 409; clearing its odometer is fine.
        await client.post(
            f"{base}/{tire_id}/dismount",
            headers=auth_headers,
            json={"dismounted_on": "2026-03-10", "dismounted_odometer_km": "12000"},
        )
        assert (
            await client.put(url, headers=auth_headers, json={"dismounted_on": None})
        ).status_code == 409
        cleared = await client.put(url, headers=auth_headers, json={"dismounted_odometer_km": None})
        assert cleared.status_code == 200, cleared.text
        (period,) = await _periods(db_session, tire_id)
        assert period.dismounted_odometer_km is None and period.dismounted_on == date_type(
            2026, 3, 10
        )

    async def test_clearing_the_mount_odometer_withdraws_the_distance(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        base = f"/api/vehicles/{vehicle}/tires"
        made = await client.post(
            f"{base}/create-and-mount",
            headers=auth_headers,
            json={
                "vin": vehicle,
                "position": "FL",
                "mounted_on": "2026-01-10",
                "mounted_odometer_km": "10000",
            },
        )
        tire_id = made.json()["id"]
        await client.post(
            f"{base}/{tire_id}/dismount",
            headers=auth_headers,
            json={"dismounted_on": "2026-03-10", "dismounted_odometer_km": "12000"},
        )
        (period,) = await _periods(db_session, tire_id)
        # Captured immediately: `_records` below calls `expire_all()`.
        period_id = period.id
        cleared = await client.put(
            f"{base}/{tire_id}/mount-periods/{period_id}",
            headers=auth_headers,
            json={"mounted_odometer_km": None},
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["distance_status"] == "nothing_bounded"
        assert period_id in cleared.json()["blocking_period_ids"]
        # And the owned mount record is gone: a value the user withdrew must
        # not survive as the vehicle's odometer.
        assert not [
            r
            for r in await _records(db_session, vehicle)
            if r.notes == auto_sync_marker(ODOMETER_SOURCE_TIRE_MOUNT, period_id)
        ]

    async def test_published_odometer_follows_the_period_by_ownership(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        base = f"/api/vehicles/{vehicle}/tires"
        made = await client.post(
            f"{base}/create-and-mount",
            headers=auth_headers,
            json={
                "vin": vehicle,
                "position": "FL",
                "mounted_on": "2026-01-10",
                "mounted_odometer_km": "10000",
            },
        )
        tire_id = made.json()["id"]
        (period,) = await _periods(db_session, tire_id)
        marker = auto_sync_marker(ODOMETER_SOURCE_TIRE_MOUNT, period.id)
        # A manual record already on the target day must survive untouched.
        manual = await client.post(
            f"/api/vehicles/{vehicle}/odometer",
            headers=auth_headers,
            json={"vin": vehicle, "date": "2026-02-10", "odometer_km": "10400", "notes": "hand"},
        )
        assert manual.status_code == 201, manual.text

        moved = await client.put(
            f"{base}/{tire_id}/mount-periods/{period.id}",
            headers=auth_headers,
            json={"mounted_on": "2026-02-10", "mounted_odometer_km": "10500"},
        )
        assert moved.status_code == 200, moved.text
        recs = await _records(db_session, vehicle)
        owned = [r for r in recs if r.notes == marker]
        assert (
            len(owned) == 1
            and owned[0].date == date_type(2026, 2, 10)
            and owned[0].odometer_km == Decimal("10500")
        )
        hand = [r for r in recs if r.notes == "hand"]
        assert (
            len(hand) == 1
            and hand[0].odometer_km == Decimal("10400")
            and hand[0].source == "manual"
        )
        assert not [r for r in recs if r.date == date_type(2026, 1, 10)], (
            "the old owned record moved, it was not copied"
        )

    async def test_a_reading_on_the_mount_day_leaves_the_mount_its_record(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """A reading at the odometer the mount already recorded that day
        publishes nothing: the record stays the period's own, so the editor
        moves it. Once it's moved off the day, the reading still stands, so it
        gets published in the mount's old place (S2-02)."""
        base = f"/api/vehicles/{vehicle}/tires"
        made = await client.post(
            f"{base}/create-and-mount",
            headers=auth_headers,
            json={
                "vin": vehicle,
                "position": "FL",
                "mounted_on": "2026-01-10",
                "mounted_odometer_km": "10000",
            },
        )
        tire_id = made.json()["id"]
        (period,) = await _periods(db_session, tire_id)
        # Captured immediately: `_records` below calls `expire_all()`.
        period_id = period.id
        mount_marker = auto_sync_marker(ODOMETER_SOURCE_TIRE_MOUNT, period_id)
        read = await client.post(
            f"{base}/{tire_id}/readings",
            headers=auth_headers,
            json={"recorded_at": "2026-01-10", "tread_depth_mm": "8.0", "odometer_km": "10000"},
        )
        assert read.status_code == 201, read.text
        assert [(r.date, r.odometer_km, r.notes) for r in await _records(db_session, vehicle)] == [
            (date_type(2026, 1, 10), Decimal("10000"), mount_marker)
        ]
        moved = await client.put(
            f"{base}/{tire_id}/mount-periods/{period_id}",
            headers=auth_headers,
            json={"mounted_on": "2026-01-12", "mounted_odometer_km": "10050"},
        )
        assert moved.status_code == 200, moved.text
        assert [(r.date, r.odometer_km, r.notes) for r in await _records(db_session, vehicle)] == [
            (
                date_type(2026, 1, 10),
                Decimal("10000"),
                auto_sync_marker(ODOMETER_SOURCE_TIRE, tire_id),
            ),
            (date_type(2026, 1, 12), Decimal("10050"), mount_marker),
        ]

    async def test_a_legacy_tire_marked_record_is_never_moved(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """A period recorded before this release published with the tire-level
        marker. Ownership cannot be established after the fact, so the editor
        leaves it and publishes fresh."""
        base = f"/api/vehicles/{vehicle}/tires"
        made = await client.post(
            f"{base}/create-and-mount",
            headers=auth_headers,
            json={
                "vin": vehicle,
                "position": "FL",
                "mounted_on": "2026-01-10",
                "mounted_odometer_km": "10000",
            },
        )
        tire_id = made.json()["id"]
        (period,) = await _periods(db_session, tire_id)
        # Captured immediately: `_records` below calls `expire_all()`.
        period_id = period.id
        (rec,) = await _records(db_session, vehicle)
        rec.notes = auto_sync_marker(ODOMETER_SOURCE_TIRE, tire_id)
        rec.source = ODOMETER_SOURCE_TIRE
        await db_session.commit()
        moved = await client.put(
            f"{base}/{tire_id}/mount-periods/{period_id}",
            headers=auth_headers,
            json={"mounted_on": "2026-02-10"},
        )
        assert moved.status_code == 200, moved.text
        recs = {r.date: r for r in await _records(db_session, vehicle)}
        assert recs[date_type(2026, 1, 10)].notes == auto_sync_marker(ODOMETER_SOURCE_TIRE, tire_id)
        assert recs[date_type(2026, 2, 10)].notes == auto_sync_marker(
            ODOMETER_SOURCE_TIRE_MOUNT, period_id
        )

    async def test_editing_a_rotation_created_period_leaves_the_rotation_record(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        base = f"/api/vehicles/{vehicle}/tires"
        fl = (
            await client.post(
                f"{base}/create-and-mount",
                headers=auth_headers,
                json={
                    "vin": vehicle,
                    "position": "FL",
                    "mounted_on": "2026-01-01",
                    "mounted_odometer_km": "1000",
                },
            )
        ).json()["id"]
        fr = (
            await client.post(
                f"{base}/create-and-mount",
                headers=auth_headers,
                json={
                    "vin": vehicle,
                    "position": "FR",
                    "mounted_on": "2026-01-01",
                    "mounted_odometer_km": "1000",
                },
            )
        ).json()["id"]
        rotated = await client.post(
            f"{base}/rotate",
            headers=auth_headers,
            json={
                "rotated_on": "2026-03-01",
                "odometer_km": "5000",
                "moves": [{"tire_id": fl, "position": "FR"}, {"tire_id": fr, "position": "FL"}],
            },
        )
        assert rotated.status_code == 200, rotated.text
        new_period = next(p for p in await _periods(db_session, fl) if p.dismounted_on is None)
        # Captured immediately: `_records` below calls `expire_all()`.
        new_period_id = new_period.id
        moved = await client.put(
            f"{base}/{fl}/mount-periods/{new_period_id}",
            headers=auth_headers,
            json={"mounted_on": "2026-03-05"},
        )
        assert moved.status_code == 200, moved.text
        recs = {r.date: r for r in await _records(db_session, vehicle)}
        assert recs[date_type(2026, 3, 1)].source == "tire_rotation" and recs[
            date_type(2026, 3, 1)
        ].odometer_km == Decimal("5000")
        assert recs[date_type(2026, 3, 5)].notes == auto_sync_marker(
            ODOMETER_SOURCE_TIRE_MOUNT, new_period_id
        )

    async def test_a_notes_only_save_leaves_a_corrected_owned_record_alone(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """The user corrected the mount's published record on the odometer
        page, which keeps its marker; a save that changes no bound must not
        republish the period's older figure on top of it."""
        base = f"/api/vehicles/{vehicle}/tires"
        made = await client.post(
            f"{base}/create-and-mount",
            headers=auth_headers,
            json={
                "vin": vehicle,
                "position": "FL",
                "mounted_on": "2026-01-10",
                "mounted_odometer_km": "10000",
            },
        )
        tire_id = made.json()["id"]
        (period,) = await _periods(db_session, tire_id)
        period_id = period.id
        (published,) = await _records(db_session, vehicle)
        corrected = await client.put(
            f"/api/vehicles/{vehicle}/odometer/{published.id}",
            headers=auth_headers,
            json={"odometer_km": "10500"},
        )
        assert corrected.status_code == 200, corrected.text
        saved = await client.put(
            f"{base}/{tire_id}/mount-periods/{period_id}",
            headers=auth_headers,
            json={
                "mounted_on": "2026-01-10",
                "mounted_odometer_km": "10000",
                "notes": "just a note",
            },
        )
        assert saved.status_code == 200, saved.text
        assert [(r.date, r.odometer_km, r.notes) for r in await _records(db_session, vehicle)] == [
            (
                date_type(2026, 1, 10),
                Decimal("10500"),
                auto_sync_marker(ODOMETER_SOURCE_TIRE_MOUNT, period_id),
            )
        ]

    async def test_a_legacy_history_with_two_faults_is_repaired_one_at_a_time(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """Whole-history refusal would reject either repair."""
        tire = Tire(vin=vehicle, position=None, brand="Legacy", mount_periods=[], readings=[])
        db_session.add(tire)
        await db_session.flush()
        # Captured immediately: `_periods` below calls `expire_all()`.
        tire_id = tire.id
        # Two reversed periods in DIFFERENT odometer ranges. Isolated execution
        # of the validator showed that fixing the first one INTO the second's
        # range (say 5000..5500 against a second period starting at 5000) is a
        # genuine new overlap and is rightly refused; that is not the case this
        # test is about.
        for start, end, lo, hi in (
            (date_type(2025, 1, 1), date_type(2025, 3, 1), "1000", "500"),
            (date_type(2025, 6, 1), date_type(2025, 8, 1), "5000", "4000"),
        ):
            db_session.add(
                TireMountPeriod(
                    tire_id=tire_id,
                    position="FL",
                    mounted_on=start,
                    dismounted_on=end,
                    mounted_odometer_km=Decimal(lo),
                    dismounted_odometer_km=Decimal(hi),
                    is_assumed=False,
                )
            )
        await db_session.commit()
        first, second = await _periods(db_session, tire_id)
        # Captured immediately: the PUT calls below run through the app, and a
        # later `_periods`/`_records` call would expire these otherwise.
        first_id, second_id = first.id, second.id
        base = f"/api/vehicles/{vehicle}/tires"

        # Leaving the edited period still reversed is refused.
        still_bad = await client.put(
            f"{base}/{tire_id}/mount-periods/{first_id}",
            headers=auth_headers,
            json={"dismounted_odometer_km": "800"},
        )
        assert still_bad.status_code == 409, still_bad.text
        # Fixing it is accepted even though the other period is still broken.
        fixed = await client.put(
            f"{base}/{tire_id}/mount-periods/{first_id}",
            headers=auth_headers,
            json={"dismounted_odometer_km": "1500"},
        )
        assert fixed.status_code == 200, fixed.text
        assert first_id not in fixed.json()["blocking_period_ids"]
        assert second_id in fixed.json()["blocking_period_ids"]
        # And then the other one.
        fixed2 = await client.put(
            f"{base}/{tire_id}/mount-periods/{second_id}",
            headers=auth_headers,
            json={"dismounted_odometer_km": "6000"},
        )
        assert fixed2.status_code == 200, fixed2.text
        assert fixed2.json()["blocking_period_ids"] == []

    async def test_the_counterpart_of_a_legacy_overlap_cannot_be_made_worse(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """The fault is keyed on the intruder (period 2);
        editing period 1 while the overlap persists must still be refused."""
        tire = Tire(vin=vehicle, position="FL", brand="Overlap", mount_periods=[], readings=[])
        db_session.add(tire)
        await db_session.flush()
        # Captured immediately: `_periods` below calls `expire_all()`.
        tire_id = tire.id
        db_session.add(
            TireMountPeriod(
                tire_id=tire_id,
                position="FL",
                mounted_on=date_type(2026, 1, 1),
                dismounted_on=date_type(2026, 1, 20),
                mounted_odometer_km=Decimal("1000"),
                dismounted_odometer_km=Decimal("2000"),
                is_assumed=False,
            )
        )
        db_session.add(
            TireMountPeriod(
                tire_id=tire_id,
                position="FL",
                mounted_on=date_type(2026, 1, 10),
                dismounted_on=None,
                mounted_odometer_km=Decimal("1500"),
                dismounted_odometer_km=None,
                is_assumed=False,
            )
        )
        await db_session.commit()
        first, second = await _periods(db_session, tire_id)
        # Captured immediately, same reason as above.
        first_id, second_id = first.id, second.id
        base = f"/api/vehicles/{vehicle}/tires"

        worse = await client.put(
            f"{base}/{tire_id}/mount-periods/{first_id}",
            headers=auth_headers,
            json={"dismounted_on": "2026-02-20"},
        )
        assert worse.status_code == 409, worse.text
        # Named as the drawer shows it, by corner and mount date, never by id.
        assert worse.json()["detail"].startswith("The FL period mounted 2026-01-10 ")
        assert f"period {second_id}" not in worse.json()["detail"]
        # Resolving it from the counterpart's side is accepted.
        fixed = await client.put(
            f"{base}/{tire_id}/mount-periods/{first_id}",
            headers=auth_headers,
            json={"dismounted_on": "2026-01-05", "dismounted_odometer_km": "1400"},
        )
        assert fixed.status_code == 200, fixed.text
        # The EDITED period is no longer implicated. Deliberately not
        # `== []`: period 2 is seeded open with a mount odometer of 1500 and
        # this edit makes 1400 the vehicle's latest reading, so
        # `distance_on_tire` rightly flags it ODOMETER_ROLLBACK. That is a
        # true statement about an unrelated property of this seed, and this
        # test is about the overlap refusal, not about the tire's distance
        # being computable.
        assert first_id not in fixed.json()["blocking_period_ids"]

    async def test_an_edit_that_hides_behind_a_running_maximum_is_refused(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """A legacy FL history where Y is already below W's dismount and Z below
        X's. X has no mount odometer. Moving X to February and ending it at
        7,800 km puts it before Y, which mounts at 7,200 km: a contradiction
        this edit creates. The date-order odometer rule used to report Y only
        against W, the period holding the highest dismount, so X was no
        participant of anything and the edit was accepted."""
        tire = Tire(vin=vehicle, position="FL", brand="Hidden", mount_periods=[], readings=[])
        db_session.add(tire)
        await db_session.flush()
        # Captured immediately: `_periods` below calls `expire_all()`.
        tire_id = tire.id
        for start, end, lo, hi in (
            (date_type(2024, 1, 1), date_type(2024, 2, 1), None, "8000"),
            (date_type(2024, 3, 1), date_type(2024, 4, 1), "7200", "8500"),
            (date_type(2024, 5, 1), date_type(2024, 6, 1), None, "9000"),
            (date_type(2024, 7, 1), None, "7000", None),
        ):
            db_session.add(
                TireMountPeriod(
                    tire_id=tire_id,
                    position="FL",
                    mounted_on=start,
                    dismounted_on=end,
                    mounted_odometer_km=None if lo is None else Decimal(lo),
                    dismounted_odometer_km=None if hi is None else Decimal(hi),
                    is_assumed=False,
                )
            )
        await db_session.commit()
        x_id = (await _periods(db_session, tire_id))[2].id
        base = f"/api/vehicles/{vehicle}/tires"

        hidden = await client.put(
            f"{base}/{tire_id}/mount-periods/{x_id}",
            headers=auth_headers,
            json={
                "mounted_on": "2024-02-15",
                "dismounted_on": "2024-02-20",
                "dismounted_odometer_km": "7800",
            },
        )
        assert hidden.status_code == 409, hidden.text
        x = (await _periods(db_session, tire_id))[2]
        assert (x.mounted_on, x.dismounted_odometer_km) == (date_type(2024, 5, 1), Decimal("9000"))

    async def test_a_conflict_names_the_intruding_period(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        base = f"/api/vehicles/{vehicle}/tires"
        made = await client.post(
            f"{base}/create-and-mount",
            headers=auth_headers,
            json={
                "vin": vehicle,
                "position": "FL",
                "mounted_on": "2026-01-01",
                "mounted_odometer_km": "1000",
            },
        )
        tire_id = made.json()["id"]
        await client.post(
            f"{base}/{tire_id}/dismount",
            headers=auth_headers,
            json={"dismounted_on": "2026-03-01", "dismounted_odometer_km": "2000"},
        )
        await client.post(
            f"{base}/{tire_id}/mount",
            headers=auth_headers,
            json={"position": "FR", "mounted_on": "2026-04-01", "mounted_odometer_km": "2500"},
        )
        first, second = await _periods(db_session, tire_id)
        # Captured immediately: a 409 rolls back and expires the session
        # (conftest's `override_get_db`), so `second` cannot be read again
        # after the PUT below without a fresh fetch.
        second_id = second.id
        bad = await client.put(
            f"{base}/{tire_id}/mount-periods/{second_id}",
            headers=auth_headers,
            json={"mounted_on": "2026-02-15"},
        )
        assert bad.status_code == 409, bad.text
        assert bad.json()["detail"] == (
            "The FR period mounted 2026-02-15 starts before the FL period mounted 2026-01-01 "
            "was dismounted on 2026-03-01."
        )
        # Nothing changed.
        _, still = await _periods(db_session, tire_id)
        assert still.mounted_on == date_type(2026, 4, 1)


_SAME_DAY = date_type(2026, 3, 1)
_EARLIER = date_type(2026, 2, 20)


@pytest.mark.asyncio
class TestEditorUnderProductionUnitOfWork:
    """The editor's odometer follow on a session that does NOT autoflush.

    `app/database.py` builds every request session with `autoflush=False`.
    This class builds its own sessionmaker pinned to that setting directly,
    independent of conftest's `test_sessionmaker`, so it keeps exercising
    production's unit of work even if conftest's setting changes.

    The shape: a period mounted and dismounted on one day, owning its mount
    record and no dismount record (dismounted without an odometer). One save
    that moves or clears the mount pair AND supplies the dismount odometer.
    The mount follow changes the owned record in memory; the dismount follow
    then looks for same-day rows by SQL. The dismount odometer equals the
    mount's, so without a flush in between that query still sees the mount
    record on its old date reading as high as the dismount, publishes
    nothing, and the vehicle ends up with no record on that day.

    Builds its own session over the test engine on purpose, and seeds through
    the real writers on it too.
    """

    @staticmethod
    def _maker(test_engine) -> async_sessionmaker[AsyncSession]:
        return async_sessionmaker(
            test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
        )

    async def _seed(self, maker: async_sessionmaker[AsyncSession], vin: str) -> tuple[int, int]:
        async with maker() as db:
            made = await TireService(db).create_and_mount(
                vin,
                TireCreateAndMountRequest(
                    vin=vin,
                    position="FL",
                    brand="Same day",
                    mounted_on=_SAME_DAY,
                    mounted_odometer_km=Decimal("10000"),
                ),
                None,
            )
        async with maker() as db:
            off = await TireService(db).dismount_tire(
                vin, made.id, TireDismountRequest(dismounted_on=_SAME_DAY), None
            )
        (period,) = off.mount_periods
        return made.id, period.id

    @staticmethod
    async def _records(maker: async_sessionmaker[AsyncSession], vin: str) -> list[tuple]:
        async with maker() as db:
            rows = (
                (
                    await db.execute(
                        select(OdometerRecord)
                        .where(OdometerRecord.vin == vin)
                        .order_by(OdometerRecord.date, OdometerRecord.id)
                    )
                )
                .scalars()
                .all()
            )
            return [(r.date, r.odometer_km, r.notes) for r in rows]

    async def test_moving_the_mount_date_and_adding_the_dismount_odometer(
        self, test_engine, vehicle
    ):
        maker = self._maker(test_engine)
        tire_id, period_id = await self._seed(maker, vehicle)
        assert await self._records(maker, vehicle) == [
            (_SAME_DAY, Decimal("10000"), auto_sync_marker(ODOMETER_SOURCE_TIRE_MOUNT, period_id))
        ]

        async with maker() as db:
            await TireService(db).update_mount_period(
                vehicle,
                tire_id,
                period_id,
                MountPeriodUpdate(
                    mounted_on=_EARLIER,
                    mounted_odometer_km=Decimal("10000"),
                    dismounted_on=_SAME_DAY,
                    dismounted_odometer_km=Decimal("10000"),
                ),
                None,
            )

        assert await self._records(maker, vehicle) == [
            (_EARLIER, Decimal("10000"), auto_sync_marker(ODOMETER_SOURCE_TIRE_MOUNT, period_id)),
            (
                _SAME_DAY,
                Decimal("10000"),
                auto_sync_marker(ODOMETER_SOURCE_TIRE_DISMOUNT, period_id),
            ),
        ]

    async def test_clearing_the_mount_odometer_and_adding_the_dismount_odometer(
        self, test_engine, vehicle
    ):
        maker = self._maker(test_engine)
        tire_id, period_id = await self._seed(maker, vehicle)

        async with maker() as db:
            await TireService(db).update_mount_period(
                vehicle,
                tire_id,
                period_id,
                MountPeriodUpdate(
                    mounted_on=_SAME_DAY,
                    mounted_odometer_km=None,
                    dismounted_on=_SAME_DAY,
                    dismounted_odometer_km=Decimal("10000"),
                ),
                None,
            )

        assert await self._records(maker, vehicle) == [
            (
                _SAME_DAY,
                Decimal("10000"),
                auto_sync_marker(ODOMETER_SOURCE_TIRE_DISMOUNT, period_id),
            )
        ]


@pytest.mark.asyncio
class TestFaultsOnTheWire:
    async def test_a_contradiction_no_figure_blocks_is_on_the_tire(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """Two closed periods whose DATES overlap but whose odometers are
        fully known and consistent. `distance_on_tire` only sums each
        period's own span and never compares one period against another, and
        with no readings on file the wear projection withholds nothing
        either, so `blocking_period_ids` stays empty even though the history
        contradicts itself -- the case `history_faults` exists for."""
        tire = Tire(vin=vehicle, position=None, brand="Overlap", mount_periods=[], readings=[])
        db_session.add(tire)
        await db_session.flush()
        tire_id = tire.id
        db_session.add_all(
            [
                TireMountPeriod(
                    tire_id=tire_id,
                    position="FL",
                    mounted_on=date_type(2026, 1, 1),
                    dismounted_on=date_type(2026, 3, 1),
                    mounted_odometer_km=Decimal("0"),
                    dismounted_odometer_km=Decimal("1000"),
                    is_assumed=False,
                ),
                TireMountPeriod(
                    tire_id=tire_id,
                    position="FL",
                    mounted_on=date_type(2026, 2, 1),
                    dismounted_on=date_type(2026, 4, 1),
                    mounted_odometer_km=Decimal("1000"),
                    dismounted_odometer_km=Decimal("2000"),
                    is_assumed=False,
                ),
            ]
        )
        await db_session.commit()
        earlier, later = await _periods(db_session, tire_id)

        base = f"/api/vehicles/{vehicle}/tires"
        listed = await client.get(base, headers=auth_headers)
        assert listed.status_code == 200, listed.text
        tire_json = next(t for t in listed.json()["tires"] if t["id"] == tire_id)

        assert tire_json["blocking_period_ids"] == []
        faults = tire_json["history_faults"]
        assert len(faults) == 1
        (fault,) = faults
        assert fault["code"] == "overlapping_dates"
        assert fault["period_id"] == later.id
        assert fault["counterpart_id"] == earlier.id
        assert fault["message"]

    async def test_a_reading_contradiction_is_on_the_tire_after_it_is_logged(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        """`add_reading` does not validate against the mount history, so a
        reading that contradicts a period only shows up here: on the next
        response, as a fault, once the history validator runs over it."""
        base = f"/api/vehicles/{vehicle}/tires"
        made = await client.post(
            f"{base}/create-and-mount",
            headers=auth_headers,
            json={
                "vin": vehicle,
                "position": "FL",
                "mounted_on": "2026-01-01",
                "mounted_odometer_km": "1000",
            },
        )
        tire_id = made.json()["id"]
        dismounted = await client.post(
            f"{base}/{tire_id}/dismount",
            headers=auth_headers,
            json={"dismounted_on": "2026-03-01", "dismounted_odometer_km": "2000"},
        )
        assert dismounted.status_code == 200, dismounted.text
        (period_id,) = [p["id"] for p in dismounted.json()["mount_periods"]]

        logged = await client.post(
            f"{base}/{tire_id}/readings",
            headers=auth_headers,
            json={"recorded_at": "2026-02-01", "odometer_km": "3000", "tread_depth_mm": "5.0"},
        )
        assert logged.status_code == 201, logged.text
        faults = [f for f in logged.json()["history_faults"] if f["code"] == "contradicts_reading"]
        assert len(faults) == 1
        assert faults[0]["period_id"] == period_id
        assert faults[0]["message"]


@pytest.mark.asyncio
class TestMessagesInTheUsersUnits:
    @staticmethod
    async def _set_unit_preference(client: AsyncClient, headers: dict, preference: str) -> None:
        response = await client.put(
            "/api/auth/me/units", headers=headers, json={"unit_preference": preference}
        )
        assert response.status_code == 200, response.text

    async def test_a_refusal_speaks_miles_to_a_user_on_miles(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        await self._set_unit_preference(client, auth_headers, "imperial")
        base = f"/api/vehicles/{vehicle}/tires"
        made = await client.post(
            f"{base}/create-and-mount",
            headers=auth_headers,
            json={
                "vin": vehicle,
                "position": "FL",
                "mounted_on": "2026-01-01",
                "mounted_odometer_km": "5000",
            },
        )
        tire_id = made.json()["id"]
        refused = await client.post(
            f"{base}/{tire_id}/dismount",
            headers=auth_headers,
            json={"dismounted_on": "2026-02-01", "dismounted_odometer_km": "1000"},
        )
        assert refused.status_code == 409, refused.text
        detail = refused.json()["detail"]
        assert " mi" in detail
        assert " km" not in detail

    async def test_a_refusal_speaks_km_to_a_user_on_km(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        await self._set_unit_preference(client, auth_headers, "metric")
        try:
            base = f"/api/vehicles/{vehicle}/tires"
            made = await client.post(
                f"{base}/create-and-mount",
                headers=auth_headers,
                json={
                    "vin": vehicle,
                    "position": "FL",
                    "mounted_on": "2026-01-01",
                    "mounted_odometer_km": "5000",
                },
            )
            tire_id = made.json()["id"]
            refused = await client.post(
                f"{base}/{tire_id}/dismount",
                headers=auth_headers,
                json={"dismounted_on": "2026-02-01", "dismounted_odometer_km": "1000"},
            )
            assert refused.status_code == 409, refused.text
            detail = refused.json()["detail"]
            assert " km" in detail
            assert " mi" not in detail
        finally:
            # The suite shares one database with no per-test rollback, and
            # `test_user` never resets `unit_preference` -- left on metric,
            # this leaks into every later test that expects the default.
            await self._set_unit_preference(client, auth_headers, "imperial")

    async def test_a_refusal_speaks_the_vehicles_unit_over_the_users(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        """#172: a vehicle set to miles speaks miles to a user on km."""
        await self._set_unit_preference(client, auth_headers, "metric")
        try:
            put = await client.put(
                f"/api/vehicles/{vehicle}", headers=auth_headers, json={"distance_unit": "mi"}
            )
            assert put.status_code == 200, put.text
            base = f"/api/vehicles/{vehicle}/tires"
            made = await client.post(
                f"{base}/create-and-mount",
                headers=auth_headers,
                json={
                    "vin": vehicle,
                    "position": "FL",
                    "mounted_on": "2026-01-01",
                    "mounted_odometer_km": "5000",
                },
            )
            tire_id = made.json()["id"]
            refused = await client.post(
                f"{base}/{tire_id}/dismount",
                headers=auth_headers,
                json={"dismounted_on": "2026-02-01", "dismounted_odometer_km": "1000"},
            )
            assert refused.status_code == 409, refused.text
            detail = refused.json()["detail"]
            assert " mi" in detail
            assert " km" not in detail
        finally:
            # Same restore as the km test above: this file's convention.
            await self._set_unit_preference(client, auth_headers, "imperial")

    async def test_the_formatter_follows_the_instance_default_without_a_user(
        self, db_session: AsyncSession
    ):
        """No caller (auth mode none) renders in the INSTANCE default, not a
        hardcoded one, so this pins the default to miles explicitly rather
        than relying on `load_default_unit_prefs`'s own fallback."""
        existing = await db_session.get(Setting, DEFAULT_UNIT_PREFS_KEY)
        original = existing.value if existing is not None else None
        if existing is not None:
            existing.value = json.dumps(IMPERIAL_PRESET.model_dump())
        else:
            db_session.add(
                Setting(
                    key=DEFAULT_UNIT_PREFS_KEY,
                    value=json.dumps(IMPERIAL_PRESET.model_dump()),
                    category="general",
                )
            )
        await db_session.commit()
        try:
            formatter = await TireService(db_session).request_distance_formatter(
                None, "NOSUCHVIN00000000"
            )
            assert " mi" in formatter(Decimal("1000"))
        finally:
            row = await db_session.get(Setting, DEFAULT_UNIT_PREFS_KEY)
            if original is None:
                if row is not None:
                    await db_session.delete(row)
            elif row is not None:
                row.value = original
            await db_session.commit()


@pytest.mark.asyncio
class TestAddingAPastPeriod:
    """`POST /mount-periods`: a closed period recorded after the fact, for
    history the user never entered at the time."""

    async def test_a_past_period_before_the_first_mount_is_recorded(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        base = f"/api/vehicles/{vehicle}/tires"
        made = await client.post(
            f"{base}/create-and-mount",
            headers=auth_headers,
            json={
                "vin": vehicle,
                "position": "FL",
                "mounted_on": "2026-06-01",
                "mounted_odometer_km": "20000",
            },
        )
        assert made.status_code == 201, made.text
        tire_id = made.json()["id"]
        (open_period,) = await _periods(db_session, tire_id)
        open_period_id = open_period.id

        added = await client.post(
            f"{base}/{tire_id}/mount-periods",
            headers=auth_headers,
            json={
                "position": "FR",
                "mounted_on": "2026-01-01",
                "mounted_odometer_km": "5000",
                "dismounted_on": "2026-03-01",
                "dismounted_odometer_km": "9000",
            },
        )
        assert added.status_code == 201, added.text
        body = added.json()
        assert body["position"] == "FL"
        new_period = next(p for p in body["mount_periods"] if p["position"] == "FR")
        assert new_period["mounted_on"] == "2026-01-01"
        assert new_period["dismounted_on"] == "2026-03-01"
        assert Decimal(str(new_period["mounted_odometer_km"])) == Decimal("5000")
        assert Decimal(str(new_period["dismounted_odometer_km"])) == Decimal("9000")
        still_open = next(p for p in body["mount_periods"] if p["id"] == open_period_id)
        assert still_open["position"] == "FL" and still_open["dismounted_on"] is None

        new_period_id = new_period["id"]
        recs = {r.notes: r for r in await _records(db_session, vehicle)}
        mount_marker = auto_sync_marker(ODOMETER_SOURCE_TIRE_MOUNT, new_period_id)
        dismount_marker = auto_sync_marker(ODOMETER_SOURCE_TIRE_DISMOUNT, new_period_id)
        assert recs[mount_marker].date == date_type(2026, 1, 1)
        assert recs[mount_marker].odometer_km == Decimal("5000")
        assert recs[dismount_marker].date == date_type(2026, 3, 1)
        assert recs[dismount_marker].odometer_km == Decimal("9000")

    async def test_a_past_period_without_odometers_publishes_nothing(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        base = f"/api/vehicles/{vehicle}/tires"
        made = await client.post(
            f"{base}/create-and-mount",
            headers=auth_headers,
            json={
                "vin": vehicle,
                "position": "FL",
                "mounted_on": "2026-06-01",
                "mounted_odometer_km": "20000",
            },
        )
        assert made.status_code == 201, made.text
        tire_id = made.json()["id"]
        records_before = len(await _records(db_session, vehicle))

        added = await client.post(
            f"{base}/{tire_id}/mount-periods",
            headers=auth_headers,
            json={"position": "FR", "mounted_on": "2026-01-01", "dismounted_on": "2026-03-01"},
        )
        assert added.status_code == 201, added.text
        new_period = next(p for p in added.json()["mount_periods"] if p["position"] == "FR")
        assert new_period["mounted_odometer_km"] is None
        assert new_period["dismounted_odometer_km"] is None
        assert len(await _records(db_session, vehicle)) == records_before
        markers = {
            auto_sync_marker(ODOMETER_SOURCE_TIRE_MOUNT, new_period["id"]),
            auto_sync_marker(ODOMETER_SOURCE_TIRE_DISMOUNT, new_period["id"]),
        }
        assert not [r for r in await _records(db_session, vehicle) if r.notes in markers]

    async def test_a_past_period_overlapping_an_existing_one_is_refused(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        base = f"/api/vehicles/{vehicle}/tires"
        made = await client.post(
            f"{base}/create-and-mount",
            headers=auth_headers,
            json={
                "vin": vehicle,
                "position": "FL",
                "mounted_on": "2026-06-01",
                "mounted_odometer_km": "20000",
            },
        )
        assert made.status_code == 201, made.text
        tire_id = made.json()["id"]
        periods_before = len(await _periods(db_session, tire_id))
        records_before = len(await _records(db_session, vehicle))

        overlapping = await client.post(
            f"{base}/{tire_id}/mount-periods",
            headers=auth_headers,
            json={
                "position": "FR",
                "mounted_on": "2026-05-01",
                "mounted_odometer_km": "18000",
                "dismounted_on": "2026-07-01",
                "dismounted_odometer_km": "21000",
            },
        )
        assert overlapping.status_code == 409, overlapping.text
        # Re-read rather than trust the stale in-memory tire: the 409 rolled
        # the request back, and these helpers `expire_all()` before querying.
        assert len(await _periods(db_session, tire_id)) == periods_before
        assert len(await _records(db_session, vehicle)) == records_before

    async def test_a_past_period_ending_after_tomorrow_is_422(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        base = f"/api/vehicles/{vehicle}/tires"
        made = await client.post(
            f"{base}/create-and-mount",
            headers=auth_headers,
            json={"vin": vehicle, "position": "FL"},
        )
        assert made.status_code == 201, made.text
        tire_id = made.json()["id"]
        too_late = (date_type.today() + timedelta(days=2)).isoformat()
        added = await client.post(
            f"{base}/{tire_id}/mount-periods",
            headers=auth_headers,
            json={"position": "FR", "mounted_on": "2026-01-01", "dismounted_on": too_late},
        )
        assert added.status_code == 422, added.text

    async def test_a_past_period_dismounted_tomorrow_is_recorded(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        """A day of slack for a user whose calendar is ahead of the server's.

        The tire is in storage, so no open period can overlap the new one and
        refuse it for a reason other than its date.
        """
        base = f"/api/vehicles/{vehicle}/tires"
        made = await client.post(base, headers=auth_headers, json={"vin": vehicle})
        assert made.status_code == 201, made.text
        mounted = (date_type.today() - timedelta(days=30)).isoformat()
        tomorrow = (date_type.today() + timedelta(days=1)).isoformat()
        added = await client.post(
            f"{base}/{made.json()['id']}/mount-periods",
            headers=auth_headers,
            json={"position": "FR", "mounted_on": mounted, "dismounted_on": tomorrow},
        )
        assert added.status_code == 201, added.text
        (period,) = added.json()["mount_periods"]
        assert period["dismounted_on"] == tomorrow

    async def test_a_same_day_past_period_is_recorded(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        """On and off the car on one day, as a swap that was undone the same
        afternoon would be."""
        base = f"/api/vehicles/{vehicle}/tires"
        made = await client.post(base, headers=auth_headers, json={"vin": vehicle})
        assert made.status_code == 201, made.text
        day = (date_type.today() - timedelta(days=30)).isoformat()
        added = await client.post(
            f"{base}/{made.json()['id']}/mount-periods",
            headers=auth_headers,
            json={"position": "RL", "mounted_on": day, "dismounted_on": day},
        )
        assert added.status_code == 201, added.text
        (period,) = added.json()["mount_periods"]
        assert period["mounted_on"] == day and period["dismounted_on"] == day

    async def test_a_past_period_dismounted_before_it_mounted_is_422(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        base = f"/api/vehicles/{vehicle}/tires"
        made = await client.post(
            f"{base}/create-and-mount",
            headers=auth_headers,
            json={"vin": vehicle, "position": "FL"},
        )
        assert made.status_code == 201, made.text
        tire_id = made.json()["id"]
        added = await client.post(
            f"{base}/{tire_id}/mount-periods",
            headers=auth_headers,
            json={"position": "FR", "mounted_on": "2026-03-01", "dismounted_on": "2026-01-01"},
        )
        assert added.status_code == 422, added.text

    async def test_a_retired_tire_can_have_a_past_period_added(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        base = f"/api/vehicles/{vehicle}/tires"
        made = await client.post(
            f"{base}/create-and-mount",
            headers=auth_headers,
            json={
                "vin": vehicle,
                "position": "FL",
                "mounted_on": "2026-06-01",
                "mounted_odometer_km": "20000",
            },
        )
        assert made.status_code == 201, made.text
        tire_id = made.json()["id"]
        retired = await client.post(
            f"{base}/{tire_id}/retire",
            headers=auth_headers,
            json={"dismounted_on": "2026-08-01", "dismounted_odometer_km": "25000"},
        )
        assert retired.status_code == 200, retired.text
        retired_on = retired.json()["retired_on"]

        added = await client.post(
            f"{base}/{tire_id}/mount-periods",
            headers=auth_headers,
            json={
                "position": "FR",
                "mounted_on": "2026-01-01",
                "mounted_odometer_km": "5000",
                "dismounted_on": "2026-03-01",
                "dismounted_odometer_km": "9000",
            },
        )
        assert added.status_code == 201, added.text
        assert added.json()["retired_on"] == retired_on

    async def test_a_past_period_needs_write_access(
        self, client: AsyncClient, owned_vehicle, owner_headers, reader_headers, db_session
    ):
        vin = owned_vehicle.vin
        made = await client.post(
            f"/api/vehicles/{vin}/tires/create-and-mount",
            headers=owner_headers,
            json={"vin": vin, "position": "FL", "mounted_on": "2026-06-01"},
        )
        assert made.status_code == 201, made.text
        tire_id = made.json()["id"]
        try:
            refused = await client.post(
                f"/api/vehicles/{vin}/tires/{tire_id}/mount-periods",
                headers=reader_headers,
                json={"position": "FR", "mounted_on": "2026-01-01", "dismounted_on": "2026-03-01"},
            )
            assert refused.status_code == 403, refused.text
            (only_period,) = await _periods(db_session, tire_id)
            assert only_period.position == "FL"
        finally:
            await db_session.execute(delete(Tire).where(Tire.id == tire_id))
            await db_session.commit()

    async def test_a_past_period_on_another_vehicles_tire_is_404(
        self, client: AsyncClient, auth_headers, vehicle, other_vehicle
    ):
        base = f"/api/vehicles/{vehicle}/tires"
        made = await client.post(
            f"{base}/create-and-mount",
            headers=auth_headers,
            json={"vin": vehicle, "position": "FL", "mounted_on": "2026-06-01"},
        )
        assert made.status_code == 201, made.text
        tire_id = made.json()["id"]
        wrong_vin = await client.post(
            f"/api/vehicles/{other_vehicle}/tires/{tire_id}/mount-periods",
            headers=auth_headers,
            json={"position": "FR", "mounted_on": "2026-01-01", "dismounted_on": "2026-03-01"},
        )
        assert wrong_vin.status_code == 404, wrong_vin.text

    async def test_a_pre_existing_manual_record_on_the_mount_date_is_untouched(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """`_publish_odometer` never touches a record it did not create, the
        rule it shares with Mount and the period editor. A past period follows
        it: the manual entry survives untouched, and because the mount's figure
        is higher, the period's own record stands beside it on that day."""
        base = f"/api/vehicles/{vehicle}/tires"
        made = await client.post(
            f"{base}/create-and-mount",
            headers=auth_headers,
            json={
                "vin": vehicle,
                "position": "FL",
                "mounted_on": "2026-06-01",
                "mounted_odometer_km": "20000",
            },
        )
        assert made.status_code == 201, made.text
        tire_id = made.json()["id"]
        manual = await client.post(
            f"/api/vehicles/{vehicle}/odometer",
            headers=auth_headers,
            json={"vin": vehicle, "date": "2026-01-01", "odometer_km": "4800", "notes": "hand"},
        )
        assert manual.status_code == 201, manual.text

        added = await client.post(
            f"{base}/{tire_id}/mount-periods",
            headers=auth_headers,
            json={
                "position": "FR",
                "mounted_on": "2026-01-01",
                "mounted_odometer_km": "5000",
                "dismounted_on": "2026-03-01",
                "dismounted_odometer_km": "9000",
            },
        )
        assert added.status_code == 201, added.text
        new_period = next(p for p in added.json()["mount_periods"] if p["position"] == "FR")
        mount_marker = auto_sync_marker(ODOMETER_SOURCE_TIRE_MOUNT, new_period["id"])
        on_the_day = [
            (r.odometer_km, r.notes, r.source)
            for r in await _records(db_session, vehicle)
            if r.date == date_type(2026, 1, 1)
        ]
        assert on_the_day == [
            (Decimal("4800"), "hand", "manual"),
            (Decimal("5000"), mount_marker, ODOMETER_SOURCE_TIRE_MOUNT),
        ]


#: 89,044 mi typed today (the exact mile) and as a service visit saved before
#: v3.4.0 stored it (the old 1.60934 km mile), rounded to the column's 0.01 km.
#: Worked from the definitions here, not read back from the code under test.
_EXACT_MILE_KM = (Decimal("89044") * Decimal("1.609344")).quantize(Decimal("0.01"))
_OLD_MILE_KM = (Decimal("89044") * Decimal("1.60934")).quantize(Decimal("0.01"))


@pytest.mark.asyncio
class TestTheOldMileAtABoundary:
    """The shape found on real data: FL mounted at a service visit's
    pre-upgrade 143,302.07 km, and the RR period before it added afterwards,
    dismounted at 89,044 mi typed today, 143,302.43 km."""

    async def _swapped_tire(self, client: AsyncClient, headers, vin: str) -> tuple[int, int]:
        assert (_EXACT_MILE_KM, _OLD_MILE_KM) == (Decimal("143302.43"), Decimal("143302.07"))
        base = f"/api/vehicles/{vin}/tires"
        made = await client.post(
            f"{base}/create-and-mount",
            headers=headers,
            json={
                "vin": vin,
                "position": "FL",
                "min_tread_mm": "2.0",
                "mounted_on": "2026-06-21",
                "mounted_odometer_km": str(_OLD_MILE_KM),
            },
        )
        assert made.status_code == 201, made.text
        tire_id = made.json()["id"]
        added = await client.post(
            f"{base}/{tire_id}/mount-periods",
            headers=headers,
            json={
                "position": "RR",
                "mounted_on": "2025-11-01",
                "mounted_odometer_km": "130000",
                "dismounted_on": "2026-06-21",
                "dismounted_odometer_km": str(_EXACT_MILE_KM),
            },
        )
        return tire_id, added.status_code

    async def test_the_past_period_is_recorded(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        tire_id, status = await self._swapped_tire(client, auth_headers, vehicle)
        assert status == 201
        periods = await _periods(db_session, tire_id)
        assert [(p.position, p.dismounted_odometer_km) for p in periods] == [
            ("FL", None),
            ("RR", _EXACT_MILE_KM),
        ]

    async def test_the_tire_keeps_its_distance_and_projection(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        tire_id, status = await self._swapped_tire(client, auth_headers, vehicle)
        assert status == 201
        base = f"/api/vehicles/{vehicle}/tires"
        for day, odometer, tread in (
            ("2026-03-01", "136000", "7.0"),
            ("2026-08-01", "150000", "6.0"),
        ):
            logged = await client.post(
                f"{base}/{tire_id}/readings",
                headers=auth_headers,
                json={"recorded_at": day, "odometer_km": odometer, "tread_depth_mm": tread},
            )
            assert logged.status_code == 201, logged.text

        listed = await client.get(base, headers=auth_headers)
        assert listed.status_code == 200, listed.text
        tire = next(t for t in listed.json()["tires"] if t["id"] == tire_id)
        assert tire["history_faults"] == []
        assert tire["distance_status"] == "complete"
        assert tire["wear_status"] == "projected"
        assert tire["projected_km_remaining"] is not None
        assert tire["blocking_period_ids"] == []
