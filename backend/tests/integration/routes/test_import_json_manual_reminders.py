"""Reminders a person made, in the JSON backup (task 8, J5, K5, N-3, S6)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.maintenance_rule import MaintenanceRule
from app.models.reminder import Reminder
from tests.integration.routes._json_backup import V9, export_json, import_json, post_json

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _seed(db_session: AsyncSession, vin: str) -> None:
    """One manual reminder per status, plus rows that must not travel as manual."""
    rule = MaintenanceRule(vin=vin, title="Oil", interval_months=6, source="manual")
    db_session.add(rule)
    await db_session.flush()
    db_session.add_all(
        [
            Reminder(
                vin=vin,
                title="Registration",
                reminder_type="date",
                due_date=date(2027, 1, 31),
                status="pending",
                notes="online",
                snoozed_until=date(2026, 11, 1),
                start_odometer_km=Decimal("51000.00"),
                last_notified_at=datetime(2026, 10, 1, 8, 0),
                created_at=datetime(2026, 1, 5, 12, 0),
            ),
            Reminder(
                vin=vin,
                title="Wipers",
                reminder_type="mileage",
                due_mileage_km=Decimal("60000.50"),
                status="done",
                maintenance_type="wiper_blades",
                completed_at=datetime(2026, 4, 2, 15, 30),
                completed_date=date(2026, 4, 2),
                completed_odometer_km=Decimal("55000.00"),
                anchor_kind="completion",
                anchor_date=date(2025, 4, 2),
                created_at=datetime(2025, 4, 2, 9, 0),
            ),
            Reminder(
                vin=vin,
                title="Grease fifth wheel",
                reminder_type="hours",
                due_hours=Decimal("1250.5"),
                status="dismissed",
                start_hours=Decimal("1000.0"),
                created_at=datetime(2025, 9, 9, 7, 0),
            ),
            # Not manual: a rule's, the tire sync's and the brake sync's.
            Reminder(
                vin=vin,
                rule_id=rule.id,
                title="Oil",
                reminder_type="date",
                due_date=date(2027, 4, 1),
                status="pending",
            ),
            Reminder(
                vin=vin,
                source="low_tread",
                title="Tire tread low (FL)",
                reminder_type="date",
                due_date=date(2026, 12, 1),
                status="pending",
            ),
            Reminder(
                vin=vin,
                source="low_brakes_front",
                title="Front brake pads low",
                reminder_type="date",
                due_date=date(2026, 12, 1),
                status="pending",
            ),
        ]
    )
    await db_session.commit()


_SKIP = {"id", "vin", "updated_at", "last_notified_at"}


async def _manual(db_session: AsyncSession, vin: str) -> list[dict[str, Any]]:
    db_session.expire_all()
    rows = (
        (
            await db_session.execute(
                select(Reminder)
                .where(Reminder.vin == vin, Reminder.rule_id.is_(None), Reminder.source.is_(None))
                .order_by(Reminder.title)
            )
        )
        .scalars()
        .all()
    )
    return [
        {c.key: getattr(r, c.key) for c in r.__table__.columns if c.key not in _SKIP} for r in rows
    ]


def _row(**over: Any) -> dict[str, Any]:
    return {
        "title": "Wiper blades",
        "reminder_type": "date",
        "due_date": "2026-12-01",
        "status": "pending",
        **over,
    }


# -- J5 / K5: every status comes back -----------------------------------------


async def test_the_export_writes_only_reminders_a_person_made(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    vin = await new_vehicle()
    await _seed(db_session, vin)
    backup = await export_json(client, auth_headers, vin)
    # main: KeyError, no manual_reminders section.
    rows = backup["manual_reminders"]
    assert [r["title"] for r in rows] == ["Registration", "Wipers", "Grease fifth wheel"]
    assert rows[0]["created_at"] == "2026-01-05T12:00:00"
    for gone in ("last_notified_at", "rule_id", "source", "tire_id", "line_item_id"):
        assert gone not in rows[0], gone


async def test_every_status_round_trips(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    source = await new_vehicle()
    target = await new_vehicle()
    await _seed(db_session, source)
    data = await import_json(
        client,
        auth_headers,
        target,
        {
            **V9,
            "manual_reminders": (await export_json(client, auth_headers, source))[
                "manual_reminders"
            ],
        },
    )
    assert data["errors"] == []
    # Counted with the legacy reminders (T-4).
    # main: the section is never read, so 0.
    assert data["reminders"]["success_count"] == 3
    assert await _manual(db_session, target) == await _manual(db_session, source)


async def test_importing_the_same_file_twice_adds_none(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    vin = await new_vehicle()
    await _seed(db_session, vin)
    before = await _manual(db_session, vin)
    backup = {**V9, "manual_reminders": [_row(), _row(), _row(title="Plates")]}
    # The file's two identical rows both land in an empty slot (R5).
    first = await import_json(client, auth_headers, vin, backup)
    # main: the section is never read.
    assert first["reminders"]["success_count"] == 3
    again = await import_json(client, auth_headers, vin, backup)
    assert again["reminders"]["skipped_count"] == 3
    assert len(await _manual(db_session, vin)) == len(before) + 3


async def test_a_rule_reminder_with_the_same_title_is_not_spent(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    vin = await new_vehicle()
    rule = MaintenanceRule(vin=vin, title="Wiper blades", interval_months=12, source="manual")
    db_session.add(rule)
    await db_session.flush()
    db_session.add(
        Reminder(
            vin=vin,
            rule_id=rule.id,
            title="Wiper blades",
            reminder_type="date",
            due_date=date(2026, 12, 1),
            status="pending",
        )
    )
    await db_session.commit()
    data = await import_json(client, auth_headers, vin, {**V9, "manual_reminders": [_row()]})
    # main: 0, the section is never read.
    assert data["reminders"]["success_count"] == 1
    assert [r["title"] for r in await _manual(db_session, vin)] == ["Wiper blades"]


async def test_a_sync_reminder_with_the_same_title_is_not_spent(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    vin = await new_vehicle()
    db_session.add(
        Reminder(
            vin=vin,
            source="low_tread",
            title="Wiper blades",
            reminder_type="date",
            due_date=date(2026, 12, 1),
            status="pending",
        )
    )
    await db_session.commit()
    data = await import_json(client, auth_headers, vin, {**V9, "manual_reminders": [_row()]})
    # Without the source filter the tire sync's row is spent and this skips.
    assert data["reminders"]["success_count"] == 1
    assert [r["title"] for r in await _manual(db_session, vin)] == ["Wiper blades"]


#: Every key part filled, so changing any one of them is a different reminder.
_STORED = {
    "title": "Plates",
    "reminder_type": "both",
    "due_date": date(2026, 12, 1),
    "due_mileage_km": Decimal("60000.00"),
    "due_hours": Decimal("1250.5"),
    "status": "pending",
}
_FILE = {
    "title": "Plates",
    "reminder_type": "both",
    "due_date": "2026-12-01",
    "due_mileage_km": "60000.00",
    "due_hours": "1250.5",
    "status": "pending",
}


@pytest.mark.parametrize(
    ("stored", "row", "skipped"),
    [
        pytest.param({}, {}, True, id="same"),
        pytest.param({}, {"title": "Tags"}, False, id="title"),
        pytest.param({}, {"reminder_type": "date"}, False, id="reminder_type"),
        pytest.param({}, {"status": "done"}, False, id="status"),
        pytest.param({}, {"due_date": "2026-12-02"}, False, id="due_date"),
        pytest.param({}, {"due_mileage_km": "60001.00"}, False, id="due_mileage_km"),
        pytest.param({}, {"due_hours": "1250.0"}, False, id="due_hours"),
        # T-16: a part the file leaves out matches any stored value.
        pytest.param(
            {"reminder_type": "hours"},
            {"reminder_type": "hours", "due_date": None, "due_mileage_km": None},
            True,
            id="no-date-or-mileage-key",
        ),
        pytest.param(
            {"reminder_type": "date"},
            {"reminder_type": "date", "due_hours": None},
            True,
            id="no-hours-key",
        ),
    ],
)
async def test_the_key_compares_each_part_the_file_has(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    new_vehicle,
    stored: dict[str, Any],
    row: dict[str, Any],
    skipped: bool,
):
    vin = await new_vehicle()
    db_session.add(Reminder(vin=vin, **(_STORED | stored)))
    await db_session.commit()
    # A None here means the file leaves the key out.
    file_row = {k: v for k, v in (_FILE | row).items() if v is not None}
    data = await import_json(client, auth_headers, vin, {**V9, "manual_reminders": [file_row]})
    assert data["errors"] == []
    assert data["reminders"]["skipped_count"] == int(skipped)
    assert data["reminders"]["success_count"] == int(not skipped)


@pytest.mark.parametrize(
    ("column", "stored"), [("due_mileage_km", "60000.004"), ("due_hours", "1250.54")]
)
async def test_a_figure_stored_past_its_scale_still_matches(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    new_vehicle,
    column: str,
    stored: str,
):
    """A legacy SQLite row can hold places past the scale; it exports rounded (T-20).

    The ORM rounds at bind, so the figure goes in through raw SQL. PostgreSQL
    rounds it in the column, so there this passes either way.
    """
    vin = await new_vehicle()
    reminder = Reminder(vin=vin, **_STORED)
    db_session.add(reminder)
    await db_session.flush()
    await db_session.execute(
        text(f"UPDATE vehicle_reminders SET {column} = {stored} WHERE id = :id"),
        {"id": reminder.id},
    )
    await db_session.commit()
    data = await import_json(client, auth_headers, vin, {**V9, "manual_reminders": [_FILE]})
    # An exact compare misses the stored row and imports it again.
    assert data["reminders"]["skipped_count"] == 1, data


async def test_a_type_that_isnt_a_code_imports_as_none_with_a_warning(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    vin = await new_vehicle()
    data = await import_json(
        client,
        auth_headers,
        vin,
        {**V9, "manual_reminders": [_row(maintenance_type="Wiper Blades")]},
    )
    # main: no warning, nothing imported.
    assert data["warnings"] == [
        "Manual reminder 0: its maintenance type isn't a code, so it was saved without one"
    ]
    assert [r["maintenance_type"] for r in await _manual(db_session, vin)] == [None]


async def test_a_bad_row_is_its_own_error(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    vin = await new_vehicle()
    data = await import_json(
        client,
        auth_headers,
        vin,
        {
            **V9,
            "manual_reminders": [
                _row(status="snoozed"),
                _row(reminder_type="mileage", due_date=None),
                _row(title="Plates"),
            ],
        },
    )
    # main: no errors, the section is never read.
    assert data["errors"] == [
        "Manual reminder 0: status must be one of pending, done, dismissed",
        "Manual reminder 1: due_mileage_km required for this reminder type",
    ]
    assert data["reminders"]["error_count"] == 2
    assert [r["title"] for r in await _manual(db_session, vin)] == ["Plates"]


async def test_manual_reminders_that_is_not_a_list_refuses_the_file(
    client: AsyncClient, auth_headers, new_vehicle
):
    vin = await new_vehicle()
    response = await post_json(client, auth_headers, vin, {**V9, "manual_reminders": {"x": 1}})
    # main: the key isn't read, so the file imports.
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "manual_reminders must be a list of records"


async def test_a_legacy_reminders_section_beside_it_still_reads_description(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    # N-3: the v2 loop reads ["description"], so the v9 rows use their own section.
    vin = await new_vehicle()
    data = await import_json(
        client,
        auth_headers,
        vin,
        {
            **V9,
            "reminders": [{"description": "Old style", "due_date": "2026-12-01"}],
            "manual_reminders": [_row(title="New style")],
        },
    )
    assert data["errors"] == []
    # main: only the legacy row.
    assert sorted(r["title"] for r in await _manual(db_session, vin)) == ["New style", "Old style"]
