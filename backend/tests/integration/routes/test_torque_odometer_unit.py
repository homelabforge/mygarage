"""A Torque device can't read TORQUE_ODOMETER as miles (O-T6, R1).

Torque sends that total (kff120c) in km, always. Set to `mi`, the device unit
wins and every reading lands 1.609x high. So the API refuses the combination
whichever field the request changes, and a device already in it can't leave
through the API either: its history needs the repair tool, not a unit flip.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice
from app.models.vehicle import Vehicle
from app.models.vehicle_telemetry import VehicleTelemetry
from app.utils.datetime_utils import utc_now

URL = "/api/livelink/devices"
TORQUE_SAYS = "Torque sends TORQUE_ODOMETER in km"
USE_KM = "Use auto or km as the odometer unit with this parameter."

MakeDevice = Callable[..., Awaitable[str]]


def _repair_command(device_id: str) -> str:
    return (
        f"python tools/repair_wican_odometer_unit.py --device-id {device_id} "
        "--key TORQUE_ODOMETER --to km"
    )


@pytest_asyncio.fixture
async def make_device(
    db_session: AsyncSession, test_user: dict[str, object]
) -> AsyncIterator[MakeDevice]:
    """Builds a device on its own vehicle, with TORQUE_ODOMETER rows already sent.

    The picker only offers keys the phone has sent, so every real declaration
    has these rows behind it.
    """
    made: list[tuple[str, str]] = []

    async def make(
        *,
        kind: str = "torque",
        odometer_unit: str | None = None,
        odometer_param_key: str | None = None,
    ) -> str:
        suffix = uuid.uuid4().hex[:10]
        vin = f"TQMI{suffix.upper()}XYZ"[:17]
        device_id = f"tqmi{suffix}"
        db_session.add(
            Vehicle(vin=vin, user_id=test_user["id"], nickname="Torque mi", vehicle_type="Car")
        )
        await db_session.flush()
        db_session.add(
            LiveLinkDevice(
                device_id=device_id,
                vin=vin,
                kind=kind,
                enabled=True,
                odometer_unit=odometer_unit,
                odometer_param_key=odometer_param_key,
            )
        )
        now = utc_now()
        db_session.add(
            VehicleTelemetry(
                vin=vin,
                device_id=device_id,
                param_key="TORQUE_ODOMETER",
                value=80000.0,
                timestamp=now,
                received_at=now,
            )
        )
        await db_session.commit()
        made.append((device_id, vin))
        return device_id

    yield make

    await db_session.rollback()
    for device_id, vin in made:
        await db_session.execute(
            delete(VehicleTelemetry).where(VehicleTelemetry.device_id == device_id)
        )
        await db_session.execute(
            delete(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id)
        )
        await db_session.execute(delete(Vehicle).where(Vehicle.vin == vin))
    await db_session.commit()


async def _saved(db_session: AsyncSession, device_id: str) -> tuple[str | None, str | None]:
    db_session.expire_all()
    row = (
        await db_session.execute(
            select(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id)
        )
    ).scalar_one()
    return row.odometer_unit, row.odometer_param_key


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unit_to_mi_while_the_key_is_torque_odometer(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    make_device: MakeDevice,
) -> None:
    """Red on f1986ea5: the history guard already 409s this, with its generic message."""
    device_id = await make_device(odometer_param_key="TORQUE_ODOMETER")

    response = await client.put(
        f"{URL}/{device_id}", headers=auth_headers, json={"odometer_unit": "mi"}
    )

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert TORQUE_SAYS in detail
    assert USE_KM in detail
    # Not in the pair yet, so nothing was stored inflated: no tool to run.
    assert "repair_wican_odometer_unit" not in detail
    assert await _saved(db_session, device_id) == (None, "TORQUE_ODOMETER")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_key_to_torque_odometer_while_the_unit_is_mi(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    make_device: MakeDevice,
) -> None:
    """Red on f1986ea5: 200, the undeclared rows don't count as history.

    No repair command: those rows went in undeclared, so as km, not inflated.
    """
    device_id = await make_device(odometer_unit="mi")

    response = await client.put(
        f"{URL}/{device_id}",
        headers=auth_headers,
        json={"odometer_param_key": "torque odometer"},
    )

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert TORQUE_SAYS in detail
    assert USE_KM in detail
    assert "repair_wican_odometer_unit" not in detail
    assert await _saved(db_session, device_id) == ("mi", None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_both_in_one_request(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    make_device: MakeDevice,
) -> None:
    """Red on f1986ea5: 200. Both guards read the pre-save declaration."""
    device_id = await make_device()

    response = await client.put(
        f"{URL}/{device_id}",
        headers=auth_headers,
        json={"odometer_param_key": "TORQUE_ODOMETER", "odometer_unit": "mi"},
    )

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert TORQUE_SAYS in detail
    assert USE_KM in detail
    assert "repair_wican_odometer_unit" not in detail
    assert await _saved(db_session, device_id) == (None, None)


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"odometer_unit": "km"},
        {"odometer_unit": "auto"},
        {"odometer_param_key": ""},
        {"odometer_param_key": "KFF1271"},
        {"odometer_unit": "km", "odometer_param_key": ""},
    ],
    ids=["unit-km", "unit-auto", "key-cleared", "key-other", "both-cleared"],
)
async def test_a_device_already_in_it_cant_leave_through_the_api(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    make_device: MakeDevice,
    body: dict[str, str],
) -> None:
    """Red on f1986ea5: the generic history message, which names the tool without --key.

    Flipping the unit would leave the inflated history behind it. The tool
    fixes that and clears the unit in one go.
    """
    device_id = await make_device(odometer_unit="mi", odometer_param_key="TORQUE_ODOMETER")

    response = await client.put(f"{URL}/{device_id}", headers=auth_headers, json=body)

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert TORQUE_SAYS in detail
    assert _repair_command(device_id) in detail
    assert USE_KM not in detail
    # The toast shows it as plain text, so no markdown backticks.
    assert "`" not in detail
    assert "Repair it with" in detail
    assert await _saved(db_session, device_id) == ("mi", "TORQUE_ODOMETER")


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"label": "Phone"},
        {"label": "Phone", "odometer_unit": "mi", "odometer_param_key": "TORQUE_ODOMETER"},
    ],
    ids=["label-only", "label-resending-the-same-pair"],
)
async def test_a_request_that_leaves_the_pair_alone_still_saves(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    make_device: MakeDevice,
    body: dict[str, str],
) -> None:
    """Guard, green at t=0. Kills a check that refuses any device sitting in the pair."""
    device_id = await make_device(odometer_unit="mi", odometer_param_key="TORQUE_ODOMETER")

    response = await client.put(f"{URL}/{device_id}", headers=auth_headers, json=body)

    assert response.status_code == 200, response.text
    assert response.json()["label"] == "Phone"
    assert await _saved(db_session, device_id) == ("mi", "TORQUE_ODOMETER")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_only_torque_is_refused(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    make_device: MakeDevice,
) -> None:
    """Guard, green at t=0. The km fact is Torque's; kills a check with no kind clause."""
    device_id = await make_device(kind="generic_mqtt")

    response = await client.put(
        f"{URL}/{device_id}",
        headers=auth_headers,
        json={"odometer_param_key": "TORQUE_ODOMETER", "odometer_unit": "mi"},
    )

    assert response.status_code == 200, response.text
    assert await _saved(db_session, device_id) == ("mi", "TORQUE_ODOMETER")
