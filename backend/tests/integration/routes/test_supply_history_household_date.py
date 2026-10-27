"""The supply ledger puts every event on the household's calendar.

A purchase and a job usage carry a household date, but an adjustment's
created_at is naive UTC (a server default, UTC on both dialects). Compared
as stored, an adjustment logged just after household midnight in Kolkata
sorted before that morning's purchase and the balance read -1; in Chicago a
late-evening adjustment landed on the next day, after that day's purchase.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import Setting
from app.models.supply import SupplyUsage

pytestmark = [pytest.mark.integration, pytest.mark.asyncio, pytest.mark.supplies]


async def _household(
    db_session: AsyncSession, keep_rows: Callable[..., Awaitable[None]], zone: str
) -> None:
    await keep_rows("timezone")
    await db_session.execute(delete(Setting).where(Setting.key == "timezone"))
    db_session.add(Setting(key="timezone", value=zone))
    await db_session.commit()


async def _supply(client: AsyncClient, headers: dict[str, str], name: str) -> int:
    response = await client.post(
        "/api/supplies", json={"name": name, "unit_type": "count"}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _purchase(
    client: AsyncClient, headers: dict[str, str], sid: int, day: str, quantity: str = "1"
) -> None:
    response = await client.post(
        f"/api/supplies/{sid}/purchases", json={"date": day, "quantity": quantity}, headers=headers
    )
    assert response.status_code == 201, response.text


async def _adjustment_at(
    client: AsyncClient,
    headers: dict[str, str],
    db_session: AsyncSession,
    sid: int,
    stored_utc: datetime,
    quantity: str = "1",
) -> int:
    """Log an adjustment, then put its created_at at `stored_utc` (naive UTC, as stored)."""
    response = await client.post(
        f"/api/supplies/{sid}/adjustments", json={"quantity": quantity}, headers=headers
    )
    assert response.status_code == 201, response.text
    usage_id = response.json()["id"]
    await db_session.execute(
        update(SupplyUsage).where(SupplyUsage.id == usage_id).values(created_at=stored_utc)
    )
    await db_session.commit()
    return usage_id


async def _ledger(client: AsyncClient, headers: dict[str, str], sid: int) -> list[dict[str, Any]]:
    response = await client.get(f"/api/supplies/{sid}/history", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["entries"]


def _order(entries: list[dict[str, Any]]) -> list[tuple[str, float]]:
    return [(e["entry_type"], float(e["running_balance"])) for e in entries]


def _days(entries: list[dict[str, Any]]) -> list[str | None]:
    """The date the modal shows for each entry."""
    return [e.get("ledger_date") for e in entries]


async def test_kolkata_adjustment_after_midnight_follows_that_mornings_purchase(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    keep_rows: Callable[..., Awaitable[None]],
) -> None:
    # 19:00 UTC on Sep 1 is 00:30 on Sep 2 in Kolkata (+05:30).
    await _household(db_session, keep_rows, "Asia/Kolkata")
    sid = await _supply(client, auth_headers, "Kolkata filter")
    await _purchase(client, auth_headers, sid, "2026-09-02")
    stored = datetime(2026, 9, 1, 19, 0)
    await _adjustment_at(client, auth_headers, db_session, sid, stored)

    entries = await _ledger(client, auth_headers, sid)

    assert min(float(e["running_balance"]) for e in entries) >= 0
    assert _order(entries) == [("purchase", 1.0), ("usage", 0.0)]
    assert _days(entries) == ["2026-09-02", "2026-09-02"]
    # `at` is the real instant, labelled with the household's offset.
    at = datetime.fromisoformat(entries[1]["at"])
    assert at == stored.replace(tzinfo=UTC)
    assert at.utcoffset() == ZoneInfo("Asia/Kolkata").utcoffset(at.replace(tzinfo=None))


async def test_chicago_late_evening_adjustment_stays_before_the_next_days_purchase(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    keep_rows: Callable[..., Awaitable[None]],
) -> None:
    # 03:00 UTC on Sep 2 is 22:00 on Sep 1 in Chicago (CDT, -05:00).
    await _household(db_session, keep_rows, "America/Chicago")
    sid = await _supply(client, auth_headers, "Chicago filter")
    await _purchase(client, auth_headers, sid, "2026-08-30")
    await _adjustment_at(client, auth_headers, db_session, sid, datetime(2026, 9, 2, 3, 0))
    await _purchase(client, auth_headers, sid, "2026-09-02")

    entries = await _ledger(client, auth_headers, sid)

    assert min(float(e["running_balance"]) for e in entries) >= 0
    assert _order(entries) == [("purchase", 1.0), ("usage", 0.0), ("purchase", 1.0)]
    assert _days(entries) == ["2026-08-30", "2026-09-01", "2026-09-02"]


async def test_same_household_day_still_puts_the_purchase_first(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    keep_rows: Callable[..., Awaitable[None]],
) -> None:
    """Guard for the tie-break: a purchase dated the same household day sorts first.

    The adjustment is at 18:30 UTC, exactly household midnight in Kolkata, so its
    wall clock ties with the purchase's midnight and only the kind decides.
    """
    await _household(db_session, keep_rows, "Asia/Kolkata")
    sid = await _supply(client, auth_headers, "Tie filter")
    await _adjustment_at(client, auth_headers, db_session, sid, datetime(2026, 9, 1, 18, 30))
    await _purchase(client, auth_headers, sid, "2026-09-02")

    entries = await _ledger(client, auth_headers, sid)

    assert _order(entries) == [("purchase", 1.0), ("usage", 0.0)]
    assert _days(entries) == ["2026-09-02", "2026-09-02"]


async def test_chicago_fall_back_hour_keeps_adjustments_in_real_order(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    keep_rows: Callable[..., Awaitable[None]],
) -> None:
    # Nov 1 is the fall-back: 06:45 UTC is 01:45 CDT, 07:15 UTC is 01:15 CST.
    # The later one has the earlier wall clock, so a wall-clock sort flips them.
    await _household(db_session, keep_rows, "America/Chicago")
    sid = await _supply(client, auth_headers, "Fall-back filter")
    await _purchase(client, auth_headers, sid, "2026-10-31", quantity="3")
    later = await _adjustment_at(
        client, auth_headers, db_session, sid, datetime(2026, 11, 1, 7, 15), quantity="2"
    )
    earlier = await _adjustment_at(
        client, auth_headers, db_session, sid, datetime(2026, 11, 1, 6, 45), quantity="1"
    )

    entries = await _ledger(client, auth_headers, sid)

    assert [e["id"] for e in entries[1:]] == [earlier, later]
    assert _order(entries) == [("purchase", 3.0), ("usage", 2.0), ("usage", 0.0)]
    assert [datetime.fromisoformat(e["at"]) for e in entries[1:]] == [
        datetime(2026, 11, 1, 6, 45, tzinfo=UTC),
        datetime(2026, 11, 1, 7, 15, tzinfo=UTC),
    ]
