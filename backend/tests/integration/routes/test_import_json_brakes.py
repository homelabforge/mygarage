"""Brakes in the JSON backup: axle setups, jobs and measurements (task 6, J1, N-2, N-5, N-7)."""

import logging
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brake import BrakeAxle, BrakeJob, BrakeMeasurement, BrakeReminderMark
from app.models.reminder import Reminder
from app.services.brake_service import BrakeService
from tests.integration.routes._json_backup import V9, export_json, import_json

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _seed(db_session: AsyncSession, vin: str) -> None:
    """A drum rear axle, a pad job on FL with the new pads measured, and two checks."""
    db_session.add(
        BrakeAxle(
            vin=vin,
            axle="rear",
            brake_type="drum",
            min_thickness_mm=Decimal("1.50"),
            new_thickness_mm=Decimal("4.50"),
            drum_max_mm=Decimal("230.50"),
        )
    )
    job = BrakeJob(
        vin=vin,
        position="FL",
        brake_type="disc",
        performed_on=date(2026, 3, 1),
        odometer_km=Decimal("40000.00"),
        engine_hours=Decimal("400.0"),
        friction_replaced=True,
        surface="resurfaced",
        notes="pads and skim",
    )
    db_session.add(job)
    await db_session.flush()
    db_session.add_all(
        [
            BrakeMeasurement(
                vin=vin,
                position="FL",
                recorded_at=date(2026, 3, 1),
                odometer_km=Decimal("40000.00"),
                inner_pad_mm=Decimal("10.00"),
                brake_job_id=job.id,
            ),
            BrakeMeasurement(
                vin=vin,
                position="RL",
                recorded_at=date(2026, 6, 1),
                odometer_km=Decimal("45000.00"),
                shoe_mm=Decimal("3.80"),
                drum_mm=Decimal("229.10"),
                notes="ok",
            ),
            BrakeMeasurement(
                vin=vin,
                position="FR",
                recorded_at=date(2026, 6, 1),
                outer_pad_mm=Decimal("8.25"),
                rotor_mm=Decimal("25.40"),
            ),
        ]
    )
    await db_session.commit()


def _columns(row: Any, skip: set[str]) -> dict[str, Any]:
    return {c.key: getattr(row, c.key) for c in row.__table__.columns if c.key not in skip}


async def _brakes(db_session: AsyncSession, vin: str) -> dict[str, Any]:
    """The vehicle's brake rows as portable content, the job link as an index."""
    db_session.expire_all()

    async def rows(model: Any) -> list[Any]:
        return list(
            (await db_session.execute(select(model).where(model.vin == vin).order_by(model.id)))
            .scalars()
            .all()
        )

    jobs = await rows(BrakeJob)
    index = {job.id: i for i, job in enumerate(jobs)}
    skip = {"id", "vin", "created_at", "updated_at"}
    return {
        "axles": [_columns(a, skip) for a in await rows(BrakeAxle)],
        "jobs": [_columns(j, skip) for j in jobs],
        "measurements": [
            {**_columns(m, skip | {"brake_job_id"}), "job": index.get(m.brake_job_id)}
            for m in await rows(BrakeMeasurement)
        ],
    }


async def _pending(db_session: AsyncSession, vin: str, source: str) -> list[Reminder]:
    db_session.expire_all()
    return list(
        (
            await db_session.execute(
                select(Reminder).where(
                    Reminder.vin == vin, Reminder.source == source, Reminder.status == "pending"
                )
            )
        )
        .scalars()
        .all()
    )


# -- J1: the family comes back whole --------------------------------------------


async def test_brakes_round_trip_into_an_empty_vehicle(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    source = await new_vehicle()
    target = await new_vehicle()
    await _seed(db_session, source)

    backup = await export_json(client, auth_headers, source)
    data = await import_json(client, auth_headers, target, backup)

    assert data["errors"] == []
    assert data["brake_axles"]["success_count"] == 1
    assert data["brake_jobs"]["success_count"] == 1
    assert data["brake_measurements"]["success_count"] == 3
    # main: the backup has no brakes, so the target has none.
    assert await _brakes(db_session, target) == await _brakes(db_session, source)


async def test_the_export_links_a_measurement_to_its_job_by_index(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    vin = await new_vehicle()
    await _seed(db_session, vin)
    backup = await export_json(client, auth_headers, vin)
    # main: KeyError, no brake_measurements section.
    assert [m["brake_job_index"] for m in backup["brake_measurements"]] == [0, None, None]
    assert "brake_job_id" not in backup["brake_measurements"][0]
    # N-5: the reminder marks key on measurement ids, so they never travel.
    assert "brake_reminder_marks" not in backup


# -- N-2: a LOW corner raises its reminder at import, not at 08:00 ---------------


async def test_a_low_corner_raises_the_axle_reminder_at_import(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    vin = await new_vehicle()
    # 2.5 mm is under the default 3.0 minimum: replace now, due the day it was measured.
    payload = {
        **V9,
        "brake_measurements": [
            {"position": "RR", "recorded_at": "2026-01-01", "inner_pad_mm": 2.5}
        ],
    }
    await import_json(client, auth_headers, vin, payload)
    pending = await _pending(db_session, vin, "low_brakes_rear")
    # main: nothing imported, nothing raised.
    assert [(r.title, r.due_date) for r in pending] == [("Rear brake pads low", date(2026, 1, 1))]
    assert await _pending(db_session, vin, "low_brakes_front") == []
    marks = (
        (await db_session.execute(select(BrakeReminderMark).where(BrakeReminderMark.vin == vin)))
        .scalars()
        .all()
    )
    assert [m.position for m in marks] == ["RR"]


async def test_a_reimport_into_the_source_skips_its_brakes(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    vin = await new_vehicle()
    payload = {
        **V9,
        "brake_measurements": [
            {"position": "FL", "recorded_at": "2026-01-01", "inner_pad_mm": 2.5}
        ],
    }
    await import_json(client, auth_headers, vin, payload)
    before = await _brakes(db_session, vin)
    backup = await export_json(client, auth_headers, vin)

    data = await import_json(client, auth_headers, vin, backup)
    # main: KeyError, no brake_measurements bucket.
    assert data["brake_measurements"]["skipped_count"] == 1
    assert data["warnings"] == [
        "Brakes: this vehicle already has brake records, so the file's brake records weren't imported"
    ]
    assert await _brakes(db_session, vin) == before
    assert len(await _pending(db_session, vin, "low_brakes_front")) == 1


async def test_one_axle_setup_on_the_target_skips_the_files_brakes(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    vin = await new_vehicle()
    db_session.add(
        BrakeAxle(
            vin=vin,
            axle="front",
            brake_type="disc",
            min_thickness_mm=Decimal("3"),
            new_thickness_mm=Decimal("10"),
        )
    )
    await db_session.commit()
    payload = {
        **V9,
        "brake_jobs": [
            {
                "position": "FL",
                "brake_type": "disc",
                "performed_on": "2026-01-01",
                "friction_replaced": True,
            }
        ],
    }
    data = await import_json(client, auth_headers, vin, payload)
    # main: no warning; the section is never read.
    assert data["warnings"] == [
        "Brakes: this vehicle already has brake records, so the file's brake records weren't imported"
    ]
    assert data["brake_jobs"]["skipped_count"] == 1
    assert (await _brakes(db_session, vin))["jobs"] == []


# -- S4, N-7: a bad row refuses the whole family -------------------------------

_AXLE = {"axle": "front", "brake_type": "disc", "min_thickness_mm": 3, "new_thickness_mm": 10}
_JOB = {
    "position": "FL",
    "brake_type": "disc",
    "performed_on": "2026-01-01",
    "friction_replaced": True,
}
_CHECK = {"position": "FL", "recorded_at": "2026-01-01", "inner_pad_mm": 6}

_REFUSED = [
    pytest.param(
        {"brake_axles": [{**_AXLE, "axle": "middle"}]},
        "Brake axle 0: axle must be one of front, rear",
        id="axle-word",
    ),
    pytest.param(
        {"brake_axles": [_AXLE, {**_AXLE, "min_thickness_mm": 2}]},
        "Brake axle 1: front is already set up by brake axle 0",
        id="axle-twice",
    ),
    pytest.param(
        {"brake_axles": [{**_AXLE, "new_thickness_mm": 3}]},
        "Brake axle 0: New thickness must be more than the minimum",
        id="axle-whole-object-rule",
    ),
    pytest.param(
        {"brake_axles": [{**_AXLE, "min_thickness_mm": 51}]},
        "Brake axle 0: min_thickness_mm must be at most 50, not 51",
        id="axle-thickness-bound",
    ),
    pytest.param(
        {"brake_axles": [{key: v for key, v in _AXLE.items() if key != "min_thickness_mm"}]},
        "Brake axle 0: min_thickness_mm is missing",
        id="axle-without-a-minimum",
    ),
    pytest.param(
        {"brake_jobs": [{k: v for k, v in _JOB.items() if k != "position"}]},
        "Brake job 0: position is missing",
        id="job-without-a-position",
    ),
    pytest.param(
        {"brake_jobs": [{**_JOB, "surface": "polished"}]},
        "Brake job 0: surface must be one of replaced, resurfaced",
        id="job-surface-word",
    ),
    pytest.param(
        {"brake_jobs": [{**_JOB, "friction_replaced": "yes"}]},
        "Brake job 0: friction_replaced must be true or false",
        id="job-friction-word",
    ),
    pytest.param(
        {"brake_jobs": [{**_JOB, "engine_hours": -1}]},
        "Brake job 0: engine_hours must be at least 0, not -1",
        id="job-hours-bound",
    ),
    pytest.param(
        {"brake_measurements": [{"position": "FL", "recorded_at": "2026-01-01"}]},
        "Brake measurement 0: has nothing measured",
        id="measurement-measures-nothing",
    ),
    pytest.param(
        {"brake_measurements": [_CHECK, "FL 6mm"]},
        "Brake measurement 1: must be an object",
        id="measurement-not-an-object",
    ),
    pytest.param(
        {"brake_measurements": [{**_CHECK, "position": "SPARE"}]},
        "Brake measurement 0: position must be one of FL, FR, RL, RR",
        id="measurement-position-word",
    ),
    pytest.param(
        {"brake_jobs": [_JOB], "brake_measurements": [{**_CHECK, "brake_job_index": 1}]},
        "Brake measurement 0: brake_job_index must be the index of a brake job in this file",
        id="job-index-out-of-range",
    ),
    pytest.param(
        {"brake_jobs": [_JOB], "brake_measurements": [{**_CHECK, "brake_job_index": True}]},
        "Brake measurement 0: brake_job_index must be the index of a brake job in this file",
        id="job-index-true",
    ),
]


@pytest.mark.parametrize(("sections", "reason"), _REFUSED)
async def test_a_bad_brake_row_refuses_the_family_and_writes_nothing(
    sections: dict[str, list[Any]],
    reason: str,
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    new_vehicle,
):
    vin = await new_vehicle()
    # A good check rides along, so the refusal is the family's, not the row's.
    sections = {"brake_measurements": [_CHECK], **sections}
    data = await import_json(client, auth_headers, vin, {**V9, **sections})
    # main: the brake sections are never read.
    assert data["errors"] == [f"{reason}, so the file's brake records weren't imported"]
    for name, rows in sections.items():
        assert data[name]["error_count"] == len(rows), name
    assert await _brakes(db_session, vin) == {"axles": [], "jobs": [], "measurements": []}


async def test_a_figure_on_an_untracked_axis_restores(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    # N-7: the create path refuses hours on a distance vehicle; a restore doesn't.
    vin = await new_vehicle()
    payload = {**V9, "brake_measurements": [{**_CHECK, "engine_hours": 120.5}]}
    data = await import_json(client, auth_headers, vin, payload)
    assert data["errors"] == []
    # main: nothing imported.
    assert [m["engine_hours"] for m in (await _brakes(db_session, vin))["measurements"]] == [
        Decimal("120.5")
    ]


# -- D-5: only a written family runs the raise; a failed raise keeps the brakes --

_LOW_RR = {"position": "RR", "recorded_at": "2026-01-01", "inner_pad_mm": 2.5}


@pytest.mark.parametrize(
    "sections",
    [
        pytest.param({"brake_measurements": [_LOW_RR]}, id="skipped"),
        pytest.param({}, id="empty"),
    ],
)
async def test_a_family_not_written_raises_nothing(
    sections: dict[str, list[Any]],
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    new_vehicle,
):
    # Passes before the feature too, on purpose: it kills a raise that runs
    # whatever the family's outcome. The LOW corner here is 08:00's to raise.
    vin = await new_vehicle()
    db_session.add(
        BrakeMeasurement(
            vin=vin, position="RR", recorded_at=date(2026, 1, 1), inner_pad_mm=Decimal("2.5")
        )
    )
    await db_session.commit()

    data = await import_json(client, auth_headers, vin, {**V9, **sections})

    assert data["errors"] == []
    assert await _pending(db_session, vin, "low_brakes_rear") == []


async def test_a_failed_raise_keeps_the_brakes(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    new_vehicle,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    real = BrakeService.raise_reminders_for
    calls: list[str] = []

    async def raises_then_fails(self: BrakeService, vin: str) -> None:
        # Writes the reminder and its mark, then raises: the savepoint takes both back.
        calls.append(vin)
        await real(self, vin)
        await self.db.flush()
        raise RuntimeError("raise failed")

    monkeypatch.setattr(BrakeService, "raise_reminders_for", raises_then_fails)
    caplog.set_level(logging.WARNING)
    vin = await new_vehicle()

    data = await import_json(client, auth_headers, vin, {**V9, "brake_measurements": [_LOW_RR]})

    assert calls == [vin]
    assert data["brake_measurements"]["success_count"] == 1
    assert [m["position"] for m in (await _brakes(db_session, vin))["measurements"]] == ["RR"]
    assert await _pending(db_session, vin, "low_brakes_rear") == []
    marks = (
        (await db_session.execute(select(BrakeReminderMark).where(BrakeReminderMark.vin == vin)))
        .scalars()
        .all()
    )
    assert marks == []
    assert any("brake reminder raise failed" in r.getMessage() for r in caplog.records)
