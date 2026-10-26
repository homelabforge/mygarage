"""A threshold alert is sent after the commit, off the ingest path (B6-1).

`check_thresholds` used to await the notification inline, so a slow service
held up the MQTT frame (and every frame behind it on the one subscriber) once
per cooldown. Now ingest decides, holds the parameter (`alert_retry_at`) and
queues the send for after the commit. The send stamps the cooldown when a
service takes it and leaves the hold when none does, as T6 did inline.

Committed, not flushed: the send runs in its own session after the commit.
"""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_parameter import LiveLinkParameter
from app.services import livelink_alerts
from app.services.livelink_ingest import ingest
from app.services.livelink_sources.base import MqttEnvelope
from app.services.livelink_sources.wican import WicanModule
from app.services.post_commit import drain
from app.services.telemetry_service import TelemetryService

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("livelink_enabled")]

#: A key nothing else registers: parameter rows are global.
KEY = "B61_COOLANT_TEMP"
SEND = (
    "app.services.notifications.dispatcher.NotificationDispatcher.notify_livelink_threshold_alert"
)

_SEQ = itertools.count()


@pytest_asyncio.fixture
async def coolant(db_session: AsyncSession) -> AsyncGenerator[None]:
    """The key's row, with a high line at 105, gone again afterwards."""
    await db_session.execute(delete(LiveLinkParameter).where(LiveLinkParameter.param_key == KEY))
    db_session.add(
        LiveLinkParameter(
            param_key=KEY,
            display_name="Coolant",
            unit="°C",
            param_class="temperature",
            category="engine",
            warning_max=105.0,
            show_on_dashboard=True,
            archive_only=False,
            storage_interval_seconds=0,
        )
    )
    await db_session.commit()
    yield
    await drain()
    await db_session.rollback()
    await db_session.execute(delete(LiveLinkParameter).where(LiveLinkParameter.param_key == KEY))
    await db_session.commit()


async def _wican(db: AsyncSession, make_livelink_vehicle) -> str:
    _vin, device = await make_livelink_vehicle("b61", str(next(_SEQ)))
    device_id = device.device_id
    await db.commit()
    return device_id


def _frame(device_id: str, value: float = 120.0) -> MqttEnvelope:
    return MqttEnvelope(f"wican/{device_id}/can/rx", f'{{"{KEY}": {value}}}'.encode())


async def _param(db: AsyncSession) -> LiveLinkParameter:
    db.expire_all()
    return (
        await db.execute(select(LiveLinkParameter).where(LiveLinkParameter.param_key == KEY))
    ).scalar_one()


class _Slow:
    """A notification service that answers when the test says so."""

    def __init__(self, results: dict[str, bool]) -> None:
        self.results = results
        self.release = asyncio.Event()
        self.calls = 0

    async def __call__(self, *args: Any, **kwargs: Any) -> dict[str, bool]:
        self.calls += 1
        await self.release.wait()
        return self.results


@pytest_asyncio.fixture
async def slow(monkeypatch) -> AsyncGenerator[_Slow]:
    """A service that answers when told, and always answers by teardown: a
    send left waiting would hold `drain` (and the next test) for ever."""
    service = _Slow({"ntfy": True})
    monkeypatch.setattr(SEND, service)
    yield service
    service.release.set()
    await drain()


@pytest.mark.usefixtures("coolant")
async def test_ingest_returns_without_waiting_for_the_send(
    db_session: AsyncSession, make_livelink_vehicle, slow: _Slow
):
    """Red on 4954e3a3: ingest awaited the send, so it was still waiting at
    the timeout."""
    device_id = await _wican(db_session, make_livelink_vehicle)

    await asyncio.wait_for(ingest(WicanModule(), _frame(device_id), db_session), timeout=2)
    await db_session.commit()

    held = await _param(db_session)
    # Held while the send is out, and not stamped until a service takes it.
    assert held.alert_retry_at is not None
    assert held.warning_last_notified_at is None

    slow.release.set()
    await drain()

    sent = await _param(db_session)
    assert slow.calls == 1
    assert sent.warning_last_notified_at is not None
    assert sent.alert_retry_at is None


@pytest.mark.usefixtures("coolant")
async def test_a_breach_while_the_send_is_out_sends_nothing_more(
    db_session: AsyncSession, make_livelink_vehicle, slow: _Slow
):
    """The hold taken at the decision is what keeps the next frames from
    queueing sends of their own (kills dropping it). On 4954e3a3 the first
    frame waits on the send, so this times out there."""
    device_id = await _wican(db_session, make_livelink_vehicle)

    for _ in range(3):
        await asyncio.wait_for(ingest(WicanModule(), _frame(device_id), db_session), timeout=2)
        await db_session.commit()
        await asyncio.sleep(0)
    slow.release.set()
    await drain()

    assert slow.calls == 1


@pytest.mark.usefixtures("coolant")
async def test_a_send_no_service_takes_keeps_the_hold(
    db_session: AsyncSession, make_livelink_vehicle, monkeypatch
):
    """Regression guard: T6's rule (R2), now in the background. No stamp, and
    the next try waits out one cooldown. Kills a send that doesn't hold."""
    device_id = await _wican(db_session, make_livelink_vehicle)
    monkeypatch.setattr(SEND, AsyncMock(return_value={"discord": False}))

    await ingest(WicanModule(), _frame(device_id), db_session)
    await db_session.commit()
    await drain()

    after = await _param(db_session)
    assert after.warning_last_notified_at is None
    assert after.alert_retry_at is not None


@pytest.mark.usefixtures("coolant")
async def test_a_rolled_back_ingest_sends_nothing(
    db_session: AsyncSession, make_livelink_vehicle, monkeypatch
):
    """The frame's own transaction failed, so its alert never happened."""
    device_id = await _wican(db_session, make_livelink_vehicle)
    send = AsyncMock(return_value={"ntfy": True})
    monkeypatch.setattr(SEND, send)

    await ingest(WicanModule(), _frame(device_id), db_session)
    await db_session.rollback()
    await drain()

    send.assert_not_awaited()
    assert (await _param(db_session)).alert_retry_at is None


#: A preset sensor's level: notify once per crossing (`once`).
TANK = "B61_TANK_LEVEL_PCT"


@pytest_asyncio.fixture
async def tank(db_session: AsyncSession) -> AsyncGenerator[None]:
    """The tank's row, with a low line at 25%, gone again afterwards."""
    await db_session.execute(delete(LiveLinkParameter).where(LiveLinkParameter.param_key == TANK))
    db_session.add(
        LiveLinkParameter(
            param_key=TANK,
            display_name="Tank 1 level",
            unit="%",
            param_class="propane",
            warning_min=25.0,
            show_on_dashboard=True,
            archive_only=False,
            storage_interval_seconds=0,
        )
    )
    await db_session.commit()
    yield
    await drain()
    await db_session.rollback()
    await db_session.execute(delete(LiveLinkParameter).where(LiveLinkParameter.param_key == TANK))
    await db_session.commit()


async def _tank_state(db: AsyncSession) -> str | None:
    db.expire_all()
    return (
        await db.execute(
            select(LiveLinkParameter.alert_state).where(LiveLinkParameter.param_key == TANK)
        )
    ).scalar_one()


async def _level(db: AsyncSession, vin: str, value: float) -> None:
    await TelemetryService(db).check_thresholds(vin, TANK, value, once=True)
    await db.commit()
    await asyncio.sleep(0)  # the send starts


@pytest.mark.usefixtures("tank")
async def test_a_refill_while_the_send_is_out_rearms_it(
    db_session: AsyncSession, make_livelink_vehicle, slow: _Slow
):
    """The delivery stored the band over the refill that landed while it was
    out, so the next drop said nothing. Red on 1083b351 (state 'low', one send)."""
    vin, _device = await make_livelink_vehicle("b61", str(next(_SEQ)))
    await db_session.commit()

    await _level(db_session, vin, 20.0)
    await _level(db_session, vin, 40.0)
    slow.release.set()
    await drain()

    assert await _tank_state(db_session) is None

    await _level(db_session, vin, 20.0)
    await drain()

    assert slow.calls == 2
    assert await _tank_state(db_session) == "low"
    # Delivered sends aren't tracked any more.
    tank_id = (
        await db_session.execute(
            select(LiveLinkParameter.id).where(LiveLinkParameter.param_key == TANK)
        )
    ).scalar_one()
    assert tank_id not in livelink_alerts._in_flight


@pytest.mark.usefixtures("tank")
async def test_jitter_while_the_send_is_out_keeps_the_band(
    db_session: AsyncSession, make_livelink_vehicle, slow: _Slow
):
    """Regression guard: only a reading clear of the margin re-arms, as when
    the band was stored inline. Kills counting any reading above the line."""
    vin, _device = await make_livelink_vehicle("b61", str(next(_SEQ)))
    await db_session.commit()

    await _level(db_session, vin, 20.0)
    await _level(db_session, vin, 27.0)
    slow.release.set()
    await drain()

    assert await _tank_state(db_session) == "low"
