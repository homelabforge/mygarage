"""A stored vocabulary value the app doesn't know reads as unknown, not a 500.

No CHECK holds these eight columns, so a restored backup, a hand edit or a
downgrade can leave anything in them, and a strict Literal on the way out turns
that one row into a 500 for every page that lists it. The plain `str` copies
don't 500, they just carry the junk to the UI. So each test writes a good row
of its own, breaks one column with raw SQL (the API refuses the bad value), and
reads it back through the real route: the field comes back null (the two
statuses: "unknown"), with one WARNING.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import date
from typing import Any

import fitz  # PyMuPDF
import pytest
import pytest_asyncio
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice
from app.models.livelink_topic_map import LiveLinkTopicMap
from app.models.maintenance_rule import MaintenanceRule
from app.models.reminder import Reminder
from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit
from app.models.tire import Tire
from app.utils import lenient_vocab
from tests.integration.routes._legacy_reads import read_ok

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

DAY = date(2020, 1, 1)
LOGGER = "app.utils.lenient_vocab"


@pytest_asyncio.fixture(autouse=True)
async def _fresh_warn_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts with nothing warned about yet, so "one WARNING" holds
    whatever ran before it in this process."""
    monkeypatch.setattr(lenient_vocab, "_warned", set())


async def _corrupt(
    db: AsyncSession, table: str, column: str, bad: str, *, key: str, value: object
) -> None:
    """Write `bad` into one stored row behind the ORM's back.

    The table and column names are this file's own constants, never input.
    """
    await db.execute(
        text(f"UPDATE {table} SET {column} = :bad WHERE {key} = :value"),
        {"bad": bad, "value": value},
    )
    await db.commit()
    # The session keeps loaded rows across commits, so without this the route
    # would read the good value back out of the identity map.
    db.expire_all()


def _warnings(caplog: pytest.LogCaptureFixture, model: str, field: str) -> list[str]:
    """The lenient reader's WARNINGs about one field."""
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER
        and record.levelno == logging.WARNING
        and f" {model}.{field} " in record.getMessage()
    ]


def _assert_one_warning(caplog: pytest.LogCaptureFixture, model: str, field: str, bad: str) -> str:
    """Exactly one WARNING about the field, naming the bad value. Returns it."""
    found = _warnings(caplog, model, field)
    assert len(found) == 1, found
    assert repr(bad) in found[0], found[0]
    return found[0]


# --- vehicles: the Literal fields and their plain-text copies -----------------


def _mine(rows: list[dict[str, Any]], vin: str) -> dict[str, Any]:
    (row,) = [row for row in rows if row["vin"] == vin]
    return row


VehicleRead = Callable[[Any, str], dict[str, Any]]

VEHICLE_READS: list[Any] = [
    # (column, bad value, response model, url, how to find the vehicle in the body)
    *[
        pytest.param(column, bad, model, url, pick, id=f"{model}.{column}")
        for column, bad in (("vehicle_type", "Hovercraft"), ("usage_unit", "furlongs"))
        for model, url, pick in (
            (
                "VehicleResponse",
                "/api/vehicles?limit=500",
                lambda body, vin: _mine(body["vehicles"], vin),
            ),
            ("VehicleResponse", "/api/vehicles/{vin}", lambda body, vin: body),
            (
                "VehicleStatistics",
                "/api/dashboard",
                lambda body, vin: _mine(body["vehicles"], vin),
            ),
            (
                "QuickEntryVehicle",
                "/api/quick-entry/vehicles",
                lambda body, vin: _mine(body["vehicles"], vin),
            ),
        )
    ],
    pytest.param(
        "usage_unit",
        "furlongs",
        "VehicleDetailStats",
        "/api/vehicles/{vin}/detail-stats",
        lambda body, vin: body,
        id="VehicleDetailStats.usage_unit",
    ),
    pytest.param(
        "vehicle_type",
        "Hovercraft",
        "VehicleAnalytics",
        "/api/analytics/vehicles/{vin}",
        lambda body, vin: body,
        id="VehicleAnalytics.vehicle_type",
    ),
]


@pytest.mark.parametrize(("column", "bad", "model", "url", "pick"), VEHICLE_READS)
async def test_a_vehicle_column_outside_its_vocabulary_reads_as_null(
    client, auth_headers, db_session, own_vehicle, caplog, column, bad, model, url, pick
):
    vin = own_vehicle.vin
    await _corrupt(db_session, "vehicles", column, bad, key="vin", value=vin)
    caplog.set_level(logging.WARNING, logger=LOGGER)

    body = await read_ok(client, auth_headers, url.format(vin=vin))

    assert pick(body, vin)[column] is None
    _assert_one_warning(caplog, model, column, bad)


async def test_the_analytics_pdf_of_a_vehicle_with_an_unknown_type_still_exports(
    client, auth_headers, db_session, own_vehicle
):
    """The export is a StreamingResponse with no response model, so the
    meta-test can't see it: it dumps VehicleAnalytics and hands the null type
    to the PDF banner."""
    vin = own_vehicle.vin
    await _corrupt(db_session, "vehicles", "vehicle_type", "Hovercraft", key="vin", value=vin)

    response = await client.get(f"/api/analytics/vehicles/{vin}/export", headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    with fitz.open(stream=response.content, filetype="pdf") as doc:
        text = "".join(page.get_text() for page in doc)
    assert "Unknown" in text
    assert "Hovercraft" not in text


# --- LiveLink devices: the two statuses read as "unknown" ---------------------


def _device_id() -> str:
    # Fits livelink_devices.device_id (VARCHAR(20)) on PostgreSQL.
    return "lenient" + uuid.uuid4().hex[:12]


async def _drop_device(db: AsyncSession, device_id: str) -> None:
    await db.rollback()
    await db.execute(delete(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id))
    await db.commit()


@pytest.mark.parametrize("column", ["ecu_status", "device_status"])
async def test_a_device_status_outside_its_vocabulary_reads_as_unknown(
    client, auth_headers, db_session, caplog, column
):
    device_id = _device_id()
    device = LiveLinkDevice(device_id=device_id, ecu_status="online", device_status="online")
    db_session.add(device)
    await db_session.commit()
    row_id = device.id
    try:
        await _corrupt(
            db_session, "livelink_devices", column, "melted", key="device_id", value=device_id
        )
        caplog.set_level(logging.WARNING, logger=LOGGER)

        listed = await read_ok(client, auth_headers, "/api/livelink/devices")

        (mine,) = [entry for entry in listed["devices"] if entry["device_id"] == device_id]
        assert mine[column] == "unknown"
        # The device's id is validated before its statuses, so the log names it.
        assert f"id={row_id}" in _assert_one_warning(
            caplog, "LiveLinkDeviceResponse", column, "melted"
        )
    finally:
        await _drop_device(db_session, device_id)


# ecu_status only: the vehicle status's device_status is computed from
# `online` now (R7), so a stored value never reaches it. A stored 'melted' just
# isn't online, and reads 'offline'.
@pytest.mark.parametrize("column", ["ecu_status"])
async def test_a_vehicle_livelink_status_outside_its_vocabulary_reads_as_unknown(
    client, auth_headers, db_session, own_vehicle, caplog, column
):
    vin = own_vehicle.vin
    device_id = _device_id()
    db_session.add(
        LiveLinkDevice(device_id=device_id, vin=vin, ecu_status="online", device_status="online")
    )
    await db_session.commit()
    try:
        await _corrupt(
            db_session, "livelink_devices", column, "melted", key="device_id", value=device_id
        )
        caplog.set_level(logging.WARNING, logger=LOGGER)

        status = await read_ok(client, auth_headers, f"/api/vehicles/{vin}/livelink/status")

        assert status["device_id"] == device_id
        assert status[column] == "unknown"
        _assert_one_warning(caplog, "VehicleLiveLinkStatus", column, "melted")
    finally:
        await _drop_device(db_session, device_id)


async def test_a_torque_source_status_outside_its_vocabulary_reads_as_unknown(
    client, auth_headers, db_session, own_vehicle, caplog
):
    vin = own_vehicle.vin
    device_id = _device_id()
    db_session.add(
        LiveLinkDevice(device_id=device_id, kind="torque", vin=vin, device_status="online")
    )
    await db_session.commit()
    try:
        await _corrupt(
            db_session,
            "livelink_devices",
            "device_status",
            "melted",
            key="device_id",
            value=device_id,
        )
        caplog.set_level(logging.WARNING, logger=LOGGER)

        listed = await read_ok(client, auth_headers, f"/api/vehicles/{vin}/livelink/torque-sources")

        (mine,) = listed["sources"]
        assert mine["device_id"] == device_id
        assert mine["device_status"] == "unknown"
        _assert_one_warning(caplog, "TorqueSourceResponse", "device_status", "melted")
    finally:
        await _drop_device(db_session, device_id)


# --- one row each: line item, tire, topic map, reminder anchor ----------------


async def test_a_line_item_category_outside_its_vocabulary_reads_as_null(
    client, auth_headers, db_session, own_vehicle, caplog
):
    vin = own_vehicle.vin
    visit = ServiceVisit(vin=vin, date=DAY)
    db_session.add(visit)
    await db_session.flush()
    item = ServiceLineItem(visit_id=visit.id, description="Lenient", category="Maintenance")
    db_session.add(item)
    await db_session.commit()
    visit_id, item_id = visit.id, item.id
    try:
        await _corrupt(
            db_session, "service_line_items", "category", "Juggling", key="id", value=item_id
        )
        caplog.set_level(logging.WARNING, logger=LOGGER)
        base = f"/api/vehicles/{vin}/service-visits"

        one = await read_ok(client, auth_headers, f"{base}/{visit_id}")
        listed = await read_ok(client, auth_headers, base)

        assert one["line_items"][0]["category"] is None
        assert listed["visits"][0]["line_items"][0]["category"] is None
        # Two reads of the one bad value, one line in the log.
        _assert_one_warning(caplog, "ServiceLineItemResponse", "category", "Juggling")
    finally:
        await db_session.rollback()
        await db_session.execute(delete(ServiceLineItem).where(ServiceLineItem.id == item_id))
        await db_session.execute(delete(ServiceVisit).where(ServiceVisit.id == visit_id))
        await db_session.commit()


async def test_a_tire_position_outside_its_vocabulary_reads_as_null(
    client, auth_headers, db_session, own_vehicle, caplog
):
    vin = own_vehicle.vin
    tire = Tire(vin=vin, position="FL")
    db_session.add(tire)
    await db_session.commit()
    tire_id = tire.id
    try:
        await _corrupt(db_session, "tires", "position", "ROOF", key="id", value=tire_id)
        caplog.set_level(logging.WARNING, logger=LOGGER)

        listed = await read_ok(client, auth_headers, f"/api/vehicles/{vin}/tires")

        (mine,) = [entry for entry in listed["tires"] if entry["id"] == tire_id]
        assert mine["position"] is None
        logged = _assert_one_warning(caplog, "TireResponse", "position", "ROOF")
        assert f"id={tire_id}" in logged
        assert f"vin={vin}" in logged
    finally:
        await db_session.rollback()
        await db_session.execute(delete(Tire).where(Tire.id == tire_id))
        await db_session.commit()


async def test_a_topic_map_role_outside_its_vocabulary_reads_as_null(
    client, auth_headers, db_session, caplog
):
    # A random topic keeps the row this run's own: the suite shares one file.
    row = LiveLinkTopicMap(
        device_id="lenient",
        topic=f"lenient/{uuid.uuid4().hex[:8]}",
        role="telemetry",
        param_key="LENIENT_PROBE",
    )
    db_session.add(row)
    await db_session.commit()
    row_id = row.id
    try:
        await _corrupt(db_session, "livelink_topic_maps", "role", "decor", key="id", value=row_id)
        caplog.set_level(logging.WARNING, logger=LOGGER)

        listed = await read_ok(client, auth_headers, "/api/livelink/topic-maps")

        (mine,) = [entry for entry in listed if entry["id"] == row_id]
        assert mine["role"] is None
        _assert_one_warning(caplog, "TopicMapResponse", "role", "decor")
    finally:
        await db_session.rollback()
        await db_session.execute(delete(LiveLinkTopicMap).where(LiveLinkTopicMap.id == row_id))
        await db_session.commit()


async def test_a_reminder_anchor_kind_outside_its_vocabulary_reads_as_null(
    client, auth_headers, db_session, own_vehicle, caplog
):
    vin = own_vehicle.vin
    reminder = Reminder(
        vin=vin,
        title="Lenient anchor",
        reminder_type="date",
        due_date=date(2030, 1, 1),
        anchor_kind="baseline",
        anchor_date=DAY,
    )
    db_session.add(reminder)
    await db_session.commit()
    reminder_id = reminder.id
    try:
        await _corrupt(
            db_session, "vehicle_reminders", "anchor_kind", "vibes", key="id", value=reminder_id
        )
        caplog.set_level(logging.WARNING, logger=LOGGER)

        listed = await read_ok(client, auth_headers, f"/api/vehicles/{vin}/reminders")

        (mine,) = [entry for entry in listed if entry["id"] == reminder_id]
        assert mine["anchor_kind"] is None
        assert f"id={reminder_id}" in _assert_one_warning(
            caplog, "ReminderResponse", "anchor_kind", "vibes"
        )
    finally:
        await db_session.rollback()
        await db_session.execute(delete(Reminder).where(Reminder.id == reminder_id))
        await db_session.commit()


async def test_a_pack_preview_over_an_anchor_outside_its_vocabulary_reads_as_null(
    client, auth_headers, db_session, own_vehicle, caplog
):
    """The preview carries the pending reminder's stored anchor kind into
    AnchorProposal, and that one was built in the service, not the route."""
    vin = own_vehicle.vin
    try:
        applied = await client.post(
            f"/api/vehicles/{vin}/reminders/apply-pack",
            headers=auth_headers,
            json={"pack_id": "oil_and_filter"},
        )
        assert applied.status_code == 201, applied.text
        (oil,) = [r for r in applied.json() if r["maintenance_type"] == "engine_oil_filter"]
        await _corrupt(
            db_session, "vehicle_reminders", "anchor_kind", "vibes", key="id", value=oil["id"]
        )
        caplog.set_level(logging.WARNING, logger=LOGGER)

        preview = await client.post(
            f"/api/vehicles/{vin}/reminders/apply-pack/preview",
            headers=auth_headers,
            json={"pack_id": "oil_and_filter"},
        )

        assert preview.status_code == 200, preview.text
        (item,) = [
            entry
            for entry in preview.json()["items"]
            if entry["maintenance_type"] == "engine_oil_filter"
        ]
        assert item["anchor"]["origin"] == "reminder"
        assert item["anchor"]["kind"] is None
        _assert_one_warning(caplog, "AnchorProposal", "kind", "vibes")
    finally:
        await db_session.rollback()
        await db_session.execute(delete(Reminder).where(Reminder.vin == vin))
        await db_session.execute(delete(MaintenanceRule).where(MaintenanceRule.vin == vin))
        await db_session.commit()
