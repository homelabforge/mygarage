"""One household "today" driven by the Timezone setting.

Plan: obsidian builds/mygarage/plans/2026-09-17-household-timezone-today.md.
Every test here was written first and failed on the pre-fix tree, where the
seven tire defaults used ``utc_now().date()`` and everything else used
``date.today()`` (the container zone), and nothing read the Timezone setting.

Clock seam: patch the ``datetime`` that ``app.utils.household_time`` imports.
The frozen instant is 2026-09-17 02:00 UTC, where UTC's calendar date
(2026-09-17) disagrees with America/Chicago's and America/Denver's
(2026-09-16).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.models.reminder import Reminder
from app.models.settings import Setting
from app.models.tire import TireMountPeriod
from app.models.vehicle import Vehicle

FROZEN_UTC = datetime(2026, 9, 17, 2, 0, tzinfo=UTC)
UTC_DATE = date(2026, 9, 17)
CHICAGO_DATE = date(2026, 9, 16)


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: D102 - datetime API
        return FROZEN_UTC.astimezone(tz) if tz else FROZEN_UTC.replace(tzinfo=None)


@pytest.fixture
def frozen_clock(monkeypatch):
    """Freeze the household clock at 2026-09-17 02:00 UTC."""
    monkeypatch.setattr("app.utils.household_time.datetime", _FrozenDatetime)


@pytest_asyncio.fixture
async def household_row(db_session):
    """Seed the timezone row (America/Chicago) and clean it up afterwards."""
    await db_session.execute(delete(Setting).where(Setting.key == "timezone"))
    db_session.add(Setting(key="timezone", value="America/Chicago"))
    await db_session.commit()
    yield "America/Chicago"
    await db_session.execute(delete(Setting).where(Setting.key == "timezone"))
    await db_session.commit()


#: A writable key a rejected batch carries FIRST, so a partial apply would show.
#: An unknown key would be refused on its own and prove nothing about the batch.
COMPANION_KEY = "ntfy_topic"
COMPANION_SEED = "tz-companion-seed"


@pytest_asyncio.fixture
async def companion_row(db_session, keep_rows):
    """Seed the companion key; its previous row goes back afterwards."""
    await keep_rows(COMPANION_KEY)
    await db_session.execute(delete(Setting).where(Setting.key == COMPANION_KEY))
    db_session.add(Setting(key=COMPANION_KEY, value=COMPANION_SEED))
    await db_session.commit()
    return COMPANION_SEED


async def _companion_value(db_session) -> str | None:
    db_session.expire_all()
    return await db_session.scalar(select(Setting.value).where(Setting.key == COMPANION_KEY))


@pytest_asyncio.fixture
async def vehicle(db_session, test_user):
    vin = f"HHTZ{uuid.uuid4().hex[:13].upper()}"
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=test_user["id"],
            nickname="Household TZ",
            vehicle_type="Car",
            year=2021,
            make="Toyota",
            model="Sienna",
        )
    )
    await db_session.commit()
    yield vin
    await db_session.execute(delete(Vehicle).where(Vehicle.vin == vin))
    await db_session.commit()


async def _mount(client: AsyncClient, headers, vin: str, position: str, **extra) -> dict:
    body = {"vin": vin, "position": position, "tread_depth_mm": "8.0", **extra}
    response = await client.post(
        f"/api/vehicles/{vin}/tires/create-and-mount", headers=headers, json=body
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _mounted_on(db_session, tire_id: int) -> date:
    period = (
        await db_session.execute(select(TireMountPeriod).where(TireMountPeriod.tire_id == tire_id))
    ).scalar_one()
    return period.mounted_on


@pytest.mark.asyncio
class TestHouseholdToday:
    async def test_tire_mount_defaults_to_household_date_not_utc(
        self, client, auth_headers, vehicle, db_session, household_row, frozen_clock
    ):
        """An API mount with no date, then a dismount on the household's date.

        Pre-fix this 409s (REVERSED_DATES): the mount defaulted to the UTC
        date, one day ahead of the household's evening.
        """
        tire = await _mount(client, auth_headers, vehicle, "FL")
        assert await _mounted_on(db_session, tire["id"]) == CHICAGO_DATE

        response = await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}/dismount",
            headers=auth_headers,
            json={"dismounted_on": CHICAGO_DATE.isoformat()},
        )
        assert response.status_code == 200, response.text

    async def test_explicit_dates_are_never_replaced(
        self, client, auth_headers, vehicle, db_session, household_row, frozen_clock
    ):
        tire = await _mount(client, auth_headers, vehicle, "FR", mounted_on="2026-09-10")
        assert await _mounted_on(db_session, tire["id"]) == date(2026, 9, 10)

    async def test_done_completes_on_the_household_date(
        self, client, auth_headers, vehicle, db_session, household_row, frozen_clock
    ):
        created = await client.post(
            f"/api/vehicles/{vehicle}/reminders",
            headers=auth_headers,
            json={"title": "Wiper blades", "reminder_type": "date", "due_date": "2026-09-16"},
        )
        assert created.status_code == 201, created.text
        reminder_id = created.json()["id"]

        response = await client.post(
            f"/api/vehicles/{vehicle}/reminders/{reminder_id}/done", headers=auth_headers
        )
        assert response.status_code == 200, response.text
        row = (
            await db_session.execute(select(Reminder).where(Reminder.id == reminder_id))
        ).scalar_one()
        assert row.status == "done"
        assert row.completed_date == CHICAGO_DATE

    async def test_inbox_calls_a_reminder_due_today_upcoming_not_overdue(
        self, client, auth_headers, vehicle, household_row, frozen_clock
    ):
        # Due TOMORROW in household terms (the app counts due-today as
        # overdue on purpose, see is_reminder_overdue). Pre-fix the server's
        # UTC/container date is already 09-17 or later during the household's
        # evening, so this exact reminder lit up overdue a night early.
        created = await client.post(
            f"/api/vehicles/{vehicle}/reminders",
            headers=auth_headers,
            json={"title": "Emissions test", "reminder_type": "date", "due_date": "2026-09-17"},
        )
        assert created.status_code == 201, created.text

        response = await client.get("/api/notifications/inbox", headers=auth_headers)
        assert response.status_code == 200, response.text
        items = [i for i in response.json()["items"] if i["vin"] == vehicle]
        assert items, "the due reminder must appear in the inbox"
        assert items[0]["kind"] == "reminder_upcoming"

    async def test_setting_writers_change_the_zone_without_restart(
        self, client, auth_headers, vehicle, db_session, household_row, frozen_clock, monkeypatch
    ):
        """Batch write, then DELETE, each take effect on the next request."""
        first = await _mount(client, auth_headers, vehicle, "RL")
        assert await _mounted_on(db_session, first["id"]) == CHICAGO_DATE

        batch = await client.post(
            "/api/settings/batch", headers=auth_headers, json={"settings": {"timezone": "UTC"}}
        )
        assert batch.status_code == 200, batch.text
        second = await _mount(client, auth_headers, vehicle, "RR")
        assert await _mounted_on(db_session, second["id"]) == UTC_DATE

        # DELETE returns the installation to the fallback chain (env next).
        monkeypatch.setenv("MYGARAGE_TIMEZONE", "America/Denver")
        deleted = await client.delete("/api/settings/timezone", headers=auth_headers)
        assert deleted.status_code == 204, deleted.text
        third = await _mount(client, auth_headers, vehicle, "FL")
        assert await _mounted_on(db_session, third["id"]) == CHICAGO_DATE  # Denver, same date


@pytest.mark.asyncio
class TestSettingsApi:
    async def test_public_settings_expose_effective_timezone(self, client, household_row):
        """Anonymous: /settings/public carries the computed effective zone."""
        response = await client.get("/api/settings/public")
        assert response.status_code == 200, response.text
        by_key = {s["key"]: s["value"] for s in response.json()["settings"]}
        assert by_key.get("effective_timezone") == "America/Chicago"

    async def test_a_blank_timezone_falls_back_to_the_server_default(
        self, client, auth_headers, household_row, monkeypatch
    ):
        """The settings tab's "Server default" option saves ''. That must be
        accepted and hand the zone back to the fallback chain."""
        monkeypatch.setenv("MYGARAGE_TIMEZONE", "America/Denver")
        batch = await client.post(
            "/api/settings/batch", headers=auth_headers, json={"settings": {"timezone": ""}}
        )
        assert batch.status_code == 200, batch.text

        response = await client.get("/api/settings/public")
        by_key = {s["key"]: s["value"] for s in response.json()["settings"]}
        assert by_key.get("effective_timezone") == "America/Denver"

    async def test_reserved_key_is_rejected_on_every_write_path(
        self, client, auth_headers, db_session, companion_row
    ):
        create = await client.post(
            "/api/settings",
            headers=auth_headers,
            json={"key": "effective_timezone", "value": "UTC"},
        )
        assert create.status_code == 422, create.text

        put = await client.put(
            "/api/settings/effective_timezone", headers=auth_headers, json={"value": "UTC"}
        )
        assert put.status_code == 422, put.text

        batch = await client.post(
            "/api/settings/batch",
            headers=auth_headers,
            json={"settings": {COMPANION_KEY: "x", "effective_timezone": "UTC"}},
        )
        assert batch.status_code == 422, batch.text
        assert "computed and read-only" in batch.text
        rows = (
            (await db_session.execute(select(Setting).where(Setting.key == "effective_timezone")))
            .scalars()
            .all()
        )
        assert rows == [], "a rejected batch writes nothing"
        assert await _companion_value(db_session) == companion_row, "nor its companion"

    async def test_invalid_timezone_value_is_rejected_and_writes_nothing(
        self, client, auth_headers, db_session, household_row, companion_row
    ):
        put = await client.put(
            "/api/settings/timezone", headers=auth_headers, json={"value": "Not/AZone"}
        )
        assert put.status_code == 422, put.text

        batch = await client.post(
            "/api/settings/batch",
            headers=auth_headers,
            json={"settings": {COMPANION_KEY: "x", "timezone": "Also/Bogus"}},
        )
        assert batch.status_code == 422, batch.text

        row_value = await db_session.scalar(select(Setting.value).where(Setting.key == "timezone"))
        assert row_value == "America/Chicago", "the stored zone must be untouched"
        assert await _companion_value(db_session) == companion_row, (
            "a rejected batch writes nothing"
        )


@pytest.mark.asyncio
class TestCodexTZR1:
    """Codex code-review round 1: the sweep missed aliased ``date_type.today()``
    call sites and two callers that pass an explicit UTC today into the shared
    overdue helper. Each test failed on the pre-fix tree."""

    async def test_webhook_dateless_records_use_household_date(
        self, client, auth_headers, vehicle, db_session, household_row, frozen_clock
    ):
        """R1-H1: dateless fuel and odometer webhooks must persist the
        household's date, not the container's."""
        from app.models.fuel import FuelRecord
        from app.models.odometer import OdometerRecord

        await db_session.execute(delete(Setting).where(Setting.key == "webhook_ingest_token"))
        db_session.add(Setting(key="webhook_ingest_token", value="tz-test-token"))
        await db_session.commit()
        headers = {"X-Webhook-Token": "tz-test-token"}

        fuel = await client.post(
            "/api/v1/webhooks/fuel",
            headers=headers,
            json={"vin": vehicle, "liters": "40.0", "odometer_km": "1000"},
        )
        assert fuel.status_code == 200, fuel.text
        odo = await client.post(
            "/api/v1/webhooks/odometer",
            headers=headers,
            json={"vin": vehicle, "odometer_km": "1100"},
        )
        assert odo.status_code == 200, odo.text

        fuel_date = await db_session.scalar(
            select(FuelRecord.date).where(FuelRecord.vin == vehicle)
        )
        odo_date = await db_session.scalar(
            select(OdometerRecord.date).where(
                OdometerRecord.vin == vehicle, OdometerRecord.source == "webhook"
            )
        )
        assert fuel_date == CHICAGO_DATE
        assert odo_date == CHICAGO_DATE
        await db_session.execute(delete(Setting).where(Setting.key == "webhook_ingest_token"))
        await db_session.commit()

    async def test_import_recurring_reminder_anchors_on_household_date(
        self, client, auth_headers, vehicle, db_session, household_row, frozen_clock
    ):
        """R1-H1: a legacy is_recurring import computes due_date from the
        household's today."""
        import json as _json
        from datetime import timedelta

        body = {
            "reminders": [
                {"description": "Oil change", "is_recurring": True, "recurrence_days": 90}
            ]
        }
        response = await client.post(
            f"/api/import/vehicles/{vehicle}/json",
            headers=auth_headers,
            files={"file": ("backup.json", _json.dumps(body), "application/json")},
        )
        assert response.status_code == 200, response.text
        summary = response.json()
        assert summary["reminders"]["success"] == 1, (summary["reminders"], summary["errors"])
        due = await db_session.scalar(select(Reminder.due_date).where(Reminder.vin == vehicle))
        assert due == CHICAGO_DATE + timedelta(days=90)

    async def test_dashboard_widget_and_inbox_agree_on_overdue(
        self, client, auth_headers, vehicle, db_session, household_row, frozen_clock
    ):
        """R1-H2: a reminder due tomorrow (household) must not be overdue on
        ANY surface. Pre-fix the dashboard and widget passed the container's
        today into is_reminder_overdue while the inbox used the household's."""
        from app.services.widget_aggregation import WidgetAggregationService

        created = await client.post(
            f"/api/vehicles/{vehicle}/reminders",
            headers=auth_headers,
            json={"title": "Brake fluid", "reminder_type": "date", "due_date": "2026-09-17"},
        )
        assert created.status_code == 201, created.text

        dash = await client.get("/api/dashboard", headers=auth_headers)
        assert dash.status_code == 200, dash.text
        mine = [v for v in dash.json()["vehicles"] if v["vin"] == vehicle]
        assert mine and mine[0]["overdue_maintenance_count"] == 0, mine

        overdue, upcoming = await WidgetAggregationService(db_session)._overdue_upcoming(
            [vehicle], None, None
        )
        assert (overdue, upcoming) == (0, 1)

    async def test_auto_archive_cutoff_is_a_household_date(
        self, db_session, test_sessionmaker, test_user, household_row, frozen_clock, monkeypatch
    ):
        """R1-H3: with an America/Los_Angeles household frozen at 2026-09-17
        05:00 UTC (household 09-16), a 30-day policy must keep a vehicle whose
        last activity date is exactly the household cutoff (08-17). Pre-fix
        the cutoff came from utc_now() (08-18) and archived it."""
        import uuid as _uuid
        from datetime import datetime as dt_cls

        from app.tasks import scheduled

        await db_session.execute(
            delete(Setting).where(Setting.key.in_(["timezone", "auto_archive_inactive_days"]))
        )
        db_session.add(Setting(key="timezone", value="America/Los_Angeles"))
        db_session.add(Setting(key="auto_archive_inactive_days", value="30"))
        vin = f"HHTZ{_uuid.uuid4().hex[:13].upper()}"
        db_session.add(
            Vehicle(
                vin=vin,
                user_id=test_user["id"],
                nickname="Archive TZ",
                vehicle_type="Car",
                year=2019,
                make="Ford",
                model="Focus",
                created_at=dt_cls(2026, 8, 17, 12, 0),
                updated_at=dt_cls(2026, 8, 17, 12, 0),
            )
        )
        await db_session.commit()

        class _Frozen5(datetime):
            @classmethod
            def now(cls, tz=None):
                frozen = datetime(2026, 9, 17, 5, 0, tzinfo=UTC)
                return frozen.astimezone(tz) if tz else frozen.replace(tzinfo=None)

        monkeypatch.setattr("app.utils.household_time.datetime", _Frozen5)
        monkeypatch.setattr(scheduled, "utc_now", lambda: datetime(2026, 9, 17, 5, 0))
        monkeypatch.setattr(scheduled, "AsyncSessionLocal", test_sessionmaker)

        await scheduled.auto_archive_inactive_vehicles()

        archived = await db_session.scalar(select(Vehicle.archived_at).where(Vehicle.vin == vin))
        assert archived is None, "activity on the household cutoff day must be kept"
        await db_session.execute(delete(Vehicle).where(Vehicle.vin == vin))
        await db_session.execute(delete(Setting).where(Setting.key == "auto_archive_inactive_days"))
        await db_session.commit()

    async def test_past_period_future_cap_uses_household_tomorrow(
        self, client, auth_headers, vehicle, db_session, household_row, frozen_clock
    ):
        """Recommended-edit sweep: MountPeriodCreate's future-date cap (today
        plus one day of browser grace). With the household on 09-16 the cap is
        09-17, so a period closed 09-18 must be refused; the pre-fix UTC cap
        (09-17 + 1) accepted it."""
        tire = await _mount(client, auth_headers, vehicle, "FL", mounted_on="2026-09-01")
        response = await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}/mount-periods",
            headers=auth_headers,
            json={
                "position": "FL",
                "mounted_on": "2026-09-10",
                "dismounted_on": "2026-09-18",
            },
        )
        assert response.status_code == 422, response.text


@pytest.mark.asyncio
class TestLivenessStaysDatabaseFree:
    """Codex PR-170 P2: the Docker HEALTHCHECK hits /health, so a locked
    SQLite file or an exhausted PG pool must not report the process dead.
    The household-zone dependency skips liveness paths (they need no
    calendar date); every API route still loads the zone."""

    async def test_health_endpoints_skip_the_zone_load(self, client, monkeypatch):
        calls: list[str] = []

        async def spy(db):
            calls.append("load")
            from zoneinfo import ZoneInfo

            return ZoneInfo("UTC")

        monkeypatch.setattr("app.utils.household_time.load_household_zone", spy)

        for path in ("/health", "/api/health"):
            response = await client.get(path)
            assert response.status_code == 200, (path, response.text)
        assert calls == [], "liveness must not touch the database"

        response = await client.get("/api/settings/public")
        assert response.status_code == 200
        assert calls == ["load"], "API routes still load the zone per request"
