"""Unit tests for odometer unit resolution in TelemetryService.

Regression cover for the LiveLink odometer auto-record dying silently on
2026-04-23. `6f04e53` ("Fix/v2.26.2 currency and metric canonical") deleted the
OBD2-PID-prefix branch that decided whether a device's odometer value needed a
unit conversion, leaving `odometer_km = int(round(value))` for every device.

That is only true for the standard SAE J1979 PID `A6-ODOMETER`. A bare
`ODOMETER` key is a WiCAN *autopid* (a user-defined CAN expression) and on a
US-market car reports **miles**. Read as kilometres it lands *below* the
vehicle's real odometer, so the monotonic guard

    if odometer_km <= float(max_odometer_km): return

swallowed every reading with no log line for four months.

Units are a per-device property, so `LiveLinkDevice.odometer_unit` carries it;
when unset we fall back to inferring from the param key shape.
"""

from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice
from app.models.odometer import OdometerRecord
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.telemetry_service import TelemetryService


@pytest_asyncio.fixture
async def make_odo_vehicle(db_session: AsyncSession):
    """Async factory: (suffix, odometer_unit) -> (vin, device_id)."""

    async def _factory(
        suffix: str,
        odometer_unit: str | None = None,
    ) -> tuple[str, str]:
        user = User(
            username=f"odounit_user_{suffix}",
            email=f"odounit_{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_admin=False,
        )
        db_session.add(user)
        await db_session.flush()

        vin = f"ODOUNITTEST{suffix:0>6}"
        db_session.add(
            Vehicle(
                vin=vin,
                user_id=user.id,
                nickname=f"Odo Unit Car {suffix}",
                vehicle_type="Car",
            )
        )
        await db_session.flush()

        device_id = f"ododev{suffix:0>6}"
        db_session.add(
            LiveLinkDevice(
                device_id=device_id,
                vin=vin,
                enabled=True,
                odometer_unit=odometer_unit,
            )
        )
        await db_session.flush()

        return vin, device_id

    return _factory


async def _livelink_records(db_session: AsyncSession, vin: str) -> list[OdometerRecord]:
    result = await db_session.execute(
        select(OdometerRecord)
        .where(OdometerRecord.vin == vin)
        .where(OdometerRecord.source == "livelink")
        .order_by(OdometerRecord.id)
    )
    return list(result.scalars().all())


@pytest.mark.asyncio
class TestOdometerUnitResolution:
    """A device's odometer units decide whether the raw value is converted."""

    async def test_bare_odometer_key_is_read_as_miles_and_converted(
        self, db_session, make_odo_vehicle
    ):
        """A WiCAN autopid `ODOMETER` in miles must land as kilometres.

        The device reports 89,984 mi. The vehicle already has a 144,784 km
        record from a fuel entry, so treating the raw value as kilometres makes
        it look like a backwards reading and the monotonic guard drops it.
        """
        vin, device_id = await make_odo_vehicle("1")
        db_session.add(
            OdometerRecord(
                vin=vin,
                date=date(2026, 8, 28),
                odometer_km=144784,
                source="fuel",
            )
        )
        await db_session.flush()

        service = TelemetryService(db_session)
        await service.store_telemetry(
            vin=vin,
            device_id=device_id,
            autopid_data={"odometer": 89984.0},
            config={},
        )
        await db_session.flush()

        records = await _livelink_records(db_session, vin)
        assert len(records) == 1, "the miles reading should have been recorded"
        # 89984 mi * 1.609344 = 144815 km
        assert int(records[0].odometer_km) == 144815

    async def test_a6_pid_odometer_stays_metric(self, db_session, make_odo_vehicle):
        """`A6-ODOMETER` is metric per SAE J1979 and must NOT be converted."""
        vin, device_id = await make_odo_vehicle("2")

        service = TelemetryService(db_session)
        await service.store_telemetry(
            vin=vin,
            device_id=device_id,
            autopid_data={"A6-ODOMETER": 12381.0},
            config={},
        )
        await db_session.flush()

        records = await _livelink_records(db_session, vin)
        assert len(records) == 1
        assert int(records[0].odometer_km) == 12381

    async def test_explicit_device_unit_overrides_key_inference(self, db_session, make_odo_vehicle):
        """An explicit `odometer_unit` wins over the param-key heuristic.

        Some hardware publishes a bare `ODOMETER` that really is metric, so the
        inference must be overridable per device.
        """
        vin, device_id = await make_odo_vehicle("3", odometer_unit="km")

        service = TelemetryService(db_session)
        await service.store_telemetry(
            vin=vin,
            device_id=device_id,
            autopid_data={"odometer": 50000.0},
            config={},
        )
        await db_session.flush()

        records = await _livelink_records(db_session, vin)
        assert len(records) == 1
        assert int(records[0].odometer_km) == 50000, "explicit km must not be converted"
