"""The odometer repair tool must run to completion on the live dialect.

This lives in `tests/integration/` deliberately. `ci.yml:25` sets
`pg-migrations-pytest-path: "tests/migrations/ tests/integration/"`, so only
tests under those two paths are executed against the PostgreSQL sidecar. The
natural home for a tools test is `tests/unit/tools/`, which runs on SQLite
only -- and on SQLite this test passes with the bug fully present, because
SQLite returns every DATE as a string. Placed there it would have been green,
in CI, forever, while the tool remained unusable on PostgreSQL.

The defect: `date.fromisoformat(row.day)` raises
`TypeError: fromisoformat: argument must be str` on the first telemetry row,
because psycopg2 adapts PostgreSQL `DATE` to `datetime.date`.
"""

import sys
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.db_url import to_sync_url


def _sync_url() -> str:
    """The URL the tool should be pointed at, matching the suite's database."""
    from tests.conftest import TEST_DATABASE_URL

    return to_sync_url(TEST_DATABASE_URL)


def _device_id(vin: str) -> str:
    """`livelink_devices.device_id` is VARCHAR(20), which PostgreSQL enforces and
    SQLite does not. A longer id passes locally and fails only in the PG job."""
    return f"d-{vin[-12:]}"


@pytest_asyncio.fixture
async def own_vehicle(db_session: AsyncSession, test_user: dict[str, object]) -> str:
    """A vehicle owned by this test alone, returned as its VIN.

    The suite shares one database with no per-test rollback, and `test_vehicle`
    hands every test the same fixed VIN. Two tests here both seed odometer
    telemetry, so sharing a VIN would let the first test's rows change the
    second test's result -- and the direction of that leak (extra telemetry,
    already-taken days) is exactly what these tests assert on.
    """
    from app.models.vehicle import Vehicle

    vin = f"TOOLTEST{uuid.uuid4().hex[:9].upper()}"
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=test_user["id"],
            nickname="Tool test",
            vehicle_type="Car",
            year=2018,
            make="Honda",
            model="Accord",
        )
    )
    await db_session.commit()
    return vin


@pytest.mark.asyncio
class TestBackfillToolRunsOnThisDialect:
    """End-to-end, against whichever database the suite is running on."""

    async def _seed(self, db_session: AsyncSession, vin: str) -> None:
        """One device and two days of odometer telemetry, in miles.

        Seeded through the ORM rather than raw INSERTs so the fixture does not
        have to track every NOT NULL column added to these tables later.
        """
        from app.models.livelink_device import LiveLinkDevice
        from app.models.vehicle_telemetry import VehicleTelemetry

        db_session.add(LiveLinkDevice(device_id=_device_id(vin), vin=vin, odometer_unit="mi"))
        base = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=3)
        for offset, value in ((0, 1000.0), (1, 1050.0)):
            db_session.add(
                VehicleTelemetry(
                    vin=vin,
                    device_id=_device_id(vin),
                    param_key="ODOMETER",
                    value=value,
                    timestamp=base + timedelta(days=offset),
                )
            )
        await db_session.commit()

    async def test_dry_run_completes_instead_of_raising_on_a_date_column(
        self, db_session: AsyncSession, own_vehicle: str, monkeypatch
    ) -> None:
        """The regression. On PostgreSQL this raised TypeError on the first row.

        Asserts the exit code rather than the written records, because the
        failure being guarded is that the tool cannot finish reading at all.
        """
        from tools.backfill_livelink_odometer import main

        vin = own_vehicle
        await self._seed(db_session, vin)

        monkeypatch.setattr(
            sys, "argv", ["backfill_livelink_odometer.py", "--db", _sync_url(), "--vin", vin]
        )
        assert main() == 0

    async def test_it_skips_a_day_that_already_has_a_record(
        self, db_session: AsyncSession, own_vehicle: str, monkeypatch
    ) -> None:
        """Reads `odometer_records.date`, the second DATE column the tool parses.

        The first test only reaches `date(timestamp)`; the `taken` and `existing`
        lookups are a separate pair of call sites and would still have been
        broken on PostgreSQL with only the first test in place.
        """
        from tools.backfill_livelink_odometer import main

        vin = own_vehicle
        await self._seed(db_session, vin)
        from app.models.odometer import OdometerRecord

        db_session.add(
            OdometerRecord(
                vin=vin,
                date=(datetime.now(UTC) - timedelta(days=3)).date(),
                odometer_km=5000,
                source="manual",
            )
        )
        await db_session.commit()

        monkeypatch.setattr(
            sys, "argv", ["backfill_livelink_odometer.py", "--db", _sync_url(), "--vin", vin]
        )
        assert main() == 0

        rows = (
            await db_session.execute(
                text("SELECT date, source FROM odometer_records WHERE vin = :v"), {"v": vin}
            )
        ).all()
        # Dry run: nothing written, and the human's record is untouched.
        assert [r.source for r in rows] == ["manual"]
        assert isinstance(rows[0].date, date | str)
