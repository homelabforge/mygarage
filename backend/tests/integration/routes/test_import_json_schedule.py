"""Maintenance rules and their reminders in the JSON backup (task 7, J5, K1, K2, N-1, N-8, S8).

Reconcile rebuilds a rule's reminder only from typed service history (N-1),
so each K1 case below would fall back to a baseline on the import day. Every
reminder travels under its rule instead, and keeps its due point through the
import and a reconcile after it.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ServiceLineItem, ServiceVisit
from app.models.maintenance_rule import MaintenanceRule
from app.models.reminder import Reminder
from tests.integration.routes._json_backup import V9, export_json, import_json

# No asyncio mark: auto mode marks the async tests, and the sync ones would warn.
pytestmark = [pytest.mark.integration]


async def _post(client: AsyncClient, headers, url: str, body: dict[str, Any]) -> dict[str, Any]:
    response = await client.post(url, headers=headers, json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()


async def _pending_id(db_session: AsyncSession, vin: str, rule_title: str) -> int:
    db_session.expire_all()
    return (
        await db_session.execute(
            select(Reminder.id)
            .join(MaintenanceRule, Reminder.rule_id == MaintenanceRule.id)
            .where(
                Reminder.vin == vin,
                MaintenanceRule.title == rule_title,
                Reminder.status == "pending",
            )
        )
    ).scalar_one()


async def _complete(client: AsyncClient, headers, vin: str, reminder_id: int, **body: Any) -> None:
    await _post(
        client,
        headers,
        f"/api/vehicles/{vin}/reminders/{reminder_id}/complete",
        {"mode": "mark_only", **body},
    )


async def _reconcile(client: AsyncClient, headers, vin: str) -> None:
    response = await client.post(f"/api/vehicles/{vin}/reminders/reconcile", headers=headers)
    assert response.status_code == 200, response.text


async def _schedule(db_session: AsyncSession, vin: str) -> list[tuple[Any, ...]]:
    """Every rule reminder's due point and what it counts from, by rule title.

    The anchor's kind is left out: a service anchor comes back as a
    completion on the same day and readings (S8).
    """
    db_session.expire_all()
    rows = await db_session.execute(
        select(MaintenanceRule, Reminder)
        .join(Reminder, Reminder.rule_id == MaintenanceRule.id)
        .where(MaintenanceRule.vin == vin)
    )
    return sorted(
        (
            rule.title,
            rule.maintenance_type,
            rule.is_active,
            reminder.title,
            reminder.notes,
            reminder.status,
            reminder.reminder_type,
            reminder.due_date,
            reminder.due_mileage_km,
            reminder.due_hours,
            reminder.anchor_date,
            reminder.anchor_odometer_km,
            reminder.completed_date,
            reminder.completed_odometer_km,
        )
        for rule, reminder in rows.all()
    )


async def _round_trip(
    client: AsyncClient, headers, db_session: AsyncSession, source: str, target: str
) -> dict[str, Any]:
    """Export the source, import into the target, reconcile both."""
    await _reconcile(client, headers, source)
    data = await import_json(client, headers, target, await export_json(client, headers, source))
    await _reconcile(client, headers, target)
    return data


# -- K1: each reminder keeps its due point through import and reconcile ----------


async def test_a_mark_done_completion_keeps_its_due_point(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    source = await new_vehicle()
    target = await new_vehicle()
    await _post(
        client,
        auth_headers,
        f"/api/vehicles/{source}/reminders",
        {
            "title": "Oil change",
            "maintenance_type": "engine_oil_filter",
            "recurrence": {"interval_months": 6, "interval_km": 8000},
        },
    )
    first = await _pending_id(db_session, source, "Oil change")
    # Marked done in March with no service record: the successor counts from it.
    await _complete(
        client, auth_headers, source, first, completed_date="2026-03-01", odometer_km=50000
    )
    successor = await _pending_id(db_session, source, "Oil change")
    renamed = await client.put(
        f"/api/vehicles/{source}/reminders/{successor}",
        headers=auth_headers,
        json={"title": "Oil change (synthetic)", "notes": "5W-30"},
    )
    assert renamed.status_code == 200, renamed.text

    data = await _round_trip(client, auth_headers, db_session, source, target)

    assert data["maintenance_rules"]["success_count"] == 1
    expected = await _schedule(db_session, source)
    # The rename reached the rule too; the done one keeps the old title.
    assert ("Oil change (synthetic)", "engine_oil_filter", True, "Oil change (synthetic)", "5W-30", "pending",
            "smart", date(2026, 9, 1), Decimal("58000.00"), None, date(2026, 3, 1),
            Decimal("50000.00"), None, None) in expected  # fmt: skip
    # main: no rule section, so the target has no schedule at all.
    assert await _schedule(db_session, target) == expected


async def test_a_typed_last_done_anchor_keeps_its_due_point(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    source = await new_vehicle()
    target = await new_vehicle()
    # "Last done" typed into the form: an anchor with no done reminder behind it.
    await _post(
        client,
        auth_headers,
        f"/api/vehicles/{source}/reminders",
        {
            "title": "Coolant flush",
            "recurrence": {"interval_months": 24},
            "anchor": {"date": "2025-06-15", "odometer_km": 30000},
        },
    )

    await _round_trip(client, auth_headers, db_session, source, target)

    expected = await _schedule(db_session, source)
    assert [(row[5], row[7], row[10]) for row in expected] == [
        ("pending", date(2027, 6, 15), date(2025, 6, 15))
    ]
    # main: nothing imported.
    assert await _schedule(db_session, target) == expected


async def test_a_typeless_rule_on_a_service_keeps_its_due_point(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    source = await new_vehicle()
    target = await new_vehicle()
    visit = ServiceVisit(
        vin=source,
        date=date(2026, 2, 10),
        odometer_km=Decimal("41000.00"),
        service_category="Maintenance",
    )
    db_session.add(visit)
    await db_session.flush()
    item = ServiceLineItem(visit_id=visit.id, description="Check the awning seals")
    db_session.add(item)
    await db_session.commit()
    # No type: reconcile never reads typed history for it (N-1).
    await _post(
        client,
        auth_headers,
        f"/api/vehicles/{source}/reminders",
        {
            "title": "Check the awning seals",
            "line_item_id": item.id,
            "recurrence": {"interval_months": 12},
        },
    )

    await _round_trip(client, auth_headers, db_session, source, target)

    expected = await _schedule(db_session, source)
    assert [(row[1], row[7], row[10], row[11]) for row in expected] == [
        (None, date(2027, 2, 10), date(2026, 2, 10), Decimal("41000.00"))
    ]
    # main: nothing imported. Without S8 the line-item link drops and reconcile
    # re-anchors on a baseline at the import day.
    assert await _schedule(db_session, target) == expected
    anchor_kinds = (
        (
            await db_session.execute(
                select(Reminder.anchor_kind).where(
                    Reminder.vin == target, Reminder.status == "pending"
                )
            )
        )
        .scalars()
        .all()
    )
    assert anchor_kinds == ["completion"]


async def test_two_rules_of_one_type_keep_their_own_due_points(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    source = await new_vehicle()
    target = await new_vehicle()
    rules_url = f"/api/vehicles/{source}/maintenance-rules"
    await _post(
        client,
        auth_headers,
        rules_url,
        {"title": "Rotate (summer)", "maintenance_type": "tire_rotation", "interval_months": 6},
    )
    await _post(
        client,
        auth_headers,
        rules_url,
        {
            "title": "Rotate (winter)",
            "maintenance_type": "tire_rotation",
            "interval_months": 12,
            "interval_km": 10000,
        },
    )
    summer = await _pending_id(db_session, source, "Rotate (summer)")
    winter = await _pending_id(db_session, source, "Rotate (winter)")
    await _complete(
        client, auth_headers, source, summer, completed_date="2026-04-01", odometer_km=20000
    )
    await _complete(
        client, auth_headers, source, winter, completed_date="2025-11-01", odometer_km=15000
    )
    # A newer typed rotation. Two rules of the type ignore typed history, so it
    # moves neither; one merged rule would count from it.
    visit = ServiceVisit(
        vin=source,
        date=date(2026, 5, 1),
        odometer_km=Decimal("21000.00"),
        service_category="Maintenance",
    )
    db_session.add(visit)
    await db_session.flush()
    db_session.add(
        ServiceLineItem(
            visit_id=visit.id, description="Rotate tires", maintenance_type="tire_rotation"
        )
    )
    await db_session.commit()

    data = await _round_trip(client, auth_headers, db_session, source, target)

    assert data["maintenance_rules"]["success_count"] == 2
    expected = await _schedule(db_session, source)
    pending = {row[0]: (row[7], row[8]) for row in expected if row[5] == "pending"}
    assert pending == {
        "Rotate (summer)": (date(2026, 10, 1), None),
        "Rotate (winter)": (date(2026, 11, 1), Decimal("25000.00")),
    }
    # main: nothing imported.
    assert await _schedule(db_session, target) == expected


async def _completed_line_item(db_session: AsyncSession, vin: str) -> ServiceLineItem:
    """The line item the vehicle's one done reminder was completed by."""
    db_session.expire_all()
    return (
        await db_session.execute(
            select(ServiceLineItem)
            .join(Reminder, Reminder.completed_line_item_id == ServiceLineItem.id)
            .where(Reminder.vin == vin, Reminder.status == "done")
        )
    ).scalar_one()


async def test_a_completion_whose_visit_moved_counts_from_the_visit(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    source = await new_vehicle()
    target = await new_vehicle()
    await _post(
        client,
        auth_headers,
        f"/api/vehicles/{source}/reminders",
        {"title": "Wax", "recurrence": {"interval_months": 12}},
    )
    pending = await _pending_id(db_session, source, "Wax")
    # The default mode writes a visit and links the done reminder to it.
    await _post(
        client,
        auth_headers,
        f"/api/vehicles/{source}/reminders/{pending}/complete",
        {"mode": "create_visit", "completed_date": "2026-06-01", "odometer_km": 50000},
    )
    item = await _completed_line_item(db_session, source)
    # A typo fixed later: it was May. The done row's own snapshot still says June.
    moved = await client.put(
        f"/api/vehicles/{source}/service-visits/{item.visit_id}",
        headers=auth_headers,
        json={"date": "2026-05-01"},
    )
    assert moved.status_code == 200, moved.text

    await _round_trip(client, auth_headers, db_session, source, target)

    expected = await _schedule(db_session, source)
    assert [(row[5], row[7]) for row in expected if row[5] == "pending"] == [
        ("pending", date(2027, 5, 1))
    ]
    got = await _schedule(db_session, target)
    # main: the stale June snapshot completes the pending one again on reconcile,
    # leaving a phantom done row and a successor due 2027-06-01.
    assert [row for row in got if row[5] == "pending"] == [
        row for row in expected if row[5] == "pending"
    ]
    assert [(row[5], row[12]) for row in got if row[5] == "done"] == [("done", date(2026, 5, 1))]


async def test_a_completion_retyped_away_stays_out_of_the_rules_history(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    source = await new_vehicle()
    target = await new_vehicle()
    await _post(
        client,
        auth_headers,
        f"/api/vehicles/{source}/reminders",
        {
            "title": "Oil change",
            "maintenance_type": "engine_oil_filter",
            "recurrence": {"interval_months": 6},
        },
    )
    pending = await _pending_id(db_session, source, "Oil change")
    await _post(
        client,
        auth_headers,
        f"/api/vehicles/{source}/reminders/{pending}/complete",
        {"mode": "create_visit", "completed_date": "2026-03-01", "odometer_km": 50000},
    )
    # That work turned out to be a rotation: it's no longer this rule's history,
    # so the source counts from a baseline today.
    item = await _completed_line_item(db_session, source)
    item.maintenance_type = "tire_rotation"
    await db_session.commit()

    await _round_trip(client, auth_headers, db_session, source, target)

    expected = await _schedule(db_session, source)
    pending_rows = [row for row in expected if row[5] == "pending"]
    assert len(pending_rows) == 1
    assert pending_rows[0][7] != date(2026, 9, 1)
    got = await _schedule(db_session, target)
    # main: the done row still says engine_oil_filter, so the target counts
    # from it and the pending one falls due 2026-09-01.
    assert [row for row in got if row[5] == "pending"] == pending_rows
    assert len(got) == len(expected)


@pytest.mark.parametrize(
    ("own", "rule_type", "item_type", "written"),
    [
        # Its own type already rules it out, and that check runs first.
        ("engine_oil_filter", "tire_rotation", "tire_rotation", "engine_oil_filter"),
        # The item was retyped away: the item's type rules it out.
        ("engine_oil_filter", "engine_oil_filter", "tire_rotation", "tire_rotation"),
        # An untyped item rules nothing out.
        ("engine_oil_filter", "engine_oil_filter", None, "engine_oil_filter"),
        # A typeless rule reads no type at all.
        (None, None, "tire_rotation", "tire_rotation"),
    ],
)
def test_a_done_reminder_carries_the_type_its_rule_reads(
    own: str | None, rule_type: str | None, item_type: str | None, written: str | None
):
    from app.routes.export import _rule_reminder_json

    rule = MaintenanceRule(id=1, title="Oil", maintenance_type=rule_type, source="manual")
    visit = ServiceVisit(
        id=2, date=date(2026, 5, 1), odometer_km=Decimal("41000.00"), engine_hours=Decimal("812.5")
    )
    item = ServiceLineItem(id=3, visit_id=2, description="Oil", maintenance_type=item_type)
    done = Reminder(
        title="Oil",
        reminder_type="date",
        status="done",
        maintenance_type=own,
        completed_date=date(2026, 6, 1),
        completed_line_item_id=3,
    )
    row = _rule_reminder_json(done, rule, {3: (item, visit)})
    assert (
        row["maintenance_type"],
        row["completed_date"],
        row["completed_odometer_km"],
        row["completed_hours"],
    ) == (written, "2026-05-01", 41000.0, 812.5)
    # A pending one keeps what it has; only `_latest_completion` reads the done ones.
    pending = Reminder(title="Oil", reminder_type="date", status="pending", maintenance_type=own)
    pending.completed_line_item_id = 3
    assert _rule_reminder_json(pending, rule, {3: (item, visit)})["maintenance_type"] == own


async def test_a_done_reminder_linked_to_another_vehicles_work_keeps_its_snapshot(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    vin = await new_vehicle()
    other = await new_vehicle()
    visit = ServiceVisit(
        vin=other,
        date=date(2026, 5, 1),
        odometer_km=Decimal("9.00"),
        service_category="Maintenance",
    )
    db_session.add(visit)
    await db_session.flush()
    item = ServiceLineItem(visit_id=visit.id, description="Wax")
    rule = MaintenanceRule(vin=vin, title="Wax", interval_months=12, source="manual")
    db_session.add_all([item, rule])
    await db_session.flush()
    db_session.add(
        Reminder(
            vin=vin,
            rule_id=rule.id,
            title="Wax",
            reminder_type="date",
            due_date=date(2026, 6, 1),
            status="done",
            completed_date=date(2026, 6, 1),
            completed_line_item_id=item.id,
        )
    )
    await db_session.commit()

    [done] = (await export_json(client, auth_headers, vin))["maintenance_rules"][0]["reminders"]
    # `_latest_completion` only reads this vehicle's work, so neither does the export.
    assert done["completed_date"] == "2026-06-01"


#: Every reminder column the backup carries (K5).
_REMINDER_COLUMNS = (
    "title",
    "reminder_type",
    "due_date",
    "due_mileage_km",
    "due_hours",
    "status",
    "notes",
    "snoozed_until",
    "maintenance_type",
    "anchor_kind",
    "anchor_date",
    "anchor_odometer_km",
    "anchor_hours",
    "start_odometer_km",
    "start_hours",
    "completed_at",
    "completed_date",
    "completed_odometer_km",
    "completed_hours",
    "created_at",
)
_RULE_COLUMNS = (
    "maintenance_type",
    "title",
    "interval_km",
    "interval_months",
    "interval_days",
    "interval_hours",
    "source",
    "source_pack_id",
    "source_pack_key",
    "notes",
    "is_active",
)


async def _columns(db_session: AsyncSession, vin: str) -> list[tuple[Any, ...]]:
    """Each rule's columns with its reminders' columns, in file order."""
    db_session.expire_all()
    rules = await _rules(db_session, vin)
    out: list[tuple[Any, ...]] = []
    for rule in sorted(rules, key=lambda r: r.id):
        reminders = (
            (
                await db_session.execute(
                    select(Reminder).where(Reminder.rule_id == rule.id).order_by(Reminder.id)
                )
            )
            .scalars()
            .all()
        )
        out.append(
            (
                tuple(getattr(rule, name) for name in _RULE_COLUMNS),
                [tuple(getattr(r, name) for name in _REMINDER_COLUMNS) for r in reminders],
            )
        )
    return out


async def test_every_rule_and_reminder_column_comes_back(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    source = await new_vehicle()
    target = await new_vehicle()
    # Inactive, so neither reconcile touches it and every column reads back as written.
    rule = MaintenanceRule(
        vin=source,
        maintenance_type="generator_service",
        title="Generator",
        interval_months=12,
        interval_hours=Decimal("150.0"),
        source="pack",
        source_pack_id="builtin:rv",
        source_pack_key="generator",
        notes="Onan",
        is_active=False,
    )
    db_session.add(rule)
    await db_session.flush()
    db_session.add_all(
        [
            Reminder(
                vin=source,
                rule_id=rule.id,
                title="Generator (last)",
                reminder_type="hours",
                due_hours=Decimal("300.0"),
                status="done",
                notes="done at the rally",
                maintenance_type="generator_service",
                anchor_kind="completion",
                anchor_date=date(2025, 4, 1),
                anchor_hours=Decimal("150.0"),
                start_odometer_km=Decimal("12000.00"),
                start_hours=Decimal("140.0"),
                completed_at=datetime(2026, 4, 2, 15, 30),
                completed_date=date(2026, 4, 1),
                completed_odometer_km=Decimal("14000.00"),
                completed_hours=Decimal("298.5"),
                created_at=datetime(2025, 4, 1, 8, 0),
            ),
            Reminder(
                vin=source,
                rule_id=rule.id,
                title="Generator",
                reminder_type="both",
                due_date=date(2027, 4, 1),
                due_mileage_km=Decimal("20000.00"),
                status="pending",
                snoozed_until=date(2026, 12, 1),
                maintenance_type="generator_service",
                anchor_kind="baseline",
                anchor_date=date(2026, 4, 1),
                anchor_odometer_km=Decimal("14000.00"),
                created_at=datetime(2026, 4, 2, 15, 30),
            ),
        ]
    )
    await db_session.commit()

    await _round_trip(client, auth_headers, db_session, source, target)

    expected = await _columns(db_session, source)
    assert len(expected[0][1]) == 2
    # main: nothing imported.
    assert await _columns(db_session, target) == expected


# -- J5 / K2: the rules skip as a family ---------------------------------------


def _rule(**over: Any) -> dict[str, Any]:
    return {
        "maintenance_type": "engine_oil_filter",
        "title": "Oil",
        "interval_km": None,
        "interval_months": 6,
        "interval_days": None,
        "interval_hours": None,
        "source": "pack",
        "source_pack_id": "builtin:gas-car",
        "source_pack_key": "oil",
        "notes": None,
        "is_active": True,
        "reminders": [
            {
                "title": "Oil",
                "reminder_type": "date",
                "due_date": "2026-12-01",
                "status": "pending",
                "maintenance_type": "engine_oil_filter",
                "anchor_kind": "completion",
                "anchor_date": "2026-06-01",
                "created_at": "2026-06-01T09:30:00",
            }
        ],
        **over,
    }


async def _rules(db_session: AsyncSession, vin: str) -> list[MaintenanceRule]:
    db_session.expire_all()
    return list(
        (await db_session.execute(select(MaintenanceRule).where(MaintenanceRule.vin == vin)))
        .scalars()
        .all()
    )


async def test_a_rule_keeps_its_pack_link_and_its_reminder_its_created_at(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    vin = await new_vehicle()
    data = await import_json(client, auth_headers, vin, {**V9, "maintenance_rules": [_rule()]})
    assert data["errors"] == []
    [rule] = await _rules(db_session, vin)
    # main: nothing imported.
    assert (rule.source, rule.source_pack_id, rule.source_pack_key) == (
        "pack",
        "builtin:gas-car",
        "oil",
    )
    [reminder] = (
        (await db_session.execute(select(Reminder).where(Reminder.rule_id == rule.id)))
        .scalars()
        .all()
    )
    assert reminder.created_at.isoformat() == "2026-06-01T09:30:00"
    assert reminder.due_date == date(2026, 12, 1)


async def test_an_inactive_rule_on_the_target_skips_the_files_rules(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    vin = await new_vehicle()
    db_session.add(
        MaintenanceRule(vin=vin, title="Old", interval_days=30, source="manual", is_active=False)
    )
    await db_session.commit()
    data = await import_json(client, auth_headers, vin, {**V9, "maintenance_rules": [_rule()]})
    # main: no warning; the section is never read.
    assert data["warnings"] == [
        "Maintenance rules: this vehicle already has maintenance rules, "
        "so the file's rules and their reminders weren't imported"
    ]
    assert data["maintenance_rules"]["skipped_count"] == 1
    assert [r.title for r in await _rules(db_session, vin)] == ["Old"]


async def test_an_unknown_anchor_kind_imports_as_none(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    vin = await new_vehicle()
    rule = _rule()
    rule["reminders"][0]["anchor_kind"] = "guess"
    data = await import_json(client, auth_headers, vin, {**V9, "maintenance_rules": [rule]})
    assert data["errors"] == []
    kinds = (
        (await db_session.execute(select(Reminder.anchor_kind).where(Reminder.vin == vin)))
        .scalars()
        .all()
    )
    # main: no reminder at all.
    assert kinds == [None]


async def test_a_reminder_type_that_isnt_a_code_is_dropped_with_a_warning(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    vin = await new_vehicle()
    rule = _rule()
    rule["reminders"][0]["maintenance_type"] = "Oil Change"
    data = await import_json(client, auth_headers, vin, {**V9, "maintenance_rules": [rule]})
    assert data["errors"] == []
    # main: no rule section, so no warning either.
    assert data["warnings"] == [
        "Maintenance rule 0, reminder 0: its maintenance type isn't a code, "
        "so it was saved without one"
    ]
    types = (
        (await db_session.execute(select(Reminder.maintenance_type).where(Reminder.vin == vin)))
        .scalars()
        .all()
    )
    assert types == [None]


_PENDING = _rule()["reminders"][0]

_REFUSED = [
    pytest.param(
        [_rule(reminders=[_PENDING, {**_PENDING, "due_date": "2027-01-01"}])],
        "Maintenance rule 0: has more than one pending reminder",
        id="two-pending",
    ),
    pytest.param(
        [_rule(interval_months=None)],
        "Maintenance rule 0: recurrence needs at least one interval",
        id="no-interval",
    ),
    pytest.param(
        [_rule(interval_km=5000, interval_hours=100)],
        "Maintenance rule 0: recurrence may use a distance or an hours interval, not both",
        id="km-and-hours",
    ),
    pytest.param(
        [_rule(is_active="yes")],
        "Maintenance rule 0: is_active must be true or false",
        id="is-active-word",
    ),
    pytest.param(
        [_rule(interval_days=0)],
        "Maintenance rule 0: interval_days must be more than 0, not 0",
        id="interval-bound",
    ),
    pytest.param(
        [_rule(source="import")],
        "Maintenance rule 0: source must be one of pack, manual, service",
        id="source-word",
    ),
    pytest.param(
        [_rule(maintenance_type="Oil Change")],
        "Maintenance rule 0: maintenance_type must be a lowercase snake_case code (2-50 chars)",
        id="type-not-a-code",
    ),
    pytest.param(
        [_rule(reminders={"title": "x"})],
        "Maintenance rule 0: reminders must be a list",
        id="reminders-not-a-list",
    ),
    pytest.param(
        [_rule(reminders=[{**_PENDING, "status": "snoozed"}])],
        "Maintenance rule 0, reminder 0: status must be one of pending, done, dismissed",
        id="status-word",
    ),
    pytest.param(
        [_rule(reminders=[{**_PENDING, "due_date": None}])],
        "Maintenance rule 0, reminder 0: due_date required for this reminder type",
        id="reminder-state",
    ),
    pytest.param(
        [_rule(reminders=[{**_PENDING, "anchor_odometer_km": -1}])],
        "Maintenance rule 0, reminder 0: anchor_odometer_km must be at least 0, not -1",
        id="anchor-bound",
    ),
    pytest.param(
        [_rule(reminders=[{**_PENDING, "status": "done", "completed_hours": -1}])],
        "Maintenance rule 0, reminder 0: completed_hours must be at least 0, not -1",
        id="completed-bound",
    ),
]


@pytest.mark.parametrize(("rules", "reason"), _REFUSED)
async def test_a_bad_rule_refuses_the_family_and_writes_nothing(
    rules: list[dict[str, Any]],
    reason: str,
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    new_vehicle,
):
    vin = await new_vehicle()
    good = _rule(title="Brakes", maintenance_type="brake_fluid")
    data = await import_json(client, auth_headers, vin, {**V9, "maintenance_rules": [*rules, good]})
    # main: the section is never read.
    assert data["errors"] == [f"{reason}, so the file's rules and their reminders weren't imported"]
    assert data["maintenance_rules"]["error_count"] == len(rules) + 1
    assert await _rules(db_session, vin) == []
