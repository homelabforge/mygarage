"""The scheduled NHTSA recall check: its switches, its interval and outages.

The job runs daily at 2 AM UTC and does the real work only when NHTSA is on,
the automatic check is on, and `nhtsa_recall_check_interval` days (less an
hour of slack) have passed since `nhtsa_last_check`. An NHTSA outage leaves
`nhtsa_last_check` alone, so the next daily tick tries again instead of
reading the outage as "no recalls" for a whole interval.

`check_recalls_all_vehicles()` opens its own `AsyncSessionLocal()`, so these
tests splice in the fixture's `db_session` the way `test_check_def_levels.py`
does. The job sweeps every non-archived vehicle in the shared, session-scoped
test database, so calls are counted for this module's VINs only, and the fake
NHTSA answers "a valid decode, zero recalls" for any VIN it doesn't know.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recall import Recall
from app.models.vehicle import Vehicle
from app.services.settings_service import SettingsService
from app.tasks import scheduled
from app.tasks.scheduled import check_recalls_all_vehicles
from app.utils.datetime_utils import utc_now
from app.utils.vin import calculate_check_digit

pytestmark = pytest.mark.unit

# Every vehicle this module creates has a VIN starting with this, so cleanup
# and call counting can tell this module's vehicles from other modules'.
_VIN_PREFIX = "1RCLTSTA"

_SETTING_KEYS = (
    "nhtsa_enabled",
    "nhtsa_auto_check",
    "nhtsa_recall_check_interval",
    "nhtsa_last_check",
)


def _vin(n: int) -> str:
    """A 17-character VIN with this module's prefix and a correct check digit,
    so `validate_vin` doesn't log a mismatch warning."""
    draft = f"{_VIN_PREFIX}0{n:08d}"
    check = calculate_check_digit(draft) or "0"
    return f"{draft[:8]}{check}{draft[9:]}"


async def _wipe(db: AsyncSession) -> None:
    """Remove this module's recalls and vehicles."""
    await db.rollback()
    await db.execute(delete(Recall).where(Recall.vin.like(f"{_VIN_PREFIX}%")))
    await db.execute(delete(Vehicle).where(Vehicle.vin.like(f"{_VIN_PREFIX}%")))
    await db.commit()


@pytest_asyncio.fixture(autouse=True)
async def _clean_slate(db_session: AsyncSession, keep_rows: Any) -> AsyncIterator[None]:
    """Start and finish with none of this module's vehicles, and with the four
    NHTSA settings as they were. The job commits for real, so without this a
    leftover vehicle would join the next test's sweep."""
    await keep_rows(*_SETTING_KEYS)
    await _wipe(db_session)
    yield
    await _wipe(db_session)


class _PassthroughSessionContext:
    """Hands the job the test's already-open session and leaves it open."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


@pytest.fixture(autouse=True)
def patch_session(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> AsyncSession:
    """Route the job's `AsyncSessionLocal()` to `db_session`, and skip the two
    seconds the job waits between vehicles."""
    monkeypatch.setattr(
        "app.tasks.scheduled.AsyncSessionLocal",
        lambda: _PassthroughSessionContext(db_session),
    )
    monkeypatch.setattr("app.tasks.scheduled.asyncio.sleep", AsyncMock())
    return db_session


@pytest.fixture(autouse=True)
def notify(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """The recall notification, counted rather than sent."""
    mock = AsyncMock(return_value={})
    monkeypatch.setattr(
        "app.services.notifications.dispatcher.NotificationDispatcher.notify_recall_detected",
        mock,
    )
    return mock


@pytest_asyncio.fixture
async def make_vehicle(db_session: AsyncSession) -> Callable[..., Awaitable[Vehicle]]:
    """Create one of this module's vehicles, committed."""
    counter = {"n": 0}

    async def _factory() -> Vehicle:
        counter["n"] += 1
        vehicle = Vehicle(
            vin=_vin(counter["n"]),
            nickname=f"Recall Sweep Car {counter['n']}",
            vehicle_type="Car",
            year=2020,
            make="TestMake",
            model="TestModel",
        )
        db_session.add(vehicle)
        await db_session.commit()
        return vehicle

    return _factory


async def _store(db: AsyncSession, **values: str) -> None:
    """Write NHTSA settings and commit, as the Settings page would."""
    for key, value in values.items():
        await SettingsService.set(db, key, value)
    await db.commit()


async def _last_check(db: AsyncSession) -> str | None:
    """`nhtsa_last_check` as stored now (the job ran on this same session)."""
    setting = await SettingsService.get(db, "nhtsa_last_check")
    return setting.value if setting is not None else None


@pytest.fixture
def recalls_fetch(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """`NHTSAService.get_vehicle_recalls`, answering no recalls. The job imports
    `NHTSAService` inside the function, so the class itself is patched."""
    mock = AsyncMock(return_value=[])
    monkeypatch.setattr("app.services.nhtsa.NHTSAService.get_vehicle_recalls", mock)
    return mock


def _fetched(mock: AsyncMock, vin: str) -> int:
    """How many times the job asked NHTSA about `vin`."""
    return sum(1 for call in mock.await_args_list if call.args[0] == vin)


# --- the switches -------------------------------------------------------------


@pytest.mark.parametrize(
    ("enabled", "auto_check", "runs"),
    [
        pytest.param("false", "true", False, id="nhtsa-off"),
        pytest.param("1", "true", True, id="nhtsa-on-as-1"),
        pytest.param("true", "off", False, id="auto-check-off"),
        pytest.param("true", "yes", True, id="auto-check-on-as-yes"),
    ],
)
async def test_the_switches_gate_the_scheduled_check(
    db_session: AsyncSession,
    make_vehicle: Callable[..., Awaitable[Vehicle]],
    recalls_fetch: AsyncMock,
    enabled: str,
    auto_check: str,
    runs: bool,
) -> None:
    """NHTSA switched off means no scheduled call, and both switches read any
    on/off word. Red as a whole on main: it ignored `nhtsa_enabled`, and read
    `nhtsa_auto_check` as on only for the exact word "true". The
    auto-check-off row alone is a guard (main skipped it too)."""
    vehicle = await make_vehicle()
    await _store(
        db_session,
        nhtsa_enabled=enabled,
        nhtsa_auto_check=auto_check,
        nhtsa_recall_check_interval="7",
        nhtsa_last_check="",
    )

    await check_recalls_all_vehicles()

    assert _fetched(recalls_fetch, vehicle.vin) == (1 if runs else 0)


# --- the interval -------------------------------------------------------------


def _ago(delta: timedelta) -> str:
    """A naive-UTC ISO timestamp `delta` before now, as the job stores it."""
    return (utc_now() - delta).isoformat()


def _ago_aware(delta: timedelta) -> str:
    """The same, written with an explicit +00:00 offset."""
    return (utc_now() - delta).replace(tzinfo=UTC).isoformat()


def _literal(text: str) -> Callable[[], str]:
    """A stored last check that isn't relative to now."""
    return lambda: text


_DAYS_7 = timedelta(days=7)
_JUST_UNDER_7 = timedelta(days=6, hours=22)


@pytest.mark.parametrize(
    ("interval", "last_check", "runs"),
    [
        pytest.param("30", partial(_ago, timedelta(days=8)), False, id="30-days-8-ago"),
        pytest.param(
            "1", partial(_ago, timedelta(hours=23, minutes=30)), True, id="1-day-23.5h-ago"
        ),
        pytest.param("1", partial(_ago, timedelta(hours=22)), False, id="1-day-22h-ago"),
        *(
            pytest.param(raw, partial(_ago, delta), runs, id=f"{label}-as-7-{when}")
            for raw, label in [
                ("weekly", "garbage"),
                ("", "blank"),
                ("0", "zero"),
                ("99999999999", "huge"),
            ]
            for delta, runs, when in [
                (_DAYS_7, True, "7d-ago"),
                (_JUST_UNDER_7, False, "6d22h-ago"),
            ]
        ),
        pytest.param("30", partial(_ago_aware, timedelta(days=8)), False, id="aware-30-days-8-ago"),
        pytest.param(
            "30", partial(_ago_aware, timedelta(days=31)), True, id="aware-30-days-31-ago"
        ),
        pytest.param("7", partial(_ago, -timedelta(days=2)), True, id="future-2-days"),
        pytest.param("7", _literal(""), True, id="guard-blank-last-check"),
        pytest.param("7", _literal("last tuesday"), True, id="guard-unparseable-last-check"),
    ],
)
async def test_the_check_runs_only_when_the_interval_is_due(
    db_session: AsyncSession,
    make_vehicle: Callable[..., Awaitable[Vehicle]],
    recalls_fetch: AsyncMock,
    interval: str,
    last_check: Callable[[], str],
    runs: bool,
) -> None:
    """`nhtsa_recall_check_interval` days, less an hour, must pass between checks.

    Red as a whole on main, which ran every Sunday whatever the setting said:
    each positive row is paired with a negative that main fails. A blank,
    garbage, zero or out-of-range interval reads as 7; the huge one also
    covers `timedelta` overflowing, which would fail every run. A last check
    in the future (a wrong clock, a restored backup) is due rather than
    blocking checks until that date. The blank and unparseable last-check
    rows are regression guards: main ran those too. Times are taken when the
    test runs, not when it's collected, so a long suite can't age a negative
    row past its boundary.
    """
    vehicle = await make_vehicle()
    await _store(
        db_session,
        nhtsa_enabled="true",
        nhtsa_auto_check="true",
        nhtsa_recall_check_interval=interval,
        nhtsa_last_check=last_check(),
    )

    await check_recalls_all_vehicles()

    assert _fetched(recalls_fetch, vehicle.vin) == (1 if runs else 0)


async def test_a_future_last_check_logs_one_warning(
    db_session: AsyncSession,
    make_vehicle: Callable[..., Awaitable[Vehicle]],
    recalls_fetch: AsyncMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A stored time two days ahead says the clock was wrong once; say so, once."""
    await make_vehicle()
    await _store(
        db_session,
        nhtsa_enabled="true",
        nhtsa_auto_check="true",
        nhtsa_recall_check_interval="7",
        nhtsa_last_check=_ago(-timedelta(days=2)),
    )
    caplog.set_level("WARNING", logger="app.tasks.scheduled")

    await check_recalls_all_vehicles()

    warnings = [r for r in caplog.records if r.name == "app.tasks.scheduled"]
    assert len(warnings) == 1, [r.getMessage() for r in warnings]
    assert "future" in warnings[0].getMessage()


# --- outages, through the real NHTSAService ----------------------------------


class _FakeNHTSA:
    """Answers httpx requests for vPIC decodes and recall lookups.

    Each of this module's VINs decodes to its own model, so a recalls request
    can be traced back to the vehicle. Any other VIN decodes to a model with no
    recalls. `fail` is (VIN, step, how) for the one request that goes wrong.
    """

    def __init__(self) -> None:
        self.models: dict[str, str] = {}
        self.recalls: dict[str, list[dict[str, str]]] = {}
        self.no_model: set[str] = set()
        self.fail: tuple[str, str, str] | None = None
        self.requested: list[str] = []

    def _failure(self, url: str, how: str) -> httpx.Response:
        request = httpx.Request("GET", url)
        if how == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if how == "503":
            return httpx.Response(503, request=request, text="Service Unavailable")
        raise AssertionError(how)

    def answer(self, url: str) -> httpx.Response:
        """The response to a GET of `url`, or the transport error it raises."""
        self.requested.append(url)
        request = httpx.Request("GET", url)
        parts = urlsplit(url)
        if "/DecodeVinValues/" in parts.path:
            vin = parts.path.rsplit("/", 1)[1]
            if self.fail and self.fail[:2] == (vin, "decode"):
                return self._failure(url, self.fail[2])
            model = "" if vin in self.no_model else self.models.get(vin, "NoRecallsModel")
            result = {"Make": "TESTMAKE", "Model": model, "ModelYear": "2020", "ErrorCode": "0"}
            return httpx.Response(200, request=request, json={"Results": [result]})
        if parts.path.endswith("/recallsByVehicle"):
            model = parse_qs(parts.query)["model"][0]
            vin = next((v for v, m in self.models.items() if m == model), None)
            if vin and self.fail and self.fail[:2] == (vin, "recalls"):
                return self._failure(url, self.fail[2])
            return httpx.Response(
                200, request=request, json={"results": self.recalls.get(vin or "", [])}
            )
        raise AssertionError(f"unexpected request {url}")


@pytest.fixture
def nhtsa(monkeypatch: pytest.MonkeyPatch) -> _FakeNHTSA:
    """The fake NHTSA behind every httpx request, with DNS lookups off."""
    fake = _FakeNHTSA()

    async def fake_get(client: object, url: str, **kwargs: object) -> httpx.Response:
        return fake.answer(url)

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)
    monkeypatch.setattr("app.utils.url_validation.resolve_hostname", lambda hostname: None)
    return fake


def _recall(campaign: str) -> dict[str, str]:
    """One recall as NHTSA's recallsByVehicle lists it."""
    return {
        "NHTSACampaignNumber": campaign,
        "Component": "AIR BAGS",
        "Summary": "The inflator may rupture.",
        "Consequence": "Metal fragments may strike occupants.",
        "Remedy": "Dealers will replace the inflator.",
    }


def _notified(mock: AsyncMock, vehicle: Vehicle) -> int:
    """Recall notifications sent for `vehicle` (they name it, not its VIN)."""
    return sum(
        1 for call in mock.await_args_list if call.kwargs["vehicle_name"] == vehicle.nickname
    )


async def _recall_rows(db: AsyncSession, vehicle: Vehicle) -> int:
    """Stored recalls for `vehicle`."""
    result = await db.execute(select(Recall).where(Recall.vin == vehicle.vin))
    return len(result.scalars().all())


@pytest.mark.parametrize(
    ("step", "how"),
    [
        pytest.param("recalls", "timeout", id="recalls-timeout"),
        pytest.param("recalls", "503", id="recalls-503"),
        pytest.param("decode", "timeout", id="decode-timeout"),
    ],
)
async def test_an_outage_leaves_the_last_check_alone(
    db_session: AsyncSession,
    make_vehicle: Callable[..., Awaitable[Vehicle]],
    nhtsa: _FakeNHTSA,
    notify: AsyncMock,
    step: str,
    how: str,
) -> None:
    """NHTSA failing for one vehicle is an outage, not "no recalls".

    Main swallowed the error, wrote `nhtsa_last_check` and so waited a whole
    interval: red. The other vehicle's new recall is still stored (the pass
    commits), and the next tick, still due, neither stores nor announces it
    a second time.
    """
    failing = await make_vehicle()
    healthy = await make_vehicle()
    nhtsa.models = {failing.vin: "FailingModel", healthy.vin: "HealthyModel"}
    nhtsa.recalls = {healthy.vin: [_recall("26V123000")]}
    nhtsa.fail = (failing.vin, step, how)
    await _store(
        db_session,
        nhtsa_enabled="true",
        nhtsa_auto_check="true",
        nhtsa_recall_check_interval="7",
        nhtsa_last_check="",
    )

    await check_recalls_all_vehicles()

    assert await _last_check(db_session) in (None, "")
    assert await _recall_rows(db_session, healthy) == 1
    assert _notified(notify, healthy) == 1

    nhtsa.requested.clear()
    await check_recalls_all_vehicles()

    assert any(healthy.vin in url for url in nhtsa.requested), "the next tick was not due"
    assert await _recall_rows(db_session, healthy) == 1
    assert _notified(notify, healthy) == 1


async def _assert_advanced(db: AsyncSession) -> None:
    """`nhtsa_last_check` was written by this run."""
    stored = await _last_check(db)
    assert stored, "nhtsa_last_check was not written"
    assert abs(utc_now() - datetime.fromisoformat(stored)) < timedelta(minutes=1)


async def test_a_clean_pass_advances_the_last_check(
    db_session: AsyncSession,
    make_vehicle: Callable[..., Awaitable[Vehicle]],
    nhtsa: _FakeNHTSA,
) -> None:
    """Every request answering 200 with no recalls is a check done.

    Regression guard (main advanced it too); it pairs with the outage test,
    which is red, so that test can't pass by never writing the timestamp.
    """
    first = await make_vehicle()
    second = await make_vehicle()
    nhtsa.models = {first.vin: "FirstModel", second.vin: "SecondModel"}
    await _store(
        db_session,
        nhtsa_enabled="true",
        nhtsa_auto_check="true",
        nhtsa_recall_check_interval="7",
        nhtsa_last_check="",
    )

    await check_recalls_all_vehicles()

    await _assert_advanced(db_session)


async def test_an_undecodable_vin_is_not_an_outage(
    db_session: AsyncSession,
    make_vehicle: Callable[..., Awaitable[Vehicle]],
    nhtsa: _FakeNHTSA,
) -> None:
    """A VIN vPIC answers for but can't give a model for (many trailers and
    RVs) can never be checked; treating it as an outage would re-query the
    whole fleet every day. It counts as checked.

    Regression guard: main wrote the timestamp unconditionally. It guards the
    outage rule against over-reaching.
    """
    undecodable = await make_vehicle()
    healthy = await make_vehicle()
    nhtsa.models = {undecodable.vin: "Unused", healthy.vin: "HealthyModel"}
    nhtsa.no_model = {undecodable.vin}
    await _store(
        db_session,
        nhtsa_enabled="true",
        nhtsa_auto_check="true",
        nhtsa_recall_check_interval="7",
        nhtsa_last_check="",
    )

    await check_recalls_all_vehicles()

    await _assert_advanced(db_session)


# --- the trigger --------------------------------------------------------------


def test_the_recall_check_is_scheduled_daily_at_2_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    """The job ticks daily and decides itself whether the interval is due.

    Pinned to UTC: the scheduler has no zone, so a local-zone cron would put
    23 or 25 hours between ticks on DST days, and the hour of slack assumes 24.
    Red on main, which registered Sunday only, in the scheduler's zone.
    """
    monkeypatch.setenv("SCHEDULER_ENABLED", "true")
    monkeypatch.setattr(scheduled.scheduler, "start", lambda *args, **kwargs: None)
    try:
        scheduled.start_scheduler()
        job = scheduled.scheduler.get_job("check_recalls_all_vehicles")
        assert job is not None
        fields = {field.name: str(field) for field in job.trigger.fields}
        assert fields["day_of_week"] == "*"
        assert fields["hour"] == "2"
        assert fields["minute"] == "0"
        assert job.trigger.timezone == UTC
    finally:
        scheduled.scheduler.remove_all_jobs()
