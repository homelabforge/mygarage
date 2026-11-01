"""The Telegram poller: offsets, exactly-once fill-ups, errors, lifecycle.

A fake Bot API (httpx.MockTransport) stands in for Telegram; no network. The
poller opens its own sessions, so `AsyncSessionLocal` is pointed at the test
database (under pytest the app's factory is bound to /data/mygarage.db).
"""

import asyncio
import json
import logging
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy import exc as sa_exc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fuel import FuelRecord
from app.models.odometer import OdometerRecord
from app.models.settings import Setting
from app.services import telegram_poller as poller_module
from app.services.telegram_fuel_commands import USAGE
from app.services.telegram_poller import (
    BACKOFF_START_SECONDS,
    COMMITTED_REPLY,
    ERROR_WAIT_SECONDS,
    OFF_WAIT_SECONDS,
    OFFSET_KEY,
    SKIPPED_REPLY,
    TelegramPoller,
    bot_id_of,
    is_outage,
    parse_stored_offset,
)

TOKEN = "123456:TEST-token"
BOT = "123456"
_KEYS = (
    "telegram_enabled",
    "telegram_inbound_enabled",
    "telegram_bot_token",
    "telegram_chat_id",
    OFFSET_KEY,
)


def _ok(result: Any) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": result})


def _error(status: int, description: str, retry_after: int | None = None) -> httpx.Response:
    body: dict[str, Any] = {"ok": False, "error_code": status, "description": description}
    if retry_after is not None:
        body["parameters"] = {"retry_after": retry_after}
    return httpx.Response(status, json=body)


class FakeTelegram:
    """The Bot API, faked: a queue of updates and a log of every call."""

    def __init__(self) -> None:
        self.queue: list[dict[str, Any]] = []
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.paths: list[str] = []
        self.sent: list[dict[str, Any]] = []
        self.fail: dict[str, httpx.Response | Exception] = {}
        self._next_id = 100

    def message(self, text: str | None, *, chat: int = 42) -> int:
        """Queue a message (text None: a sticker or photo); return its update id."""
        self._next_id += 1
        message: dict[str, Any] = {
            "message_id": self._next_id,
            "date": 1_790_000_000,
            "chat": {"id": chat},
        }
        if text is not None:
            message["text"] = text
        self.queue.append({"update_id": self._next_id, "message": message})
        return self._next_id

    def raw(self, update: dict[str, Any]) -> int:
        self._next_id += 1
        self.queue.append({"update_id": self._next_id, **update})
        return self._next_id

    @property
    def replies(self) -> list[str]:
        return [m["text"] for m in self.sent]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        params = json.loads(request.content or b"{}")
        self.paths.append(request.url.path)
        self.calls.append((method, params))
        failure = self.fail.get(method)
        if isinstance(failure, Exception):
            raise failure
        if failure is not None:  # a fresh copy: a Response is not reusable across requests
            return httpx.Response(failure.status_code, json=json.loads(failure.content))
        if method == "deleteWebhook":
            return _ok(True)
        if method == "sendMessage":
            self.sent.append(params)
            return _ok({"message_id": 1})
        if method == "getUpdates":
            offset = params.get("offset", 0)
            if offset < 0:  # "all previous updates will be forgotten"
                self.queue = self.queue[offset:]
                return _ok(list(self.queue))
            self.queue = [u for u in self.queue if u["update_id"] >= offset]
            return _ok(self.queue[: params.get("limit", 100)])
        return _error(404, "Not Found")

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self._handle))


async def _round(poller: TelegramPoller, fake: FakeTelegram) -> float:
    async with fake.client() as client:
        return await poller.run_once(client)


async def _set(db_session, key: str, value: str) -> None:
    db_session.expire_all()
    row = await db_session.get(Setting, key)
    if row is None:
        db_session.add(Setting(key=key, value=value))
    else:
        row.value = value
    await db_session.commit()


async def _stored(db_session) -> str | None:
    db_session.expire_all()
    return await db_session.scalar(select(Setting.value).where(Setting.key == OFFSET_KEY))


async def _fill_ups(db_session, vin: str) -> int:
    return await db_session.scalar(
        select(func.count())
        .select_from(FuelRecord)
        .where(FuelRecord.vin == vin, FuelRecord.notes == "via telegram")
    )


@pytest.fixture
def sessions(test_sessionmaker):
    """The poller's own sessions, on the test database."""
    with patch.object(poller_module, "AsyncSessionLocal", test_sessionmaker):
        yield


@pytest_asyncio.fixture
async def switches(db_session):
    """Telegram and fuel commands on for bot 123456, chat 42; restored after."""
    previous: dict[str, str | None] = {}
    for key in (*_KEYS, "timezone"):
        row = await db_session.get(Setting, key)
        previous[key] = row.value if row is not None else None
    for key, value in (
        ("telegram_enabled", "true"),
        ("telegram_inbound_enabled", "true"),
        ("telegram_bot_token", TOKEN),
        ("telegram_chat_id", "42"),
        (OFFSET_KEY, ""),
    ):
        await _set(db_session, key, value)
    yield
    await db_session.rollback()
    db_session.expire_all()
    for key, value in previous.items():
        row = await db_session.get(Setting, key)
        if value is None:
            if row is not None:
                await db_session.delete(row)
        elif row is not None:
            row.value = value
        else:
            db_session.add(Setting(key=key, value=value))
    await db_session.commit()


@pytest_asyncio.fixture(autouse=True)
async def _no_telegram_fill_ups(db_session):
    async def _wipe():
        ids = select(FuelRecord.id).where(FuelRecord.notes == "via telegram")
        await db_session.execute(
            delete(OdometerRecord).where(OdometerRecord.fuel_record_id.in_(ids))
        )
        await db_session.execute(delete(FuelRecord).where(FuelRecord.notes == "via telegram"))
        await db_session.commit()

    await _wipe()
    yield
    await db_session.rollback()
    await _wipe()


# --- pure helpers ---------------------------------------------------------


def test_bot_id_is_the_token_prefix_and_only_digits():
    assert bot_id_of("123456:abc") == "123456"
    assert bot_id_of("not-a-token") is None
    assert bot_id_of("12a:abc") is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("123456:7", 7),
        ("123456:0", 0),
        ("999:7", None),
        ("garbage", None),
        ("", None),
        (None, None),
    ],
)
def test_a_stored_offset_counts_only_for_its_own_bot(value, expected):
    assert parse_stored_offset(value, "123456") == expected


@pytest.mark.parametrize(
    "exc",
    [
        sa_exc.OperationalError("SELECT 1", {}, Exception("database is locked")),
        sa_exc.InterfaceError("SELECT 1", {}, Exception("connection closed")),
        ConnectionRefusedError(111, "Connection refused"),
        TimeoutError(),
        # PostgreSQL's pool exhausted: a bare SQLAlchemyError, no DBAPI error inside.
        sa_exc.TimeoutError("QueuePool limit of size 5 overflow 10 reached"),
    ],
)
def test_outages(exc):
    assert is_outage(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        sa_exc.IntegrityError("INSERT", {}, Exception("constraint")),
        RuntimeError("bug"),
        KeyError("k"),
    ],
)
def test_not_outages(exc):
    assert is_outage(exc) is False


def test_an_invalidated_connection_is_an_outage():
    exc = sa_exc.DBAPIError("SELECT 1", {}, Exception("gone"), connection_invalidated=True)
    assert is_outage(exc) is True


# --- off ------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("telegram_enabled", "false"),
        ("telegram_inbound_enabled", "false"),
        ("telegram_bot_token", ""),
    ],
)
async def test_nothing_is_asked_of_telegram_while_off(db_session, switches, sessions, key, value):
    await _set(db_session, key, value)
    fake = FakeTelegram()
    poller = TelegramPoller()

    assert await _round(poller, fake) == OFF_WAIT_SECONDS
    assert fake.calls == []
    assert poller.status["state"] == "off"


@pytest.mark.asyncio
async def test_switching_off_clears_the_offset(db_session, switches, sessions):
    await _set(db_session, OFFSET_KEY, f"{BOT}:7")
    await _set(db_session, "telegram_inbound_enabled", "false")

    await _round(TelegramPoller(), FakeTelegram())

    assert await _stored(db_session) == ""


@pytest.mark.asyncio
async def test_off_with_no_offset_row_at_all(db_session, switches, sessions):
    """settings_init creates the row at boot, but a fresh or restored database may lack it."""
    await _set(db_session, "telegram_inbound_enabled", "false")
    await db_session.execute(delete(Setting).where(Setting.key == OFFSET_KEY))
    await db_session.commit()
    poller = TelegramPoller()

    assert await _round(poller, FakeTelegram()) == OFF_WAIT_SECONDS
    assert poller.status["state"] == "off"


# --- starting and resuming -------------------------------------------------


@pytest.mark.asyncio
async def test_switching_on_clears_the_webhook_and_skips_the_backlog(
    db_session, switches, sessions
):
    fake = FakeTelegram()
    sent_while_off = fake.message("help")
    poller = TelegramPoller()

    await _round(poller, fake)

    assert fake.calls[0] == ("deleteWebhook", {"drop_pending_updates": False})
    assert fake.calls[1] == ("getUpdates", {"offset": -1, "timeout": 0})
    assert fake.replies == []
    assert await _stored(db_session) == f"{BOT}:{sent_while_off + 1}"
    assert poller.status["state"] == "listening"


@pytest.mark.asyncio
async def test_an_empty_bootstrap_still_resumes_after_a_restart(db_session, switches, sessions):
    fake = FakeTelegram()
    await _round(TelegramPoller(), fake)
    assert await _stored(db_session) == f"{BOT}:0"

    fake.message("help")  # sent while MyGarage is down
    await _round(TelegramPoller(), fake)  # a new process

    assert fake.replies == [USAGE]


@pytest.mark.asyncio
async def test_a_restart_resumes_where_it_left_off(db_session, switches, sessions):
    fake = FakeTelegram()
    waiting = fake.message("help")
    await _set(db_session, OFFSET_KEY, f"{BOT}:{waiting}")

    await _round(TelegramPoller(), fake)

    assert ("getUpdates", {"offset": -1, "timeout": 0}) not in fake.calls
    assert fake.replies == [USAGE]
    assert await _stored(db_session) == f"{BOT}:{waiting + 1}"


@pytest.mark.asyncio
@pytest.mark.parametrize("stored", ["999:5", "garbage"])
async def test_another_bots_or_an_unreadable_offset_starts_over(
    db_session, switches, sessions, stored
):
    await _set(db_session, OFFSET_KEY, stored)
    fake = FakeTelegram()

    await _round(TelegramPoller(), fake)

    assert ("getUpdates", {"offset": -1, "timeout": 0}) in fake.calls


@pytest.mark.asyncio
async def test_an_offset_cleared_while_polling_starts_over(db_session, switches, sessions):
    fake = FakeTelegram()
    poller = TelegramPoller()
    await _round(poller, fake)
    await _set(db_session, OFFSET_KEY, "")
    fake.calls.clear()

    await _round(poller, fake)

    assert ("getUpdates", {"offset": -1, "timeout": 0}) in fake.calls


@pytest.mark.asyncio
async def test_a_malformed_token_stores_nothing(db_session, switches, sessions):
    await _set(db_session, "telegram_bot_token", "not-a-token")
    fake = FakeTelegram()
    poller = TelegramPoller()

    assert await _round(poller, fake) == ERROR_WAIT_SECONDS
    assert fake.calls == []
    assert poller.status["error_code"] == "bot_token_rejected"
    assert await _stored(db_session) == ""


@pytest.mark.asyncio
async def test_a_token_with_stray_whitespace_still_works(db_session, switches, sessions):
    await _set(db_session, "telegram_bot_token", f" {TOKEN} \n")
    fake = FakeTelegram()

    await _round(TelegramPoller(), fake)

    assert fake.paths and all(p.startswith(f"/bot{TOKEN}/") for p in fake.paths)


@pytest.mark.asyncio
async def test_switched_off_while_waiting_handles_nothing(db_session, switches, sessions):
    fake = FakeTelegram()
    poller = TelegramPoller()
    await _round(poller, fake)
    waiting = fake.message("help")

    config = poller_module._Config(token=TOKEN, chat_id="42")
    with patch.object(poller_module, "_read_config", AsyncMock(side_effect=[config, None])):
        await _round(poller, fake)

    assert fake.replies == []
    assert await _stored(db_session) == f"{BOT}:0"  # the waiting message was not acknowledged
    assert waiting > 0


# --- handling --------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_command_logs_a_fill_up_and_replies(db_session, switches, sessions, test_vehicle):
    fake = FakeTelegram()
    poller = TelegramPoller()
    await _round(poller, fake)
    vin = test_vehicle["vin"]
    update = fake.message(f"fuel {vin} 10000 40")

    await _round(poller, fake)

    assert await _fill_ups(db_session, vin) == 1
    # The reply echoes what it logged (#172); the bare reading's unit is the
    # owner's, which this module does not pin, so only the shape is asserted.
    assert fake.replies[0].startswith("Logged 10,000 ")
    assert f"for {test_vehicle['nickname']} on " in fake.replies[0]
    assert await _stored(db_session) == f"{BOT}:{update + 1}"


@pytest.mark.asyncio
async def test_an_update_without_text_does_not_block_the_next(db_session, switches, sessions):
    fake = FakeTelegram()
    poller = TelegramPoller()
    await _round(poller, fake)
    fake.message(None)
    fake.raw({"edited_message": {"message_id": 5, "chat": {"id": 42}, "text": "x"}})
    last = fake.message("help")

    await _round(poller, fake)

    assert fake.replies == [USAGE]
    assert await _stored(db_session) == f"{BOT}:{last + 1}"


@pytest.mark.asyncio
async def test_a_backlog_over_one_hundred_is_handled_over_rounds(db_session, switches, sessions):
    fake = FakeTelegram()
    poller = TelegramPoller()
    await _round(poller, fake)
    for _ in range(105):
        fake.message("help")

    await _round(poller, fake)
    assert len(fake.replies) == 100
    await _round(poller, fake)
    assert len(fake.replies) == 105


@pytest.mark.asyncio
async def test_a_rejection_after_a_flush_commits_the_offset_and_nothing_else(
    db_session, switches, sessions, test_vehicle
):
    fake = FakeTelegram()
    poller = TelegramPoller()
    await _round(poller, fake)
    vin = test_vehicle["vin"]
    update = fake.message(f"fuel {vin} 10000 40")

    with patch(
        "app.services.fuel_ingest.apply_fuel_record_side_effects",
        AsyncMock(side_effect=HTTPException(status_code=400, detail="nope")),
    ):
        await _round(poller, fake)

    assert await _fill_ups(db_session, vin) == 0
    assert fake.replies == ["Could not log that: nope"]
    assert await _stored(db_session) == f"{BOT}:{update + 1}"


@pytest.mark.asyncio
async def test_a_failed_reply_never_undoes_the_fill_up(
    db_session, switches, sessions, test_vehicle
):
    fake = FakeTelegram()
    poller = TelegramPoller()
    await _round(poller, fake)
    vin = test_vehicle["vin"]
    update = fake.message(f"fuel {vin} 10000 40")
    fake.fail["sendMessage"] = _error(403, "Forbidden: bot was blocked by the user")

    await _round(poller, fake)

    assert await _fill_ups(db_session, vin) == 1
    assert await _stored(db_session) == f"{BOT}:{update + 1}"
    assert poller.status["state"] == "listening"


# --- exactly once ------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_exception_after_the_commit_replies_logged_and_does_not_duplicate(
    db_session, switches, sessions, test_vehicle
):
    fake = FakeTelegram()
    poller = TelegramPoller()
    await _round(poller, fake)
    vin = test_vehicle["vin"]
    fake.message(f"fuel {vin} 10000 40")

    # The refresh is the only work left after the commit.
    with patch.object(AsyncSession, "refresh", AsyncMock(side_effect=RuntimeError("db went away"))):
        await _round(poller, fake)
    await _round(poller, fake)

    assert await _fill_ups(db_session, vin) == 1
    assert fake.replies == [COMMITTED_REPLY]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outage",
    [
        sa_exc.OperationalError("INSERT", {}, Exception("database is locked")),
        ConnectionRefusedError(111, "Connection refused"),  # PostgreSQL down, unwrapped
        sa_exc.TimeoutError("QueuePool limit of size 5 overflow 10 reached"),
    ],
    ids=["sqlite-locked", "postgres-down", "postgres-pool-exhausted"],
)
async def test_an_outage_never_skips_a_message(
    db_session, switches, sessions, test_vehicle, outage
):
    fake = FakeTelegram()
    poller = TelegramPoller()
    await _round(poller, fake)
    vin = test_vehicle["vin"]
    update = fake.message(f"fuel {vin} 10000 40")

    waits = []
    with patch(
        "app.services.fuel_ingest.apply_fuel_record_side_effects", AsyncMock(side_effect=outage)
    ):
        for _ in range(6):
            waits.append(await _round(poller, fake))
            assert poller.status["error_code"] == "database_error"
    # Telegram answers every round; the back-off still grows (Codex plan R1-M1).
    assert waits == [5.0, 10.0, 20.0, 40.0, 60.0, 60.0]
    assert await _stored(db_session) == f"{BOT}:0"  # never acknowledged
    assert SKIPPED_REPLY not in fake.replies
    assert update > 0

    await _round(poller, fake)  # the database is back

    assert await _fill_ups(db_session, vin) == 1
    assert fake.replies[-1].startswith("Logged 10,000 ")
    assert f"for {test_vehicle['nickname']} on " in fake.replies[-1]


@pytest.mark.asyncio
async def test_a_deterministic_failure_is_skipped_after_three_rounds(
    db_session, switches, sessions, test_vehicle
):
    fake = FakeTelegram()
    poller = TelegramPoller()
    await _round(poller, fake)
    vin = test_vehicle["vin"]
    fake.message(f"fuel {vin} 10000 40")
    after = fake.message("help")
    broken = AsyncMock(side_effect=sa_exc.IntegrityError("INSERT", {}, Exception("constraint")))

    with patch("app.services.fuel_ingest.apply_fuel_record_side_effects", broken):
        for _ in range(3):
            assert await _round(poller, fake) == ERROR_WAIT_SECONDS
            assert poller.status["error_code"] == "unexpected"
            assert fake.replies == []
        await _round(poller, fake)

    assert fake.replies == [SKIPPED_REPLY, USAGE]
    assert await _stored(db_session) == f"{BOT}:{after + 1}"
    assert await _fill_ups(db_session, vin) == 0


@pytest.mark.asyncio
async def test_a_failing_skip_is_retried_not_rehandled(
    db_session, switches, sessions, test_vehicle
):
    fake = FakeTelegram()
    poller = TelegramPoller()
    await _round(poller, fake)
    vin = test_vehicle["vin"]
    update = fake.message(f"fuel {vin} 10000 40")
    broken = AsyncMock(side_effect=RuntimeError("bug"))

    with patch("app.services.fuel_ingest.apply_fuel_record_side_effects", broken):
        for _ in range(3):
            await _round(poller, fake)
        real_commit = poller._commit_offset
        poller._commit_offset = AsyncMock(  # type: ignore[method-assign]
            side_effect=[sa_exc.OperationalError("UPDATE", {}, Exception("locked"))]
        )
        await _round(poller, fake)
        assert poller.status["error_code"] == "database_error"
        poller._commit_offset = real_commit  # type: ignore[method-assign]
        await _round(poller, fake)

    assert broken.await_count == 3  # the fourth and fifth rounds skipped, they did not re-handle
    assert fake.replies == [SKIPPED_REPLY]
    assert await _stored(db_session) == f"{BOT}:{update + 1}"


@pytest.mark.asyncio
async def test_skipping_a_chatless_update_sends_nothing(db_session, switches, sessions):
    fake = FakeTelegram()
    poller = TelegramPoller()
    await _round(poller, fake)
    chatless = fake.raw({"channel_post": {"message_id": 1}})
    poller._failures[(BOT, chatless)] = (3, "RuntimeError")

    await _round(poller, fake)

    assert not [m for m, _ in fake.calls if m == "sendMessage"]
    assert await _stored(db_session) == f"{BOT}:{chatless + 1}"


@pytest.mark.asyncio
async def test_a_new_bot_token_restarts_polling(db_session, switches, sessions):
    fake_a = FakeTelegram()
    poller = TelegramPoller()
    await _round(poller, fake_a)
    await _set(db_session, "telegram_bot_token", "654321:OTHER-token")
    fake_b = FakeTelegram()

    await _round(poller, fake_b)

    assert fake_b.calls[0] == ("deleteWebhook", {"drop_pending_updates": False})
    assert ("getUpdates", {"offset": -1, "timeout": 0}) in fake_b.calls
    assert await _stored(db_session) == "654321:0"


@pytest.mark.asyncio
async def test_failures_counted_for_one_bot_never_skip_anothers(
    db_session, switches, sessions, test_vehicle
):
    """Update ids are per bot: the new bot's update 101 is not the old bot's."""
    fake_a = FakeTelegram()
    poller = TelegramPoller()
    await _round(poller, fake_a)
    vin = test_vehicle["vin"]
    failing = fake_a.message(f"fuel {vin} 10000 40")
    with patch(
        "app.services.fuel_ingest.apply_fuel_record_side_effects",
        AsyncMock(side_effect=RuntimeError("bug")),
    ):
        for _ in range(3):
            await _round(poller, fake_a)

    await _set(db_session, "telegram_bot_token", "654321:OTHER-token")
    fake_b = FakeTelegram()
    await _round(poller, fake_b)  # the new bot starts clean
    same_number = fake_b.message(f"fuel {vin} 10000 40")
    assert same_number == failing
    await _round(poller, fake_b)

    assert await _fill_ups(db_session, vin) == 1
    assert SKIPPED_REPLY not in fake_b.replies


# --- Telegram and network errors -------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "code", "wait"),
    [
        (_error(401, "Unauthorized"), "bot_token_rejected", ERROR_WAIT_SECONDS),
        (_error(404, "Not Found"), "bot_token_rejected", ERROR_WAIT_SECONDS),
        (
            _error(409, "Conflict: terminated by other getUpdates request"),
            "conflict",
            ERROR_WAIT_SECONDS,
        ),
        (_error(429, "Too Many Requests: retry after 7", retry_after=7), "rate_limited", 7.0),
        (_error(500, "Internal Server Error"), "unreachable", BACKOFF_START_SECONDS),
        (_error(502, "Bad Gateway"), "unreachable", BACKOFF_START_SECONDS),
        (_error(400, "Bad Request: wrong offset"), "unexpected", ERROR_WAIT_SECONDS),
    ],
)
async def test_each_telegram_error_sets_the_status_and_its_back_off(
    db_session, switches, sessions, response, code, wait
):
    fake = FakeTelegram()
    fake.fail["getUpdates"] = response
    poller = TelegramPoller()

    assert await _round(poller, fake) == wait
    assert (poller.status["state"], poller.status["error_code"]) == ("error", code)
    assert poller.status["description"] == response.json()["description"]

    del fake.fail["getUpdates"]
    await _round(poller, fake)
    assert (poller.status["state"], poller.status["error_code"]) == ("listening", None)


@pytest.mark.asyncio
async def test_after_an_error_polling_restarts_and_clears_the_webhook_again(
    db_session, switches, sessions
):
    fake = FakeTelegram()
    poller = TelegramPoller()
    await _round(poller, fake)
    fake.fail["getUpdates"] = _error(
        409, "Conflict: can't use getUpdates method while webhook is active"
    )
    await _round(poller, fake)
    del fake.fail["getUpdates"]
    fake.calls.clear()

    await _round(poller, fake)

    assert fake.calls[0][0] == "deleteWebhook"


@pytest.mark.asyncio
async def test_network_failures_back_off_doubling_to_a_cap_and_reset(
    db_session, switches, sessions
):
    fake = FakeTelegram()
    fake.fail["deleteWebhook"] = httpx.ConnectError("boom")
    poller = TelegramPoller()

    waits = [await _round(poller, fake)]
    since = poller.status["since"]
    waits += [await _round(poller, fake) for _ in range(5)]
    assert waits == [5.0, 10.0, 20.0, 40.0, 60.0, 60.0]
    assert poller.status["error_code"] == "unreachable"
    assert poller.status["since"] == since  # one outage, not six

    del fake.fail["deleteWebhook"]
    await _round(poller, fake)
    assert poller.status["state"] == "listening"
    # Polling is running now, so the next round goes straight to getUpdates.
    fake.fail["getUpdates"] = httpx.ConnectError("boom")
    assert await _round(poller, fake) == BACKOFF_START_SECONDS


@pytest.mark.asyncio
async def test_no_log_line_holds_the_token(db_session, switches, sessions, caplog, test_vehicle):
    caplog.set_level(logging.DEBUG)
    fake = FakeTelegram()
    poller = TelegramPoller()
    fake.fail["getUpdates"] = _error(401, "Unauthorized")
    await _round(poller, fake)
    del fake.fail["getUpdates"]
    await _round(poller, fake)
    fake.message(f"fuel {test_vehicle['vin']} 10000 40")
    # An exception whose own text holds the URL, as some httpx errors' do.
    fake.fail["sendMessage"] = httpx.ConnectError(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    )
    await _round(poller, fake)

    assert "TEST-token" not in caplog.text


# --- lifecycle ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_cancels_the_loop_and_closes_its_client(db_session, switches, sessions):
    await _set(db_session, "telegram_inbound_enabled", "false")
    fake = FakeTelegram()
    clients: list[httpx.AsyncClient] = []
    parked = asyncio.Event()

    def client_factory() -> httpx.AsyncClient:
        clients.append(fake.client())
        return clients[-1]

    async def sleep(seconds: float) -> None:
        parked.set()
        await asyncio.Event().wait()  # until cancelled

    poller = TelegramPoller()
    poller.client_factory = client_factory
    poller.sleep = sleep

    await poller.start()
    await asyncio.wait_for(parked.wait(), timeout=5)
    await poller.stop()

    assert len(clients) == 1
    assert clients[0].is_closed
    assert poller.status["state"] == "off"
